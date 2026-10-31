"""F3 link: a saved course -> benefit check request -> verdict, estimate and dated steps.

The check itself is the benefits module's POST /api/benefits/check logic, called
in-process. This module only builds its input from the course (visits per
sigungu, nights, check-in dates, place names, categorized spend) and turns the
chosen program's timeline into the step list of design 5-3. Application links
come only from program data.
"""
from datetime import date, timedelta

from sqlmodel import Session

from .benefit_bridge import PASSTHROUGH, region_of
from .benefits.routes import check_benefits
from .benefits.schemas import (BenefitCheckRequest, BenefitCheckResponse, ExpectedSpend, ProgramEvaluation,
                               VisitInput)


def course_visits(body: dict) -> list[VisitInput]:
    """One visit per sigungu in the course, in first-visit order."""
    visits: dict[str, dict] = {}
    for day in body["days"]:
        day_date = date.fromisoformat(day["date"])
        for item in day["items"]:
            place = item.get("place")
            code = (place or {}).get("sigungu_code") or body["region"]["sigungu_code"]
            visit = visits.setdefault(code, {"dates": set(), "places": [], "checkins": [], "spend": {}})
            visit["dates"].add(day_date)
            if place and place["title"] not in visit["places"]:
                visit["places"].append(place["title"])
            if item["kind"] == "stay":
                visit["checkins"].append(day_date)
    for item in body.get("spend_breakdown", {}).get("items", []):
        visit = visits.get(item["sigungu_code"])
        if visit and item.get("category"):
            visit["spend"][item["category"]] = visit["spend"].get(item["category"], 0) + item["krw"]
    out = []
    for code, visit in visits.items():
        region = region_of(code)
        if region is None:
            continue
        checkins = sorted(visit["checkins"])
        start = min(visit["dates"])
        end = max([*visit["dates"], *(d + timedelta(days=1) for d in checkins)])
        spend = visit["spend"]
        out.append(VisitInput(region=region, start_date=start, end_date=end, nights=len(checkins),
                              checkin_dates=checkins or None, places=visit["places"][:50] or None,
                              expected_spend=ExpectedSpend(by_category=spend, total=sum(spend.values()))
                              if spend else None))
    return out


def course_request(body: dict, residence_code: str | None, conditions: dict | None,
                   today: date) -> BenefitCheckRequest:
    fields = {k: v for k, v in (conditions or {}).items() if k in PASSTHROUGH}
    if "residence" not in fields and region_of(residence_code):
        fields["residence"] = region_of(residence_code)
    fields.setdefault("expected_spend_total", body.get("estimated_spend_krw"))
    return BenefitCheckRequest(trip_start=date.fromisoformat(body["start_date"]),
                               trip_end=date.fromisoformat(body["end_date"]), visits=course_visits(body),
                               party_size=body["party_size"], reference_date=today, include_external=True,
                               **fields)


def _step(key: str, title: str, today: date, due: date | None = None, due_text: str | None = None,
          detail: str | None = None, action_url: str | None = None, passed: bool | None = None,
          period: tuple[date, date] | None = None) -> dict:
    return {"key": key, "title": title, "due": due.isoformat() if due else None,
            "d_day": (due - today).days if due else None,
            "due_text": due_text if not due else None,
            "passed": passed if passed is not None else (due < today if due else None),
            "period": {"start": period[0].isoformat(), "end": period[1].isoformat()} if period else None,
            "detail": detail, "action_url": action_url}


def steps(ev: ProgramEvaluation, trip_start: date, trip_end: date, today: date) -> list[dict]:
    """여행 전·중·후 할 일. Unknown deadlines stay null with a 'check the notice' text."""
    tl, how = ev.timeline, ev.how_to_apply
    apply_url = how.application_url or how.official_info_url
    out = []
    if tl.application_period and tl.application_period.end:
        out.append(_step("application_close", "접수 마감", today, due=tl.application_period.end,
                         detail="신청(접수) 기간 끝", action_url=apply_url))
    out.append(_step("pre_apply", "여행 전 · 사전 신청·승인", today, due=tl.pre_apply_deadline,
                     due_text="출발 전까지 · 공고 확인", detail=how.pre_apply_channel, action_url=apply_url,
                     passed=tl.pre_apply_deadline_passed))
    if how.payment_methods:
        out.append(_step("payment", "여행 전 · 결제 수단 준비", today, due=trip_start - timedelta(days=1),
                         detail=", ".join(how.payment_methods)))
    out.append(_step("during", "여행 중 · 결제·증빙 남기기", today, period=(trip_start, trip_end),
                     detail=", ".join(how.proof_items) if how.proof_items else "증빙 항목 공고 확인"))
    out.append(_step("settle", "여행 후 · 정산 신청", today, due=tl.settlement_deadline,
                     due_text="여행 후 · 공고 확인", action_url=apply_url))
    payout = how.payout
    detail = None
    if payout:
        parts = [payout.method, f"사용기한 {payout.voucher_valid_until}" if payout.voucher_valid_until else None,
                 payout.voucher_validity_note]
        detail = " · ".join(p for p in parts if p) or None
    out.append(_step("payout", "환급·사용", today, detail=detail or "지급 방식 공고 확인"))
    return out


def pick_course_program(results: list, program_id: str | None):
    """The course's own program if it was checked, else the first general-visitor result with no unmet condition.

    Results are sorted eligible-first, open-first. Non-travel services never reach `results` (the engine drops
    them); travel support limited to a group (audience 'targeted') and programs with an unmet condition are
    not featured. The verdict is untouched, so 'needs_verification' stays as it is.
    """
    if program_id:
        own = next((r for r in results if r.benefit_id == program_id), None)
        if own is not None:
            return own
    return next((r for r in results if not r.unmet_conditions and getattr(r, "audience", "general") == "general"), None)


def check_course(session: Session, body: dict, program_id: str | None, residence_code: str | None,
                 conditions: dict | None, today: date) -> dict:
    request = course_request(body, residence_code, conditions, today)
    response: BenefitCheckResponse = check_benefits(request, session)
    selected = pick_course_program(response.results, program_id)
    trip_start, trip_end = request.trip_start, request.trip_end
    return {
        "program_id": program_id,
        "selected": None if selected is None else {
            "benefit_id": selected.benefit_id, "name": selected.name, "round_id": selected.round_id,
            "is_course_program": selected.benefit_id == program_id,
            "verdict": selected.verdict, "can_apply_now": selected.can_apply_now,
            "estimate": selected.estimate.model_dump(mode="json"),
            "timeline": selected.timeline.model_dump(mode="json"),
            "missing_user_fields": selected.missing_user_fields,
            "official_checks_needed": selected.official_checks_needed,
            "steps": steps(selected, trip_start, trip_end, today),
        },
        "spend_input": {"total": request.expected_spend_total,
                        "visits": [{"region": v.region.model_dump(), "start_date": v.start_date.isoformat(),
                                    "end_date": v.end_date.isoformat(), "nights": v.nights,
                                    "places": len(v.places or []),
                                    "expected_spend": v.expected_spend.model_dump() if v.expected_spend else None}
                                   for v in request.visits]},
        "check": response.model_dump(mode="json"),
    }
