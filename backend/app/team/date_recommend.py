"""POST /api/team/date-recommendations: trip dates -> Gwangju/Jeonnam regions with festivals and/or benefits.

Rough version for quick testing. It reuses stored data only:
- festivals: `place` rows of type 15 from `python -m app.team.sync_tourism --steps festivals`
  (Snapshot.festivals_during: event period overlaps the trip by at least one day)
- benefits: the benefits engine through benefit_port (stored gov24/tour50 sync data + manual registry)
No external call is made per request, no AI scoring, no generated amounts or dates.
User inputs (residence, birth date) are passed to the benefit check only; never stored or echoed.
"""
from datetime import date, datetime, timedelta, timezone
import json

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlmodel import select

from . import benefit_port
from .benefit_port import ProgramSummary, RegionBenefitQuery
from .benefits.schemas import Region
from .course_routes import SessionDep
from .regions import sigungu_map, today_kst
from .tourapi import has_service_key
from .tourism_data import cache_stats, load_snapshot
from .tourism_models import Place, TourismSyncRun

router = APIRouter(tags=["date-recommend"])
MAX_DAYS = 60                      # benefits engine accepts trips up to 60 days
FESTIVAL_STALE = timedelta(days=7)
PERIOD_CODES = {"trip_period", "application_period", "posted_status", "pre_apply"}
PREPARE = {
    "festivals": "python -m app.team.sync_tourism --steps codes,festivals  (TOURAPI_SERVICE_KEY 필요)",
    "benefits": "python -m app.team.benefits.cli sync  (반값여행 현황은 키 불필요, 공공서비스 API는 키 필요)",
    "script": "scripts/prepare-date-data.ps1",
}


class DateRecommendIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_date: date
    end_date: date
    residence: str | Region | None = Field(
        default=None, description="주민등록상 거주지: 5자리 시군구 코드(meta) 또는 {sido, sigungu}")
    party_size: int | None = Field(default=None, ge=1, le=20)
    birth_date: date | None = None
    sigungu_code: str | None = Field(
        default=None, description="선택 지역(5자리 시군구 코드). 주면 그 지역 결과를 selected_region으로 항상 반환")

    @model_validator(mode="after")
    def _dates(self):
        if self.sigungu_code is not None and self.sigungu_code not in sigungu_map():
            raise ValueError("sigungu_code는 광주·전남 27개 시군구 코드여야 해요")
        if self.end_date < self.start_date:
            raise ValueError("end_date는 start_date 이후여야 해요")
        if (self.end_date - self.start_date).days >= MAX_DAYS:
            raise ValueError(f"여행 기간은 {MAX_DAYS}일 미만이어야 해요")
        if self.start_date < today_kst()[0]:
            raise ValueError("여행 시작일은 오늘 이후여야 해요")
        if isinstance(self.residence, str) and not (len(self.residence) == 5 and self.residence.isdigit()):
            raise ValueError("residence 코드는 5자리 숫자여야 해요")
        return self


