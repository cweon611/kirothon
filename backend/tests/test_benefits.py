"""Travel benefit check: rule engine, gov24 client, and /api/benefits endpoints.

All gov24 traffic here goes through httpx.MockTransport. These tests prove the
logic, not that the live API works (see VALIDATION notes for live checks).
"""
from datetime import date, datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.team.benefits import gov24, registry
from app.team.benefits.gov24 import Gov24Client, _Cache, get_gov24_client
from app.team.benefits.schemas import (
    AgeRule, BenefitProgram, BenefitRule, CapRule, DateRange, FamilyRule, LodgingCap,
    ParticipationRule, PartyRule, PreApplyRule, Region, ResidenceRule, SourceRef, StayRule,
    VisitRule, YouthRule,
)

KEY = "TEST-SECRET-KEY-DO-NOT-LEAK"
REF = "2026-10-30"


def jn(name):
    return Region(sido="전라남도", sigungu=name)


def verified(**overrides) -> BenefitProgram:
    """A fully confirmed program so each test can relax exactly one rule."""
    base = dict(
        id="manual:test-muan", program_id="test-muan", round_id="r1", provider="전라남도 무안군",
        name="테스트 무안 반값여행", target_regions=[jn("무안군")],
        application_period=DateRange(start=date(2026, 9, 1), end=date(2026, 12, 15)),
        trip_period=DateRange(start=date(2026, 11, 1), end=date(2026, 11, 30)),
        posted_status="open", status_checked_at=datetime(2026, 10, 29, tzinfo=timezone.utc),
        residence_rule=ResidenceRule(excluded_regions=[jn("무안군")]),
        age_rule=AgeRule(min_age=18, basis="full_age_on_trip_start"),
        party_rule=PartyRule(min_size=1, max_size=10),
        family_rule=FamilyRule(requires_family=False, requires_same_address=False),
        participation_rule=ParticipationRule(repeat_allowed=False),
        benefit=BenefitRule(
            benefit_type="local_voucher", refund_rate=0.5, min_spend=100_000, rounding_unit=1000,
            lodging_cap=LodgingCap(applies=False),
            caps=[CapRule(label="개인", amount=100_000, per="group", max_party_size=1),
                  CapRule(label="팀", amount=200_000, per="group", min_party_size=2)],
            eligible_spend=["lodging", "food", "cafe", "experience", "admission"],
            excluded_spend=["transport"],
        ),
        visit_rule=VisitRule(must_include=["무안황토갯벌랜드"], min_total_places=2),
        stay_rule=StayRule(min_nights=1, checkin_weekdays=[0, 1, 2, 3, 4], checkin_scope="all"),
        pre_apply=PreApplyRule(required=True, days_before_trip=5, channel="테스트 누리집"),
        settlement_days_after_trip=7,
        official_info_url="https://example.go.kr/notice", application_url="https://example.go.kr/apply",
        source_type="official_notice",
        sources=[SourceRef(source_type="official_notice", url="https://example.go.kr/notice")],
        verification_status="verified", last_verified_at=datetime(2026, 10, 29, tzinfo=timezone.utc),
    )
    base.update(overrides)
    return BenefitProgram(**base)


def visit(sigungu="무안군", start="2026-11-10", end="2026-11-11", **kw):
    v = {"region": {"sido": "전라남도", "sigungu": sigungu}, "start_date": start, "end_date": end,
         "nights": 1, "places": ["무안황토갯벌랜드", "회산백련지"],
         "expected_spend": {"by_category": {"lodging": 100_000, "food": 96_000}}}
    v.update(kw)
    return v


def body(**kw):
    b = {"departure": {"sido": "광주광역시", "sigungu": "북구"},
         "residence": {"sido": "광주광역시", "sigungu": "북구"},
         "trip_start": "2026-11-10", "trip_end": "2026-11-11", "party_size": 2,
         "birth_date": "1990-05-05", "is_family": False, "same_address": False,
         "prior_participated_program_ids": [], "visits": [visit()],
         "reference_date": REF, "include_external": False}
    b.update(kw)
    return b


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv(gov24.ENV_SERVICE_KEY, raising=False)
    monkeypatch.setattr(registry, "_ENTRIES", [verified()])
    gov24.clear_cache()
    with TestClient(app) as value:
        yield value
    app.dependency_overrides.clear()


