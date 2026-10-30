"""F1 grouping/scoring and F2 itinerary rules on synthetic data (requirements 1-2)."""
from datetime import date

from fastapi import HTTPException

from app.team import regions as regions_mod
from app.team import tourism_data
from app.team.benefit_port import BenefitLookup
from app.team.planner import (build_course, closed_on, opening_window, order_places, parse_minutes,
                              path_cost)
from app.team.reasons import generate_for_day, parse_output, rule_sentence
from app.team.recommend import TripQuery, recommend
from app.team.regions import origins

from course_fixtures import DONGGU, HAMPYEONG, MUAN, SINAN, lite, program, snapshot

TODAY = date(2026, 11, 2)
MON, TUE, FRI, SAT = date(2026, 11, 9), date(2026, 11, 10), date(2026, 11, 13), date(2026, 11, 14)


def trip(trip_type="1N2D", start=TUE, origin="gj-buk", interests=("nature",), party=2, transport="car"):
    return TripQuery(trip_type, start, origin, list(interests), party, transport)


def lookup(by_region=None, status="ok", alternatives=()):
    return BenefitLookup(status, "2026-10-30T09:00:00+09:00", {k: tuple(v) for k, v in (by_region or {}).items()},
                         scope_note="테스트 범위", alternatives=tuple(alternatives))


def run_recommend(query=None, look=None, snap=None):
    query = query or trip()
    return recommend(snap or snapshot(), query, origins()[query.origin], look or lookup())


# ---------- F1 ----------

def test_refund_group_first_even_with_lower_score():
    result = run_recommend(look=lookup({MUAN: [program()]}))
    regions = result["regions"]
    assert regions[0]["sigungu_code"] == MUAN and regions[0]["group"] == 1
    hampyeong = next(r for r in regions if r["sigungu_code"] == HAMPYEONG)
    assert hampyeong["group"] == 2 and hampyeong["score"] > regions[0]["score"]
    assert regions[0]["refund"]["badge"] == "applicable"
    assert result["no_refund_notice"] is None


def test_excluded_residence_is_not_group_one():
    excluded = program(judgment="ineligible")
    regions = run_recommend(look=lookup({MUAN: [excluded]}))["regions"]
    muan = next(r for r in regions if r["sigungu_code"] == MUAN)
    assert muan["group"] == 2 and muan["refund"]["badge"] == "ineligible"


def test_closed_application_badge_and_not_first():
    regions = run_recommend(look=lookup({MUAN: [program(application_open=False)]}))["regions"]
    muan = next(r for r in regions if r["sigungu_code"] == MUAN)
    assert muan["group"] == 2 and muan["refund"]["badge"] == "closed"
    assert regions[0]["sigungu_code"] != MUAN


def test_needs_verification_stays_in_group_one_with_badge():
    regions = run_recommend(look=lookup({MUAN: [program(judgment="needs_verification")]}))["regions"]
    assert regions[0]["sigungu_code"] == MUAN and regions[0]["refund"]["badge"] == "needs_verification"


def test_day_trip_with_overnight_program_is_needs_stay():
    regions = run_recommend(trip("day"), lookup({MUAN: [program(min_nights=1)]}))["regions"]
    muan = next(r for r in regions if r["sigungu_code"] == MUAN)
    assert muan["group"] == 2 and muan["refund"]["badge"] == "needs_stay"
    only_stay = program(judgment="ineligible", unmet_codes=("stay",), min_nights=1)
    regions = run_recommend(trip("day"), lookup({MUAN: [only_stay]}))["regions"]
    assert next(r for r in regions if r["sigungu_code"] == MUAN)["refund"]["badge"] == "needs_stay"
    also_residence = program(judgment="ineligible", unmet_codes=("stay", "residence"), min_nights=1)
    regions = run_recommend(trip("day"), lookup({MUAN: [also_residence]}))["regions"]
    assert next(r for r in regions if r["sigungu_code"] == MUAN)["refund"]["badge"] == "ineligible"


def test_unmet_condition_on_unverified_data_is_not_a_refund_region():
    unverified_unmet = program(judgment="needs_verification", application_open=None, unmet_codes=("trip_period",))
    regions = run_recommend(look=lookup({MUAN: [unverified_unmet]}))["regions"]
    muan = next(r for r in regions if r["sigungu_code"] == MUAN)
    assert muan["group"] == 2 and muan["refund"]["badge"] == "unmet_unverified"


def test_regions_without_cached_data_are_skipped():
    result = run_recommend(look=lookup({"46800": [program(pid="jangheung", codes=("46800",))]}))
    assert "46800" not in [r["sigungu_code"] for r in result["regions"]]
    assert result["excluded_no_data"] == 27 - 4
    assert all(r["travel_min"] is not None for r in result["regions"])


