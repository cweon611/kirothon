"""HTTP contract of /api/team/* for the frontend (validation, storage, swap, reasons, privacy)."""
import json

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.database import engine
from app.main import app
from app.team import benefit_port
from app.team.benefit_bridge import BenefitsEnginePort
from app.team.benefits.store_models import (BenefitRecordVersion, BenefitSourceRecord, BenefitSyncRun,
                                            BenefitSyncState)
from app.team.tourism_models import Course, HubRank, Place, RelatedPlace, TourismSyncRun

from course_fixtures import MUAN, FakePort, hub_rows, place_rows, program, related_rows

TRIP = {"trip_type": "1N2D", "start_date": "2026-11-10", "origin": "gj-buk", "interests": ["nature"],
        "party_size": 2}
RESIDENCE = "29170"
MUAN_PROGRAM = "manual:muan-halfprice-2026"  # benefits module's manual registry entry
TABLES = (Place, HubRank, RelatedPlace, Course, TourismSyncRun,
          BenefitSourceRecord, BenefitRecordVersion, BenefitSyncRun, BenefitSyncState)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("TEAM_TODAY", "2026-11-02")
    monkeypatch.delenv("TOURAPI_SERVICE_KEY", raising=False)
    monkeypatch.delenv("KIROTHON_DATA_GO_KR_SERVICE_KEY", raising=False)
    previous = benefit_port.get_benefit_port()
    with TestClient(app) as test_client:
        with Session(engine) as session:
            for model in TABLES:
                for row in session.exec(select(model)).all():
                    session.delete(row)
            session.add_all(place_rows() + hub_rows() + related_rows())
            session.add(TourismSyncRun(status="success", base_ym_hub="202410", base_ym_related="202410"))
            session.commit()
        yield test_client
    benefit_port.set_benefit_port(previous)


@pytest.fixture
def port():
    fake = FakePort({MUAN: [program(required_place_names=("테스트승달산",))]})
    benefit_port.set_benefit_port(fake)
    return fake


def test_meta_lists_inputs_and_data_status(client):
    benefit_port.set_benefit_port(benefit_port.NotConnectedBenefitPort())
    data = client.get("/api/team/meta").json()
    assert data["today"] == "2026-11-02" and data["today_fixed"] is True
    assert {o["key"] for o in data["origins"]} >= {"gj-buk", "st-mokpo"}
    assert [i["key"] for i in data["interests"]] == ["nature", "history", "food", "activity", "healing"]
    assert sum(len(g["sigungu"]) for g in data["trip_regions"]) == 27
    assert data["tourism_data"]["places"] > 0 and data["tourism_data"]["status"] == "ready"
    assert data["benefit_port"]["connected"] is False


@pytest.mark.parametrize("patch", [{"interests": ["nature", "history", "food", "activity"]},
                                   {"interests": []}, {"interests": ["nature", "nature"]},
                                   {"start_date": "2026-11-01"}, {"origin": "seoul"}, {"party_size": 0},
                                   {"trip_type": "3N4D"}, {"unknown": 1}])
def test_validation_returns_422(client, patch):
    assert client.post("/api/team/recommend", json={**TRIP, **patch}).status_code == 422


def test_recommend_uses_benefit_port_and_does_not_echo_residence(client, port):
    res = client.post("/api/team/recommend", json={**TRIP, "residence_code": RESIDENCE,
                                                   "benefit_conditions": {"birth_date": "1999-01-01"}})
    assert res.status_code == 200
    data = res.json()
    assert data["regions"][0]["sigungu_code"] == MUAN and data["regions"][0]["group"] == 1
    assert data["benefit_lookup"]["status"] == "ok" and data["benefit_lookup"]["connected"] is True
    sent = port.queries[-1]
    assert sent.residence_code == RESIDENCE and sent.conditions == {"birth_date": "1999-01-01"}
    assert len(sent.sigungu_codes) == 27
    assert RESIDENCE not in res.text and "1999-01-01" not in res.text


def test_recommend_when_benefit_module_crashes(client):
    benefit_port.set_benefit_port(FakePort(fail=True))
    data = client.post("/api/team/recommend", json=TRIP).json()
    assert data["no_refund_notice"]["code"] == "benefit_lookup_failed"
    assert all(r["group"] == 2 for r in data["regions"])


