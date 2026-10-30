import asyncio
from datetime import datetime
import sqlite3
from contextlib import closing
from uuid import uuid4
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.team import tourism
from app.team.sync_tourism import match_hub
from app.database import DB_PATH

def place(id='a', lat=35.1466, lon=126.9198, **fields):
    return dict(id=id, name=id, lat=lat, lon=lon, category='관광명소', hours='', rest='', **fields)

def test_distance_and_boundary():
    assert tourism.distance(tourism.CENTER, tourism.CENTER) == 0
    assert .9 < tourism.distance(tourism.CENTER, (35.1556,126.9198)) < 1.1
    assert not tourism.supported(37.5,127)
    assert not tourism.normalize({'contentid':'a','mapx':'bad','mapy':35})

@pytest.mark.parametrize('hours,rest,hour,expected', [
    ('09:00~18:00','연중무휴',10,'운영시간상 방문 가능'),
    ('09:00~18:00','연중무휴',18,'운영시간상 방문 불가'),
    ('22:00~02:00','연중무휴',23,'확인 필요'),
    ('09:00~18:00','월요일 휴무',10,'확인 필요'),
    ('09:00~18:00 (임시휴무)','연중무휴',10,'확인 필요'),
    ('','',10,'확인 필요'), ('25:00~26:00','없음',10,'확인 필요')])
def test_hours_conservative(hours, rest, hour, expected):
    assert tourism.operating_status(hours, rest, datetime(2026,10,30,hour,tzinfo=tourism.KST)) == expected

def test_rank_exclusions_ties_and_radius():
    places=[place('b'),place('a'),place('visited'),place('skip'),place('outside',37,127)]
    ranked=tourism.rank(places,*tourism.CENTER,3,['visited'],['skip'])
    assert [p['id'] for p in ranked] == ['a','b']
    assert ranked[0]['score'] == 1
    assert tourism.rank(places,*tourism.CENTER,3,[],[], '문화공간') == []

def test_closed_filtered_before_rank():
    p=place()
    p.update(hours='09:00~18:00',rest='연중무휴')
    with patch.object(tourism,'operating_status',return_value='운영시간상 방문 불가'):
        assert tourism.rank([p],*tourism.CENTER,3,[],[]) == []

def test_matching_requires_name_coordinate_and_uniqueness():
    hub=dict(mapY=35.1466,mapX=126.9198,hubTatsNm='a')
    assert match_hub(hub,[place()])['id'] == 'a'
    assert match_hub(hub,[place(lat=35.17)]) is None
    assert match_hub(hub,[place(),place()]) is None

@pytest.mark.parametrize('count',[0,1,2,8])
def test_recommendation_counts_and_key_absence(count):
    with patch.object(tourism,'catalogue',AsyncMock(return_value=([place(str(i)) for i in range(count)],'2026-10-30',False))):
        with TestClient(app) as client:
            res=client.post('/api/team/recommendations',json=dict(lat=35.1466,lon=126.9198))
            assert res.status_code == 200
            assert len(res.json()['places']) == min(5,count)
            assert res.json()['factors'] == {'distance':1.0}
            assert 'serviceKey' not in res.text

def test_outside_and_invalid_requests_never_call_provider():
    with patch.object(tourism,'catalogue',AsyncMock()) as source:
        with TestClient(app) as client:
            for data in [dict(lat=37.5,lon=127),dict(lat=91,lon=126),dict(lat=35.14,lon=126.92,radius=10)]:
                assert client.post('/api/team/recommendations',json=data).status_code == 422
        source.assert_not_called()

def test_upstream_failure_is_actionable_and_redacted():
    with patch.object(tourism,'catalogue',AsyncMock(side_effect=tourism.SourceError('secret'))):
        with TestClient(app) as client:
            res=client.post('/api/team/recommendations',json=dict(lat=35.1466,lon=126.9198))
            assert res.status_code == 503 and 'secret' not in res.text

def test_events_reject_coordinates_and_distinguish_actions():
    sid=str(uuid4())
    with TestClient(app) as client:
        assert client.post('/api/team/events',json=dict(session_id=sid,event='select',lat=35)).status_code == 422
        for event in ['select','directions','visit','skip','next']:
            assert client.post('/api/team/events',json=dict(session_id=sid,event=event,place_id='a')).status_code == 204
    with closing(sqlite3.connect(DB_PATH.with_name('tourism-events.sqlite3'))) as db:
        assert [r[0] for r in db.execute('select event from events where session=?',(sid,))] == ['select','directions','visit','skip','next']

def test_cache_fallback(monkeypatch):
    import time
    monkeypatch.setattr(tourism,'_lock',asyncio.Lock())
    monkeypatch.setattr(tourism,'_cache',{'catalogue':dict(time=time.time()-4000,places=[place()],at='old')})
    with patch.object(tourism,'fetch',side_effect=tourism.SourceError('down')):
        places,at,stale=asyncio.run(tourism.catalogue())
    assert stale and at == 'old' and len(places) == 1
