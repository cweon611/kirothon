"""benefit_port implementation backed by the benefits engine (app.team.benefits).

For each candidate sigungu it builds a one-visit BenefitCheckRequest (trip dates,
nights, check-in date, party size, residence) and runs the same stored-data
evaluation as POST /api/benefits/check. No external calls are made, and the
engine's verdicts are passed through unchanged; F1/F2 only read them.
"""
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from pydantic import ValidationError
from sqlmodel import Session

from ..database import engine as db_engine
from .benefit_port import BenefitLookup, CourseConstraints, ProgramSummary, RegionBenefitQuery
from .benefits import engine as rules
from .benefits import sync as benefit_sync
from .benefits.routes import source_statuses
from .benefits.schemas import BenefitCheckRequest, BenefitProgram, ProgramEvaluation, Region, VisitInput
from .benefits.search import collect_stored
from .regions import load_codes, sigungu_map

# Fields of BenefitCheckRequest the frontend may pass through benefit_conditions.
PASSTHROUGH = ("residence", "departure", "birth_date", "age", "is_family", "same_address",
               "prior_participated_program_ids", "expected_spend_total")


def region_of(code: str | None) -> Region | None:
    """Internal 5-digit code -> benefits Region (seed sigungu, else synced legal-dong list)."""
    if not code:
        return None
    seed = sigungu_map().get(code)
    if seed:
        return Region(sido=seed.sido, sigungu=seed.name)
    for row in load_codes().get("ldong_all") or []:
        if row.get("code") == code:
            return Region(sido=row.get("sido") or None, sigungu=row.get("name") or None)
    return None


def build_request(query: RegionBenefitQuery, code: str) -> BenefitCheckRequest:
    if getattr(query, "assume_stay", True):
        nights = (query.trip_end - query.trip_start).days
        checkins = [query.trip_start + timedelta(days=i) for i in range(nights)] or None
    else:
        nights, checkins = None, None
    visit = VisitInput(region=region_of(code), start_date=query.trip_start, end_date=query.trip_end,
                       nights=nights, checkin_dates=checkins)
    fields = {k: v for k, v in (query.conditions or {}).items() if k in PASSTHROUGH}
    if "residence" not in fields:
        residence = region_of(query.residence_code)
        if residence:
            fields["residence"] = residence
    return BenefitCheckRequest(trip_start=query.trip_start, trip_end=query.trip_end, visits=[visit],
                               party_size=query.party_size, reference_date=query.today,
                               include_external=True, **fields)


def summarize(ev: ProgramEvaluation, program: BenefitProgram, code: str, query: RegionBenefitQuery) -> ProgramSummary:
    est = ev.estimate
    rate = est.refund_rate if est.refund_rate is not None else (program.benefit.refund_rate if program.benefit else None)
    if ev.data_freshness is not None:
        stale = ev.data_freshness.stale
    elif ev.timeline.status_checked_at:
        checked = ev.timeline.status_checked_at.astimezone(rules.KST).date()
        stale = (query.today - checked).days > rules.STALE_DAYS
    else:
        stale = None
    # Condition labels only: details can quote the user's own inputs.
    reasons = [f"불충족: {r.label}" for r in ev.unmet_conditions] \
        + [f"확인 필요: {r.label}" for r in ev.unresolved_conditions]
    visit, stay = program.visit_rule, program.stay_rule
    return ProgramSummary(
        program_id=ev.benefit_id, name=ev.name, judgment=ev.verdict, round_id=ev.round_id,
        sigungu_codes=(code,), posted_status=ev.timeline.posted_status, application_open=ev.can_apply_now,
        rate=rate, cap_krw=est.cap_amount, stale=stale,
        last_verified_at=ev.last_verified_at.isoformat() if ev.last_verified_at else None,
        source_url=ev.how_to_apply.official_info_url or next((s.url for s in ev.sources if s.url), None),
        apply_url=ev.how_to_apply.application_url, reasons=tuple(dict.fromkeys(reasons))[:4],
        unmet_codes=tuple(r.code for r in ev.unmet_conditions),
        constraints=CourseConstraints(
            required_place_names=tuple(visit.must_include) if visit and visit.must_include else None,
            any_of_place_names=tuple(visit.any_of) if visit and visit.any_of and visit.min_any_of else None,
            min_any_of=visit.min_any_of if visit and visit.any_of and visit.min_any_of else None,
            min_spots=visit.min_total_places if visit else None,
            min_nights=stay.min_nights if stay else None,
            stay_checkin_weekdays=tuple(stay.checkin_weekdays) if stay and stay.checkin_weekdays is not None
            else None,
        ),
        details=program_details(ev, program),
    )


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


def _period(rng) -> dict | None:
    return {"start": _iso(rng.start), "end": _iso(rng.end)} if rng else None


