"""POST /api/team/date-recommendations (mock data only: synthetic DB rows, FakePort, synthetic tour50 page).

Real-data runs are done by hand against the local DB (see docs/date-recommendations.md).
"""
from datetime import date, datetime, timedelta, timezone
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, delete

from app.database import engine
from app.main import app
from app.team import benefit_port
from app.team.benefit_bridge import BenefitsEnginePort
from app.team.benefit_port import BenefitLookup, ProgramSummary
from app.team.benefits import config as bconfig, registry, sync as bsync, tour50
from app.team.benefits.schemas import (
    AgeRule, BenefitProgram, BenefitRule, CapRule, DateRange, FamilyRule, ParticipationRule, PartyRule,
    PreApplyRule, Region, ResidenceRule, SourceRef, StayRule, VisitRule,
)
from app.team.benefits.store_models import BenefitRecordVersion, BenefitSourceRecord, BenefitSyncRun, BenefitSyncState
from app.team.tourism_models import Course, HubRank, Place, RelatedPlace, TourismSyncRun

import test_benefit_sync as t50

TODAY = "2026-11-02"
TRIP = {"start_date": "2026-11-07", "end_date": "2026-11-08"}
MUAN, HAMPYEONG, DAMYANG, GOKSEONG, GANGJIN = "46840", "46860", "46710", "46720", "46810"
URL = "/api/team/date-recommendations"
TABLES = (Place, HubRank, RelatedPlace, Course, TourismSyncRun,
          BenefitSourceRecord, BenefitRecordVersion, BenefitSyncRun, BenefitSyncState)


def summary(pid, judgment, code, *, open_=True, unmet=(), details=None, apply_url="https://example.invalid/apply"):
    d = {"trip_period": {"start": "2026-11-01", "end": "2026-11-30"},
         "application_period": {"start": "2026-10-01", "end": None}, "support": "환급률 50%",
         "estimated_amount": None, "missing_user_fields": [], "unmet": [{"code": c, "label": c, "confirmed": True}
                                                                        for c in unmet],
         "unresolved": [], "data_origin": "manual_registry", "last_success_at": None, "sources": []}
    d.update(details or {})
    return ProgramSummary(program_id=pid, name=f"테스트 {pid}", judgment=judgment, round_id="r1",
                          sigungu_codes=(code,), posted_status="open" if open_ else "closed",
                          application_open=open_, apply_url=apply_url, source_url="https://example.invalid/notice",
                          unmet_codes=tuple(unmet), details=d)


class Port:
    connected = True

    def __init__(self, by_region=None, status="ok", fail=False):
        self.by_region, self.status, self.fail, self.queries = by_region or {}, status, fail, []

    def lookup(self, query):
        self.queries.append(query)
        if self.fail:
            raise RuntimeError("down")
        return BenefitLookup(self.status, "2026-11-02T09:00:00+00:00",
                             {k: tuple(v) for k, v in self.by_region.items()}, scope_note="테스트 범위")

    def program(self, *a):
        return None


def festival(cid, code, start, end, title=None):
    return Place(content_id=cid, content_type_id="15", title=title or f"테스트축제{cid}", sigungu_code=code,
                 addr=f"테스트 주소 {cid}", event_start=start, event_end=end, source="kor",
                 fetched_at=datetime.now(timezone.utc))


def festival_run(status="ok", run_status="success", age=timedelta(0), message=None):
    now = datetime.now(timezone.utc) - age
    steps = {"calls": 2, "festivals": {"status": status, "rows": 2, "failures": [], "notes": []}} \
        if status else {"calls": 0}
    return TourismSyncRun(status=run_status, started_at=now, finished_at=now, message=message,
                          steps_json=json.dumps(steps))


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("TEAM_TODAY", TODAY)
    monkeypatch.setenv(bconfig.ENV_SYNC_MODE, "off")
    monkeypatch.delenv("TOURAPI_SERVICE_KEY", raising=False)
    monkeypatch.delenv("KIROTHON_DATA_GO_KR_SERVICE_KEY", raising=False)
    monkeypatch.setattr(registry, "_ENTRIES", [])
    monkeypatch.setattr(tour50.time, "sleep", lambda s: None)
    previous = benefit_port.get_benefit_port()
    with TestClient(app) as c:
        with Session(engine) as s:
            for model in TABLES:
                s.exec(delete(model))
            s.commit()
        yield c
    benefit_port.set_benefit_port(previous)


