"""SQLite tables for collected benefit data, version history, and sync runs.

These are new team tables. schema_check freezes their columns once created,
so any later column change needs a reviewed migration.
Timestamps are timezone-aware UTC (SQLModel UTCDateTime).
User request data (residence, birth date, ...) is never stored here.
"""
from datetime import datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class BenefitSourceRecord(SQLModel, table=True):
    __tablename__ = "benefit_source_record"
    __table_args__ = (UniqueConstraint("source", "source_key", name="uq_benefit_source_key"),)

    id: int | None = Field(default=None, primary_key=True)
    source: str = Field(index=True)               # gov24_api | kto_tour50
    source_key: str = Field(index=True)           # gov24 서비스ID, tour50:<시군구코드>:<연도>:<차수>
    program_key: str = Field(index=True)          # 사업 단위 내부 ID
    round_key: str | None = None                  # 모집 차수 내부 ID
    title: str
    sigungu_code: str | None = None
    payload_json: str                             # 해시·비교 대상 정규화 필드
    raw_json: str                                 # 원문 조각
    content_hash: str
    version: int
    review_status: str                            # needs_review | conflict | admin_reviewed
    review_notes_json: str
    source_updated_at: datetime | None = None     # 원본 제공 수정 시각
    first_seen_at: datetime
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    content_changed_at: datetime
    missing_since: datetime | None = None         # 정상 수집에서 사라진 시각(삭제하지 않음)


class BenefitRecordVersion(SQLModel, table=True):
    __tablename__ = "benefit_record_version"

    id: int | None = Field(default=None, primary_key=True)
    record_id: int = Field(index=True)
    version: int
    content_hash: str
    payload_json: str
    changed_fields_json: str
    captured_at: datetime
    sync_run_id: int | None = None


class BenefitSyncRun(SQLModel, table=True):
    __tablename__ = "benefit_sync_run"

    id: int | None = Field(default=None, primary_key=True)
    source: str = Field(index=True)
    trigger: str                                  # startup | scheduled | manual
    started_at: datetime
    finished_at: datetime | None = None
    status: str                                   # running | ok | partial | error | not_configured | skipped_locked
    pages_fetched: int = 0
    records_seen: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    marked_missing: int = 0
    error_code: str | None = None
    message: str | None = None


class BenefitSyncState(SQLModel, table=True):
    __tablename__ = "benefit_sync_state"

    source: str = Field(primary_key=True)
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    last_status: str | None = None
    last_error_code: str | None = None
    last_run_id: int | None = None
    lease_owner: str | None = None                # 다중 프로세스 중복 실행 방지
    lease_until: datetime | None = None
