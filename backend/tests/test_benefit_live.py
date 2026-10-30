"""Real external calls. Skipped unless KIROTHON_LIVE_TESTS=1.

- tour50: public page, no key.
- gov24: needs KIROTHON_DATA_GO_KR_SERVICE_KEY in the environment; the key is never printed.
These tests write only to the temporary test DB from conftest.
"""
import os

import pytest
from sqlmodel import Session, select

from app.database import engine
from app.team.benefits import gov24, sync, tour50
from app.team.benefits.store_models import BenefitSourceRecord

pytestmark = pytest.mark.skipif(os.environ.get("KIROTHON_LIVE_TESTS") != "1",
                                reason="live external calls disabled (set KIROTHON_LIVE_TESTS=1)")


def _factory():
    return Session(engine)


def test_live_tour50_page_parses():
    items, pages = tour50.collect(retries=1)
    assert pages == 1 and items
    regions = {e.program.target_regions[0].sigungu for e in items if e.program.target_regions}
    print(f"\nLIVE tour50: {len(items)} rounds, {len(regions)} regions")
    for e in items:
        if e.program.posted_status:
            print(" ", e.source_key, e.program.posted_status, e.program.trip_period, e.review_status)


def test_live_tour50_sync_twice_is_idempotent():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app):
        pass
    first = sync.run_sync("kto_tour50", "manual", _factory, retries=1)
    second = sync.run_sync("kto_tour50", "manual", _factory, retries=1)
    print(f"\nLIVE tour50 sync: {first.status} created={first.created}; "
          f"{second.status} unchanged={second.unchanged} updated={second.updated}")
    assert first.status == "ok" and second.status == "ok"
    assert second.created == 0


@pytest.mark.skipif(not gov24.service_key_configured(), reason="no gov24 key in environment")
def test_live_gov24_travel_services():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app):
        pass
    run = sync.run_sync("gov24_api", "manual", _factory, retries=1)
    print(f"\nLIVE gov24 sync: {run.status} pages={run.pages_fetched} seen={run.records_seen} "
          f"error={run.error_code}")
    assert run.status in {"ok", "partial"}
    words = ("반값", "여행경비", "숙박", "휴가", "관광객")
    with _factory() as s:
        for rec in s.exec(select(BenefitSourceRecord).where(BenefitSourceRecord.source == "gov24_api")).all():
            if any(w in rec.title for w in words):
                print("  ", rec.source_key, rec.title)
