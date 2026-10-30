"""Client for 행정안전부_대한민국 공공서비스(혜택) 정보 (data.go.kr 15113968).

Confirmed from the official Swagger spec
(https://infuser.odcloud.kr/api/stages/44436/api-docs, linked from
https://www.data.go.kr/data/15113968/openapi.do):

- host api.odcloud.kr, basePath /api, HTTPS
- GET /gov24/v3/serviceList        page, perPage, returnType,
                                   cond[서비스ID::EQ], cond[서비스명::LIKE],
                                   cond[등록일시::LT|LTE|GT|GTE], cond[수정일시::LT|LTE|GT|GTE]
- GET /gov24/v3/serviceDetail      page, perPage, cond[서비스ID::EQ]
- GET /gov24/v3/supportConditions  page, perPage, cond[서비스ID::EQ]
- auth: query ``serviceKey`` or header ``Authorization`` (query is used here)
- response envelope: page, perPage, totalCount, currentCount, matchCount, data[]
- a request without a key returns HTTP 401 {"code": -401, "msg": "인증키는 필수 항목 입니다."}
  (checked live on 2026-10-30)

The key is read from the environment on every call and is never logged,
returned, or included in error messages.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote

import httpx

BASE_URL = "https://api.odcloud.kr/api/gov24/v3"
ENV_SERVICE_KEY = "KIROTHON_DATA_GO_KR_SERVICE_KEY"
ENV_CACHE_TTL = "KIROTHON_GOV24_CACHE_TTL_SECONDS"
ENV_MAX_PAGES = "KIROTHON_GOV24_MAX_PAGES"
ENV_DAILY_LIMIT = "KIROTHON_GOV24_DAILY_CALL_LIMIT"
PER_PAGE = 100
DEFAULT_MAX_PAGES = 5
DEFAULT_CACHE_TTL = 6 * 3600
ERROR_CACHE_TTL = 60
DEFAULT_DAILY_LIMIT = 9000  # data.go.kr 개발계정 10,000/일 아래로 여유를 둔다
TIMEOUT = httpx.Timeout(10.0, connect=5.0)
KST = timezone(timedelta(hours=9))

# httpx logs full request URLs (including the serviceKey query) at INFO level.
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger(__name__)


class Gov24Error(Exception):
    """``code`` is safe to return to clients; the message never contains the key or URL."""

    def __init__(self, code: str, message: str, status: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass
class ListResult:
    records: list[dict]
    pages_fetched: int
    match_count: int | None
    truncated: bool
    from_cache: bool
    fetched_at: datetime


@dataclass
class _Cache:
    entries: dict = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)
    day: str = ""
    calls: int = 0

    def get(self, key):
        with self.lock:
            hit = self.entries.get(key)
            if hit and hit[0] > time.monotonic():
                return hit[1]
            self.entries.pop(key, None)
            return None

    def put(self, key, value, ttl: float):
        with self.lock:
            if len(self.entries) > 2000:
                self.entries.clear()
            self.entries[key] = (time.monotonic() + ttl, value)

    def take_call(self, limit: int) -> bool:
        with self.lock:
            today = datetime.now(KST).date().isoformat()
            if today != self.day:
                self.day, self.calls = today, 0
            if self.calls >= limit:
                return False
            self.calls += 1
            return True

    def clear(self):
        with self.lock:
            self.entries.clear()
            self.calls = 0


_CACHE = _Cache()


def clear_cache() -> None:
    _CACHE.clear()


def _int_env(name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(os.environ.get(name, default))
    except ValueError:
        return default
    return min(max(value, low), high)


def service_key_configured() -> bool:
    return bool(os.environ.get(ENV_SERVICE_KEY, "").strip())


class Gov24Client:
    def __init__(self, service_key: str, transport: httpx.BaseTransport | None = None,
                 cache: _Cache | None = None, use_cache: bool = True, retries: int = 0,
                 retry_delay: float = 2.0):
        key = service_key.strip()
        # data.go.kr issues an Encoding and a Decoding key; httpx encodes params itself.
        self._key = unquote(key) if "%" in key else key
        self._transport = transport
        self._cache = cache or _CACHE
        self._use_cache = use_cache
        self._retries = max(0, min(retries, 3))
        self._retry_delay = retry_delay
        self.max_pages = _int_env(ENV_MAX_PAGES, DEFAULT_MAX_PAGES, 1, 20)
        self.cache_ttl = _int_env(ENV_CACHE_TTL, DEFAULT_CACHE_TTL, 0, 7 * 86400)
        self.daily_limit = _int_env(ENV_DAILY_LIMIT, DEFAULT_DAILY_LIMIT, 1, 1_000_000)

    def __repr__(self):  # never expose the key
        return "Gov24Client(<key hidden>)"

    # ------------------------------------------------------------ transport
    def _get(self, path: str, params: dict) -> dict:
        """Limited retries only for transient failures (timeout, network, 429, 5xx)."""
        delay = self._retry_delay
        for attempt in range(self._retries + 1):
            try:
                return self._get_once(path, params)
            except Gov24Error as exc:
                transient = exc.code in {"timeout", "network_error", "rate_limited", "upstream_error"}
                if not transient or attempt >= self._retries:
                    raise
                time.sleep(delay)
                delay *= 2.5
        raise AssertionError("unreachable")

    def _get_once(self, path: str, params: dict) -> dict:
        cache_key = (path, tuple(sorted(params.items())))
        cached = self._cache.get(cache_key) if self._use_cache else None
        if cached is not None:
            if isinstance(cached, Gov24Error):
                raise cached
            return {**cached, "_from_cache": True}
        if not self._cache.take_call(self.daily_limit):
            raise Gov24Error("local_rate_limit", "외부 API 일일 호출 한도(서버 설정)에 도달했습니다.")
        try:
            with httpx.Client(base_url=BASE_URL, timeout=TIMEOUT, transport=self._transport) as client:
                response = client.get(path, params={**params, "serviceKey": self._key,
                                                    "returnType": "JSON"})
        except httpx.TimeoutException:
            err = Gov24Error("timeout", "공공서비스 API 응답 시간 초과")
            self._cache.put(cache_key, err, ERROR_CACHE_TTL)
            raise err from None
        except httpx.HTTPError as exc:
            log.warning("gov24 request failed: %s", type(exc).__name__)
            err = Gov24Error("network_error", "공공서비스 API 연결 실패")
            self._cache.put(cache_key, err, ERROR_CACHE_TTL)
            raise err from None
        if response.status_code != 200:
            code = {401: "auth_error", 403: "auth_error", 429: "rate_limited"}.get(
                response.status_code, "upstream_error" if response.status_code >= 500 else "http_error")
            err = Gov24Error(code, f"공공서비스 API 오류 (HTTP {response.status_code})", response.status_code)
            log.warning("gov24 %s returned HTTP %s", path, response.status_code)
            self._cache.put(cache_key, err, ERROR_CACHE_TTL)
            raise err
        try:
            payload = response.json()
        except ValueError:
            raise Gov24Error("bad_response", "공공서비스 API 응답이 JSON이 아닙니다.") from None
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise Gov24Error("bad_response", "공공서비스 API 응답에 data 목록이 없습니다.")
        payload["_fetched_at"] = datetime.now(timezone.utc).isoformat()
        if self.cache_ttl and self._use_cache:
            self._cache.put(cache_key, payload, self.cache_ttl)
        return {**payload, "_from_cache": False}

    # ------------------------------------------------------------ operations
    def list_services(self, name_like: str) -> ListResult:
        records: list[dict] = []
        pages = 0
        match_count = None
        from_cache = True
        fetched = []
        for page in range(1, self.max_pages + 1):
            payload = self._get("/serviceList", {"page": page, "perPage": PER_PAGE,
                                                 "cond[서비스명::LIKE]": name_like})
            pages += 1
            from_cache = from_cache and payload["_from_cache"]
            fetched.append(payload["_fetched_at"])
            batch = payload["data"]
            records.extend(r for r in batch if isinstance(r, dict))
            total = payload.get("matchCount", payload.get("totalCount"))
            match_count = total if isinstance(total, int) else match_count
            if not batch or (match_count is not None and len(records) >= match_count):
                break
            if match_count is None and len(batch) < PER_PAGE:
                break
        truncated = match_count is not None and len(records) < match_count
        oldest = min(datetime.fromisoformat(x) for x in fetched)
        return ListResult(records, pages, match_count, truncated, from_cache, oldest)

    def _single(self, path: str, service_id: str) -> tuple[dict | None, bool]:
        payload = self._get(path, {"page": 1, "perPage": 1, "cond[서비스ID::EQ]": service_id})
        data = [r for r in payload["data"] if isinstance(r, dict)]
        return (data[0] if data else None), payload["_from_cache"]

    def service_summary(self, service_id: str) -> tuple[dict | None, bool]:
        """serviceList row (has 상세조회URL, which serviceDetail does not)."""
        return self._single("/serviceList", service_id)

    def service_detail(self, service_id: str) -> tuple[dict | None, bool]:
        return self._single("/serviceDetail", service_id)

    def support_conditions(self, service_id: str) -> tuple[dict | None, bool]:
        return self._single("/supportConditions", service_id)


def get_gov24_client() -> Gov24Client | None:
    """FastAPI dependency. None when the server has no key configured."""
    key = os.environ.get(ENV_SERVICE_KEY, "")
    return Gov24Client(key) if key.strip() else None
