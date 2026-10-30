import asyncio
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, ConfigDict
from ..database import DB_PATH
from . import tourism

router = APIRouter(prefix='/api/team', tags=['tourism'])

class RecommendationRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    radius: Literal[3, 5] = 3
    visited: list[str] = Field(default_factory=list, max_length=500)
    excluded: list[str] = Field(default_factory=list, max_length=500)
    category: Literal['전체', '관광명소', '문화공간', '야외활동'] = '전체'

@router.post('/recommendations')
async def recommendations(req: RecommendationRequest):
    if not tourism.supported(req.lat, req.lon):
        raise HTTPException(422, '지원 지역 밖입니다. 광주 도심 시연 구역의 시작 위치를 선택해 주세요.')
    try:
        async with asyncio.timeout(9):
            places, at, stale = await tourism.catalogue()
            enriched = [dict(tourism._cache.get('detail:'+p['id'], {}).get('value', p)) for p in places]
            ranked = tourism.rank(enriched, req.lat, req.lon, req.radius, req.visited, req.excluded, req.category)
            return dict(request_id=str(uuid4()), places=ranked[:5], total=len(ranked),
                        fetched_at=at, stale=stale, factors={'distance': 1.0}, mode='live',
                        notice='연관 지표 미적용 · 거리 기반 추천',
                        truncated=tourism._cache.get('catalogue', {}).get('truncated', False))
    except (tourism.SourceError, TimeoutError):
        raise HTTPException(503, '관광정보 서버 응답이 지연되거나 연결되지 않았습니다. 다시 시도해 주세요.') from None

@router.get('/places/{place_id}')
async def place_detail(place_id: str):
    try:
        async with asyncio.timeout(9):
            places, _, _ = await tourism.catalogue()
            place = next((p for p in places if p['id'] == place_id), None)
            if not place:
                raise HTTPException(404, '장소를 찾을 수 없습니다.')
            return await tourism.detail(place)
    except (tourism.SourceError, TimeoutError):
        raise HTTPException(503, '상세정보를 불러오지 못했습니다. 기본 정보는 계속 확인할 수 있습니다.') from None

class Event(BaseModel):
    model_config = ConfigDict(extra='forbid')
    session_id: UUID
    event: Literal['request', 'impression', 'detail', 'select', 'directions', 'visit', 'skip', 'next', 'error', 'reset']
    place_id: str | None = Field(default=None, max_length=64)

@router.post('/events', status_code=204)
def event(event: Event):
    path = Path(DB_PATH).with_name('tourism-events.sqlite3')
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('CREATE TABLE IF NOT EXISTS events (session TEXT, event TEXT, place TEXT, created TEXT)')
        db.execute('DELETE FROM events WHERE created < ?', ((now-timedelta(days=30)).isoformat(),))
        db.execute('INSERT INTO events VALUES (?, ?, ?, ?)',
                   (str(event.session_id), event.event, event.place_id, now.isoformat()))