# ------------------------------------------------------------------ data status
def _aware(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def festival_source(session) -> dict:
    """State of the festival step across tourism sync runs (no key needed to read)."""
    runs = session.exec(select(TourismSyncRun).order_by(TourismSyncRun.id.desc()).limit(50)).all()
    last_attempt = last_ok = None
    for run in runs:
        try:
            steps = json.loads(run.steps_json or "{}")
        except ValueError:
            steps = {}
        step = steps.get("festivals")
        whole_failed = run.status == "failed" and not steps.get("festivals")
        if step is None and not whole_failed:
            continue
        if last_attempt is None:
            last_attempt = (run, step)
        if step and step.get("status") == "ok" and run.status in {"success", "partial"}:
            last_ok = run
            break
    count = len(session.exec(select(Place.content_id).where(Place.content_type_id == "15")).all())
    out = {"source": "kto_festival", "collection_method": "public_api",
           "api": "한국관광공사 국문 관광정보 KorService2 searchFestival2", "records": count,
           "key_configured": has_service_key(), "last_attempt_at": None, "last_attempt_status": None,
           "last_success_at": None, "stale": True, "status": "never_synced", "message": None}
    if last_attempt:
        run, step = last_attempt
        out["last_attempt_at"] = _aware(run.started_at).isoformat()
        out["last_attempt_status"] = (step or {}).get("status") or run.status
        if run.status == "failed" and not step:
            out["message"] = "축제 수집 실패: " + (run.message or "원인 미기록")
    if last_ok and last_ok.finished_at:
        finished = _aware(last_ok.finished_at)
        out["last_success_at"] = finished.isoformat()
        out["stale"] = datetime.now(timezone.utc) - finished > FESTIVAL_STALE
    if last_ok and not out["stale"] and out["last_attempt_status"] == "ok":
        out["status"] = "ok"
    elif last_ok:
        out["status"] = "stale" if out["stale"] else "partial"
    elif last_attempt:
        out["status"] = "error"
    if out["status"] != "ok" and not out["message"]:
        out["message"] = ("축제 데이터를 수집한 적이 없어요." if out["status"] == "never_synced" else
                          "축제 데이터가 오래됐거나 일부 실패했어요." if out["status"] in {"stale", "partial"} else
                          "마지막 축제 수집이 실패했어요.")
        if not out["key_configured"]:
            out["message"] += " TOURAPI_SERVICE_KEY가 설정되지 않았어요."
    return out


def benefit_sources(session) -> list[dict]:
    from .benefits.routes import source_statuses
    rows = []
    for s in source_statuses(session):
        rows.append({"source": s.source, "collection_method": s.collection_method, "status": s.status,
                     "records": s.records_seen, "last_attempt_at": _iso(s.last_attempt_at),
                     "last_success_at": _iso(s.last_success_at), "stale": s.stale,
                     "error_code": s.error_code, "message": s.message})
    return rows


def _iso(value):
    return value.isoformat() if value is not None else None


def _ok(src: dict) -> bool:
    return src["status"] == "ok" and not src["stale"]


# ------------------------------------------------------------------ per region
def festival_view(event, fetched: dict) -> dict:
    return {"content_id": event.content_id, "title": event.title, "start_date": event.event_start,
            "end_date": event.event_end, "place": event.addr, "overview": event.overview,
            "source": "한국관광공사 KorService2(searchFestival2)",
            # The festival list API returns no homepage URL and details are not collected for festivals.
            "source_url": None, "fetched_at": fetched.get(event.content_id)}


def undated_festivals(snapshot, code: str, fetched: dict) -> list[dict]:
    """Festivals of the region whose period is unknown: never mixed into the confirmed list."""
    return [festival_view(e, fetched) for e in snapshot.festivals.get(code, [])
            if not e.event_start or not e.event_end]


def program_view(p: ProgramSummary, excluded_reason: str | None = None) -> dict:
    d = p.details or {}
    view = {
        "program_id": p.program_id, "round_id": p.round_id, "name": p.name, "judgment": p.judgment,
        "posted_status": p.posted_status, "application_open": p.application_open,
        "trip_period": d.get("trip_period"), "application_period": d.get("application_period"),
        "application_start_at": d.get("application_start_at"), "application_end_at": d.get("application_end_at"),
        "support": d.get("support"), "payout_method": d.get("payout_method"), "match_basis": d.get("match_basis"),
        "conditions_text": d.get("conditions_text"), "estimated_amount": d.get("estimated_amount"),
        "audience": d.get("audience", "general"),
        "budget_remaining": d.get("budget_remaining"),
        "apply_url": p.apply_url, "official_url": p.source_url,
        "missing_user_fields": d.get("missing_user_fields", []),
        "needs_official_check": [x["label"] for x in d.get("unresolved", [])],
        "reasons": list(p.reasons),
        "data_origin": d.get("data_origin"), "source_type": d.get("source_type"),
        "verification_status": d.get("verification_status"), "review_status": d.get("review_status"),
        "last_success_at": d.get("last_success_at"), "last_verified_at": p.last_verified_at,
        "stale": p.stale, "sources": d.get("sources", []),
    }
    if excluded_reason:
        view["excluded_reason"] = excluded_reason
    return view


def split_programs(programs: tuple[ProgramSummary, ...]):
    applicable, needs_check, excluded = [], [], []
    keys = {(p.details or {}).get("program_key") for p in programs}
    for p in programs:
        unmet = set(p.unmet_codes)
        related = set((p.details or {}).get("related_program_ids") or []) & keys
        if related and p.judgment != "potentially_eligible":
            # Explicit admin link (registry related_program_ids), not name similarity.
            excluded.append(program_view(p, "같은 사업의 공식 페이지 수집 자료(" + ", ".join(sorted(related))
                                         + ")가 있어 그 차수별 판정을 따름"))
            continue
        # Non-travel public services (수학여행비, 자녀돌봄휴가비 …) never reach this list: the engine drops them.
        if p.judgment == "ineligible":
            labels = ", ".join(x["label"] for x in (p.details or {}).get("unmet", [])) or "조건 미상"
            excluded.append(program_view(p, f"확인된 필수 조건 불충족: {labels}"))
        elif p.application_open is False:
            excluded.append(program_view(p, "현재 신청할 수 없음(접수 마감·시작 전·사전 신청 기한 경과)"))
        elif unmet:
            labels = ", ".join(x["label"] for x in (p.details or {}).get("unmet", []))
            kind = "기간·접수 조건" if unmet & PERIOD_CODES else "자격 조건"
            excluded.append(program_view(p, f"미검증 자료상 {kind} 불충족({labels}) — 공식 확인 전 추천하지 않음"))
        elif p.judgment == "potentially_eligible":
            applicable.append(program_view(p))
        else:
            needs_check.append(program_view(p))
    return applicable, needs_check, excluded


CATEGORY = {
    1: ("festival_and_benefit", "기간 내 축제와 신청 가능 예상 혜택이 모두 있어요."),
    2: ("festival_or_benefit", None),
    3: ("benefit_needs_verification", "기간이 맞을 수 있는 혜택 후보가 있지만 사용자 정보나 공식 조건 확인이 필요해요."),
}


def classify(fests: list, applicable: list, needs_check: list) -> tuple[int, str, str] | None:
    """Category keeps 'applicable' (조건 확인됨) and 'needs_verification' (추가 확인 필요) apart.

    A festival region that also has needs-verification candidates is not 'festival_only'
    and is not upgraded to 'festival_and_benefit' either.
    """
    if fests and applicable:
        return (1, *CATEGORY[1])
    if fests and needs_check:
        return (2, "festival_and_benefit_needs_verification",
                f"여행 기간에 진행되는 축제·행사 {len(fests)}건과, 사용자 정보나 공식 조건 확인이 필요한 "
                f"혜택 후보 {len(needs_check)}건이 있어요.")
    if fests or applicable:
        if fests:
            reason = f"여행 기간에 진행되는 축제·행사 {len(fests)}건이 있어요."
        else:
            reason = f"신청 가능 예상 혜택 {len(applicable)}건이 있어요."
            if needs_check:
                reason += f" 확인이 필요한 혜택 후보 {len(needs_check)}건도 있어요."
        return 2, "festival_only" if fests else "benefit_only", reason
    if needs_check:
        return (3, *CATEGORY[3])
    return None


# ------------------------------------------------------------------ endpoint
@router.post("/date-recommendations")
def date_recommendations(body: DateRecommendIn, session: SessionDep):
    today = today_kst()[0]
    codes = (body.sigungu_code,) if body.sigungu_code else tuple(sigungu_map())
    conditions = {}
    residence_code = None
    if isinstance(body.residence, Region):
        conditions["residence"] = body.residence
    else:
        residence_code = body.residence
    if body.birth_date:
        conditions["birth_date"] = body.birth_date
    query = RegionBenefitQuery("day" if body.start_date == body.end_date else "multi", body.start_date,
                               body.end_date, codes, body.party_size, today, residence_code, conditions,
                               assume_stay=False)
    lookup = benefit_port.safe_lookup(query)

    snapshot = load_snapshot(session)
    fetched = {p.content_id: _iso(_aware(p.fetched_at)) for p in session.exec(
        select(Place).where(Place.content_type_id == "15")).all()}
    fest_src = festival_source(session)
    ben_srcs = benefit_sources(session) if lookup.status != "not_connected" else []
    benefit_ok = lookup.status == "ok"
    festival_ok = _ok(fest_src)

    missing_inputs = [f for f, v in (("residence", body.residence), ("party_size", body.party_size),
                                     ("birth_date", body.birth_date)) if v is None]
    warnings = [w for w in (
        None if festival_ok else "축제 데이터가 최신이 아니거나 수집되지 않았어요.",
        None if benefit_ok else "일부 지원제도 출처를 확인하지 못했거나 정보가 오래됐어요.",
    ) if w]

    def entry(code: str) -> dict:
        region = sigungu_map()[code]
        fests = [festival_view(e, fetched) for e in sorted(
            snapshot.festivals_during(code, body.start_date, body.end_date),
            key=lambda e: (e.event_start or "", e.title))]
        applicable, needs_check, excluded = split_programs(lookup.by_region.get(code, ()))
        cls = classify(fests, applicable, needs_check)
        group, category, reason = cls if cls else (None, "none", None)
        return {
            "sigungu_code": code, "name": region.label, "sido": region.sido,
            "group": group, "category": category, "reason": reason,
            "festivals": fests, "festivals_undated": undated_festivals(snapshot, code, fetched),
            "benefits": {"applicable": applicable, "needs_verification": needs_check, "excluded": excluded},
            "missing_user_fields": sorted({f for p in applicable + needs_check for f in p["missing_user_fields"]}),
            "data_warnings": warnings,
        }

    regions, unmatched = [], []
    for code in codes:
        item = entry(code)
        if item["group"] is None:
            unmatched.append(item["name"])
        else:
            regions.append(item)
    selected = None
    if body.sigungu_code:
        selected = entry(body.sigungu_code)
        selected["states"] = {
            "festivals": ("found" if selected["festivals"] else
                          "unavailable" if not festival_ok and fest_src["status"] in {"never_synced", "error"}
                          else "none_in_period"),
            "festivals_stale": fest_src["stale"] and fest_src["status"] != "never_synced",
            "benefits": ("unavailable" if lookup.status in {"error", "not_connected"} else
                         "found" if selected["benefits"]["applicable"] or selected["benefits"]["needs_verification"]
                         else "excluded_only" if selected["benefits"]["excluded"] else "none_in_scope"),
            "benefits_partial": lookup.status == "partial",
            "needs_user_info": bool(selected["missing_user_fields"]),
        }
    regions.sort(key=lambda r: (r["group"], -len(r["benefits"]["applicable"]), -len(r["festivals"]),
                                -len(r["benefits"]["needs_verification"]), r["name"]))

    complete = festival_ok and benefit_ok
    if regions:
        outcome = "matches_found"
        message = f"조건에 맞는 지역 {len(regions)}곳을 찾았어요."
    elif complete:
        outcome = "no_match_in_scope"
        message = "조회 범위 안에서 기간에 맞는 축제·혜택 후보가 있는 지역을 찾지 못했어요."
    else:
        outcome = "source_unavailable"
        message = "일부 데이터를 확인하지 못해 '축제·혜택 없음'으로 판단할 수 없어요."
    return {
        "query": {"start_date": body.start_date.isoformat(), "end_date": body.end_date.isoformat(),
                  "days": (body.end_date - body.start_date).days + 1,
                  "provided": [f for f in ("residence", "party_size", "birth_date") if f not in missing_inputs]},
        "today": today.isoformat(), "today_fixed": today_kst()[1],
        "outcome": outcome, "message": message, "complete": complete,
        "regions": regions,
        "selected_region": selected,
        "regions_not_matched": {
            "names": unmatched,
            "meaning": ("확인된 데이터 범위에서 기간에 맞는 축제·혜택 후보가 없음" if complete else
                        "데이터 일부를 확인하지 못해 '없음'으로 단정하지 않음"),
        },
        "missing_user_fields": missing_inputs,
        "data_status": {
            "festivals": fest_src,
            "benefits": {"lookup_status": lookup.status, "checked_at": lookup.checked_at,
                         "failed_sources": list(lookup.failed_sources), "message": lookup.message,
                         "scope_note": lookup.scope_note, "sources": ben_srcs},
            "tourism_cache": cache_stats(session),
            "prepare_commands": PREPARE if not complete else None,
        },
        "sorting": "1) 축제+신청 가능 예상 혜택 2) 둘 중 하나 3) 확인 필요 혜택 후보만 (AI 점수 없음)",
        "disclaimer": ("판정은 저장된 공식 출처 데이터와 입력값만 비교한 예상이에요. 최종 승인·지원액은 운영 기관 심사를 따르며, "
                       "금액을 확인하지 못하면 null로 표시해요."),
    }
