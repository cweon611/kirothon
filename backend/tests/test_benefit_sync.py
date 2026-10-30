"""Periodic collection: storage, versioning, failure handling, and its effect on judgements.

Everything here is example data (httpx.MockTransport + a synthetic page that
mirrors the structure of the real tour50 page). Live calls are in
test_benefit_live.py and only run when KIROTHON_LIVE_TESTS=1.
"""
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, delete, select

from app.database import engine
from app.main import app
from app.team.benefits import config, gov24, registry, sync, tour50
from app.team.benefits.gov24 import Gov24Client, _Cache
from app.team.benefits.schemas import BenefitProgram, Region, SourceRef
from app.team.benefits.store_models import (
    BenefitRecordVersion, BenefitSourceRecord, BenefitSyncRun, BenefitSyncState,
)

KEY = "TEST-SECRET-KEY-DO-NOT-LEAK"
REF = "2026-10-30"


# ------------------------------------------------------------------ synthetic tour50 page
def aside(trvid, sggcd, sgg, status, rounds_detail, *, bgn="2026-09-07", end="2026-11-30",
          trvnm=None, apply=True, special="관광지 2개소(사진) 방문", sido="전남광주통합특별시"):
    btn = "신청하러 가기" if apply else "홈페이지 바로가기"
    names = {"ONGOING": "신청접수중", "READY": "준비중", "END": "마감"}
    return f'''
     	<aside class="cl-posi-detail step-{trvid}"
     		data-trvid="{trvid}"
       		data-mtpcdocd="12"
       		data-mtpcdocdnm="{sido}"
       		data-signgucd="{sggcd}"
       		data-signgucdnm="{sgg}"
       		data-govnm=""
       		data-trvnm="{trvnm or '2026-전라남도 ' + sgg[:-1]}"
       		data-link="https://example.go.kr/{sggcd}/"
       		data-evtbgndt="{bgn}"
       		data-evtenddt="{end}"
       		data-sttscd="{status}"
       		data-sttsnm="{names[status]}"
     	>
	        <div class="d2">
	            <dl><dt>사업기간 : </dt><dd>{bgn.replace('-', '.')}-{end.replace('-', '.')}<br>
	                {rounds_detail}<br>(차수별 선착순 접수로 조기마감될 수 있음)</dd></dl>
	            <dl><dt>지역화폐 : </dt><dd>chak 앱</dd></dl>
	            <dl><dt>특이사항 : </dt><dd>{special}</dd></dl>
	            <dl><dt>문의전화 :</dt><dd><a href="tel:061-000-{trvid:04d}" class="cus-tel">061-000-{trvid:04d}</a></dd></dl>
	        </div>
	        <div class="d3"><button data-href="https://example.go.kr/{sggcd}/apply"  class="cl-request" data-trvid='{trvid}' data-signgucd='{sggcd}' data-town="x">{btn}</button></div>
	    </aside>'''


def schedule(trvid, sggcd, town, items):
    lis = "".join(f'<li class="{"on" if on else ""}">\n<span>{label}</span> <p>{p}</p>\n</li>'
                  for label, p, on in items)
    return f'''<li class="swiper-slide"><a href="javascript:func_go_detail('{town}','{trvid}')"
       data-trvid="{trvid}"
       data-signgucd="{sggcd}"
       data-town="{town}">
    <dl><dt>{town}</dt><dd><ol>{lis}</ol><span>x</span></dd></dl></a></li>'''


GENERAL = """<p>숙박, 식사, 체험 등 여행 중 사용한 금액의 <br>50%를 환급받을 수 있으며, 1인 최대 10만원, 2인 이상은 최대 20만원
<br>까지 지원됩니다. <br>- 청년(사업공고일 또는 사업개시일 기준 19~34세, 청년기본법상 청년)은 환급률 20%p 상향하여 1인당 70%인 최대 14만원까지 환급 가능
<br>*다만 지자체마다 상이할 수 있으므로 반드시 신청 전 지자체 홈페이지 통해 확인</p>
<p>※ 사전에 신청하지 않을 경우 지원 불가</p><p>사용 금액의 50%를 지역화폐로 환급 받을 수 있습니다.</p>"""


