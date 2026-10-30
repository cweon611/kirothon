"""F1 refund-first region recommendation (design 9-3).

Grouping uses only the benefits module's judgment (benefit_port); this module
never decides eligibility. Scores order regions inside a group only.
"""
from dataclasses import dataclass, field
from datetime import date, timedelta

from .benefit_port import BenefitLookup, ProgramSummary
from .geo import move_minutes
from .regions import Origin, interest_basis, sigungu_map
from .tourism_data import Snapshot

TRAVEL_CAP_MIN = {"day": 150, "1N2D": 240}
FULL_ACCESS_MIN = 60
JUDGMENT_ORDER = {"potentially_eligible": 0, "needs_verification": 1, "ineligible": 2}
DISPLAYABLE_PHOTO = {"Type1", "Type3"}


@dataclass
class TripQuery:
    trip_type: str
    start_date: date
    origin: str
    interests: list[str]
    party_size: int
    transport: str = "car"
    meal_cost_krw: int | None = None
    room_price_krw: int | None = None

    @property
    def end_date(self) -> date:
        return self.start_date + timedelta(days=1 if self.trip_type == "1N2D" else 0)

    def public(self) -> dict:
        return {"trip_type": self.trip_type, "start_date": self.start_date.isoformat(),
                "end_date": self.end_date.isoformat(), "origin": self.origin, "interests": self.interests,
                "party_size": self.party_size, "transport": self.transport}


@dataclass
class RegionResult:
    code: str
    group: int
    score: int
    breakdown: dict
    travel_min: int | None
    program: ProgramSummary | None
    badge: str
    tags: list[str] = field(default_factory=list)


def classify(programs: tuple[ProgramSummary, ...], trip_type: str) -> tuple[ProgramSummary | None, str, bool]:
    """Return (representative program, badge, is_group1)."""
    if not programs:
        return None, "none", False

    def needs_stay(p: ProgramSummary) -> bool:
        return trip_type == "day" and (p.constraints.min_nights or 0) >= 1

    # needs_verification with an unmet condition means "unmet, but the rule is not from a
    # verified source"; such programs are shown in group 2, not as refund regions.
    usable = [p for p in programs
              if p.judgment != "ineligible" and p.application_open is not False and not needs_stay(p)
              and not (p.judgment == "needs_verification" and p.unmet_codes)]
    if usable:
        best = min(usable, key=lambda p: (JUDGMENT_ORDER[p.judgment], -(p.cap_krw or 0), p.program_id))
        applicable = best.judgment == "potentially_eligible" and best.application_open is True
        return best, "applicable" if applicable else "needs_verification", True
    # A day trip fails an overnight program only because of the stay: show "needs_stay", not "ineligible".
    stay = [p for p in programs if needs_stay(p) and p.application_open is not False
            and (p.judgment != "ineligible" or set(p.unmet_codes) <= {"stay"})]
    if stay:
        return stay[0], "needs_stay", False
    closed = [p for p in programs if p.application_open is False]
    if closed:
        return closed[0], "closed", False
    unverified = [p for p in programs if p.judgment == "needs_verification"]
    if unverified:
        return unverified[0], "unmet_unverified", False
    return programs[0], "ineligible", False


def score_region(snapshot: Snapshot, code: str, query: TripQuery, origin: Origin) -> dict:
    cap = TRAVEL_CAP_MIN[query.trip_type]
    centroid, basis = snapshot.centroid(code)
    travel = move_minutes((origin.lat, origin.lng), centroid, query.transport) if centroid else None
    if travel is None:
        access = 0.0
    elif travel <= FULL_ACCESS_MIN:
        access = 30.0
    else:
        access = max(0.0, 30.0 * (cap - travel) / (cap - FULL_ACCESS_MIN))
    pool = snapshot.spots(code) + (snapshot.of_type(code, "39") if "food" in query.interests else [])
    matched = [p for p in pool if snapshot.interest_labels(p, query.interests)]
    interest = 40.0 * len(matched) / len(pool) if pool else 0.0
    hub_hits = []
    for hub in snapshot.hubs.get(code, [])[:5]:
        place = snapshot.places.get(hub.content_id or "")
        if place and snapshot.interest_labels(place, query.interests):
            hub_hits.append(hub)
    festivals = snapshot.festivals_during(code, query.start_date, query.end_date)
    breakdown = {"interest": round(interest), "access": round(access), "hub": 4 * len(hub_hits),
                 "season": 10 if festivals else 0}
    return {"travel_min": travel, "over_cap": travel is not None and travel > cap, "centroid_basis": basis,
            "breakdown": breakdown, "score": sum(breakdown.values()), "matched": matched,
            "hub_hits": hub_hits, "festivals": festivals}


