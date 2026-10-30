"""Boundary between course planning (F1, F2) and the benefit check (지원제도 판정).

The benefit check, its data, refund amounts and application deadlines belong to
the benefits module (POST /api/benefits/check). This file only defines what
F1/F2 need from it, so neither side guesses the other's internals:

* F1 asks, for each candidate sigungu, which programs a hypothetical visit on
  the trip dates would match, with the benefits module's own judgment.
* F2 asks for the course constraints of one chosen program (required places,
  stay weekdays, merchant region) and never re-judges eligibility.

team/routes.py registers benefit_bridge.BenefitsEnginePort, which runs the
benefits engine in-process. Without a registered port the default reports
`not_connected`; F1 then shows no refund group instead of claiming that no
program exists. Values the benefits module could not confirm stay None.
"""
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Literal, Protocol

Judgment = Literal["potentially_eligible", "ineligible", "needs_verification"]
LookupStatus = Literal["ok", "partial", "error", "not_connected"]


@dataclass(frozen=True)
class CourseConstraints:
    required_place_names: tuple[str, ...] | None = None
    required_content_ids: tuple[str, ...] | None = None
    min_spots: int | None = None
    min_nights: int | None = None
    stay_checkin_weekdays: tuple[int, ...] | None = None  # 0=Mon ... 6=Sun
    merchant_region_only: bool | None = None


@dataclass(frozen=True)
class ProgramSummary:
    program_id: str
    name: str
    judgment: Judgment
    round_id: str | None = None
    sigungu_codes: tuple[str, ...] = ()
    posted_status: str | None = None
    application_open: bool | None = None
    rate: float | None = None
    cap_krw: int | None = None
    stale: bool | None = None
    last_verified_at: str | None = None
    source_url: str | None = None
    apply_url: str | None = None
    reasons: tuple[str, ...] = ()
    unmet_codes: tuple[str, ...] = ()  # codes of unmet conditions, e.g. ("stay",)
    constraints: CourseConstraints = field(default_factory=CourseConstraints)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class RegionBenefitQuery:
    trip_type: str
    trip_start: date
    trip_end: date
    sigungu_codes: tuple[str, ...]
    party_size: int
    today: date
    residence_code: str | None = None
    # Opaque passthrough (birth date, family, past participation ...) in the
    # benefits module's own request format. Never stored by F1/F2.
    conditions: dict = field(default_factory=dict)


@dataclass(frozen=True)
class BenefitLookup:
    status: LookupStatus
    checked_at: str | None = None
    by_region: dict[str, tuple[ProgramSummary, ...]] = field(default_factory=dict)
    scope_note: str | None = None
    message: str | None = None
    failed_sources: tuple[str, ...] = ()
    alternatives: tuple[ProgramSummary, ...] = ()


class BenefitPort(Protocol):
    def lookup(self, query: RegionBenefitQuery) -> BenefitLookup: ...

    def program(self, program_id: str, query: RegionBenefitQuery) -> ProgramSummary | None: ...


class NotConnectedBenefitPort:
    connected = False

    def lookup(self, query: RegionBenefitQuery) -> BenefitLookup:
        return BenefitLookup(status="not_connected",
                             message="지원제도 확인 모듈이 아직 연결되지 않아 환급 가능 여부를 확인하지 않았어요.")

    def program(self, program_id: str, query: RegionBenefitQuery) -> ProgramSummary | None:
        return None


_port: BenefitPort = NotConnectedBenefitPort()


def get_benefit_port() -> BenefitPort:
    return _port


def set_benefit_port(port: BenefitPort) -> None:
    global _port
    _port = port


def is_connected() -> bool:
    return getattr(_port, "connected", True) is not False


def safe_lookup(query: RegionBenefitQuery) -> BenefitLookup:
    """A failing benefits module must not break course recommendation."""
    try:
        return get_benefit_port().lookup(query)
    except Exception:  # noqa: BLE001 -- the port is owned by another module
        return BenefitLookup(status="error", message="지원제도 확인 중 오류가 나서 환급 가능 여부를 확인하지 못했어요.")


def safe_program(program_id: str, query: RegionBenefitQuery) -> tuple[ProgramSummary | None, str]:
    """Return (program, status) where status is ok | not_found | error | not_connected."""
    if not is_connected():
        return None, "not_connected"
    try:
        program = get_benefit_port().program(program_id, query)
    except Exception:  # noqa: BLE001
        return None, "error"
    return program, "ok" if program else "not_found"