def test_course_lifecycle_without_storing_user_conditions(client, port):
    res = client.post("/api/team/courses", json={**TRIP, "sigungu_code": MUAN, "program_id": "muan_test",
                                                 "residence_code": RESIDENCE, "meal_cost_krw": 15000})
    assert res.status_code == 200, res.text
    course = res.json()
    assert len(course["id"]) == 8 and course["region"]["refund_program_id"] == "muan_test"
    assert "judgment" not in course["region"]["refund_program"]
    assert any(i["required"] for d in course["days"] for i in d["items"])
    assert course["spend_inputs"]["meal_cost_krw"] == 15000
    with Session(engine) as session:
        stored = session.get(Course, course["id"])
        assert RESIDENCE not in stored.body_json and "residence" not in stored.model_dump()
    again = client.get(f"/api/team/courses/{course['id']}").json()
    assert again["days"] == course["days"]
    assert client.get("/api/team/courses/nope1234").status_code == 404


def test_course_rejects_program_outside_region_and_reports_unchecked(client, port):
    res = client.post("/api/team/courses", json={**TRIP, "sigungu_code": "46860", "program_id": "muan_test"})
    assert res.status_code == 422 and res.json()["code"] == "program_region_mismatch"
    benefit_port.set_benefit_port(benefit_port.NotConnectedBenefitPort())
    body = client.post("/api/team/courses", json={**TRIP, "sigungu_code": MUAN, "program_id": "muan_test"}).json()
    assert any(w["code"] == "benefit_unchecked" for w in body["warnings"])


def test_swap_candidates_and_swap(client, port):
    course = client.post("/api/team/courses", json={**TRIP, "sigungu_code": MUAN, "program_id": "muan_test"}).json()
    spots = [(d["day"], i) for d in course["days"] for i in d["items"] if i["kind"] == "spot"]
    day, target = next((d, i) for d, i in spots if i["swappable"] and i["place"]["sigungu_code"] == MUAN)
    required_day, required = next((d, i) for d, i in spots if i["required"])
    cands = client.get(f"/api/team/courses/{course['id']}/candidates",
                       params={"day": day, "order": target["order"]}).json()["candidates"]
    used = {i["place"]["content_id"] for _, i in spots}
    assert 0 < len(cands) <= 3 and not used & {c["content_id"] for c in cands}
    blocked = client.get(f"/api/team/courses/{course['id']}/candidates",
                         params={"day": required_day, "order": required["order"]})
    assert blocked.status_code == 422 and blocked.json()["code"] == "not_swappable"
    swapped = client.post(f"/api/team/courses/{course['id']}/swap",
                          json={"day": day, "order": target["order"], "content_id": cands[0]["content_id"]})
    assert swapped.status_code == 200, swapped.text
    new_ids = [i["place"]["content_id"] for d in swapped.json()["days"] for i in d["items"] if i["kind"] == "spot"]
    assert cands[0]["content_id"] in new_ids and target["place"]["content_id"] not in new_ids
    day, target = next((d["day"], i) for d in swapped.json()["days"] for i in d["items"]
                       if i["kind"] == "spot" and i["swappable"])
    bad = client.post(f"/api/team/courses/{course['id']}/swap",
                      json={"day": day, "order": target["order"], "content_id": "h1"})
    assert bad.status_code == 422 and bad.json()["code"] == "invalid_replacement"


def test_reasons_endpoint_limits_ai_calls_and_reuses(client):
    course = client.post("/api/team/courses", json={**TRIP, "sigungu_code": MUAN}).json()
    first = client.post(f"/api/team/courses/{course['id']}/reasons", json={"day": 1}).json()
    assert first["status"] == "mock" and first["ai_calls"] == 1
    assert all(i["reason_by"] == "mock" for i in first["items"])
    repeat = client.post(f"/api/team/courses/{course['id']}/reasons", json={"day": 1}).json()
    assert repeat["status"] == "stored" and repeat["ai_calls"] == 1
    client.post(f"/api/team/courses/{course['id']}/reasons", json={"day": 2})
    stored = client.get(f"/api/team/courses/{course['id']}").json()
    assert stored["ai_calls"] == 2 and stored["ai_calls_left"] == 0
    assert client.post(f"/api/team/courses/{course['id']}/reasons", json={"day": 3}).status_code == 422