def reason_tags(snapshot: Snapshot, code: str, query: TripQuery, origin: Origin, scored: dict,
                program: ProgramSummary | None, badge: str) -> list[str]:
    tags = []
    if program and badge == "applicable":
        tags.append(f"{program.name} 적용 예상")
    elif program and badge == "needs_verification":
        tags.append(f"{program.name} 확인 필요")
    if program and program.stale:
        tags.append("공고 재확인 필요")
    counts = {}
    for place in scored["matched"]:
        for label in snapshot.interest_labels(place, query.interests):
            counts[label] = counts.get(label, 0) + 1
    if counts:
        label = max(counts, key=lambda k: (counts[k], k))
        tags.append(f"{label} 일치 {counts[label]}곳")
    if scored["hub_hits"]:
        tags.append(f"중심 관광지 '{scored['hub_hits'][0].name}'")
    if scored["festivals"]:
        tags.append(f"여행일 축제·행사 {len(scored['festivals'])}건")
    if scored["travel_min"] is not None:
        tags.append(f"{origin.name}에서 약 {scored['travel_min']}분")
    else:
        tags.append("이동시간 확인 필요")
    if len(tags) < 2:
        tags.append(f"관광 정보 {len(snapshot.spots(code))}곳")
    return tags[:4]


def candidate_view(snapshot: Snapshot, code: str, query: TripQuery, limit: int = 10) -> list[dict]:
    items = []
    for cand in snapshot.candidates(code, query.interests)[:limit]:
        place = cand.place
        items.append({
            "content_id": place.content_id, "title": place.title, "category": place.category,
            "summary": (place.overview or place.addr or "")[:80] or None, "evidence": cand.evidence[0],
            "evidence_all": cand.evidence, "interest_labels": cand.interest_labels,
            "image_url": place.image_url if place.cpyright_type in DISPLAYABLE_PHOTO else None,
            "source": place.source,
        })
    return items


def program_view(program: ProgramSummary | None, badge: str) -> dict | None:
    if program is None:
        return None if badge in ("none", "unknown") else {"badge": badge}
    return {"program_id": program.program_id, "round_id": program.round_id, "name": program.name,
            "judgment": program.judgment, "badge": badge, "posted_status": program.posted_status,
            "application_open": program.application_open, "rate": program.rate, "cap_krw": program.cap_krw,
            "stale": program.stale, "last_verified_at": program.last_verified_at,
            "source_url": program.source_url, "reasons": list(program.reasons)}


def recommend(snapshot: Snapshot, query: TripQuery, origin: Origin, lookup: BenefitLookup,
              limit: int = 3) -> dict:
    lookup_ok = lookup.status in ("ok", "partial")
    results: list[RegionResult] = []
    scored_by_code: dict[str, dict] = {}
    excluded, no_data = [], []
    for code in sigungu_map():
        scored = score_region(snapshot, code, query, origin)
        if scored["over_cap"]:
            excluded.append(code)
            continue
        if scored["travel_min"] is None:  # nothing cached: no course can be built there
            no_data.append(code)
            continue
        programs = lookup.by_region.get(code, ()) if lookup_ok else ()
        program, badge, group1 = classify(programs, query.trip_type)
        if not lookup_ok or (lookup.status == "partial" and code not in lookup.by_region):
            badge = "unknown"
        result = RegionResult(code, 1 if group1 else 2, scored["score"], scored["breakdown"],
                              scored["travel_min"], program, badge)
        result.tags = reason_tags(snapshot, code, query, origin, scored, program, badge)
        results.append(result)
        scored_by_code[code] = scored
    results.sort(key=lambda r: (r.group, -r.score, -((r.program.cap_krw if r.program else 0) or 0), r.code))
    regions = []
    for result in results[:limit]:
        region = sigungu_map()[result.code]
        candidates = candidate_view(snapshot, result.code, query)
        regions.append({
            "sigungu_code": result.code, "name": region.label, "sido": region.sido, "group": result.group,
            "score": result.score, "score_breakdown": result.breakdown, "travel_min": result.travel_min,
            "travel_note": "대중교통 추정치 · 실제 배차 확인" if query.transport == "transit" else "직선거리 기반 추정치",
            "refund": program_view(result.program, result.badge), "reason_tags": result.tags,
            "photos": [c["image_url"] for c in candidates if c["image_url"]][:3],
            "photo_credit": "한국관광공사",
            "candidates": candidates, "demo_data": result.code in snapshot.demo_filled,
        })
    return {"regions": regions, "no_refund_notice": notice(lookup, results),
            "excluded_by_travel_cap": len(excluded), "excluded_no_data": len(no_data),
            "interest_basis": interest_basis(snapshot.codes)}


def notice(lookup: BenefitLookup, results: list[RegionResult]) -> dict | None:
    if lookup.status == "not_connected":
        return {"code": "benefit_not_connected", "message": lookup.message
                or "지원제도 확인이 연결되지 않아 환급 지역을 구분하지 않았어요."}
    if lookup.status == "error":
        return {"code": "benefit_lookup_failed",
                "message": lookup.message or "지원제도를 확인하지 못했어요. 환급제가 없다는 뜻은 아니에요."}
    if any(r.group == 1 for r in results):
        return None
    alt = lookup.alternatives[0] if lookup.alternatives else None
    return {"code": "no_applicable_program_in_scope",
            "message": "조회한 범위에서 선택한 날짜에 신청 가능한 환급제를 찾지 못했어요.",
            "scope_note": lookup.scope_note, "partial": lookup.status == "partial",
            "nearest_program": program_view(alt, "alternative") if alt else None}