def use_programs(monkeypatch, *programs):
    monkeypatch.setattr(registry, "_ENTRIES", list(programs))


def check(client, **kw):
    r = client.post("/api/benefits/check", json=body(**kw))
    assert r.status_code == 200, r.text
    return r.json()


def only(data, benefit_id="manual:test-muan"):
    return next(x for x in data["results"] if x["benefit_id"] == benefit_id)


def codes(result, bucket):
    return {c["code"] for c in result[bucket]}


# ------------------------------------------------------------------ baseline
def test_fully_confirmed_program_is_potentially_eligible(client):
    data = check(client)
    r = only(data)
    assert r["verdict"] == "potentially_eligible"
    assert r["can_apply_now"] is True
    assert r["unmet_conditions"] == [] and r["unresolved_conditions"] == []
    est = r["estimate"]
    assert est["recognized_spend"] == 196_000 and est["amount"] == 98_000
    assert est["amount_kind"] == "calculated" and est["cap_label"] == "팀"
    assert r["timeline"]["pre_apply_deadline"] == "2026-11-05"
    assert r["timeline"]["settlement_deadline"] == "2026-11-18"
    assert r["how_to_apply"]["application_url"] == "https://example.go.kr/apply"
    assert data["sources"][0]["status"] == "skipped"


# ------------------------------------------------------------------ 1. trip period boundary
@pytest.mark.parametrize("start,end,verdict,status", [
    ("2026-11-29", "2026-11-30", "potentially_eligible", "met"),          # ends exactly on last day
    ("2026-11-30", "2026-12-01", "needs_verification", "unconfirmed_program_rule"),  # crosses end
    ("2026-12-01", "2026-12-02", "ineligible", "unmet"),                   # fully outside
])
def test_trip_period_boundaries(client, monkeypatch, start, end, verdict, status):
    # 2026-11-29 is a Sunday: drop the weekday rule so only the period is tested.
    use_programs(monkeypatch, verified(stay_rule=StayRule(min_nights=1, checkin_weekdays=None)))
    data = check(client, trip_start=start, trip_end=end,
                 visits=[visit(start=start, end=end, checkin_dates=[start])])
    r = only(data)
    trip = next(c for bucket in ("met_conditions", "unmet_conditions", "unresolved_conditions")
                for c in r[bucket] if c["code"] == "trip_period")
    assert trip["status"] == status
    assert r["verdict"] == verdict


# ------------------------------------------------------------------ 2. excluded residence
def test_excluded_residence_is_ineligible(client):
    r = only(check(client, residence={"sido": "전남", "sigungu": "무안군"}))
    assert r["verdict"] == "ineligible"
    assert "residence" in codes(r, "unmet_conditions")
    assert r["estimate"]["amount"] is None


def test_departure_is_not_treated_as_residence(client):
    r = only(check(client, departure={"sido": "전라남도", "sigungu": "무안군"}))
    assert r["verdict"] == "potentially_eligible"


def test_residence_of_visited_region_excluded(client, monkeypatch):
    use_programs(monkeypatch, verified(
        target_regions=[jn("무안군"), jn("여수시")],
        residence_rule=ResidenceRule(exclude_scope="visited_target_regions")))
    r = only(check(client, residence={"sido": "전라남도", "sigungu": "무안군"}))
    assert r["verdict"] == "ineligible"
    r = only(check(client, residence={"sido": "전라남도", "sigungu": "여수시"}))
    assert r["verdict"] == "potentially_eligible"


def test_residence_without_sigungu_needs_input(client):
    r = only(check(client, residence={"sido": "전라남도"}))
    assert r["verdict"] == "needs_verification"
    assert "residence.sigungu" in r["missing_user_fields"]