def seed(*rows):
    with Session(engine) as s:
        s.add_all(rows)
        s.commit()


def post(client, **extra):
    r = client.post(URL, json={**TRIP, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def by_code(data):
    return {r["sigungu_code"]: r for r in data["regions"]}


# ------------------------------------------------------------------ classification (FakePort)
def test_festival_benefit_both_none_and_order(client):
    seed(festival("d1", DAMYANG, "2026-11-01", "2026-11-10"),          # opened before the trip
         festival("h1", HAMPYEONG, "2026-11-08", "2026-11-08"),        # last trip day only
         festival("g0", GOKSEONG, "2026-11-01", "2026-11-06"),         # ends the day before: excluded
         festival("g9", GOKSEONG, "2026-11-09", "2026-11-12"),         # starts the day after: excluded
         festival_run())
    benefit_port.set_benefit_port(Port({
        MUAN: [summary("muan", "potentially_eligible", MUAN)],
        HAMPYEONG: [summary("hp", "potentially_eligible", HAMPYEONG)],
        GANGJIN: [summary("gj", "needs_verification", GANGJIN,
                          details={"missing_user_fields": ["residence"]})],
    }))
    data = post(client)
    regions = by_code(data)
    assert data["outcome"] == "matches_found" and data["complete"] is True
    assert [r["sigungu_code"] for r in data["regions"]] == [HAMPYEONG, MUAN, DAMYANG, GANGJIN]
    assert regions[HAMPYEONG]["category"] == "festival_and_benefit" and regions[HAMPYEONG]["group"] == 1
    assert regions[MUAN]["category"] == "benefit_only" and regions[MUAN]["festivals"] == []
    assert regions[DAMYANG]["category"] == "festival_only" and regions[DAMYANG]["benefits"]["applicable"] == []
    fest = regions[DAMYANG]["festivals"][0]
    assert (fest["start_date"], fest["end_date"], fest["place"]) == ("2026-11-01", "2026-11-10", "테스트 주소 d1")
    assert fest["source"].startswith("한국관광공사") and fest["fetched_at"]
    assert regions[GANGJIN]["category"] == "benefit_needs_verification" and regions[GANGJIN]["group"] == 3
    assert regions[GANGJIN]["missing_user_fields"] == ["residence"]
    assert GOKSEONG not in regions and "곡성군" in data["regions_not_matched"]["names"]
    assert data["regions_not_matched"]["meaning"].startswith("확인된 데이터 범위")
    prog = regions[MUAN]["benefits"]["applicable"][0]
    assert prog["trip_period"] == {"start": "2026-11-01", "end": "2026-11-30"}
    assert prog["apply_url"] and prog["estimated_amount"] is None


def test_closed_or_ineligible_programs_are_not_recommended(client):
    seed(festival("d1", DAMYANG, "2026-11-05", "2026-11-09"), festival_run())
    benefit_port.set_benefit_port(Port({
        MUAN: [summary("closed", "needs_verification", MUAN, open_=False)],
        DAMYANG: [summary("res", "ineligible", DAMYANG, unmet=("residence",))],
        GOKSEONG: [summary("old", "needs_verification", GOKSEONG, unmet=("trip_period",))],
    }))
    data = post(client)
    regions = by_code(data)
    assert MUAN not in regions and GOKSEONG not in regions          # only excluded programs
    excluded = regions[DAMYANG]["benefits"]["excluded"][0]             # festival region keeps it, separately
    assert regions[DAMYANG]["category"] == "festival_only"
    assert "불충족" in excluded["excluded_reason"] and regions[DAMYANG]["benefits"]["applicable"] == []


def test_data_failure_is_not_reported_as_nothing(client):
    seed(festival_run(status=None, run_status="failed",
                      message="TOURAPI_SERVICE_KEY(또는 KIROTHON_DATA_GO_KR_SERVICE_KEY) 환경변수가 설정되지 않았습니다."))
    benefit_port.set_benefit_port(Port(fail=True))
    data = post(client)
    assert data["regions"] == [] and data["outcome"] == "source_unavailable" and data["complete"] is False
    assert "단정하지 않음" in data["regions_not_matched"]["meaning"]
    fest = data["data_status"]["festivals"]
    assert fest["status"] == "error" and "환경변수" in fest["message"] and fest["key_configured"] is False
    assert data["data_status"]["benefits"]["lookup_status"] == "error"
    assert data["data_status"]["prepare_commands"]["script"].endswith("prepare-date-data.ps1")


def test_never_synced_and_stale_festivals(client):
    benefit_port.set_benefit_port(Port())
    data = post(client)
    assert data["data_status"]["festivals"]["status"] == "never_synced" and data["outcome"] == "source_unavailable"
    seed(festival("d1", DAMYANG, "2026-11-01", "2026-11-30"), festival_run(age=timedelta(days=10)))
    data = post(client)
    assert data["data_status"]["festivals"]["status"] == "stale" and data["complete"] is False
    assert by_code(data)[DAMYANG]["data_warnings"]


def test_date_only_query_passes_no_guessed_conditions(client):
    port = Port()
    benefit_port.set_benefit_port(port)
    seed(festival_run())
    data = post(client)
    q = port.queries[0]
    assert q.party_size is None and q.residence_code is None and q.conditions == {} and q.assume_stay is False
    assert (q.trip_start, q.trip_end) == (date(2026, 11, 7), date(2026, 11, 8))
    assert data["missing_user_fields"] == ["residence", "party_size", "birth_date"]


# ------------------------------------------------------------------ real benefits engine
def verified_program(**over):
    base = dict(
        id="manual:test-date", program_id="test-date", round_id="2026-1", provider="전라남도 무안군",
        name="테스트 무안 여행지원", target_regions=[Region(sido="전라남도", sigungu="무안군")],
        application_period=DateRange(start=date(2026, 10, 1), end=date(2026, 11, 20)),
        trip_period=DateRange(start=date(2026, 11, 1), end=date(2026, 11, 30)),
        posted_status="open", status_checked_at=datetime.now(timezone.utc),
        residence_rule=ResidenceRule(excluded_regions=[Region(sido="전라남도", sigungu="무안군")]),
        age_rule=AgeRule(min_age=18, basis="full_age_on_trip_start"), party_rule=PartyRule(min_size=1, max_size=10),
        family_rule=FamilyRule(requires_family=False, requires_same_address=False),
        participation_rule=ParticipationRule(repeat_allowed=True), visit_rule=VisitRule(),
        stay_rule=StayRule(min_nights=0), pre_apply=PreApplyRule(required=False),
        benefit=BenefitRule(benefit_type="local_voucher", refund_rate=0.5,
                            caps=[CapRule(label="개인", amount=100_000, per="group")]),
        application_url="https://example.invalid/apply", official_info_url="https://example.invalid/notice",
        source_type="official_notice", sources=[SourceRef(source_type="official_notice", url="https://example.invalid/notice")],
        verification_status="verified", last_verified_at=datetime.now(timezone.utc))
    base.update(over)
    return BenefitProgram(**base)


def engine_client(monkeypatch, *programs):
    monkeypatch.setattr(registry, "_ENTRIES", list(programs))
    benefit_port.set_benefit_port(BenefitsEnginePort())


def test_engine_date_only_needs_verification_then_eligible(client, monkeypatch):
    engine_client(monkeypatch, verified_program())
    seed(festival_run())
    data = post(client)
    muan = by_code(data)[MUAN]
    assert muan["category"] == "benefit_needs_verification"
    prog = muan["benefits"]["needs_verification"][0]
    assert prog["judgment"] == "needs_verification"
    assert {"residence", "party_size", "birth_date"} <= set(prog["missing_user_fields"])
    assert prog["support"].startswith("환급률 50%") and prog["estimated_amount"] is None
    data = post(client, residence="29170", party_size=2, birth_date="1990-05-05")
    muan = by_code(data)[MUAN]
    assert muan["category"] == "benefit_only"
    assert muan["benefits"]["applicable"][0]["judgment"] == "potentially_eligible"
    assert "29170" not in json.dumps(data) and "1990-05-05" not in json.dumps(data)


def test_festival_with_needs_verification_benefit_is_not_festival_only(client, monkeypatch):
    """무안 case: a festival plus a '추가 확인 필요' program must keep both facts, without
    promoting the program to 'applicable'."""
    engine_client(monkeypatch, verified_program())
    seed(festival_run(), festival("m1", MUAN, "2026-11-06", "2026-11-08"))
    data = post(client, sigungu_code=MUAN)
    for muan in (by_code(data)[MUAN], data["selected_region"]):
        assert muan["category"] == "festival_and_benefit_needs_verification" and muan["group"] == 2
        assert muan["benefits"]["applicable"] == []
        assert [p["judgment"] for p in muan["benefits"]["needs_verification"]] == ["needs_verification"]
        assert "확인이 필요한" in muan["reason"] and len(muan["festivals"]) == 1
    assert data["selected_region"]["states"]["benefits"] == "found"
    confirmed = post(client, sigungu_code=MUAN, residence="29170", party_size=2, birth_date="1990-05-05")
    muan = confirmed["selected_region"]
    assert muan["category"] == "festival_and_benefit" and muan["group"] == 1
    assert muan["benefits"]["needs_verification"] == [] and len(muan["benefits"]["applicable"]) == 1


def test_engine_excluded_residence_and_closed_application(client, monkeypatch):
    seed(festival_run())
    engine_client(monkeypatch, verified_program())
    data = post(client, residence={"sido": "전라남도", "sigungu": "무안군"}, party_size=2, birth_date="1990-05-05")
    assert MUAN not in by_code(data)
    engine_client(monkeypatch, verified_program(application_period=DateRange(start=date(2026, 10, 1),
                                                                              end=date(2026, 11, 1))))
    data = post(client, residence="29170", party_size=2, birth_date="1990-05-05")
    assert MUAN not in by_code(data)
    seed(festival("m1", MUAN, "2026-11-06", "2026-11-08"))
    muan = by_code(post(client, residence="29170", party_size=2, birth_date="1990-05-05"))[MUAN]
    assert muan["category"] == "festival_only"
    assert muan["benefits"]["excluded"][0]["program_id"] == "manual:test-date"


def test_linked_manual_entry_defers_to_official_rounds(client, monkeypatch):
    """A registry entry explicitly linked to tour50 rounds must not keep a region alive
    after every official round is closed; an unlinked entry with a similar name stays."""
    linked = verified_program(id="manual:jh-linked", program_id="jh-linked", name="지역사랑 휴가지원 (장흥)",
                              target_regions=[Region(sido="전라남도", sigungu="장흥군")],
                              verification_status="unverified", source_type="news_report", trip_period=None,
                              related_program_ids=["kto50:12770:2026"])
    monkeypatch.setattr(registry, "_ENTRIES", [linked])
    benefit_port.set_benefit_port(BenefitsEnginePort())
    seed(festival_run())
    t50.sync_tour50(t50.page(t50.jangheung()))
    assert "46800" not in by_code(post(client))
    unlinked = linked.model_copy(update={"id": "manual:jh-other", "related_program_ids": []})
    monkeypatch.setattr(registry, "_ENTRIES", [unlinked])
    region = by_code(post(client))["46800"]
    assert region["category"] == "benefit_needs_verification"
    assert region["benefits"]["needs_verification"][0]["program_id"] == "manual:jh-other"


def test_engine_with_synced_tour50_rounds(client, monkeypatch):
    benefit_port.set_benefit_port(BenefitsEnginePort())
    seed(festival_run())
    t50.sync_tour50(t50.page(t50.jangheung(), t50.gangjin()))
    data = post(client)
    regions = by_code(data)
    gangjin = regions[GANGJIN]
    assert gangjin["category"] == "benefit_needs_verification"
    prog = gangjin["benefits"]["needs_verification"][0]
    assert prog["program_id"] == "kto50:12780-2026-3" and prog["posted_status"] == "open"
    assert prog["trip_period"] == {"start": "2026-10-20", "end": "2026-11-30"}
    assert prog["application_start_at"].startswith("2026-10-20T09:00")
    assert prog["budget_remaining"] is None and prog["last_success_at"]
    assert any(p["program_id"] == "kto50:12780-2026-2" for p in gangjin["benefits"]["excluded"])
    assert "46800" not in regions  # 장흥 2차 travel period ends 11-02: only excluded programs


# ------------------------------------------------------------------ validation
@pytest.mark.parametrize("body", [
    {"start_date": "2026-11-08", "end_date": "2026-11-07"},
    {"start_date": "2026-11-01", "end_date": "2026-11-02"},          # before TEAM_TODAY
    {"start_date": "2026-11-07", "end_date": "2027-02-01"},          # too long
    {**TRIP, "residence": "abc"},
    {**TRIP, "party_size": 0},
    {**TRIP, "origin": "gj-buk"},                                      # extra field
])
def test_validation(client, body):
    benefit_port.set_benefit_port(Port())
    assert client.post(URL, json=body).status_code == 422


def test_long_trip_allowed(client):
    benefit_port.set_benefit_port(Port())
    seed(festival("d1", DAMYANG, "2026-11-20", "2026-11-22"), festival_run())
    data = post(client, start_date="2026-11-07", end_date="2026-11-25")
    assert data["query"]["days"] == 19 and DAMYANG in by_code(data)


# ------------------------------------------------------------------ selected region (slingshot flow)
def test_selected_region_always_returned_with_states(client):
    seed(festival("d1", DAMYANG, "2026-10-20", "2026-11-10", title="테스트진행중축제"),  # opened before trip
         festival("dx", DAMYANG, None, None, title="테스트일정미정"),
         festival_run())
    port = Port({MUAN: [summary("muan", "needs_verification", MUAN, details={"missing_user_fields": ["residence"]})],
                 HAMPYEONG: [summary("closed", "needs_verification", HAMPYEONG, open_=False)]})
    benefit_port.set_benefit_port(port)
    fest_only = post(client, sigungu_code=DAMYANG)["selected_region"]
    assert port.queries[-1].sigungu_codes == (DAMYANG,)
    assert [f["title"] for f in fest_only["festivals"]] == ["테스트진행중축제"]
    assert [f["title"] for f in fest_only["festivals_undated"]] == ["테스트일정미정"]
    assert fest_only["states"]["festivals"] == "found" and fest_only["states"]["benefits"] == "none_in_scope"
    ben_only = post(client, sigungu_code=MUAN)["selected_region"]
    assert ben_only["states"] == {"festivals": "none_in_period", "festivals_stale": False, "benefits": "found",
                                  "benefits_partial": False, "needs_user_info": True}
    closed = post(client, sigungu_code=HAMPYEONG)["selected_region"]
    assert closed["category"] == "none" and closed["states"]["benefits"] == "excluded_only"
    none = post(client, sigungu_code=GOKSEONG)["selected_region"]
    assert none["name"] == "곡성군" and none["festivals"] == [] and none["states"]["benefits"] == "none_in_scope"


def test_selected_region_failure_states(client):
    benefit_port.set_benefit_port(Port(fail=True))
    sel = post(client, sigungu_code=DAMYANG)["selected_region"]
    assert sel["states"]["festivals"] == "unavailable" and sel["states"]["benefits"] == "unavailable"
    assert client.post(URL, json={**TRIP, "sigungu_code": "11110"}).status_code == 422


# ------------------------------------------------------------------ gov24 audience (영광 수학여행비 오추천)
def test_gov24_restricted_audience_is_not_recommended(client):
    YG = "46870"
    rows = [
        {**t50._row("SCHOOL1", "기초생활수급자 수학여행비 및 체험학습비 지원", provider="전라남도 영광군"),
         "지원대상": "기초생활보장수급자(생계,의료,주거,교육) 중 수학여행에 실제 참여하는 학생"},
        {**t50._row("VISIT1", "영광 여행 숙박비 지원", provider="전라남도 영광군"), "지원대상": "관외 거주 관광객"},
        {**t50._row("PLAIN1", "영광 여행 프로그램 운영", provider="전라남도 영광군"), "지원대상": "신청자"},
    ]
    rows += [
        {**t50._row("CARE1", "저소득 한부모가족 유급 자녀돌봄휴가비 지원", provider="전라남도 영광군"),
         "지원대상": "저소득 한부모가족"},
        {**t50._row("BIZ1", "관광객 유치 여행사 인센티브 지원", provider="전라남도 영광군"),
         "지원대상": "등록 여행사", "사용자구분": "법인/시설/단체"},
        {**t50._row("DIS1", "장애인 가족사랑여행 지원", provider="전라남도 영광군"), "지원대상": "관내 등록 장애인 가족"},
    ]
    bsync.run_sync("gov24_api", "manual", t50.factory, gov24_client=t50.gov_client(t50.FakeGov24(rows=rows)))
    seed(festival_run())
    benefit_port.set_benefit_port(BenefitsEnginePort())
    sel = post(client, sigungu_code=YG)["selected_region"]
    every = {p["program_id"]: p for k in ("applicable", "needs_verification", "excluded") for p in sel["benefits"][k]}
    # Not travel support (school trip, care-leave pay, a grant for businesses): absent from every list.
    assert not {"gov24:SCHOOL1", "gov24:CARE1", "gov24:BIZ1"} & set(every)
    shown = {p["program_id"]: p for p in sel["benefits"]["needs_verification"]}
    assert shown["gov24:VISIT1"]["audience"] == "general" and shown["gov24:VISIT1"]["match_basis"] == "text_hint"
    # Travel support limited to a group: kept, marked targeted, never 'applicable' while membership is unknown.
    for pid in ("gov24:DIS1", "gov24:PLAIN1"):
        assert shown[pid]["audience"] == "targeted" and shown[pid]["judgment"] == "needs_verification"
    assert not sel["benefits"]["applicable"]


def test_gov24_audience_kinds():
    from app.team.benefits.engine import audience_kind
    from app.team.benefits.schemas import BenefitProgram
    def prog(name, **raw):
        return BenefitProgram(id=f"gov24:{name}", program_id=f"gov24:{name}", name=name, source_type="gov24_api",
                              sources=[], verification_status="unverified", raw_text=raw)
    assert audience_kind(prog("국민기초생활수급자 고등학생 수학여행비 지원")) == "not_travel"
    assert audience_kind(prog("저소득 한부모가족 유급 자녀돌봄휴가비 지원", 사용자구분="개인")) == "not_travel"
    assert audience_kind(prog("관광객 유치 여행사 인센티브 지원", 사용자구분="법인/시설/단체")) == "not_travel"
    assert audience_kind(prog("공중위생업소(숙박업) 시설개선 지원")) == "not_travel"
    assert audience_kind(prog("관광취약계층 행복여행활동 지원", 지원대상="기초생활수급자")) == "targeted"
    assert audience_kind(prog("섬 여행 숙박비 지원", 지원대상="관외 거주 관광객")) == "general"
    tour50 = prog("반값여행").model_copy(update={"source_type": "official_webpage"})
    assert audience_kind(tour50) == "general"


def test_match_basis_for_official_page_rounds(client):
    benefit_port.set_benefit_port(BenefitsEnginePort())
    seed(festival_run())
    t50.sync_tour50(t50.page(t50.gangjin()))
    sel = post(client, sigungu_code=GANGJIN)["selected_region"]
    prog = sel["benefits"]["needs_verification"][0]
    assert prog["program_id"] == "kto50:12780-2026-3" and prog["match_basis"] == "target_region"
    assert prog["payout_method"] and prog["conditions_text"].startswith("관광지 2개소")
