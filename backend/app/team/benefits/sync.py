"""Periodic collection of external benefit data into SQLite (주기적 자동 갱신).

Neither source offers webhooks or change notifications, so each source is
polled on its own interval (config.py). Rules:

- Content is compared by SHA-256 of the normalized payload (volatile fields
  such as fetch time are excluded). A change creates a new version row with
  the list of changed fields; an identical re-collection only moves
  last_attempt_at/last_success_at.
- Errors, empty results, truncated pages, or parse failures never delete
  records or change their status. Records absent from a complete, non-empty
  collection get ``missing_since`` set; their data is kept.
- A DB lease (benefit_sync_state) plus an in-process lock prevents concurrent
  runs of the same source across threads and processes sharing the DB.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import socket
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

import httpx
from sqlalchemy import or_, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from . import config, tour50
from .gov24 import ENV_SERVICE_KEY, Gov24Client, Gov24Error
from .schemas import BenefitProgram, SyncMeta
from .search import GOV24_KEYWORDS, program_from_gov24
from .store_models import BenefitRecordVersion, BenefitSourceRecord, BenefitSyncRun, BenefitSyncState

log = logging.getLogger(__name__)
SYNC_GOV24_KEYWORDS = [*GOV24_KEYWORDS, "숙박"]
LEASE_SECONDS = 15 * 60
_OWNER = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
_LOCKS = {s: threading.Lock() for s in config.SOURCES}
_VOLATILE = {"status_checked_at", "sync"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def aware(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


# ------------------------------------------------------------------ hashing
def normalized_payload(program: BenefitProgram) -> dict:
    data = program.model_dump(mode="json", exclude=_VOLATILE)
    for s in data.get("sources", []):
        s.pop("retrieved_at", None)
    data["_status_checked"] = program.status_checked_at is not None
    return data


def content_hash(payload: dict) -> str:
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def changed_fields(old: dict, new: dict) -> list[str]:
    return sorted(k for k in set(old) | set(new) if old.get(k) != new.get(k))


def parse_source_time(value) -> datetime | None:
    """gov24 수정일시: accept 'YYYYMMDDHHMMSS' or ISO; anything else → None (raw kept)."""
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y%m%d%H%M%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone(timedelta(hours=9))) \
                .astimezone(timezone.utc)
        except ValueError:
            continue
    return None


# ------------------------------------------------------------------ items
@dataclass
class Item:
    source_key: str
    program_key: str
    round_key: str | None
    title: str
    sigungu_code: str | None
    program: BenefitProgram
    raw: dict
    review_status: str
    review_notes: list[str]
    source_updated_at: datetime | None


@dataclass
class Collected:
    items: list[Item]
    complete: bool              # every page/keyword fetched; safe to mark missing records
    pages: int
    errors: list[str]
    deferred_keys: set[str]     # existing records intentionally not refreshed this run


# ------------------------------------------------------------------ collectors
def collect_tour50(transport: httpx.BaseTransport | None = None, retries: int = 2) -> Collected:
    extracted, pages = tour50.collect(transport, retries)
    items = [Item(e.source_key, e.program_key, e.round_key, e.title, e.sigungu_code, e.program, e.raw,
                  e.review_status, e.review_notes, e.source_updated_at) for e in extracted]
    return Collected(items, complete=True, pages=pages, errors=[], deferred_keys=set())


def collect_gov24(client: Gov24Client, session: Session) -> Collected:
    records: dict[str, dict] = {}
    pages, errors, complete = 0, [], True
    for kw in SYNC_GOV24_KEYWORDS:
        try:
            res = client.list_services(kw)
        except Gov24Error as exc:
            errors.append(f"{kw}:{exc.code}")
            complete = False
            continue
        pages += res.pages_fetched
        complete = complete and not res.truncated
        for r in res.records:
            if r.get("서비스ID"):
                records.setdefault(str(r["서비스ID"]), r)
    if len(errors) == len(SYNC_GOV24_KEYWORDS):
        raise Gov24Error(errors[0].split(":", 1)[1], "공공서비스 API 목록 조회 전부 실패")

    stored = {r.source_key: r for r in session.exec(
        select(BenefitSourceRecord).where(BenefitSourceRecord.source == "gov24_api")).all()}
    budget = config.gov24_max_detail_per_run()
    items, deferred = [], set()
    now = datetime.now(timezone.utc)
    for sid, row in records.items():
        old = stored.get(sid)
        old_raw = json.loads(old.raw_json) if old else {}
        same_version = old is not None and old_raw.get("list", {}).get("수정일시") == row.get("수정일시") \
            and old_raw.get("detail") is not None
        if same_version:
            detail, conditions = old_raw.get("detail"), old_raw.get("conditions")
        elif budget > 0:
            budget -= 1
            try:
                detail, _ = client.service_detail(sid)
                conditions, _ = client.support_conditions(sid)
            except Gov24Error as exc:
                errors.append(f"detail {sid}:{exc.code}")
                if old is not None:
                    deferred.add(sid)
                    continue
                detail = conditions = None
        else:
            if old is not None:
                deferred.add(sid)
                continue
            detail = conditions = None
        program = program_from_gov24(row, detail, conditions, [], now)
        notes = ["공공서비스 API는 여행 기간·환급률·상한·접수 상태를 구조화해 제공하지 않음"]
        if detail is None:
            notes.append("상세·지원조건 미수집(호출 상한 또는 오류)")
        items.append(Item(sid, f"gov24:{sid}", None, program.name, None, program,
                          {"list": row, "detail": detail, "conditions": conditions},
                          "needs_review", notes, parse_source_time(row.get("수정일시"))))
    if deferred:
        complete = False
    return Collected(items, complete=complete and not errors, pages=pages, errors=errors,
                     deferred_keys=deferred)


# ------------------------------------------------------------------ lease
def _state(session: Session, source: str) -> BenefitSyncState:
    state = session.get(BenefitSyncState, source)
    if state is None:
        try:
            session.add(BenefitSyncState(source=source))
            session.commit()
        except IntegrityError:
            session.rollback()
        state = session.get(BenefitSyncState, source)
    return state


def acquire_lease(session: Session, source: str, now: datetime) -> bool:
    _state(session, source)
    result = session.execute(
        update(BenefitSyncState)
        .where(BenefitSyncState.source == source)
        .where(or_(BenefitSyncState.lease_until.is_(None), BenefitSyncState.lease_until < now,
                   BenefitSyncState.lease_owner == _OWNER))
        .values(lease_owner=_OWNER, lease_until=now + timedelta(seconds=LEASE_SECONDS)))
    session.commit()
    return result.rowcount == 1


def release_lease(session: Session, source: str) -> None:
    session.execute(update(BenefitSyncState).where(BenefitSyncState.source == source)
                    .where(BenefitSyncState.lease_owner == _OWNER)
                    .values(lease_owner=None, lease_until=None))
    session.commit()


# ------------------------------------------------------------------ upsert
def apply_items(session: Session, source: str, collected: Collected, run: BenefitSyncRun,
                now: datetime) -> None:
    existing = {r.source_key: r for r in session.exec(
        select(BenefitSourceRecord).where(BenefitSourceRecord.source == source)).all()}
    seen = set(collected.deferred_keys)
    for item in collected.items:
        seen.add(item.source_key)
        payload = normalized_payload(item.program)
        digest = content_hash(payload)
        rec = existing.get(item.source_key)
        if rec is None:
            rec = BenefitSourceRecord(
                source=source, source_key=item.source_key, program_key=item.program_key,
                round_key=item.round_key, title=item.title, sigungu_code=item.sigungu_code,
                payload_json=json.dumps(payload, ensure_ascii=False),
                raw_json=json.dumps(item.raw, ensure_ascii=False, default=str),
                content_hash=digest, version=1, review_status=item.review_status,
                review_notes_json=json.dumps(item.review_notes, ensure_ascii=False),
                source_updated_at=item.source_updated_at, first_seen_at=now,
                last_attempt_at=now, last_success_at=now, content_changed_at=now)
            session.add(rec)
            session.flush()
            session.add(BenefitRecordVersion(record_id=rec.id, version=1, content_hash=digest,
                                             payload_json=rec.payload_json,
                                             changed_fields_json=json.dumps(["(created)"]),
                                             captured_at=now, sync_run_id=run.id))
            run.created += 1
            continue
        rec.last_attempt_at = rec.last_success_at = now
        rec.missing_since = None
        rec.source_updated_at = item.source_updated_at or rec.source_updated_at
        if rec.content_hash == digest:
            run.unchanged += 1
            session.add(rec)
            continue
        old_payload = json.loads(rec.payload_json)
        diff = changed_fields(old_payload, payload)
        rec.version += 1
        rec.payload_json = json.dumps(payload, ensure_ascii=False)
        rec.raw_json = json.dumps(item.raw, ensure_ascii=False, default=str)
        rec.content_hash, rec.title = digest, item.title
        rec.content_changed_at = now
        rec.review_status = item.review_status        # 내용이 바뀌면 이전 관리자 검토는 무효
        rec.review_notes_json = json.dumps(item.review_notes, ensure_ascii=False)
        session.add(rec)
        session.add(BenefitRecordVersion(record_id=rec.id, version=rec.version, content_hash=digest,
                                         payload_json=rec.payload_json,
                                         changed_fields_json=json.dumps(diff, ensure_ascii=False),
                                         captured_at=now, sync_run_id=run.id))
        run.updated += 1
    for key, rec in existing.items():
        if key in seen:
            continue
        rec.last_attempt_at = now
        if collected.complete and collected.items and rec.missing_since is None:
            rec.missing_since = now
            run.marked_missing += 1
        session.add(rec)


# ------------------------------------------------------------------ run
def run_sync(source: str, trigger: str, session_factory: Callable[[], Session],
             gov24_client: Gov24Client | None = None, tour50_transport: httpx.BaseTransport | None = None,
             retries: int = 2) -> BenefitSyncRun:
    if source not in config.SOURCES:
        raise ValueError(f"unknown source {source}")
    lock = _LOCKS[source]
    with session_factory() as session:
        now = utcnow()
        run = BenefitSyncRun(source=source, trigger=trigger, started_at=now, status="running")
        if not lock.acquire(blocking=False) or not _lease_or_release(session, source, now, lock):
            run.status, run.finished_at = "skipped_locked", utcnow()
            run.message = "같은 출처의 동기화가 이미 실행 중"
            session.add(run)
            session.commit()
            session.refresh(run)
            return run
        try:
            session.add(run)
            session.commit()
            session.refresh(run)
            _execute(source, session, run, gov24_client, tour50_transport, retries)
        finally:
            try:
                release_lease(session, source)
            finally:
                lock.release()
        session.refresh(run)
        return run


def _lease_or_release(session, source, now, lock) -> bool:
    if acquire_lease(session, source, now):
        return True
    lock.release()
    return False


def _execute(source, session, run, gov24_client, tour50_transport, retries):
    state = _state(session, source)
    now = run.started_at
    state.last_attempt_at = now
    try:
        if source == "kto_tour50":
            if not config.tour50_enabled():
                raise _NotConfigured("disabled", "KIROTHON_TOUR50_ENABLED=false")
            collected = collect_tour50(tour50_transport, retries)
        else:
            client = gov24_client
            if client is None:
                key = os.environ.get(ENV_SERVICE_KEY, "").strip()
                if not key:
                    raise _NotConfigured("missing_service_key", "공공데이터포털 인증키 미설정")
                # Sync always reads the source (no response cache) but shares the daily call budget.
                client = Gov24Client(key, use_cache=False, retries=retries)
            collected = collect_gov24(client, session)
        run.pages_fetched = collected.pages
        run.records_seen = len(collected.items) + len(collected.deferred_keys)
        previously = session.exec(select(BenefitSourceRecord.id)
                                  .where(BenefitSourceRecord.source == source)).first()
        if not collected.items and not collected.deferred_keys and previously is not None:
            run.status, run.error_code = "partial", "empty_result"  # not counted as success
            run.message = "빈 결과 — 기존 데이터를 유지하고 정상 수집으로 보지 않음"
        else:
            apply_items(session, source, collected, run, now)
            run.status = "ok" if collected.complete and not collected.errors else "partial"
            if collected.errors:
                run.error_code = collected.errors[0].split(":")[-1]
                run.message = "; ".join(collected.errors[:5])
            elif not collected.complete:
                run.message = "일부 페이지·상세만 수집(상한·지연) — 누락 표시 생략"
    except _NotConfigured as exc:
        session.rollback()
        run.status, run.error_code, run.message = "not_configured", exc.code, exc.message
    except (Gov24Error, tour50.Tour50Error) as exc:
        session.rollback()
        run.status, run.error_code, run.message = "error", exc.code, exc.message
    except Exception as exc:  # noqa: BLE001 -- never let a sync failure touch stored data
        session.rollback()
        log.exception("benefit sync %s failed", source)
        run.status, run.error_code, run.message = "error", "internal_error", type(exc).__name__
    run.finished_at = utcnow()
    state = _state(session, source)
    state.last_attempt_at = now
    if run.status == "ok" or (run.status == "partial" and run.error_code != "empty_result"):
        state.last_success_at = now
    state.last_status, state.last_error_code, state.last_run_id = run.status, run.error_code, run.id
    session.add(run)
    session.add(state)
    session.commit()


class _NotConfigured(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


# ------------------------------------------------------------------ read side
def source_states(session: Session) -> dict[str, BenefitSyncState | None]:
    return {s: session.get(BenefitSyncState, s) for s in config.SOURCES}


def is_stale(last_success: datetime | None, source: str, now: datetime | None = None) -> bool:
    if last_success is None:
        return True
    now = now or utcnow()
    return (now - aware(last_success)).total_seconds() > config.stale_after_seconds(source)


def load_programs(session: Session) -> list[tuple[BenefitProgram, BenefitSourceRecord]]:
    now = utcnow()
    out = []
    for rec in session.exec(select(BenefitSourceRecord)).all():
        out.append((to_program(rec, now), rec))
    return out


def to_program(rec: BenefitSourceRecord, now: datetime | None = None) -> BenefitProgram:
    payload = json.loads(rec.payload_json)
    checked = payload.pop("_status_checked", False)
    program = BenefitProgram.model_validate(payload)
    success = aware(rec.last_success_at)
    if checked:
        program.status_checked_at = success
    for s in program.sources:
        s.retrieved_at = success
    stale = is_stale(rec.last_success_at, rec.source, now)
    program.sync = SyncMeta(
        source=rec.source, source_key=rec.source_key, record_version=rec.version,
        review_status=rec.review_status, review_notes=json.loads(rec.review_notes_json),
        source_updated_at=aware(rec.source_updated_at), last_attempt_at=aware(rec.last_attempt_at),
        last_success_at=success, content_changed_at=aware(rec.content_changed_at),
        missing_from_source_since=aware(rec.missing_since), stale=stale)
    return program


def due_sources(session: Session, now: datetime | None = None) -> list[str]:
    now = now or utcnow()
    due = []
    for source, state in source_states(session).items():
        last = aware(state.last_attempt_at) if state else None
        if last is None or (now - last).total_seconds() >= config.interval_seconds(source):
            due.append(source)
    return due


# ------------------------------------------------------------------ scheduler
class Scheduler:
    """Background thread: initial sync when data is missing/old, then periodic polling."""

    def __init__(self, session_factory: Callable[[], Session], tick_seconds: float = 60.0):
        self._factory = session_factory
        self._tick = tick_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name="benefit-sync", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout)

    def _loop(self):
        first = True
        while not self._stop.is_set():
            try:
                with self._factory() as session:
                    due = due_sources(session)
                for source in due:
                    if self._stop.is_set():
                        break
                    run_sync(source, "startup" if first else "scheduled", self._factory)
            except Exception:  # noqa: BLE001
                log.exception("benefit scheduler tick failed")
            first = False
            self._stop.wait(self._tick)
