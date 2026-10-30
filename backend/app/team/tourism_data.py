"""Read-only snapshot of the tourism cache for one request (F1, F2).

Screen requests never call the public APIs for lists; they read this snapshot.
"""
from dataclasses import dataclass, field
from datetime import date
import json

from sqlmodel import Session, func, select

from .regions import (SPOT_TYPES, CONTENT_TYPES, demo_places, interests, load_codes,
                      place_matches_interest, sigungu_map)
from .tourism_models import HubRank, Place, RelatedPlace, TourismSyncRun

DEMO_MIN_SPOTS = 5


@dataclass
class PlaceLite:
    content_id: str
    content_type_id: str
    title: str
    sigungu_code: str | None
    lat: float | None = None
    lng: float | None = None
    lcls1: str | None = None
    lcls2: str | None = None
    addr: str | None = None
    image_url: str | None = None
    cpyright_type: str | None = None
    overview: str | None = None
    intro: dict = field(default_factory=dict)
    room_price_krw: int | None = None
    event_start: str | None = None
    event_end: str | None = None
    source: str = "kor"
    has_detail: bool = False

    @property
    def coord(self) -> tuple[float, float] | None:
        return (self.lat, self.lng) if self.lat is not None and self.lng is not None else None

    @property
    def category(self) -> str:
        return CONTENT_TYPES.get(self.content_type_id, "기타")

    @classmethod
    def from_row(cls, row: Place) -> "PlaceLite":
        try:
            intro = json.loads(row.intro_json) if row.intro_json else {}
        except ValueError:
            intro = {}
        return cls(row.content_id, row.content_type_id, row.title, row.sigungu_code, row.lat, row.lng,
                   row.lcls1, row.lcls2, row.addr, row.image_url, row.cpyright_type, row.overview,
                   intro if isinstance(intro, dict) else {}, row.room_price_krw, row.event_start,
                   row.event_end, row.source, row.detail_fetched_at is not None)


@dataclass
class Candidate:
    place: PlaceLite
    evidence: list[str]
    hub_rank: int | None = None
    related_rank: int | None = None
    interest_labels: list[str] = field(default_factory=list)


@dataclass
class Snapshot:
    places: dict[str, PlaceLite]
    hubs: dict[str, list[HubRank]]
    related: dict[str, list[RelatedPlace]]
    codes: dict
    last_sync: TourismSyncRun | None = None
    demo_filled: set[str] = field(default_factory=set)

    def __post_init__(self):
        self.by_sigungu: dict[str, list[PlaceLite]] = {}
        self.festivals: dict[str, list[PlaceLite]] = {}
        for place in self.places.values():
            if not place.sigungu_code:
                continue
            target = self.festivals if place.content_type_id == "15" else self.by_sigungu
            target.setdefault(place.sigungu_code, []).append(place)
        for rows in list(self.by_sigungu.values()) + list(self.festivals.values()):
            rows.sort(key=lambda p: p.content_id)

    @property
    def is_empty(self) -> bool:
        return not self.places

    def spots(self, code: str) -> list[PlaceLite]:
        return [p for p in self.by_sigungu.get(code, []) if p.content_type_id in SPOT_TYPES]

    def of_type(self, code: str, content_type_id: str) -> list[PlaceLite]:
        return [p for p in self.by_sigungu.get(code, []) if p.content_type_id == content_type_id]

    def centroid(self, code: str) -> tuple[tuple[float, float] | None, str]:
        """Design 8-1: mean of the top-5 hub coordinates, else mean of cached places."""
        points = [(h.lat, h.lng) for h in self.hubs.get(code, [])[:5] if h.lat and h.lng]
        basis = "hub_top5"
        if not points:
            points = [p.coord for p in self.spots(code) if p.coord]
            basis = "places"
        if not points:
            return None, "none"
        return (sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points)), basis

    def festivals_during(self, code: str, start: date, end: date) -> list[PlaceLite]:
        hits = []
        for event in self.festivals.get(code, []):
            if not event.event_start or not event.event_end:
                continue
            if event.event_start <= end.isoformat() and event.event_end >= start.isoformat():
                hits.append(event)
        return hits

    def interest_labels(self, place: PlaceLite, selected: list[str]) -> list[str]:
        catalog = interests()
        return [catalog[key].label for key in selected
                if key in catalog and place_matches_interest(place.content_type_id, place.lcls1,
                                                             place.lcls2, catalog[key], self.codes)]

    def candidates(self, code: str, selected: list[str], *, strict: bool = True,
                   types: tuple[str, ...] = SPOT_TYPES) -> list[Candidate]:
        """Hub top 10 -> their related places (same sigungu first) -> other cached places."""
        region = sigungu_map().get(code)
        label = region.label if region else code
        found: dict[str, Candidate] = {}

        def add(place: PlaceLite | None, evidence: str | None, hub: int | None = None,
                rel: int | None = None) -> None:
            if not place or place.content_type_id not in types or place.sigungu_code != code:
                return
            labels = self.interest_labels(place, selected)
            if strict and not labels:
                return
            item = found.setdefault(place.content_id, Candidate(place, [], interest_labels=labels))
            if evidence and evidence not in item.evidence:
                item.evidence.append(evidence)
            item.hub_rank = item.hub_rank or hub
            item.related_rank = item.related_rank or rel

        top_hubs = self.hubs.get(code, [])[:10]
        for hub in top_hubs:
            add(self.places.get(hub.content_id or ""), f"{label} 중심 관광지 {hub.rank}위", hub=hub.rank)
        hub_codes = {h.hub_code for h in top_hubs}
        related = [r for r in self.related.get(code, []) if r.src_code in hub_codes]
        related.sort(key=lambda r: (r.rel_sigungu_code != code, r.rank, r.rel_code))
        for row in related:
            add(self.places.get(row.rel_content_id or ""), f"{row.src_name} 방문객이 함께 찾는 곳 {row.rank}위",
                rel=row.rank)
        rest = sorted(self.by_sigungu.get(code, []), key=lambda p: (p.image_url is None, p.title, p.content_id))
        for place in rest:
            add(place, None)
        for item in found.values():
            if not item.evidence:
                item.evidence.append(f"관심 분야: {item.interest_labels[0]}" if item.interest_labels
                                     else f"{label} 관광 정보")
        return list(found.values())