# ------------------------------------------------------------------ 3. youth basis date
YOUTH = YouthRule(min_age=19, max_age=34)
# Turns 35 on 2026-11-05: 34 on the application date (10-30), 35 on trip start (11-10).
BIRTH = "1991-11-05"


@pytest.mark.parametrize("basis,rate,amount", [
    ("full_age_on_application_date", 0.7, 137_000),
    ("full_age_on_trip_start", 0.5, 98_000),
])
def test_youth_rate_depends_on_basis(client, monkeypatch, basis, rate, amount):
    use_programs(monkeypatch, verified(
        youth_rule=YOUTH.model_copy(update={"basis": basis}),
        benefit=verified().benefit.model_copy(update={"youth_refund_rate": 0.7})))
    r = only(check(client, birth_date=BIRTH))
    assert r["estimate"]["refund_rate"] == rate
    assert r["estimate"]["amount"] == amount


def test_youth_basis_unknown_gives_null_amount(client, monkeypatch):
    use_programs(monkeypatch, verified(
        youth_rule=YOUTH, benefit=verified().benefit.model_copy(update={"youth_refund_rate": 0.7})))
    r = only(check(client, birth_date=BIRTH))
    assert r["estimate"]["amount"] is None
    assert "청년 환급률 적용 여부 판단 불가" in r["estimate"]["unavailable_reasons"]


def test_age_rule_basis_unknown_and_result_differs(client, monkeypatch):
    use_programs(monkeypatch, verified(age_rule=AgeRule(max_age=34, basis=None)))
    r = only(check(client, birth_date=BIRTH))
    age = next(c for c in r["unresolved_conditions"] if c["code"] == "age")
    assert age["status"] == "unconfirmed_program_rule"
    assert r["verdict"] == "needs_verification"


def test_age_only_input_near_birthday_asks_for_birth_date(client, monkeypatch):
    use_programs(monkeypatch, verified(age_rule=AgeRule(max_age=34, basis="full_age_on_trip_start")))
    r = only(check(client, birth_date=None, age=34))
    assert "birth_date" in r["missing_user_fields"]
    r = only(check(client, birth_date=None, age=30))
    assert "age" in codes(r, "met_conditions")


# ------------------------------------------------------------------ 4. missing info
def test_missing_user_fields_are_reported_not_guessed(client):
    data = check(client, residence=None, party_size=None, birth_date=None,
                 prior_participated_program_ids=None, visits=[visit(places=None)])
    r = only(data)
    assert r["verdict"] == "needs_verification"
    for f in ("residence", "party_size", "birth_date", "prior_participated_program_ids", "visits[0].places"):
        assert f in data["missing_fields"], f
    assert data["outcome"] == "insufficient_information"
    assert r["estimate"]["amount"] is None


def test_missing_program_rule_is_not_treated_as_no_limit(client, monkeypatch):
    use_programs(monkeypatch, verified(residence_rule=None, party_rule=None))
    r = only(check(client))
    assert {"residence", "party_size"} <= codes(r, "unresolved_conditions")
    assert r["verdict"] == "needs_verification"
    assert r["can_apply_now"] is True  # application timing itself is confirmed


def test_unverified_source_never_ineligible_or_eligible(client, monkeypatch):
    use_programs(monkeypatch, verified(verification_status="unverified", source_type="news_report"))
    r = only(check(client, residence={"sido": "전라남도", "sigungu": "무안군"}))
    assert r["verdict"] == "needs_verification"
    assert "residence" in codes(r, "unmet_conditions")
    assert any("미검증 자료 기준 불충족" in s for s in r["official_checks_needed"])


# ------------------------------------------------------------------ 5. deadlines
def test_application_closed(client, monkeypatch):
    use_programs(monkeypatch, verified(application_period=DateRange(start=date(2026, 9, 1), end=date(2026, 10, 29))))
    r = only(check(client))
    assert r["verdict"] == "ineligible" and r["can_apply_now"] is False
    assert r["timeline"]["application_closed"] is True


@pytest.mark.parametrize("status", ["closed_early", "budget_exhausted", "ended"])
def test_posted_closed_status(client, monkeypatch, status):
    use_programs(monkeypatch, verified(posted_status=status))
    r = only(check(client))
    assert r["verdict"] == "ineligible" and r["can_apply_now"] is False