def jangheung(status="ONGOING", trip2="10.12~11.02", start2="9.28 10시~"):
    return (schedule(39, "12770", "장흥", [
                ("1차", "여행일정 : 9.19~10.11<br>신청마감 : 9.21 12:00", False),
                ("2차", f"여행기간 : {trip2}<br>신청접수 : {start2}", True)]),
            aside(39, "12770", "장흥군", status,
                  f"● 1차 여행기간 : 9.19~10.11<br>- 9.21(월) 12시 신청 마감<br>"
                  f"● 2차 여행기간 : {trip2.replace('.0', '.')}<br>- 9.28(월) 10시 부터"))


def gangjin():
    return (schedule(7, "12780", "강진", [
                ("2차", "여행기간 : 10.01~10.31<br>신청마감 : 9.29 10:40", False),
                ("3차", "여행기간 : 10.20~11.30<br>신청접수 : 10.20 09시~", True)]),
            aside(7, "12780", "강진군", "ONGOING",
                  "● 3차 여행기간 : 10.20~11.30<br>- 10.20(화) 9시 부터", bgn="2026-06-10"))


def page(*regions, general=GENERAL):
    sched = "".join(s for s, _ in regions)
    asides = "".join(a for _, a in regions)
    return f"<html><body><ul>{sched}</ul>{general}{asides}</body></html>"


class Tour50Server:
    def __init__(self, html="", status=200, fail=None):
        self.html, self.status, self.fail, self.calls = html, status, fail, 0

    def __call__(self, request):
        self.calls += 1
        assert "korean.visitkorea.or.kr" in request.url.host
        if self.fail == "timeout":
            raise httpx.ReadTimeout("timeout", request=request)
        return httpx.Response(self.status, text=self.html)


# ------------------------------------------------------------------ fake gov24
def _row(sid, name, provider="전라남도 무안군", modified="20261001000000"):
    return {"서비스ID": sid, "서비스명": name, "소관기관명": provider, "지원대상": "관광객",
            "상세조회URL": f"https://www.gov.kr/portal/rcvfvrSvc/dtlEx/{sid}", "수정일시": modified}


class FakeGov24:
    def __init__(self, rows=None, fail=None, conditions=None):
        self.rows, self.fail, self.conditions, self.calls = rows or [], fail, conditions or {}, []

    def __call__(self, request: httpx.Request):
        self.calls.append(request)
        assert request.url.params["serviceKey"] == KEY
        if self.fail == "timeout":
            raise httpx.ReadTimeout("timed out", request=request)
        if self.fail:
            return httpx.Response(self.fail, json={"code": -self.fail, "msg": "error"})
        page_no = int(request.url.params.get("page", 1))
        per = int(request.url.params.get("perPage", 10))
        sid = request.url.params.get("cond[서비스ID::EQ]")
        if sid:
            rows = [r for r in self.rows if r["서비스ID"] == sid]
            if request.url.path.endswith("supportConditions"):
                rows = [{"서비스ID": sid, **self.conditions.get(sid, {})}] if rows else []
            elif request.url.path.endswith("serviceDetail"):
                rows = [{**r, "온라인신청사이트URL": "https://apply.example/" + sid} for r in rows]
            return httpx.Response(200, json={"page": 1, "perPage": 1, "data": rows, "matchCount": len(rows)})
        like = request.url.params.get("cond[서비스명::LIKE]", "")
        rows = [r for r in self.rows if like in r["서비스명"]]
        chunk = rows[(page_no - 1) * per: page_no * per]
        return httpx.Response(200, json={"page": page_no, "perPage": per, "totalCount": len(rows),
                                         "currentCount": len(chunk), "matchCount": len(rows), "data": chunk})