def _latest_by_sigungu(rows: list, key=lambda r: r.sigungu_code) -> dict[str, list]:
    latest: dict[str, str] = {}
    for row in rows:
        code = key(row)
        latest[code] = max(latest.get(code, ""), row.base_ym)
    grouped: dict[str, list] = {}
    for row in rows:
        if row.base_ym == latest[key(row)]:
            grouped.setdefault(key(row), []).append(row)
    return grouped


def load_snapshot(session: Session) -> Snapshot:
    places = {row.content_id: PlaceLite.from_row(row) for row in session.exec(select(Place)).all()}
    hubs = _latest_by_sigungu(list(session.exec(select(HubRank)).all()))
    for rows in hubs.values():
        rows.sort(key=lambda h: (h.rank, h.hub_code))
    related = _latest_by_sigungu(list(session.exec(select(RelatedPlace)).all()))
    last = session.exec(select(TourismSyncRun).order_by(TourismSyncRun.id.desc()).limit(1)).first()
    snapshot = Snapshot(places, hubs, related, load_codes(), last)
    _fill_demo(snapshot)
    return snapshot


def _fill_demo(snapshot: Snapshot) -> None:
    """Requirement 1-7: a sigungu with fewer than 5 cached spots gets team demo data."""
    by_code: dict[str, list[dict]] = {}
    for row in demo_places():
        by_code.setdefault(str(row.get("sigungu_code")), []).append(row)
    for code, rows in by_code.items():
        if len(snapshot.spots(code)) >= DEMO_MIN_SPOTS:
            continue
        for row in rows:
            content_id = str(row.get("content_id") or "")
            if not content_id or content_id in snapshot.places:
                continue
            place = PlaceLite(content_id, str(row.get("content_type_id") or "12"), str(row.get("title") or ""),
                              code, row.get("lat"), row.get("lng"), addr=row.get("addr"),
                              image_url=row.get("image_url"), overview=row.get("overview"), source="demo")
            snapshot.places[content_id] = place
            snapshot.by_sigungu.setdefault(code, []).append(place)
        snapshot.demo_filled.add(code)


def cache_stats(session: Session) -> dict:
    count = lambda model: session.exec(select(func.count()).select_from(model)).one()  # noqa: E731
    last = session.exec(select(TourismSyncRun).order_by(TourismSyncRun.id.desc()).limit(1)).first()
    success = session.exec(select(TourismSyncRun).where(TourismSyncRun.status.in_(["success", "partial"]))
                           .order_by(TourismSyncRun.id.desc()).limit(1)).first()
    places = count(Place)
    return {
        "status": "empty" if not places else ("partial" if success and success.status == "partial" else "ready"),
        "places": places,
        "hub_rows": count(HubRank),
        "related_rows": count(RelatedPlace),
        "last_attempt_at": last.started_at.isoformat() if last else None,
        "last_attempt_status": last.status if last else None,
        "last_success_at": success.finished_at.isoformat() if success and success.finished_at else None,
        "base_ym_hub": success.base_ym_hub if success else None,
        "base_ym_related": success.base_ym_related if success else None,
    }