def support_text(program: BenefitProgram) -> str | None:
    """Support content from stored facts only (no generated wording about amounts)."""
    b = program.benefit
    parts = []
    if b and b.refund_rate is not None:
        parts.append(f"환급률 {round(b.refund_rate * 100)}%")
    if b and b.youth_refund_rate is not None:
        parts.append(f"청년 {round(b.youth_refund_rate * 100)}%")
    if b and b.caps:
        parts.append("상한 " + ", ".join(f"{c.label} {c.amount:,}원" for c in b.caps))
    if b and b.min_spend is not None:
        parts.append(f"최소 인정 소비 {b.min_spend:,}원")
    if program.payout and program.payout.method:
        parts.append(f"지급: {program.payout.method}")
    if parts:
        return " · ".join(parts)
    return program.raw_text.get("지원내용") or None


def program_details(ev: ProgramEvaluation, program: BenefitProgram) -> dict:
    t = ev.timeline
    fresh = ev.data_freshness
    unresolved = [{"code": r.code, "label": r.label, "detail": r.detail} for r in ev.unresolved_conditions
                  if r.status != "missing_user_info"]
    return {
        "program_key": ev.program_id,
        "related_program_ids": list(ev.related_program_ids),
        "trip_period": _period(t.trip_period),
        "application_period": _period(t.application_period),
        "application_start_at": _iso(t.application_start_at),
        "application_end_at": _iso(t.application_end_at),
        "pre_apply_deadline": _iso(t.pre_apply_deadline),
        "budget_remaining": t.budget_remaining,
        "support": support_text(program),
        "estimated_amount": ev.estimate.amount,
        "estimate_unavailable_reasons": list(ev.estimate.unavailable_reasons),
        "missing_user_fields": list(ev.missing_user_fields),
        "unmet": [{"code": r.code, "label": r.label, "confirmed": r.rule_confirmed} for r in ev.unmet_conditions],
        "unresolved": unresolved[:8],
        "data_origin": ev.data_origin,
        "source_type": ev.source_type,
        "verification_status": ev.verification_status,
        "review_status": ev.review_status,
        "last_success_at": _iso(fresh.last_success_at) if fresh else None,
        "source_updated_at": _iso(fresh.source_updated_at) if fresh else None,
        "sources": [{"type": s.source_type, "title": s.title, "url": s.url} for s in ev.sources],
    }


def _failed_sources(session: Session) -> list[str]:
    bad = []
    for s in source_statuses(session):
        if s.status not in {"ok", "skipped"} or (s.status == "ok" and s.stale):
            bad.append(f"{s.source}:{s.error_code or s.status}{':stale' if s.stale else ''}")
    return bad


def _invalid(exc: ValidationError) -> BenefitLookup:
    fields = sorted({".".join(str(p) for p in e["loc"]) for e in exc.errors()})
    return BenefitLookup(status="error", message="benefit_conditions가 지원제도 API 입력 형식과 맞지 않아요: "
                                                 + ", ".join(fields))


class BenefitsEnginePort:
    connected = True

    def lookup(self, query: RegionBenefitQuery) -> BenefitLookup:
        try:
            requests = {code: build_request(query, code) for code in query.sigungu_codes if region_of(code)}
        except ValidationError as exc:
            return _invalid(exc)
        with Session(db_engine) as session:
            stored = benefit_sync.load_programs(session)
            failed = _failed_sources(session)
        by_region: dict[str, tuple[ProgramSummary, ...]] = {}
        manual_count = 0
        for code, request in requests.items():
            programs, manual_count = collect_stored(stored, rules.visit_regions(request))
            pairs = [(ev, program) for program, origin in programs
                     if (ev := rules.evaluate(program, origin, request, query.today))]
            official = {ev.program_id for ev, _ in pairs if ev.data_origin != "manual_registry"}
            found = []
            for ev, program in pairs:
                summary = summarize(ev, program, code, query)
                linked = tuple(i for i in program.related_program_ids if i in official)
                if ev.data_origin == "manual_registry" and linked:
                    summary = replace(summary, superseded_by=linked)
                found.append(summary)
            if found:
                by_region[code] = tuple(found)
        return BenefitLookup(
            status="partial" if failed else "ok",
            checked_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            by_region=by_region,
            scope_note=(f"공공서비스(혜택) API·반값여행 현황 수집 자료와 수동 등록 자료 {manual_count}건 기준이에요. "
                        "결과가 없어도 그 지역에 지원제도가 없다는 뜻은 아니에요."),
            message=("일부 지원제도 출처를 확인하지 못했거나 정보가 오래돼, 저장된 이전 자료와 수동 등록 자료로 판정했어요."
                     if failed else None),
            failed_sources=tuple(failed),
        )

    def program(self, program_id: str, query: RegionBenefitQuery) -> ProgramSummary | None:
        code = query.sigungu_codes[0] if query.sigungu_codes else None
        request = build_request(query, code)
        with Session(db_engine) as session:
            stored = benefit_sync.load_programs(session)
        programs, _ = collect_stored(stored, rules.visit_regions(request))
        for program, origin in programs:
            if program.id == program_id:
                ev = rules.evaluate(program, origin, request, query.today)
                return summarize(ev, program, code, query) if ev else None
        return None
