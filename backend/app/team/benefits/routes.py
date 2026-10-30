"""/api/benefits — travel benefit lookup and rule-based eligibility check.

The check reads data already collected by the periodic sync (sync.py) plus the
manual registry. It never calls external sources per request.
User conditions in requests are used only for the check and are not stored.
Manual sync and run history are operator tasks; the project has no admin
authentication, so they are local commands (cli.py), not HTTP endpoints.
"""
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from itertools import combinations
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlmodel import Session, select

from . import config, engine, sync
from .gov24 import Gov24Client, Gov24Error, get_gov24_client
from .registry import find_manual
from .schemas import (
    BenefitCheckRequest, BenefitCheckResponse, BenefitDetailResponse, BenefitProgram,
    CombinedEstimate, ProgramEvaluation, SearchScope, SourcesResponse, SourceStatus, VisitScope,
)
from .search import collect_stored, merge, program_from_gov24
from .store_models import BenefitSourceRecord

log = logging.getLogger(__name__)
_scheduler: sync.Scheduler | None = None


def _session_factory():
    from ...database import engine as db_engine  # resolved at call time
    return Session(db_engine)


@asynccontextmanager
async def lifespan(app):
    """Runs after the app's own lifespan setup (schema check, create_all)."""
    global _scheduler
    if config.scheduler_enabled():
        _scheduler = sync.Scheduler(_session_factory)
        _scheduler.start()
        log.info("benefit periodic sync started")
    try:
        yield
    finally:
        if _scheduler:
            _scheduler.stop()
            _scheduler = None


def get_db():
    with _session_factory() as session:
        yield session


router = APIRouter(prefix="/api/benefits", tags=["benefits"], lifespan=lifespan)
Gov24Dep = Annotated[Gov24Client | None, Depends(get_gov24_client)]
DbDep = Annotated[Session, Depends(get_db)]

DISCLAIMER = ("판정은 입력값과 확인된 제도 조건만 비교한 결과이며 최종 승인을 보장하지 않습니다. "
              "예상액은 추정치이고 실제 지급은 운영 기관 심사 결과를 따릅니다. "
              "정보는 주기적 자동 갱신(실시간 아님) 기준입니다.")
UPDATE_METHOD = ("주기적 자동 갱신(polling). 공공서비스 API와 반값여행 현황 페이지 모두 웹훅·변경 알림을 "
                 "제공하지 않아 실시간 반영이 아닙니다.")
_ORDER = {"potentially_eligible": 0, "needs_verification": 1, "ineligible": 2}
_METHOD = {"gov24_api": "public_api", "kto_tour50": "official_webpage"}


# ------------------------------------------------------------------ source status
def source_statuses(session: Session, include_external: bool = True) -> list[SourceStatus]:
    out = []
    states = sync.source_states(session)
    for source in config.SOURCES:
        st = states.get(source)
        count = len(session.exec(select(BenefitSourceRecord.id)
                                 .where(BenefitSourceRecord.source == source)).all())
        s = SourceStatus(source=source, status="never_synced", collection_method=_METHOD[source],
                         data_origin="stored_sync", records_seen=count,
                         refresh_interval_seconds=config.interval_seconds(source))
        if st and st.last_attempt_at:
            s.last_attempt_at = sync.aware(st.last_attempt_at)
            s.last_success_at = sync.aware(st.last_success_at)
            s.status = {"ok": "ok", "partial": "partial", "not_configured": "not_configured",
                        "skipped_locked": "ok"}.get(st.last_status or "", "error")
            s.error_code = st.last_error_code
        s.stale = sync.is_stale(st.last_success_at if st else None, source)
        s.fetched_at = s.last_success_at
        if s.status == "not_configured":
            s.message = "서버 설정이 없어 수집하지 않음(인증키 또는 수집 비활성화)"
        elif s.status == "never_synced":
            s.message = "아직 수집 이력 없음"
        elif s.stale:
            s.message = "마지막 정상 수집이 갱신 주기를 넘김 — 저장된 이전 데이터 사용"
        if not include_external:
            s.status, s.message = "skipped", "요청에서 수집 데이터 사용을 끔(include_external=false)"
        out.append(s)
    return out


def _source_ok(s: SourceStatus) -> bool:
    return s.status in {"ok", "skipped"} and (s.status == "skipped" or not s.stale)