@pytest.mark.parametrize("trip_start,passed", [("2026-11-03", True), ("2026-11-04", False)])
def test_pre_apply_deadline_inclusive(client, trip_start, passed):
    end = "2026-11-05"
    data = check(client, trip_start=trip_start, trip_end=end,
                 visits=[visit(start=trip_start, end=end, nights=None, checkin_dates=None)])
    r = only(data)
    assert r["timeline"]["pre_apply_deadline_passed"] is passed
    if passed:
        assert "pre_apply" in codes(r, "unmet_conditions") and r["can_apply_now"] is False
    else:
        assert "pre_apply" in codes(r, "met_conditions")


def test_pre_apply_basis_ambiguous_for_later_region(client):
    # whole trip starts 11-03 (deadline 10-29 passed) but 무안 visit starts 11-05 (deadline 10-31)
    data = check(client, trip_start="2026-11-03", trip_end="2026-11-06",
                 visits=[visit("장흥군", "2026-11-03", "2026-11-05", nights=2),
                         visit(start="2026-11-05", end="2026-11-06", checkin_dates=["2026-11-05"])])
    pre = next(c for c in only(data)["unresolved_conditions"] if c["code"] == "pre_apply")
    assert pre["status"] == "unconfirmed_program_rule"


def test_stale_status_requires_recheck(client, monkeypatch):
    use_programs(monkeypatch, verified(status_checked_at=datetime(2026, 10, 1, tzinfo=timezone.utc)))
    r = only(check(client))
    assert any("오래됨" in s for s in r["official_checks_needed"])


# ------------------------------------------------------------------ 6. multi-region
def test_multi_region_matches_each_program_to_its_region(client, monkeypatch):
    yeosu = verified(id="manual:test-yeosu", program_id="test-yeosu", name="테스트 여수",
                     target_regions=[jn("여수시")], residence_rule=ResidenceRule(excluded_regions=[]),
                     visit_rule=VisitRule())
    use_programs(monkeypatch, verified(), yeosu)
    data = check(client, trip_start="2026-11-10", trip_end="2026-11-13", visits=[
        visit(),
        visit("여수시", "2026-11-11", "2026-11-13", nights=2, places=["오동도"],
              expected_spend={"by_category": {"lodging": 300_000, "food": 100_000}}),
    ])
    muan, ys = only(data), only(data, "manual:test-yeosu")
    assert [m["region"]["sigungu"] for m in muan["matched_visits"]] == ["무안군"]
    assert [m["region"]["sigungu"] for m in ys["matched_visits"]] == ["여수시"]
    assert muan["estimate"]["recognized_spend"] == 196_000
    assert ys["estimate"]["recognized_spend"] == 400_000 and ys["estimate"]["amount"] == 200_000
    assert data["combined_estimate"]["amount"] is None  # stacking not confirmed
    assert len(data["scope"]["visits"]) == 2


def test_combined_only_when_stacking_confirmed(client, monkeypatch):
    a = verified(stackable_with=["manual:test-yeosu"])
    b = verified(id="manual:test-yeosu", program_id="test-yeosu", target_regions=[jn("여수시")],
                 residence_rule=ResidenceRule(excluded_regions=[]), visit_rule=VisitRule(),
                 stackable_with=["manual:test-muan"])
    use_programs(monkeypatch, a, b)
    data = check(client, trip_start="2026-11-10", trip_end="2026-11-13", visits=[
        visit(), visit("여수시", "2026-11-12", "2026-11-13")])
    assert data["combined_estimate"]["amount"] == 98_000 * 2


def test_unmatched_region_returns_no_match_not_absence(client):
    data = check(client, visits=[visit("담양군")])
    assert data["results"] == []
    assert data["outcome"] == "no_match_in_scope"
    assert "없다는 뜻이 아닙니다" in data["coverage_note"]


