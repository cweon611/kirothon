"""Environment-driven settings for periodic benefit data collection.

Every value is read at call time (never at import) so tests and the deploy
check can change the environment freely.
"""
import os

ENV_SYNC_MODE = "KIROTHON_BENEFIT_SYNC_MODE"            # auto | on | off
ENV_GOV24_INTERVAL = "KIROTHON_BENEFIT_SYNC_GOV24_SECONDS"
ENV_TOUR50_INTERVAL = "KIROTHON_BENEFIT_SYNC_TOUR50_SECONDS"
ENV_STALE_FACTOR = "KIROTHON_BENEFIT_STALE_FACTOR"
ENV_TOUR50_ENABLED = "KIROTHON_TOUR50_ENABLED"
ENV_GOV24_MAX_DETAIL = "KIROTHON_GOV24_MAX_DETAIL_PER_RUN"

DEFAULT_GOV24_INTERVAL = 6 * 3600   # 목록·상세: 원본 갱신이 잦지 않고 일 10,000건 한도 공유
DEFAULT_TOUR50_INTERVAL = 30 * 60   # 접수 상태: 단일 페이지 1회 요청
MIN_GOV24_INTERVAL = 30 * 60
MIN_TOUR50_INTERVAL = 10 * 60
SOURCES = ("gov24_api", "kto_tour50")


def _int(name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(os.environ.get(name, "") or default)
    except ValueError:
        return default
    return min(max(value, low), high)


def interval_seconds(source: str) -> int:
    if source == "gov24_api":
        return _int(ENV_GOV24_INTERVAL, DEFAULT_GOV24_INTERVAL, MIN_GOV24_INTERVAL, 7 * 86400)
    return _int(ENV_TOUR50_INTERVAL, DEFAULT_TOUR50_INTERVAL, MIN_TOUR50_INTERVAL, 7 * 86400)


def stale_after_seconds(source: str) -> int:
    """Data is stale when the last successful collection is older than factor × interval."""
    return interval_seconds(source) * _int(ENV_STALE_FACTOR, 2, 1, 48)


def gov24_max_detail_per_run() -> int:
    return _int(ENV_GOV24_MAX_DETAIL, 40, 0, 500)


def tour50_enabled() -> bool:
    return os.environ.get(ENV_TOUR50_ENABLED, "true").strip().lower() not in {"0", "false", "off", "no"}


def scheduler_enabled() -> bool:
    """auto: run on the server (bedrock mode), not in local mock mode, tests, or deploy check."""
    mode = os.environ.get(ENV_SYNC_MODE, "auto").strip().lower()
    if mode in {"on", "true", "1"}:
        return True
    if mode in {"off", "false", "0"}:
        return False
    return os.environ.get("KIROTHON_AI_MODE", "bedrock").strip().lower() == "bedrock"