def test_lookup_failure_is_not_reported_as_no_program():
    failed = run_recommend(look=lookup(status="error"))
    assert failed["no_refund_notice"]["code"] == "benefit_lookup_failed"
    assert all(r["group"] == 2 and r["refund"] is None for r in failed["regions"])
    unplugged = run_recommend(look=BenefitLookup("not_connected"))
    assert unplugged["no_refund_notice"]["code"] == "benefit_not_connected"
    empty = run_recommend(look=lookup({}, alternatives=[program(pid="next_round")]))
    assert empty["no_refund_notice"]["code"] == "no_applicable_program_in_scope"
    assert empty["no_refund_notice"]["nearest_program"]["program_id"] == "next_round"
    assert empty["no_refund_notice"]["scope_note"] == "테스트 범위"


def test_partial_lookup_marks_unchecked_regions_unknown():
    regions = run_recommend(look=lookup({MUAN: [program()]}, status="partial"))["regions"]
    assert regions[0]["sigungu_code"] == MUAN and regions[0]["group"] == 1
    others = [r for r in regions if r["sigungu_code"] != MUAN]
    assert all(r["refund"] is None for r in others)


def test_travel_cap_excludes_far_regions_and_tags_and_determinism():
    query = trip("day", origin="st-yeosuexpo")
    first = run_recommend(query)
    assert SINAN not in [r["sigungu_code"] for r in first["regions"]]
    assert first["excluded_by_travel_cap"] >= 1
    assert all(len(r["reason_tags"]) >= 2 for r in first["regions"])
    assert run_recommend(query) == first


def test_candidates_carry_evidence_and_interest_filter():
    regions = run_recommend(trip(interests=("history",)), lookup({MUAN: [program()]}))["regions"]
    muan = regions[0]
    assert muan["candidates"][0]["evidence"] == "무안군 중심 관광지 2위"
    assert {c["category"] for c in muan["candidates"]} == {"문화시설"}


def test_demo_data_fills_thin_regions(monkeypatch):
    demo = [{"content_id": f"demo-{i}", "title": f"테스트시연{i}", "sigungu_code": "46800", "content_type_id": "12",
             "lat": 34.68 + i * 0.01, "lng": 126.9} for i in range(5)]
    monkeypatch.setattr(tourism_data, "demo_places", lambda: demo)
    snap = snapshot()
    tourism_data._fill_demo(snap)
    assert "46800" in snap.demo_filled and len(snap.spots("46800")) == 5
    assert MUAN not in snap.demo_filled
    assert all(p.source == "demo" for p in snap.spots("46800"))


# ---------- F2 ----------

def course(query, prog=None, status="ok", snap=None, fixed=None):
    return build_course(snap or snapshot(), query, origins()[query.origin], MUAN, prog, status, TODAY, fixed=fixed)


def items(body, kind=None):
    return [i for d in body["days"] for i in d["items"] if kind is None or i["kind"] == kind]


def minutes(hhmm):
    return int(hhmm[:2]) * 60 + int(hhmm[3:])


def test_day_trip_ends_by_19_and_links_gwangju_first():
    body = course(trip("day", start=TUE))
    day = body["days"][0]
    assert minutes(day["items"][-1]["end"]) <= 19 * 60
    assert day["items"][0]["place"]["sigungu_code"] == DONGGU
    assert "광주 문화관광" in day["items"][0]["reason_tags"]
    assert [i["meal"] for i in items(body, "meal")][0] == "lunch"
    assert all(i["reason_tags"] and i["reason_text"] for i in day["items"])


def test_long_moves_are_flagged():
    body = course(trip("day", start=TUE))
    moves = [i for i in items(body) if i["move_min_from_prev"] > 40]
    assert moves and all(i["move_warning"] for i in moves)
    assert all(not i["move_warning"] for i in items(body) if i["move_min_from_prev"] <= 40)


def test_closed_weekday_place_is_skipped_and_unknown_is_flagged():
    monday = course(trip("day", start=MON))
    ids = {i["place"]["content_id"] for i in items(monday, "spot")}
    assert "m1" not in ids  # 매주 월요일 휴무
    tuesday = course(trip("1N2D", start=TUE))
    spots = {i["place"]["content_id"]: i for i in items(tuesday, "spot")}
    assert "m1" in spots and not spots["m1"]["check_before_visit"]
    flagged = [i for i in spots.values() if i["place"]["content_id"] in ("m4", "m6")]
    assert flagged and all(i["check_before_visit"] for i in flagged)


