"""'환급제 한눈에' list (design 5-7): benefit programs whose target region is in Gwangju/Jeonnam.

Reads the benefits module's stored sync data and manual registry; no external calls
and no eligibility judgment (that needs the user's conditions: /api/benefits/check).
"""
from datetime import date

from sqlmodel import Session

from .benefit_bridge import region_of
from .benefits import sync as benefit_sync
from .benefits.engine import CLOSED, KST, STALE_DAYS
from .benefits.regions import region_matches
from .benefits.routes import source_statuses
from .benefits.schemas import BenefitProgram
from .benefits.search import collect_stored
from .regions import sigungu_map

STATUS_ORDER = {"open": 0, "closing_soon": 1, "upcoming": 2, None: 3}


def open_now(p: BenefitProgram, today: date) -> bool | None:
    """True/False only when the posted status or a complete application period says so."""
    if p.posted_status in ("open", "closing_soon"):
        return True
    if p.posted_status in CLOSED or p.posted_status == "upcoming":
        return False
    period = p.application_period
    if period and period.start and period.end:
        return period.start <= today <= period.end
    if period and period.end and period.end < today:
        return False
    return None


def _stale(p: BenefitProgram, today: date) -> bool | None:
    if p.sync is not None:
        return p.sync.stale
    if p.status_checked_at:
        return (today - p.status_checked_at.astimezone(KST).date()).days > STALE_DAYS
    return None


def _dates(rng) -> dict | None:
    return {"start": rng.start.isoformat() if rng.start else None,
            "end": rng.end.isoformat() if rng.end else None} if rng else None


def list_programs(session: Session, today: date) -> dict:
    regions = {code: region_of(code) for code in sigungu_map()}
    stored = benefit_sync.load_programs(session)
    programs, _ = collect_stored(stored, list(regions.values()))
    official = {p.program_id for p, origin in programs if origin != "manual_registry"}
    items = []
    for p, origin in programs:
        targets = p.target_regions or p.region_hints
        codes = [code for code, region in regions.items()
                 if any(region_matches(target, region) for target in targets or [])]
        if not codes:
            continue
        state = open_now(p, today)
        items.append({
            "program_id": p.id, "family_id": p.program_id, "round_id": p.round_id, "name": p.name,
            "provider": p.provider, "sigungu_codes": codes,
            "sigungu_names": [sigungu_map()[c].label for c in codes],
            "posted_status": p.posted_status, "open_now": state,
            "application_period": _dates(p.application_period), "trip_period": _dates(p.trip_period),
            "refund_rate": p.benefit.refund_rate if p.benefit else None,
            "benefit_type": p.benefit.benefit_type if p.benefit else None,
            "data_origin": origin, "source_type": p.source_type,
            "verification_status": p.verification_status,
            "review_status": p.sync.review_status if p.sync else None,
            "status_checked_at": p.status_checked_at.isoformat() if p.status_checked_at else None,
            "stale": _stale(p, today),
            "superseded_by": [i for i in p.related_program_ids if i in official] if origin == "manual_registry" else [],
            "official_info_url": p.official_info_url, "application_url": p.application_url,
        })
    rank = {True: 0, None: 1, False: 2}
    items.sort(key=lambda i: (rank[i["open_now"]], STATUS_ORDER.get(i["posted_status"], 4),
                              i["sigungu_codes"][0], i["name"]))
    sources = source_statuses(session)
    return {
        "today": today.isoformat(),
        "scope": "광주·전남 27개 시군구를 대상 지역으로 하는 지원제도(수집 자료 + 수동 등록 자료)",
        "counts": {"total": len(items), "open_now": sum(1 for i in items if i["open_now"] is True)},
        "programs": items,
        "sources": [{"source": s.source, "status": s.status, "stale": s.stale,
                     "last_success_at": s.last_success_at.isoformat() if s.last_success_at else None}
                    for s in sources],
        "note": "접수 여부는 게시 상태·신청 기간 기준이며 개인 자격 판정이 아니에요. 목록에 없다고 지원제도가 없다는 뜻은 아니에요.",
    }