def gov_client(fake):
    return Gov24Client(KEY, transport=httpx.MockTransport(fake), cache=_Cache(), use_cache=False,
                       retries=0)


# ------------------------------------------------------------------ fixtures
def factory():
    return Session(engine)


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.delenv(gov24.ENV_SERVICE_KEY, raising=False)
    monkeypatch.setenv(config.ENV_SYNC_MODE, "off")
    monkeypatch.setattr(registry, "_ENTRIES", [])
    monkeypatch.setattr(tour50.time, "sleep", lambda s: None)
    with TestClient(app):
        pass  # ensure tables exist
    with factory() as s:
        for model in (BenefitRecordVersion, BenefitSourceRecord, BenefitSyncRun, BenefitSyncState):
            s.exec(delete(model))
        s.commit()
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def sync_tour50(html, **kw):
    return sync.run_sync("kto_tour50", "manual", factory,
                         tour50_transport=httpx.MockTransport(Tour50Server(html, **kw)), retries=0)


def records(source="kto_tour50"):
    with factory() as s:
        return {r.source_key: r for r in s.exec(
            select(BenefitSourceRecord).where(BenefitSourceRecord.source == source)).all()}


def versions(record_id):
    with factory() as s:
        return s.exec(select(BenefitRecordVersion).where(BenefitRecordVersion.record_id == record_id)
                      .order_by(BenefitRecordVersion.version)).all()


def visit(sigungu, start, end, nights=1, **kw):
    return {"region": {"sido": "전라남도", "sigungu": sigungu}, "start_date": start, "end_date": end,
            "nights": nights, **kw}