def test_spots_wait_for_opening_and_out_of_hours_are_replaced():
    early = lite("m8", "테스트새벽시장", MUAN, 34.975, 126.495, restdate="연중무휴", usetime="05:00~08:00")
    body = course(trip("1N2D", start=TUE), snap=snapshot([early]))
    assert "m8" not in {i["place"]["content_id"] for i in items(body, "spot")}
    link = body["days"][0]["items"][0]
    assert link["place"]["content_id"] == "g1" and link["start"] == "10:00"
    assert link["check_reasons"] == []


def test_overnight_stays_in_refund_region_and_day2_returns_by_17():
    body = course(trip("1N2D", start=TUE), program(), "ok")
    stay = items(body, "stay")[0]
    assert stay["place"]["sigungu_code"] == MUAN and stay["in_refund_region"]
    assert stay["refund_note"] == "영수증 보관"
    assert minutes(body["days"][1]["return_depart"]) <= 17 * 60
    assert body["region"]["refund_program_id"] == "muan_test"
    day1 = [i for i in body["days"][0]["items"] if i["end"]]
    idle = [minutes(b["start"]) - b["move_min_from_prev"] - minutes(a["end"]) for a, b in zip(day1, day1[1:])]
    assert max(idle) < 120, "a spare nearby spot fills a 2h+ gap before dinner"


def test_required_place_is_pinned_and_not_swappable():
    prog = program(required_place_names=("테스트승달산", "없는 테스트장소"), min_spots=2)
    body = course(trip("1N2D", start=TUE), prog)
    pinned = [i for i in items(body, "spot") if i["place"]["content_id"] == "m4"]
    assert pinned and pinned[0]["required"] and not pinned[0]["swappable"]
    assert any(w["code"] == "required_place_unmatched" for w in body["warnings"])


def test_any_of_places_rule_pins_one_target_or_warns():
    body = course(trip("1N2D", start=TUE), program(any_of_place_names=("없는 테스트섬", "테스트연꽃방죽"), min_any_of=1))
    pinned = [i for i in items(body, "spot") if i["place"]["content_id"] == "m2"]
    assert pinned and pinned[0]["required"]
    missing = course(trip("1N2D", start=TUE), program(any_of_place_names=("없는 테스트섬",), min_any_of=1))
    assert any(w["code"] == "required_any_unmatched" for w in missing["warnings"])


def test_spend_items_carry_benefit_categories():
    body = course(trip("1N2D", start=TUE))
    categories = {i["category"] for i in body["spend_breakdown"]["items"]}
    assert {"food", "lodging"} <= categories <= {"food", "lodging", "admission"}


def test_name_variants_and_address_resolution():
    from app.team.regions import name_variants, sigungu_from_address
    assert "식영정" in name_variants("무안식영정", MUAN)
    assert name_variants("톱머리해변", MUAN) & name_variants("톱머리 해수욕장", MUAN)
    assert name_variants("홀통해변", MUAN) <= name_variants("홀통유원지·홀통해변", MUAN)
    assert "롯데아울렛" in name_variants("롯데아울렛/남악점", MUAN)
    assert "구" not in name_variants("동구청", DONGGU) and "동구청" in name_variants("동구청", DONGGU)
    assert sigungu_from_address("전라남도 무안군 망운면 1") == MUAN
    assert sigungu_from_address("전남광주통합특별시 무안군 현경면") == MUAN
    assert sigungu_from_address("광주광역시 동구 문화전당로 38") == DONGGU
    assert sigungu_from_address("부산광역시 동구 중앙대로") is None
    assert sigungu_from_address("전라북도 무안군") is None


def test_stay_weekday_rule_warns_and_suggests_date():
    prog = program(stay_checkin_weekdays=(0, 1, 2, 3, 4))
    body = course(trip("1N2D", start=SAT), prog)
    warning = next(w for w in body["warnings"] if w["code"] == "stay_weekday")
    assert warning["suggested_date"] == FRI.isoformat()
    assert not any(w["code"] == "stay_weekday" for w in course(trip("1N2D", start=TUE), prog)["warnings"])


def test_unchecked_benefits_are_reported_not_assumed():
    body = course(trip("1N2D", start=TUE), None, "not_connected")
    assert any(w["code"] == "benefit_unchecked" for w in body["warnings"])
    assert all(not i["in_refund_region"] for i in items(body))
    assert body["estimated_refund_krw"] is None


def test_transit_multiplies_and_notes():
    car = course(trip("day", start=TUE))
    transit = course(trip("day", start=TUE, transport="transit"))
    assert transit["days"][0]["items"][0]["move_min_from_prev"] > car["days"][0]["items"][0]["move_min_from_prev"]
    assert all(i["transit_note"] == "실제 배차 확인" for i in items(transit))