# ------------------------------------------------------------------ 7. estimate limits
def test_estimate_null_when_eligible_spend_unknown(client, monkeypatch):
    use_programs(monkeypatch, verified(benefit=verified().benefit.model_copy(update={"eligible_spend": None})))
    est = only(check(client))["estimate"]
    assert est["amount"] is None and "인정 지출 항목 미확인" in est["unavailable_reasons"]


def test_estimate_null_when_caps_unknown(client, monkeypatch):
    use_programs(monkeypatch, verified(benefit=verified().benefit.model_copy(update={"caps": None})))
    est = only(check(client))["estimate"]
    assert est["amount"] is None and "지원 상한 미확인" in est["unavailable_reasons"]


def test_estimate_null_when_min_spend_unknown(client, monkeypatch):
    use_programs(monkeypatch, verified(benefit=verified().benefit.model_copy(update={"min_spend": None})))
    est = only(check(client))["estimate"]
    assert est["amount"] is None and "최소 인정 소비액 미확인" in est["unavailable_reasons"]


def test_total_budget_is_not_multiplied_by_rate(client):
    est = only(check(client, expected_spend_total=500_000, visits=[visit(expected_spend=None)]))["estimate"]
    assert est["amount"] is None
    assert any("항목별" in x for x in est["unavailable_reasons"])


def test_excluded_spend_shortfall_and_cap(client):
    est = only(check(client, visits=[visit(expected_spend={"by_category": {"food": 60_000, "transport": 90_000}})]))["estimate"]
    assert est["recognized_spend"] == 60_000 and est["amount"] == 0
    assert est["shortfall_to_min_spend"] == 40_000
    est = only(check(client, visits=[visit(expected_spend={"by_category": {"lodging": 900_000}})]))["estimate"]
    assert est["amount"] == 200_000  # capped


def test_rounding_and_lodging_cap(client, monkeypatch):
    b = verified().benefit.model_copy(update={"lodging_cap": LodgingCap(applies=True, amount_per_night=80_000)})
    use_programs(monkeypatch, verified(benefit=b))
    est = only(check(client, visits=[visit(expected_spend={"by_category": {"lodging": 150_000, "food": 33_300}})]))["estimate"]
    assert est["recognized_spend"] == 113_300
    assert est["amount"] == 56_000  # 56,650 floored to 1,000


def test_unknown_rounding_marks_upper_bound(client, monkeypatch):
    use_programs(monkeypatch, verified(benefit=verified().benefit.model_copy(update={"rounding_unit": None})))
    est = only(check(client))["estimate"]
    assert est["amount"] == 98_000 and est["amount_kind"] == "upper_bound"


def test_ambiguous_cap_tier_returns_null(client, monkeypatch):
    caps = [CapRule(label="2인 이상", amount=200_000, per="group", min_party_size=2),
            CapRule(label="가족", amount=500_000, per="group", min_party_size=2, family=True)]
    use_programs(monkeypatch, verified(benefit=verified().benefit.model_copy(update={"caps": caps})))
    est = only(check(client, is_family=True))["estimate"]
    assert est["amount"] is None and any("여러 개" in x for x in est["unavailable_reasons"])


def test_stay_weekday_rule(client):
    # 2026-11-14 is a Saturday
    r = only(check(client, trip_start="2026-11-14", trip_end="2026-11-15",
                   visits=[visit(start="2026-11-14", end="2026-11-15")]))
    assert "stay" in codes(r, "unmet_conditions") and r["verdict"] == "ineligible"


def test_prior_participation(client):
    r = only(check(client, prior_participated_program_ids=["test-muan"]))
    assert "participation" in codes(r, "unmet_conditions")


# ------------------------------------------------------------------ registry / validation
def test_seed_registry_entries_are_unverified():
    for p in registry._ENTRIES:
        assert p.verification_status == "unverified"
        assert p.unverified_fields


def test_request_validation(client):
    assert client.post("/api/benefits/check", json=body(trip_end="2026-11-01")).status_code == 422
    assert client.post("/api/benefits/check", json=body(visits=[visit(start="2026-11-20", end="2026-11-21")])).status_code == 422
    assert client.post("/api/benefits/check", json=body(visits=[])).status_code == 422
