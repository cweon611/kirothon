"""S1 collection: API client parsing/paging/errors and sync idempotency. No live calls."""
import json

import httpx
import pytest
from sqlmodel import Session, select

from app.database import engine, init_db
from app.team import sync_tourism
from app.team.regions import internal_code, name_key
from app.team.sync_tourism import build_parser, match_name, resolve_ldong, run
from app.team.tourapi import TourApiClient, TourApiError, parse_page
from app.team.tourism_models import HubRank, Place, RelatedPlace, TourismSyncRun

SECRET = "TEST-KEY-must-not-leak+/="


def body(items, total=None, code="0000", page=1, rows=100):
    return json.dumps({"response": {"header": {"resultCode": code, "resultMsg": "OK"},
                                    "body": {"items": {"item": items} if items != "" else "",
                                             "totalCount": len(items) if total is None else total,
                                             "pageNo": page, "numOfRows": rows}}})


def test_parse_page_shapes_and_codes():
    assert parse_page(body(""), "x").items == []
    assert parse_page(body({"contentid": "1"}, total=1), "x").items == [{"contentid": "1"}]
    assert parse_page(json.dumps({"response": {"header": {"resultCode": "03"}}}), "x").items == []
    with pytest.raises(TourApiError) as exc:
        parse_page(json.dumps({"response": {"header": {"resultCode": "21", "resultMsg": "TEMPORARILY_DISABLE"}}}), "x")
    assert exc.value.kind == "auth"
    gateway = ("<OpenAPI_ServiceResponse><cmmMsgHeader><returnAuthMsg>LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR"
               "</returnAuthMsg><returnReasonCode>22</returnReasonCode></cmmMsgHeader></OpenAPI_ServiceResponse>")
    with pytest.raises(TourApiError) as exc:
        parse_page(gateway, "x")
    assert exc.value.kind == "quota"
    with pytest.raises(TourApiError) as exc:
        parse_page("<html>maintenance</html>", "x")
    assert exc.value.kind == "parse"


def test_paging_collects_every_page_and_sends_common_params():
    seen = []

    def handler(request: httpx.Request):
        seen.append(dict(request.url.params))
        page = int(request.url.params["pageNo"])
        start = (page - 1) * 100
        items = [{"contentid": str(i)} for i in range(start, min(start + 100, 250))]
        return httpx.Response(200, text=body(items, total=250, page=page))

    with TourApiClient(SECRET, transport=httpx.MockTransport(handler), min_interval=0, sleep=lambda s: None) as client:
        items, total, truncated = client.fetch_all("KorService2", "areaBasedList2", num_of_rows=100,
                                                   contentTypeId="12", lDongRegnCd="46", lDongSignguCd="840")
    assert (len(items), total, truncated) == (250, 250, False)
    assert [p["pageNo"] for p in seen] == ["1", "2", "3"]
    assert all(p["MobileOS"] == "WEB" and p["_type"] == "json" and p["serviceKey"] == SECRET for p in seen)


def test_max_pages_reports_truncation():
    handler = lambda r: httpx.Response(200, text=body([{"contentid": r.url.params["pageNo"]}], total=50, rows=1))  # noqa: E731
    with TourApiClient(SECRET, transport=httpx.MockTransport(handler), min_interval=0, sleep=lambda s: None) as client:
        items, total, truncated = client.fetch_all("KorService2", "areaBasedList2", num_of_rows=1, max_pages=3)
    assert len(items) == 3 and total == 50 and truncated


@pytest.mark.parametrize("failure", ["timeout", "500"])
def test_retries_then_raises_without_key_in_message(failure):
    calls = []

    def handler(request):
        calls.append(1)
        if failure == "timeout":
            raise httpx.ReadTimeout("timed out " + str(request.url), request=request)
        return httpx.Response(500, text="error")

    with TourApiClient(SECRET, transport=httpx.MockTransport(handler), retries=2, min_interval=0,
                       sleep=lambda s: None) as client:
        with pytest.raises(TourApiError) as exc:
            client.get("KorService2", "detailCommon2", contentId="1")
    assert len(calls) == 3
    assert SECRET not in str(exc.value) and "serviceKey" not in str(exc.value)


