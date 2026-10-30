"""KTO public API client (KorService2, LocgoHubTarService1, TarRlteTarService1).

Operations and fields follow the Swagger specs embedded in the data.go.kr pages
15101578, 15128559 and 15128560 (checked 2026-10-30). The service key is read
only from the TOURAPI_SERVICE_KEY environment variable and never appears in
exceptions, logs or return values.
"""
from dataclasses import dataclass
import json
import logging
import os
import re
import time
from collections.abc import Callable, Iterator
from urllib.parse import unquote

import httpx

BASE_URL = "https://apis.data.go.kr/B551011"
KEY_ENV = "TOURAPI_SERVICE_KEY"
# A data.go.kr key belongs to the account, so the benefits module's key also works
# once the tourism APIs are approved for that account.
SHARED_KEY_ENV = "KIROTHON_DATA_GO_KR_SERVICE_KEY"
APP_ENV = "TOURAPI_MOBILE_APP"
OPERATIONS = {
    "KorService2": {"ldongCode2", "lclsSystmCode2", "areaBasedList2", "locationBasedList2",
                    "searchKeyword2", "searchFestival2", "searchStay2", "detailCommon2",
                    "detailIntro2", "detailInfo2", "detailImage2", "areaBasedSyncList2"},
    "LocgoHubTarService1": {"areaBasedList1"},
    "TarRlteTarService1": {"areaBasedList1", "searchKeyword1"},
}
# resultCode values listed in the Swagger responses; "0000" is the success header
# code returned by KorService2 (to confirm on the first live call).
SUCCESS_CODES = {"0000", "00"}
NODATA_CODES = {"03"}
RETRYABLE_CODES = {"05", "02"}
AUTH_CODES = {"20", "21", "30", "31", "32", "33"}
QUOTA_CODES = {"22"}

# httpx logs full request URLs (including serviceKey) at INFO level.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


class TourApiError(Exception):
    """kind: config | auth | quota | timeout | http | parse | upstream."""

    def __init__(self, kind: str, message: str, code: str | None = None):
        super().__init__(message)
        self.kind = kind
        self.code = code

    def to_dict(self) -> dict:
        return {"kind": self.kind, "code": self.code, "message": str(self)}


@dataclass
class Page:
    items: list[dict]
    total_count: int
    page_no: int
    num_of_rows: int


def env_service_key() -> str:
    return (os.environ.get(KEY_ENV, "").strip() or os.environ.get(SHARED_KEY_ENV, "").strip())


def has_service_key() -> bool:
    return bool(env_service_key())