def _coverage(sources: list[SourceStatus], manual_count: int) -> str:
    parts = [
        "공공서비스(혜택) API는 서비스명 키워드(" + "·".join(sync.SYNC_GOV24_KEYWORDS) + ")로 수집하며 "
        "여행 기간·환급률·상한·접수 상태·예산 잔액은 구조화돼 있지 않습니다.",
        "반값여행 현황은 한국관광공사 공식 페이지에 게시된 지역(지역사랑 휴가지원 사업)만 포함합니다. "
        "지자체 자체 사업은 수동 등록 자료로만 다룹니다.",
        f"수동 등록 자료 {manual_count}건은 공식 공고 검토 상태를 함께 표시합니다.",
        "결과가 없더라도 해당 지역에 지원제도가 없다는 뜻이 아닙니다.",
    ]
    bad = [s for s in sources if not _source_ok(s)]
    if bad:
        parts.insert(0, "확인하지 못했거나 오래된 출처: " + ", ".join(
            f"{s.source}({s.error_code or s.status}{', 오래됨' if s.stale else ''})" for s in bad) + ".")
    return " ".join(parts)


def _combined(results: list[ProgramEvaluation], programs: dict[str, BenefitProgram]) -> CombinedEstimate:
    usable = [r for r in results if r.verdict != "ineligible" and r.estimate.amount is not None]
    if not usable:
        return CombinedEstimate(note="계산 가능한 예상 지원액이 없습니다.")
    tentative = any(r.verdict != "potentially_eligible" or r.estimate.amount_kind != "calculated"
                    for r in usable)
    suffix = " 확인 필요 항목이 있는 참고값입니다." if tentative else ""
    if len(usable) == 1:
        r = usable[0]
        return CombinedEstimate(amount=r.estimate.amount, benefit_ids=[r.benefit_id],
                                note="계산 가능한 제도가 1건입니다." + suffix)
    by_id = {r.benefit_id: r for r in usable}

    def stack_ok(a: str, b: str) -> bool:
        p = programs.get(a)
        return bool(p and p.stackable_with and b in p.stackable_with)

    confirmed = all(stack_ok(a, b) and stack_ok(b, a) for a, b in combinations(by_id, 2))
    same_type = len({r.estimate.benefit_type for r in usable}) == 1
    if confirmed and same_type:
        return CombinedEstimate(amount=sum(r.estimate.amount for r in usable), benefit_ids=list(by_id),
                                note="중복 적용이 확인된 제도만 합산했습니다." + suffix)
    return CombinedEstimate(benefit_ids=[], note="중복 적용 가능 여부가 확인되지 않아 합산하지 않았습니다. 제도별 금액을 따로 보세요.")


# ------------------------------------------------------------------ endpoints
@router.post("/check", response_model=BenefitCheckResponse)
def check_benefits(data: BenefitCheckRequest, session: DbDep):
    ref = data.reference_date or engine.today_kst()
    regions = engine.visit_regions(data)
    stored = sync.load_programs(session) if data.include_external else []
    programs, manual_count = collect_stored(stored, regions)
    by_id = {p.id: p for p, _ in programs}
    sources = source_statuses(session, data.include_external)
    sources.append(SourceStatus(source="manual_registry", status="ok", data_origin="local_registry",
                                collection_method="admin_registry", records_seen=manual_count,
                                message="관리자 등록 보조 자료(공식 공고 검토 전 항목 포함)"))

    results = [e for p, origin in programs if (e := engine.evaluate(p, origin, data, ref))]
    results.sort(key=lambda r: (_ORDER[r.verdict], r.can_apply_now is False, r.name))
    missing = sorted({f for r in results if r.verdict != "ineligible" for f in r.missing_user_fields})

    auto = sources[:-1]
    all_ok = all(_source_ok(s) for s in auto)
    if results:
        if (not any(r.verdict == "potentially_eligible" for r in results)
                and any(r.missing_user_fields for r in results if r.verdict == "needs_verification")):
            outcome, message = "insufficient_information", "후보 제도를 찾았지만 자격 판단에 필요한 정보가 부족합니다."
        else:
            outcome, message = "candidates_found", f"후보 제도 {len(results)}건을 판정했습니다."
        if not all_ok:
            message += " 일부 출처는 확인하지 못했거나 정보가 오래됐습니다."
    elif not all_ok:
        outcome = "source_unavailable"
        message = "일부 출처를 확인하지 못했거나 정보가 오래돼 '지원제도 없음'으로 판단할 수 없습니다."
    else:
        outcome, message = "no_match_in_scope", "조회 범위 안에서 일치하는 제도를 찾지 못했습니다."

    return BenefitCheckResponse(
        success=all_ok, partial_failure=not all_ok,
        outcome=outcome, message=message,
        checked_at=datetime.now(timezone.utc),
        scope=SearchScope(trip_start=data.trip_start, trip_end=data.trip_end, reference_date=ref,
                          visits=[VisitScope(region=v.region, dates=engine.visit_dates(v)) for v in data.visits],
                          gov24_keywords=list(sync.SYNC_GOV24_KEYWORDS) if data.include_external else []),
        sources=sources, coverage_note=_coverage(auto, manual_count), missing_fields=missing,
        results=results, combined_estimate=_combined(results, by_id), disclaimer=DISCLAIMER,
    )