def check(client, visits, **kw):
    starts = [v["start_date"] for v in visits]
    ends = [v["end_date"] for v in visits]
    body = {"residence": {"sido": "광주광역시", "sigungu": "북구"}, "trip_start": min(starts),
            "trip_end": max(ends), "party_size": 2, "birth_date": "1990-05-05", "visits": visits,
            "reference_date": REF, **kw}
    r = client.post("/api/benefits/check", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def result(data, benefit_id):
    return next(x for x in data["results"] if x["benefit_id"] == benefit_id)


def codes(r, bucket):
    return {c["code"] for c in r[bucket]}


# ------------------------------------------------------------------ parser
def test_parser_keeps_rounds_separate_and_reads_times():
    items = {e.source_key: e for e in tour50.parse(page(jangheung(), gangjin()), datetime.now())}
    assert set(items) == {"tour50:12770:2026:1", "tour50:12770:2026:2",
                          "tour50:12780:2026:2", "tour50:12780:2026:3"}
    r2 = items["tour50:12770:2026:2"].program
    assert r2.id == "kto50:12770-2026-2" and r2.program_id == "kto50:12770:2026"
    assert r2.posted_status == "open" and r2.application_start_at.hour == 10
    assert (str(r2.trip_period.start), str(r2.trip_period.end)) == ("2026-10-12", "2026-11-02")
    assert r2.application_end_at is None and r2.budget_remaining is None
    r1 = items["tour50:12770:2026:1"].program
    assert r1.posted_status is None  # status is posted only for the current round
    assert r1.application_end_at.isoformat() == "2026-09-21T12:00:00+09:00"
    assert r2.benefit.refund_rate == 0.5 and r2.benefit.eligible_spend is None
    assert r2.youth_rule.basis is None and r2.youth_rule.max_age == 34
    assert r2.contacts == ["061-000-0039"] and r2.application_url.endswith("/apply")
    assert r2.source_type == "official_webpage" and r2.verification_status == "unverified"
    assert "posted_status" in r2.verified_fields and "benefit" not in r2.verified_fields


def test_parser_flags_conflicts_inside_the_page():
    sched = schedule(13, "12740", "고흥", [("5차", "여행기간 : 11.01~11.30<br>신청접수 : 10.30 17:00", True)])
    asd = aside(13, "12740", "고흥군", "END", "● 5차 여행기간 : 11.1~11.30<br>- 10.30(금) 17시 신청 마감",
                trvnm="2025-전라남도 고흥", bgn="2026-04-01")
    (e,) = tour50.parse(page((sched, asd)), datetime.now())
    assert e.review_status == "conflict"
    fields = {c.field for c in e.program.conflicts}
    assert {"program_year", "start_at"} <= fields
    assert "application_period" not in e.program.verified_fields


def test_parser_structure_change_raises():
    with pytest.raises(tour50.Tour50StructureError):
        tour50.parse("<html><body>새 디자인</body></html>", datetime.now())


# ------------------------------------------------------------------ collection & versions
def test_initial_sync_then_identical_resync_creates_no_duplicates():
    html = page(jangheung(), gangjin())
    run1 = sync_tour50(html)
    assert run1.status == "ok" and run1.created == 4 and run1.pages_fetched == 1
    before = records()
    run2 = sync_tour50(html)
    assert run2.status == "ok" and run2.created == 0 and run2.unchanged == 4 and run2.updated == 0
    after = records()
    assert set(after) == set(before)
    for key, rec in after.items():
        assert rec.version == 1 and len(versions(rec.id)) == 1
        assert rec.content_changed_at == before[key].content_changed_at
        assert rec.last_success_at >= before[key].last_success_at
        assert rec.source_updated_at is None  # the page exposes no modification time


def test_changed_round_creates_version_and_new_round_is_added():
    sync_tour50(page(jangheung()))
    old = records()["tour50:12770:2026:2"]
    sched, asd = jangheung(trip2="10.12~10.25")
    extra = schedule(39, "12770", "장흥", [])  # unused duplicate list is ignored
    html = page((sched + extra, asd))
    html = html.replace("<li class=\"on\">", "<li class=\"\">")  # previous current round
    html = html.replace("</ol>", "<li class=\"on\">\n<span>3차</span> <p>여행기간 : 11.03~11.30<br>신청접수 : 10.27 10시~</p>\n</li></ol>", 1)
    run = sync_tour50(html)
    assert run.status == "ok" and run.created == 1 and run.updated >= 1
    recs = records()
    assert "tour50:12770:2026:3" in recs
    changed = recs["tour50:12770:2026:2"]
    assert changed.version == 2 and changed.content_changed_at > old.content_changed_at
    vs = versions(changed.id)
    assert [v.version for v in vs] == [1, 2]
    diff = json.loads(vs[1].changed_fields_json)
    assert "trip_period" in diff and "posted_status" in diff


@pytest.mark.parametrize("server", [
    dict(status=500), dict(status=429), dict(fail="timeout"),
    dict(html="<html>구조 변경</html>"),
])
def test_failures_keep_existing_data(server):
    sync_tour50(page(jangheung()))
    before = {k: (r.content_hash, r.version, r.last_success_at, r.missing_since) for k, r in records().items()}
    with factory() as s:
        success_before = s.get(BenefitSyncState, "kto_tour50").last_success_at
    run = sync_tour50(server.pop("html", ""), **server)
    assert run.status == "error"
    assert run.error_code in {"upstream_error", "rate_limited", "timeout", "structure_changed"}
    after = {k: (r.content_hash, r.version, r.last_success_at, r.missing_since) for k, r in records().items()}
    assert after == before
    with factory() as s:
        st = s.get(BenefitSyncState, "kto_tour50")
        assert st.last_success_at == success_before and st.last_attempt_at > success_before
        assert st.last_status == "error"


def test_record_absent_from_complete_collection_is_kept_and_flagged(client):
    sync_tour50(page(jangheung(), gangjin()))
    run = sync_tour50(page(jangheung()))
    assert run.marked_missing == 2
    recs = records()
    assert recs["tour50:12780:2026:3"].missing_since is not None  # not deleted
    data = check(client, [visit("강진군", "2026-11-10", "2026-11-11")])
    r = result(data, "kto50:12780-2026-3")
    assert "source_presence" in codes(r, "unresolved_conditions")
    assert r["verdict"] == "needs_verification"


def test_retries_are_limited(monkeypatch):
    server = Tour50Server("", status=503)
    sync.run_sync("kto_tour50", "manual", factory, tour50_transport=httpx.MockTransport(server), retries=2)
    assert server.calls == 3


# ------------------------------------------------------------------ judgement uses stored data
def test_status_and_trip_period_changes_update_judgement(client):
    sync_tour50(page(jangheung("ONGOING")))
    v = [visit("장흥군", "2026-10-31", "2026-11-01")]
    r = result(check(client, v), "kto50:12770-2026-2")
    assert r["verdict"] == "needs_verification" and r["can_apply_now"] is None
    assert "posted_status" in codes(r, "met_conditions") and "trip_period" in codes(r, "met_conditions")
    assert r["timeline"]["application_start_at"].startswith("2026-09-28T10:00")
    assert r["timeline"]["budget_remaining"] is None
    assert r["data_freshness"]["last_success_at"] is not None and r["data_freshness"]["stale"] is False

    sync_tour50(page(jangheung("END")))
    r = result(check(client, v), "kto50:12770-2026-2")
    assert r["verdict"] == "ineligible" and r["can_apply_now"] is False
    assert r["timeline"]["posted_status"] == "closed"

    sync_tour50(page(jangheung("ONGOING", trip2="10.12~10.25")))
    r = result(check(client, v), "kto50:12770-2026-2")
    assert "trip_period" in codes(r, "unmet_conditions") and r["verdict"] == "ineligible"


def test_check_does_not_call_external_sources(client, monkeypatch):
    sync_tour50(page(jangheung()))

    def boom(*a, **k):
        raise AssertionError("external call during check")
    monkeypatch.setattr(tour50, "fetch_html", boom)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", boom)  # real network transport only
    data = check(client, [visit("장흥군", "2026-10-31", "2026-11-01")])
    assert data["results"]


def test_stale_data_is_not_used_as_confirmed(client):
    sync_tour50(page(jangheung("END")))
    old = sync.utcnow() - timedelta(days=3)
    with factory() as s:
        for rec in s.exec(select(BenefitSourceRecord)).all():
            rec.last_success_at = old
            s.add(rec)
        st = s.get(BenefitSyncState, "kto_tour50")
        st.last_success_at = st.last_attempt_at = old
        s.add(st)
        s.commit()
    data = check(client, [visit("장흥군", "2026-10-31", "2026-11-01")])
    r = result(data, "kto50:12770-2026-2")
    assert "data_freshness" in codes(r, "unresolved_conditions")
    assert r["verdict"] == "needs_verification"  # closed status is not trusted when stale
    assert all(not c["rule_confirmed"] for c in r["unmet_conditions"])
    src = next(s for s in data["sources"] if s["source"] == "kto_tour50")
    assert src["stale"] is True and data["partial_failure"] is True and data["success"] is False


def test_conflict_record_is_not_used_for_amount(client):
    sched = schedule(13, "12740", "고흥", [("5차", "여행기간 : 11.01~11.30<br>신청접수 : 10.30 17:00", True)])
    asd = aside(13, "12740", "고흥군", "ONGOING", "● 5차 여행기간 : 11.1~11.30<br>- 10.30(금) 17시 신청 마감")
    sync_tour50(page((sched, asd)))
    data = check(client, [visit("고흥군", "2026-11-10", "2026-11-11",
                                expected_spend={"by_category": {"lodging": 100000}})])
    r = result(data, "kto50:12740-2026-5")
    assert r["review_status"] == "conflict"
    assert "review_status" in codes(r, "unresolved_conditions")
    assert r["estimate"]["amount"] is None
    assert r["verdict"] == "needs_verification"


def test_separate_programs_in_same_region_are_not_merged(client, monkeypatch):
    own = BenefitProgram(
        id="manual:gangjin-own-2026", program_id="gangjin-own-halfprice", round_id="2026-12",
        provider="전라남도 강진군", name="강진군 자체 반값여행 (예시)",
        target_regions=[Region(sido="전라남도", sigungu="강진군")], source_type="project_doc",
        sources=[SourceRef(source_type="project_doc", title="test")], verification_status="unverified")
    monkeypatch.setattr(registry, "_ENTRIES", [own])
    sync_tour50(page(gangjin()))
    data = check(client, [visit("강진군", "2026-11-10", "2026-11-11")])
    ids = {(x["benefit_id"], x["program_id"]) for x in data["results"]}
    assert ("manual:gangjin-own-2026", "gangjin-own-halfprice") in ids
    assert ("kto50:12780-2026-3", "kto50:12780:2026") in ids
    assert ("kto50:12780-2026-2", "kto50:12780:2026") in ids


def test_never_synced_is_not_reported_as_no_benefit(client):
    data = check(client, [visit("담양군", "2026-11-10", "2026-11-11")])
    assert data["results"] == [] and data["outcome"] == "source_unavailable"
    assert {s["status"] for s in data["sources"] if s["source"] != "manual_registry"} == {"never_synced"}


def test_fresh_complete_sources_allow_no_match(client):
    sync_tour50(page(jangheung()))
    sync.run_sync("gov24_api", "manual", factory, gov24_client=gov_client(FakeGov24(rows=[])))
    data = check(client, [visit("담양군", "2026-11-10", "2026-11-11")])
    assert data["outcome"] == "no_match_in_scope" and data["success"] is True
    assert "없다는 뜻이 아닙니다" in data["coverage_note"]


# ------------------------------------------------------------------ gov24 collection
def test_gov24_multi_page_collection_and_candidates(client):
    rows = [_row("MUAN01", "무안 반값여행 지원")]
    rows += [_row(f"S{i:04d}", f"일반 여행 서비스 {i}", provider="서울특별시 종로구") for i in range(150)]
    fake = FakeGov24(rows=rows, conditions={"MUAN01": {"JA0110": 19, "JA0111": 39}})
    run = sync.run_sync("gov24_api", "manual", factory, gov24_client=gov_client(fake))
    assert run.status == "ok" and run.created == 151 and run.pages_fetched >= 2 + 1 + 1 + 1
    rec = records("gov24_api")["MUAN01"]
    assert rec.source_updated_at == datetime(2026, 9, 30, 15, 0, tzinfo=timezone.utc)  # KST → UTC
    data = check(client, [visit("무안군", "2026-11-10", "2026-11-11")])
    r = result(data, "gov24:MUAN01")
    assert r["data_origin"] == "gov24_api" and r["matched_visits"][0]["match_basis"] == "text_hint"
    assert r["how_to_apply"]["application_url"] == "https://apply.example/MUAN01"
    assert r["data_freshness"]["source_updated_at"].startswith("2026-09-30T15:00")
    assert "age" in codes(r, "met_conditions")
    assert not any(x["benefit_id"].startswith("gov24:S") for x in data["results"])


def test_gov24_unchanged_modification_time_skips_detail_calls():
    fake = FakeGov24(rows=[_row("MUAN01", "무안 여행 지원")])
    sync.run_sync("gov24_api", "manual", factory, gov24_client=gov_client(fake))
    detail_calls = sum(1 for c in fake.calls if "cond[서비스ID::EQ]" in str(c.url))
    run = sync.run_sync("gov24_api", "manual", factory, gov24_client=gov_client(fake))
    assert run.unchanged == 1
    assert sum(1 for c in fake.calls if "cond[서비스ID::EQ]" in str(c.url)) == detail_calls


def test_gov24_modified_record_creates_new_version():
    fake = FakeGov24(rows=[_row("MUAN01", "무안 여행 지원")])
    sync.run_sync("gov24_api", "manual", factory, gov24_client=gov_client(fake))
    fake.rows = [_row("MUAN01", "무안 여행 지원(변경)", modified="20261020000000")]
    run = sync.run_sync("gov24_api", "manual", factory, gov24_client=gov_client(fake))
    rec = records("gov24_api")["MUAN01"]
    assert run.updated == 1 and rec.version == 2
    assert "name" in json.loads(versions(rec.id)[1].changed_fields_json)


def test_gov24_empty_after_data_keeps_records():
    sync.run_sync("gov24_api", "manual", factory, gov24_client=gov_client(FakeGov24(rows=[_row("M1", "여행 지원")])))
    run = sync.run_sync("gov24_api", "manual", factory, gov24_client=gov_client(FakeGov24(rows=[])))
    assert run.status == "partial" and run.error_code == "empty_result"
    assert records("gov24_api")["M1"].missing_since is None
    with factory() as s:
        st = s.get(BenefitSyncState, "gov24_api")
        assert st.last_status == "partial"


@pytest.mark.parametrize("fail,code", [(401, "auth_error"), (500, "upstream_error"), ("timeout", "timeout")])
def test_gov24_errors_recorded_without_key(fail, code):
    run = sync.run_sync("gov24_api", "manual", factory, gov24_client=gov_client(FakeGov24(fail=fail)))
    assert run.status == "error" and run.error_code == code
    assert KEY not in json.dumps(run.model_dump(), default=str)


def test_gov24_not_configured():
    run = sync.run_sync("gov24_api", "manual", factory)
    assert run.status == "not_configured" and run.error_code == "missing_service_key"


def test_gov24_detail_budget_defers_without_marking_missing(monkeypatch):
    rows = [_row(f"M{i}", f"여행 {i}") for i in range(5)]
    sync.run_sync("gov24_api", "manual", factory, gov24_client=gov_client(FakeGov24(rows=rows)))
    monkeypatch.setenv(config.ENV_GOV24_MAX_DETAIL, "1")
    changed = [_row(f"M{i}", f"여행 {i}", modified="20261021000000") for i in range(5)]
    run = sync.run_sync("gov24_api", "manual", factory, gov24_client=gov_client(FakeGov24(rows=changed)))
    assert run.updated == 1 and run.marked_missing == 0 and run.status == "partial"
    assert all(r.missing_since is None for r in records("gov24_api").values())


# ------------------------------------------------------------------ concurrency & scheduling
def test_lease_held_by_other_process_skips_run():
    with factory() as s:
        sync._state(s, "kto_tour50")
        st = s.get(BenefitSyncState, "kto_tour50")
        st.lease_owner, st.lease_until = "other-host:1", sync.utcnow() + timedelta(minutes=5)
        s.add(st)
        s.commit()
    server = Tour50Server(page(jangheung()))
    run = sync.run_sync("kto_tour50", "scheduled", factory, tour50_transport=httpx.MockTransport(server))
    assert run.status == "skipped_locked" and server.calls == 0


def test_expired_lease_is_taken_over():
    with factory() as s:
        sync._state(s, "kto_tour50")
        st = s.get(BenefitSyncState, "kto_tour50")
        st.lease_owner, st.lease_until = "crashed:1", sync.utcnow() - timedelta(minutes=1)
        s.add(st)
        s.commit()
    assert sync_tour50(page(jangheung())).status == "ok"


def test_in_process_overlap_is_skipped():
    lock = sync._LOCKS["kto_tour50"]
    lock.acquire()
    try:
        assert sync_tour50(page(jangheung())).status == "skipped_locked"
    finally:
        lock.release()


def test_due_sources_and_intervals(monkeypatch):
    with factory() as s:
        assert set(sync.due_sources(s)) == {"gov24_api", "kto_tour50"}  # initial sync
    sync_tour50(page(jangheung()))
    with factory() as s:
        assert sync.due_sources(s) == ["gov24_api"]
        later = sync.utcnow() + timedelta(seconds=config.interval_seconds("kto_tour50") + 1)
        assert "kto_tour50" in sync.due_sources(s, later)
    monkeypatch.setenv(config.ENV_TOUR50_INTERVAL, "5")  # below minimum → clamped
    assert config.interval_seconds("kto_tour50") == config.MIN_TOUR50_INTERVAL
    monkeypatch.setenv(config.ENV_GOV24_INTERVAL, "43200")
    assert config.interval_seconds("gov24_api") == 43200


def test_scheduler_mode(monkeypatch):
    monkeypatch.setenv(config.ENV_SYNC_MODE, "auto")
    monkeypatch.setenv("KIROTHON_AI_MODE", "mock")
    assert config.scheduler_enabled() is False
    monkeypatch.setenv("KIROTHON_AI_MODE", "bedrock")
    assert config.scheduler_enabled() is True
    monkeypatch.setenv(config.ENV_SYNC_MODE, "off")
    assert config.scheduler_enabled() is False


def test_scheduler_runs_due_sources_once(monkeypatch):
    calls = []
    monkeypatch.setattr(sync, "run_sync", lambda source, trigger, f, **k: calls.append((source, trigger)))
    sched = sync.Scheduler(factory, tick_seconds=0.05)
    sched.start()
    import time as _t
    deadline = _t.monotonic() + 5
    while len(calls) < 2 and _t.monotonic() < deadline:
        _t.sleep(0.05)
    sched.stop()
    assert calls[:2] == [("gov24_api", "startup"), ("kto_tour50", "startup")]


# ------------------------------------------------------------------ read APIs
def test_sources_and_detail_endpoints(client):
    sync_tour50(page(jangheung()))
    sync.run_sync("gov24_api", "manual", factory, gov24_client=gov_client(FakeGov24(rows=[_row("MUAN01", "무안 여행 지원")])))
    s = client.get("/api/benefits/sources").json()
    assert "주기적 자동 갱신" in s["update_method"] and "실시간 아님" not in s["update_method"]
    by = {x["source"]: x for x in s["sources"]}
    assert by["kto_tour50"]["collection_method"] == "official_webpage"
    assert by["gov24_api"]["collection_method"] == "public_api"
    assert by["kto_tour50"]["refresh_interval_seconds"] == 1800
    d = client.get("/api/benefits/kto50:12770-2026-2").json()
    assert d["data_origin"] == "kto_tour50" and d["benefit"]["sync"]["record_version"] == 1
    assert d["benefit"]["sync"]["last_success_at"] and d["stale_status"] is False
    g = client.get("/api/benefits/gov24:MUAN01").json()
    assert g["data_origin"] == "gov24_api" and g["benefit"]["sync"]["source"] == "gov24_api"
    assert client.get("/api/benefits/kto50:99999-2026-1").status_code == 404
    assert client.get("/api/benefits/gov24:NOPE").status_code == 503  # not stored, no key
    assert client.get("/api/benefits/bad id").status_code == 422


def test_no_admin_http_endpoints(client):
    paths = set(client.get("/openapi.json").json()["paths"])
    assert "/api/benefits/check" in paths and "/api/benefits/sources" in paths
    assert not any("sync" in p or "admin" in p or "history" in p for p in paths)


def test_cli_status_and_history(capsys):
    from app.team.benefits import cli
    sync_tour50(page(jangheung()))
    assert cli.main(["status"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["kto_tour50"]["last_status"] == "ok" and out["kto_tour50"]["records"] == 2
    assert cli.main(["history", "--limit", "5"]) == 0
    hist = json.loads(capsys.readouterr().out)
    assert hist[0]["source"] == "kto_tour50" and hist[0]["trigger"] == "manual"
    assert cli.main(["versions", "tour50:12770:2026:2"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["version"] == 1