class TourApiClient:
    def __init__(self, service_key: str | None = None, *, timeout: float = 10.0,
                 min_interval: float = 0.2, retries: int = 2,
                 transport: httpx.BaseTransport | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        key = (service_key if service_key is not None else env_service_key()).strip()
        if not key:
            raise TourApiError("config", f"{KEY_ENV}(또는 {SHARED_KEY_ENV}) 환경변수가 설정되지 않았습니다.")
        # Decoding key goes into params; an Encoding key would be double-encoded.
        self._key = unquote(key)
        self._app = os.environ.get(APP_ENV, "").strip() or "RefundFirstCourse"
        self._timeout = timeout
        self._min_interval = min_interval
        self._retries = retries
        self._sleep = sleep
        self._last_call = 0.0
        self._client = httpx.Client(timeout=timeout, transport=transport)
        self.calls = 0

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _throttle(self) -> None:
        wait = self._min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            self._sleep(wait)
        self._last_call = time.monotonic()

    def get(self, service: str, operation: str, **params) -> Page:
        if operation not in OPERATIONS.get(service, set()):
            raise TourApiError("config", f"지원하지 않는 오퍼레이션: {service}/{operation}")
        query = {"serviceKey": self._key, "MobileOS": "WEB", "MobileApp": self._app, "_type": "json",
                 "pageNo": 1, "numOfRows": 100}
        query.update({k: v for k, v in params.items() if v is not None})
        url = f"{BASE_URL}/{service}/{operation}"
        last: TourApiError | None = None
        for attempt in range(self._retries + 1):
            if attempt:
                self._sleep(min(2.0 * attempt, 5.0))
            self._throttle()
            self.calls += 1
            try:
                response = self._client.get(url, params=query)
            except httpx.TimeoutException:
                last = TourApiError("timeout", f"{service}/{operation} 응답 시간 초과({self._timeout:.0f}초)")
                continue
            except httpx.HTTPError as exc:
                # The exception text can contain the request URL with the key.
                last = TourApiError("http", f"{service}/{operation} 연결 실패({type(exc).__name__})")
                continue
            if response.status_code == 429 or response.status_code >= 500:
                last = TourApiError("http", f"{service}/{operation} HTTP {response.status_code}",
                                    str(response.status_code))
                continue
            if response.status_code >= 400:
                raise TourApiError("http", f"{service}/{operation} HTTP {response.status_code}",
                                   str(response.status_code))
            try:
                return parse_page(response.text, f"{service}/{operation}")
            except TourApiError as exc:
                if exc.code in RETRYABLE_CODES:
                    last = exc
                    continue
                raise
        assert last is not None
        raise last

    def iter_pages(self, service: str, operation: str, *, num_of_rows: int = 100,
                   max_pages: int = 20, **params) -> Iterator[Page]:
        """Yield pages until totalCount is covered. Stops at max_pages (caller reports truncation)."""
        page_no = 1
        while page_no <= max_pages:
            page = self.get(service, operation, pageNo=page_no, numOfRows=num_of_rows, **params)
            yield page
            if not page.items or page_no * num_of_rows >= page.total_count:
                return
            page_no += 1

    def fetch_all(self, service: str, operation: str, *, num_of_rows: int = 100,
                  max_pages: int = 20, **params) -> tuple[list[dict], int, bool]:
        """Return (items, total_count, truncated)."""
        items: list[dict] = []
        total = 0
        for page in self.iter_pages(service, operation, num_of_rows=num_of_rows,
                                    max_pages=max_pages, **params):
            items.extend(page.items)
            total = page.total_count
        return items, total, total > len(items)


def parse_page(text: str, label: str) -> Page:
    """Parse a data.go.kr JSON body. Gateway errors arrive as XML even with _type=json."""
    try:
        data = json.loads(text)
    except ValueError:
        code = _xml_tag(text, "returnReasonCode") or _xml_tag(text, "resultCode")
        reason = _xml_tag(text, "returnAuthMsg") or _xml_tag(text, "resultMsg") or "응답 형식 오류"
        if code is None:
            raise TourApiError("parse", f"{label} 응답을 해석하지 못했습니다(JSON 아님).") from None
        raise _code_error(label, code, reason) from None
    if not isinstance(data, dict) or not isinstance(data.get("response"), dict):
        raise TourApiError("parse", f"{label} 응답에 response 항목이 없습니다.")
    header = data["response"].get("header") or {}
    code = str(header.get("resultCode", "")).strip()
    if code in NODATA_CODES:
        return Page([], 0, 1, 0)
    if code not in SUCCESS_CODES:
        raise _code_error(label, code, str(header.get("resultMsg") or ""))
    body = data["response"].get("body") or {}
    items = body.get("items")
    rows = items.get("item", []) if isinstance(items, dict) else []
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list):
        raise TourApiError("parse", f"{label} items 형식이 예상과 다릅니다.")
    try:
        return Page([r for r in rows if isinstance(r, dict)], int(body.get("totalCount") or 0),
                    int(body.get("pageNo") or 1), int(body.get("numOfRows") or 0))
    except (TypeError, ValueError):
        raise TourApiError("parse", f"{label} 페이지 정보를 해석하지 못했습니다.") from None


def _xml_tag(text: str, tag: str) -> str | None:
    match = re.search(rf"<{tag}>\s*([^<]*?)\s*</{tag}>", text or "")
    return match.group(1) if match else None


def _code_error(label: str, code: str, reason: str) -> TourApiError:
    reason = re.sub(r"[^0-9A-Za-z가-힣_()\s.-]", "", reason)[:80]
    if code in AUTH_CODES:
        return TourApiError("auth", f"{label} 인증키 오류({code} {reason})", code)
    if code in QUOTA_CODES:
        return TourApiError("quota", f"{label} 일일 호출 한도 초과({code} {reason})", code)
    return TourApiError("upstream", f"{label} 오류 응답({code} {reason})", code)