def test_missing_key_and_unknown_operation_fail_fast(monkeypatch):
    monkeypatch.delenv("TOURAPI_SERVICE_KEY", raising=False)
    monkeypatch.delenv("KIROTHON_DATA_GO_KR_SERVICE_KEY", raising=False)
    with pytest.raises(TourApiError) as exc:
        TourApiClient()
    assert exc.value.kind == "config"
    with TourApiClient(SECRET) as client, pytest.raises(TourApiError):
        client.get("KorService2", "madeUpOperation")


def test_shared_portal_key_is_used_when_tourapi_key_is_absent(monkeypatch):
    from app.team.tourapi import has_service_key
    monkeypatch.delenv("TOURAPI_SERVICE_KEY", raising=False)
    monkeypatch.setenv("KIROTHON_DATA_GO_KR_SERVICE_KEY", SECRET)
    assert has_service_key()
    seen = []
    handler = lambda r: seen.append(r.url.params["serviceKey"]) or httpx.Response(200, text=body([]))  # noqa: E731
    with TourApiClient(transport=httpx.MockTransport(handler), min_interval=0) as client:
        client.get("KorService2", "ldongCode2")
    assert seen == [SECRET]


def test_ldong_resolution_detects_code_change():
    rows = [{"lDongRegnCd": "52", "lDongRegnNm": "전남광주통합특별시", "lDongSignguCd": "840", "lDongSignguNm": "무안군"},
            {"lDongRegnCd": "29", "lDongRegnNm": "광주광역시", "lDongSignguCd": "110", "lDongSignguNm": "동구"},
            {"lDongRegnCd": "26", "lDongRegnNm": "부산광역시", "lDongSignguCd": "110", "lDongSignguNm": "중구"}]
    resolved, changed, unresolved = resolve_ldong(rows)
    assert resolved["46840"] == ["52", "840"] and resolved["29110"] == ["29", "110"]
    assert [c["internal"] for c in changed] == ["46840"]
    assert "46110" in unresolved
    assert internal_code("52", "840", {"ldong": resolved}) == "46840"
    assert internal_code("46", "840", {}) == "46840"


def test_name_matching_requires_unique_or_coordinate():
    place = lambda cid, title, lat=35.0, lng=126.5: Place(content_id=cid, content_type_id="12", title=title,  # noqa: E731
                                                          sigungu_code="46840", lat=lat, lng=lng)
    pool = {"46840": [place("1", "무안 황토 갯벌랜드"), place("2", "테스트공원"), place("3", "테스트공원", 35.2)]}
    assert name_key("무안황토갯벌랜드(본관)") == name_key("무안 황토 갯벌랜드")
    assert match_name("무안황토갯벌랜드", "46840", pool, {}) == ("1", "name")
    assert match_name("테스트공원", "46840", pool, {}) == (None, None)
    assert match_name("테스트공원", "46840", pool, {}, (35.2, 126.5)) == ("3", "name+coord")
    assert match_name("테스트공원", "46840", pool, {"46840:테스트공원": "9"}) == ("9", "override")


