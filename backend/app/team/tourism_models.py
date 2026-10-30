"""Tourism cache and generated-course tables (S1, F1, F2).

All tables are new; no existing column is changed. Residence, age and other
user conditions are never stored here: courses keep only the trip query.
"""
from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Place(SQLModel, table=True):
    """KorService2 list/detail cache. `sigungu_code` is the internal 5-digit key."""
    __tablename__ = "place"

    content_id: str = Field(primary_key=True)
    content_type_id: str = Field(index=True)
    title: str
    sigungu_code: str | None = Field(default=None, index=True)
    ldong_regn_cd: str | None = None
    ldong_signgu_cd: str | None = None
    lcls1: str | None = None
    lcls2: str | None = None
    lcls3: str | None = None
    addr: str | None = None
    lat: float | None = None
    lng: float | None = None
    image_url: str | None = None
    thumb_url: str | None = None
    cpyright_type: str | None = None
    tel: str | None = None
    overview: str | None = None
    intro_json: str | None = None
    room_price_krw: int | None = None
    event_start: str | None = None
    event_end: str | None = None
    source: str = "kor"
    source_modified: str | None = None
    fetched_at: datetime = Field(default_factory=utc_now)
    detail_fetched_at: datetime | None = None


class HubRank(SQLModel, table=True):
    """LocgoHubTarService1 areaBasedList1 rows (navigation-based hub rank)."""
    __tablename__ = "hub_rank"

    id: int | None = Field(default=None, primary_key=True)
    base_ym: str = Field(index=True)
    sigungu_code: str = Field(index=True)
    rank: int
    hub_code: str
    name: str
    lat: float | None = None
    lng: float | None = None
    category_l: str | None = None
    category_m: str | None = None
    content_id: str | None = None
    match_method: str | None = None
    fetched_at: datetime = Field(default_factory=utc_now)


class RelatedPlace(SQLModel, table=True):
    """TarRlteTarService1 areaBasedList1 rows (navigation-based related rank)."""
    __tablename__ = "related_place"

    id: int | None = Field(default=None, primary_key=True)
    base_ym: str = Field(index=True)
    sigungu_code: str = Field(index=True)
    src_code: str
    src_name: str
    rel_code: str
    rel_name: str
    rel_sigungu_code: str | None = None
    rel_category_l: str | None = None
    rel_category_m: str | None = None
    rel_category_s: str | None = None
    rank: int
    src_content_id: str | None = None
    rel_content_id: str | None = None
    fetched_at: datetime = Field(default_factory=utc_now)


class Course(SQLModel, table=True):
    """Generated course for share links. No residence or age is stored."""
    __tablename__ = "course"

    id: str = Field(primary_key=True)
    created_at: datetime = Field(default_factory=utc_now, index=True)
    trip_type: str
    start_date: str
    origin: str
    interests: str
    party_size: int
    transport: str
    sigungu_code: str
    program_id: str | None = None
    body_json: str
    reasons_json: str = "{}"
    ai_calls: int = 0


class TourismSyncRun(SQLModel, table=True):
    """One run of `python -m app.team.sync_tourism`. Never stores the key."""
    __tablename__ = "tourism_sync_run"

    id: int | None = Field(default=None, primary_key=True)
    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None
    status: str = "running"
    base_ym_hub: str | None = None
    base_ym_related: str | None = None
    steps_json: str = "{}"
    message: str | None = None