@router.get("/sources", response_model=SourcesResponse)
def get_sources(session: DbDep):
    """Public, read-only collection status (no error history, no secrets)."""
    return SourcesResponse(checked_at=datetime.now(timezone.utc), update_method=UPDATE_METHOD,
                           sources=source_statuses(session))


BenefitId = Annotated[str, Path(pattern=r"^(manual|gov24|kto50):[A-Za-z0-9_.\-]{1,80}$")]


@router.get("/{benefit_id}", response_model=BenefitDetailResponse)
def get_benefit(benefit_id: BenefitId, session: DbDep, gov24: Gov24Dep):
    kind, _, ext = benefit_id.partition(":")
    statuses = {s.source: s for s in source_statuses(session)}
    if kind == "manual":
        program = find_manual(benefit_id)
        if program is None:
            raise HTTPException(status_code=404, detail="Benefit not found")
        status = SourceStatus(source="manual_registry", status="ok", data_origin="local_registry",
                              collection_method="admin_registry")
        origin = "manual_registry"
        if program.external_service_id:
            stored = _stored_gov24(session, program.external_service_id)
            if stored:
                program, origin, status = merge(program, stored), "merged", statuses["gov24_api"]
        return _detail(program, origin, status)
    if kind == "kto50":
        parts = ext.split("-")
        rec = None
        if len(parts) == 3:
            rec = session.exec(select(BenefitSourceRecord).where(BenefitSourceRecord.source == "kto_tour50")
                               .where(BenefitSourceRecord.source_key == "tour50:" + ":".join(parts))).first()
        if rec is None:
            raise HTTPException(status_code=404, detail="Benefit not found")
        return _detail(sync.to_program(rec), "kto_tour50", statuses["kto_tour50"])
    stored = _stored_gov24(session, ext)
    if stored:
        return _detail(stored, "gov24_api", statuses["gov24_api"])
    api, status = _fetch_gov24(gov24, ext)
    if api is None:
        raise HTTPException(status_code=404, detail="Benefit not found")
    return _detail(api, "gov24_api", status)


def _stored_gov24(session: Session, service_id: str) -> BenefitProgram | None:
    rec = session.exec(select(BenefitSourceRecord).where(BenefitSourceRecord.source == "gov24_api")
                       .where(BenefitSourceRecord.source_key == service_id)).first()
    return sync.to_program(rec) if rec else None


def _fetch_gov24(client: Gov24Client | None, service_id: str):
    """Fallback for an ID not yet collected: one cached lookup, clearly marked live."""
    status = SourceStatus(source="gov24_api", status="ok", queries=[f"서비스ID={service_id}"],
                          collection_method="public_api")
    if client is None:
        raise HTTPException(status_code=503, detail="External benefit API key is not configured on the server")
    try:
        summary, cached_s = client.service_summary(service_id)
        detail, cached_d = client.service_detail(service_id)
        conditions, cached_c = client.support_conditions(service_id)
    except Gov24Error as exc:
        raise HTTPException(status_code=502, detail=f"External benefit API error: {exc.code}") from None
    now = datetime.now(timezone.utc)
    flags = [cached_s, cached_d, cached_c]
    status.pages_fetched, status.fetched_at = 3, now
    status.data_origin = "cache" if all(flags) else "live_api" if not any(flags) else "mixed"
    if summary is None and detail is None:
        return None, status
    status.records_seen = 1
    record = {**(detail or {}), **(summary or {}), "서비스ID": service_id}
    return program_from_gov24(record, detail, conditions, [], now), status


def _detail(program, origin, status) -> BenefitDetailResponse:
    stale = None
    if program.sync:
        stale = program.sync.stale
    elif program.status_checked_at:
        stale = (engine.today_kst() - program.status_checked_at.astimezone(engine.KST).date()).days > engine.STALE_DAYS
    return BenefitDetailResponse(benefit=program, data_origin=origin, source_status=status,
                                 stale_status=stale, disclaimer=DISCLAIMER)