class FakeClient:
    """Stands in for TourApiClient; records calls and returns canned rows."""

    def __init__(self, fail_hub_for=(), empty_hub_for=(), place_title="테스트공원"):
        self.calls = 0
        self.fail_hub_for = set(fail_hub_for)
        self.empty_hub_for = set(empty_hub_for)
        self.place_title = place_title

    def get(self, service, operation, **params):
        from app.team.tourapi import Page
        self.calls += 1
        return Page([], 0, 1, 0)

    def fetch_all(self, service, operation, **params):
        self.calls += 1
        if operation == "areaBasedList2":
            code = params["lDongRegnCd"] + params["lDongSignguCd"]
            if params["contentTypeId"] != "12":
                return [], 0, False
            return [{"contentid": f"{code}-1", "contenttypeid": "12", "title": self.place_title,
                     "lDongRegnCd": params["lDongRegnCd"], "lDongSignguCd": params["lDongSignguCd"],
                     "mapx": "126.5", "mapy": "35.0", "modifiedtime": "20261001120000"}], 1, False
        if service == "LocgoHubTarService1":
            code = params["signguCd"]
            if code in self.fail_hub_for:
                raise TourApiError("timeout", "LocgoHubTarService1/areaBasedList1 응답 시간 초과(10초)")
            if code in self.empty_hub_for:
                return [], 0, False
            return [{"hubTatsCd": f"H{code}", "hubTatsNm": self.place_title, "hubRank": "1",
                     "mapX": "126.5", "mapY": "35.0", "signguCd": code}], 1, False
        if service == "TarRlteTarService1":
            code = params["signguCd"]
            return [{"tAtsCd": f"H{code}", "tAtsNm": self.place_title, "rlteTatsCd": f"R{code}",
                     "rlteTatsNm": "없는곳", "rlteSignguCd": code, "rlteRank": "1"}], 1, False
        return [], 0, False


def sync_args(*extra):
    return build_parser().parse_args(["--steps", "places,hubs,related,match", "--base-ym", "202410",
                                      "--sigungu", "46840", "--sigungu", "46860", *extra])


@pytest.fixture
def clean_tourism_tables():
    init_db()

    def wipe():
        with Session(engine) as session:
            for model in (Place, HubRank, RelatedPlace, TourismSyncRun):
                for row in session.exec(select(model)).all():
                    session.delete(row)
            session.commit()
    wipe()
    yield
    wipe()


def test_sync_is_idempotent_and_keeps_rows_on_failure(clean_tourism_tables):
    first = run(sync_args(), client=FakeClient())
    assert first.status == "success"
    with Session(engine) as session:
        assert len(session.exec(select(Place)).all()) == 2
        assert len(session.exec(select(HubRank)).all()) == 2
        hub = session.exec(select(HubRank).where(HubRank.sigungu_code == "46840")).one()
        assert hub.content_id == "46840-1" and hub.match_method == "name+coord"
    second = run(sync_args(), client=FakeClient(fail_hub_for={"46840"}, empty_hub_for={"46860"},
                                                place_title="테스트공원 개명"))
    assert second.status == "partial"
    steps = json.loads(second.steps_json)
    assert steps["hubs"]["failures"][0]["target"] == "46840"
    assert any(n.get("kept_previous") for n in steps["hubs"]["notes"])
    with Session(engine) as session:
        assert len(session.exec(select(Place)).all()) == 2, "re-sync must upsert, not duplicate"
        assert session.get(Place, "46840-1").title == "테스트공원 개명"
        assert len(session.exec(select(HubRank)).all()) == 2, "failed/empty sigungu keep previous hubs"
    assert SECRET not in second.steps_json


def test_sync_without_key_records_failed_run(clean_tourism_tables, monkeypatch):
    monkeypatch.delenv("TOURAPI_SERVICE_KEY", raising=False)
    monkeypatch.delenv("KIROTHON_DATA_GO_KR_SERVICE_KEY", raising=False)
    record = run(sync_args())
    assert record.status == "failed" and "TOURAPI_SERVICE_KEY" in record.message


def test_concurrent_run_marker_blocks_second_run(clean_tourism_tables):
    with Session(engine) as session:
        session.add(TourismSyncRun(status="running"))
        session.commit()
    with pytest.raises(SystemExit):
        run(sync_args(), client=FakeClient())
    assert run(sync_args("--force"), client=FakeClient()).status == "success"


def test_month_back_and_probe_stops_on_first_data():
    assert sync_tourism.month_back("202601", 1) == "202512"
    assert sync_tourism.month_back("202504", 12) == "202404"

    class Probe(FakeClient):
        def get(self, service, operation, **params):
            from app.team.tourapi import Page
            self.calls += 1
            return Page([{"x": 1}] if params["baseYm"] <= "202504" else [], 1, 1, 1)

    client = Probe()
    assert sync_tourism.probe_base_ym(client, "TarRlteTarService1", "202507", "46840") == "202504"
    assert client.calls == 4
