"""F1/F2 <-> benefits engine adapter, run against the benefits module's manual registry.

No external calls: the sync tables are emptied, so gov24/tour50 show as never synced.
"""
from datetime import date

import pytest
from sqlmodel import Session, select

import app.main  # noqa: F401 -- registers every table and the default benefit port
from app.database import engine, init_db
from app.team import benefit_port
from app.team.benefit_bridge import BenefitsEnginePort, build_request, region_of
from app.team.benefit_port import RegionBenefitQuery
from app.team.benefits.store_models import (BenefitRecordVersion, BenefitSourceRecord, BenefitSyncRun,
                                            BenefitSyncState)
from app.team.recommend import TripQuery, recommend
from app.team.regions import origins, sigungu_map

from course_fixtures import MUAN, SINAN, snapshot

TODAY = date(2026, 11, 2)
TUE, WED = date(2026, 11, 10), date(2026, 11, 11)


@pytest.fixture(autouse=True)
def empty_benefit_store():
    init_db()
    with Session(engine) as session:
        for model in (BenefitSourceRecord, BenefitRecordVersion, BenefitSyncRun, BenefitSyncState):
            for row in session.exec(select(model)).all():
                session.delete(row)
        session.commit()


def query(trip_type="1N2D", codes=None, residence="29170", conditions=None):
    end = WED if trip_type == "1N2D" else TUE
    return RegionBenefitQuery(trip_type, TUE, end, tuple(codes or sigungu_map()), 2, TODAY, residence,
                              dict(conditions or {}))


def test_registered_as_default_port():
    assert isinstance(benefit_port.get_benefit_port(), BenefitsEnginePort)


def test_request_mapping_for_regions_stay_and_conditions():
    overnight = build_request(query(conditions={"birth_date": "1999-05-01", "visits": "ignored"}), MUAN)
    visit = overnight.visits[0]
    assert (visit.region.sido, visit.region.sigungu) == ("전라남도", "무안군")
    assert visit.nights == 1 and visit.checkin_dates == [TUE]
    assert (overnight.residence.sido, overnight.residence.sigungu) == ("광주광역시", "북구")
    assert overnight.birth_date == date(1999, 5, 1) and overnight.reference_date == TODAY
    day = build_request(query("day"), MUAN)
    assert day.visits[0].nights == 0 and day.visits[0].checkin_dates is None
    seoul = build_request(query(conditions={"residence": {"sido": "서울특별시", "sigungu": "강남구"}}), MUAN)
    assert seoul.residence.sigungu == "강남구"
    assert region_of("11680") is None and build_request(query(residence="11680"), MUAN).residence is None


def test_lookup_passes_engine_verdicts_and_constraints():
    lookup = BenefitsEnginePort().lookup(query())
    assert lookup.status == "partial"
    assert {s.split(":")[0] for s in lookup.failed_sources} == {"gov24_api", "kto_tour50"}
    muan = {p.program_id: p for p in lookup.by_region[MUAN]}["manual:muan-halfprice-2026"]
    assert muan.judgment == "needs_verification" and muan.sigungu_codes == (MUAN,)
    assert muan.constraints.required_place_names == ("무안황토갯벌랜드",)
    assert muan.constraints.min_spots == 2 and muan.constraints.min_nights == 1
    assert muan.constraints.stay_checkin_weekdays == (0, 1, 2, 3, 4)
    assert all(r.startswith(("불충족: ", "확인 필요: ")) for r in muan.reasons)
    assert "광주" not in " ".join(muan.reasons) and "북구" not in " ".join(muan.reasons)


def test_recommend_grouping_with_engine_results():
    snap = snapshot()
    one_night = TripQuery("1N2D", TUE, "gj-buk", ["nature"], 2)
    result = recommend(snap, one_night, origins()["gj-buk"], BenefitsEnginePort().lookup(query()), limit=27)
    by_code = {r["sigungu_code"]: r for r in result["regions"]}
    assert by_code[MUAN]["group"] == 1 and by_code[MUAN]["refund"]["badge"] == "needs_verification"
    # Island program: trip period (unverified) ended 2026-11-04 -> unmet, kept out of the refund group.
    assert by_code[SINAN]["group"] == 2 and by_code[SINAN]["refund"]["badge"] == "unmet_unverified"
    assert "불충족: 여행 인정 기간" in by_code[SINAN]["refund"]["reasons"]
    day = TripQuery("day", TUE, "gj-buk", ["nature"], 2)
    result = recommend(snap, day, origins()["gj-buk"], BenefitsEnginePort().lookup(query("day")), limit=27)
    muan = next(r for r in result["regions"] if r["sigungu_code"] == MUAN)
    assert muan["group"] == 2 and muan["refund"]["badge"] == "needs_stay"


def test_program_lookup_is_region_scoped_and_invalid_conditions_are_errors():
    port = BenefitsEnginePort()
    assert port.program("manual:muan-halfprice-2026", query(codes=[MUAN])).program_id == "manual:muan-halfprice-2026"
    assert port.program("manual:muan-halfprice-2026", query(codes=["46860"])) is None
    bad = port.lookup(query(conditions={"birth_date": "nope"}))
    assert bad.status == "error" and "birth_date" in bad.message