def test_spend_breakdown_uses_party_meals_and_default_room():
    body = course(trip("1N2D", start=TUE, party=2))
    meals = items(body, "meal")
    spend = body["spend_breakdown"]
    assert sum(i["krw"] for i in spend["items"] if "명 ×" in i["label"]) == len(meals) * 2 * 12_000
    assert any(i["label"].startswith("숙박") and i["krw"] == 100_000 and i["basis"] == "default" for i in spend["items"])
    assert any(i["basis"] == "tourapi_usefee" and i["krw"] == 4_000 for i in spend["items"]) or \
        "m3" not in {i["place"]["content_id"] for i in items(body, "spot")}
    assert body["estimated_spend_krw"] == spend["total_krw"] == sum(spend["by_sigungu"].values())


def test_fixed_plan_keeps_given_spots():
    fixed = {1: ["m2", "m5"]}
    body = course(trip("day", start=TUE), fixed=fixed)
    assert [i["place"]["content_id"] for i in items(body, "spot")] == ["m2", "m5"]


def test_two_opt_removes_crossing():
    start = (0.0, 0.0)
    square = [lite("a", "a", MUAN, 0.0, 1.0), lite("c", "c", MUAN, 1.0, 0.0),
              lite("b", "b", MUAN, 1.0, 1.0), lite("d", "d", MUAN, 0.0, 2.0)]
    route = order_places(start, square)
    assert path_cost(start, route) <= path_cost(start, square)
    assert len(route) == 4


def test_text_parsers():
    assert closed_on(lite("p", "p", MUAN, 0, 0, restdate="매주 월, 화요일"), TUE) is True
    assert closed_on(lite("p", "p", MUAN, 0, 0, restdate="매주 월요일 (공휴일 다음날)"), TUE) is None
    assert closed_on(lite("p", "p", MUAN, 0, 0, restdate="연중무휴"), MON) is False
    assert closed_on(lite("p", "p", MUAN, 0, 0), MON) is None
    assert opening_window(lite("p", "p", MUAN, 0, 0, usetime="하절기 09:00~18:00 / 동절기 09:00~17:00")) is None
    assert opening_window(lite("p", "p", MUAN, 0, 0, usetime="09:00~18:00")) == (540, 1080)
    assert parse_minutes("1시간 30분") == 90 and parse_minutes("약 2시간") == 120 and parse_minutes("") is None


# ---------- reasons ----------

def test_rule_sentence_and_ai_output_filtering():
    assert rule_sentence(["이전 장소에서 5분", "환급 지역", "관심 분야: 자연·바다"]) == "환급 지역 · 관심 분야: 자연·바다"
    parsed = parse_output("1. 갯벌을 걸으며 노을을 보는 곳\n2. 입장료 2,000원으로 즐기는 박물관\n"
                          "3. " + "가" * 31 + "\nfoo\n4) 연꽃이 피는 방죽 산책", 4)
    assert parsed == {1: "갯벌을 걸으며 노을을 보는 곳", 4: "연꽃이 피는 방죽 산책"}


def test_ai_reasons_mock_failure_quota_and_reuse():
    body = course(trip("1N2D", start=TUE))
    calls = []

    def mock(text, instruction, model):
        calls.append(text)
        assert len(text) <= 4000 and len(instruction) <= 300
        return {"mode": "mock", "text": "[로컬 모의 응답 — 실제 AI 결과가 아닙니다]"}

    state, n, status = generate_for_day(body, {}, 1, 0, {}, generate=mock)
    assert (n, status) == (1, "mock")
    assert {v["by"] for v in state["texts"].values()} == {"mock"}
    state, n, status = generate_for_day(body, state, 1, n, {}, generate=mock)
    assert (n, status, len(calls)) == (1, "stored", 1)

    def throttled(*args):
        raise HTTPException(429, "AI 호출 한도 초과")

    state, n, status = generate_for_day(body, state, 2, n, {}, generate=throttled)
    assert (n, status) == (2, "failed") and state["days"]["2"] == "rule"
    state, n, status = generate_for_day(body, {"days": {}}, 1, 2, {}, generate=mock)
    assert status == "quota" and len(calls) == 1


def test_interest_codes_from_sync_take_precedence():
    codes = {"lcls": {"nature": {"lcls1": ["NA"]}}}
    nature = regions_mod.interests()["nature"]
    assert regions_mod.place_matches_interest("14", "NA", None, nature, codes)
    assert not regions_mod.place_matches_interest("12", "HS", None, nature, codes)
    assert regions_mod.place_matches_interest("12", None, None, nature, {})