def test_place_detail_from_cache_with_visit_date(client):
    data = client.get("/api/team/places/m1", params={"date": "2026-11-09"}).json()
    assert data["closed_on_visit_date"] is True and data["rest_text"] == "매주 월요일"
    assert data["opening_window"] == {"open": "09:00", "close": "18:00"}
    assert "무안군 중심 관광지 1위" in data["evidence"] and data["detail_status"] == "cached"
    assert data["image_credit"] == "한국관광공사"
    unknown = client.get("/api/team/places/m4", params={"date": "2026-11-09"}).json()
    assert unknown["check_before_visit"] is True and unknown["detail_status"] == "not_fetched"
    assert client.get("/api/team/places/none").status_code == 404


def test_benefits_engine_is_wired_by_default(client):
    assert isinstance(benefit_port.get_benefit_port(), BenefitsEnginePort)
    assert client.get("/api/team/meta").json()["benefit_port"]["connected"] is True
    assert client.get("/api/benefits/sources").status_code == 200


def test_recommend_through_benefits_engine(client):
    data = client.post("/api/team/recommend", json={**TRIP, "residence_code": RESIDENCE}).json()
    lookup = data["benefit_lookup"]
    assert lookup["connected"] is True and lookup["status"] == "partial"
    assert {"gov24_api", "kto_tour50"} <= {s.split(":")[0] for s in lookup["failed_sources"]}
    first = data["regions"][0]
    assert first["sigungu_code"] == MUAN and first["group"] == 1
    assert first["refund"]["program_id"] == MUAN_PROGRAM and first["refund"]["badge"] == "needs_verification"
    day = client.post("/api/team/recommend", json={**TRIP, "trip_type": "day"}).json()
    muan = next(r for r in day["regions"] if r["sigungu_code"] == MUAN)
    assert muan["group"] == 2 and muan["refund"]["badge"] == "needs_stay"
    assert day["no_refund_notice"]["code"] == "no_applicable_program_in_scope" and day["no_refund_notice"]["partial"]
    bad = client.post("/api/team/recommend", json={**TRIP, "benefit_conditions": {"birth_date": "not-a-date"}}).json()
    assert bad["no_refund_notice"]["code"] == "benefit_lookup_failed"
    assert "birth_date" in bad["benefit_lookup"]["message"]


def test_course_applies_benefits_engine_constraints(client):
    saturday = client.post("/api/team/courses", json={**TRIP, "start_date": "2026-11-14", "sigungu_code": MUAN,
                                                      "program_id": MUAN_PROGRAM, "residence_code": RESIDENCE})
    assert saturday.status_code == 200, saturday.text
    body = saturday.json()
    assert body["region"]["refund_program"]["program_id"] == MUAN_PROGRAM
    warnings = {w["code"]: w for w in body["warnings"]}
    assert warnings["stay_weekday"]["suggested_date"] == "2026-11-13"
    assert "무안황토갯벌랜드" in warnings["required_place_unmatched"]["message"]
    elsewhere = client.post("/api/team/courses", json={**TRIP, "sigungu_code": "46860", "program_id": MUAN_PROGRAM})
    assert any(w["code"] == "program_not_found" for w in elsewhere.json()["warnings"])


def test_empty_cache_is_explicit(client):
    with Session(engine) as session:
        for model in (Place, HubRank, RelatedPlace):
            for row in session.exec(select(model)).all():
                session.delete(row)
        session.commit()
    data = client.post("/api/team/recommend", json=TRIP).json()
    assert data["regions"] == [] and data["notice"]["code"] == "tourism_cache_empty"
    res = client.post("/api/team/courses", json={**TRIP, "sigungu_code": MUAN})
    assert res.status_code == 503 and res.json()["code"] == "tourism_cache_empty"
    assert json.loads(json.dumps(client.get("/api/team/meta").json()))["tourism_data"]["status"] == "empty"
