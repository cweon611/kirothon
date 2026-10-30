"""TourAPI adapter. Upstream URLs and keys must never appear in logs/errors."""
import asyncio
from datetime import datetime, timezone, timedelta
from html import unescape
import json
import math
import os
from pathlib import Path
import re
import time
from urllib.parse import urlencode, unquote
from urllib.request import urlopen

KST = timezone(timedelta(hours=9))
CENTER = (35.1466, 126.9198)
SOURCE = 'https://www.data.go.kr/data/15101578/openapi.do'
BASE = 'https://apis.data.go.kr/B551011/KorService2/'
CATEGORIES = {'12': '관광명소', '14': '문화공간', '28': '야외활동'}
_cache = {}
_lock = asyncio.Lock()
CACHE_FILE = Path(__file__).resolve().parents[3] / '.local-data' / 'tourism-catalogue.json'

class SourceError(Exception):
    pass

def api_key():
    key = os.getenv('TOUR_API_KEY', '')
    if not key:
        local = Path(__file__).resolve().parents[2] / '.env.local'
        if local.exists():
            for line in local.read_text(encoding='utf-8').splitlines():
                if line.startswith('TOUR_API_KEY='):
                    key = line.split('=', 1)[1].strip()
    return unquote(key)

def clean(value):
    return unescape(re.sub('<[^>]*>', ' ', str(value or ''))).strip()

def fetch(operation, service='KorService2', **params):
    key = api_key()
    if not key:
        raise SourceError('관광정보 인증키가 설정되지 않았습니다.')
    query = urlencode(dict(serviceKey=key, MobileOS='WEB', MobileApp='GwangjuWalk',
                          _type='json', **({'numOfRows': 500, 'pageNo': 1} | params)))
    try:
        if service not in ('KorService2', 'LocgoHubTarService1', 'TarRlteTarService1'):
            raise ValueError('unsupported provider')
        with urlopen('https://apis.data.go.kr/B551011/' + service + '/' + operation + '?' + query, timeout=6) as response:
            data = json.load(response)['response']
        if str(data['header']['resultCode']) != '0000':
            raise ValueError('upstream rejected request')
        body = data.get('body') or {}
        rows = (body.get('items') or {}).get('item', [])
        return rows if isinstance(rows, list) else [rows], int(body.get('totalCount', 0))
    except Exception:
        raise SourceError('관광정보를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.') from None

def distance(a, b):
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    h = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(math.radians(b[1]-a[1])/2)**2
    return 6371 * 2 * math.asin(math.sqrt(min(1, h)))

def supported(lat, lon):
    # Pilot rectangle, not an administrative boundary.
    return 35.115 <= lat <= 35.180 and 126.885 <= lon <= 126.955

def enrichment():
    path = Path(__file__).resolve().parents[3] / '.local-data' / 'tourism-enrichment.json'
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}

def attach_evidence(place):
    return dict(place, evidence=enrichment().get('places', {}).get(place['id'], {}))

def normalize(row):
    try:
        lat, lon = float(row['mapy']), float(row['mapx'])
    except (KeyError, TypeError, ValueError):
        return None
    category = str(row.get('contenttypeid'))
    if not supported(lat, lon) or category not in CATEGORIES or not row.get('contentid'):
        return None
    return dict(id=str(row['contentid']), name=clean(row.get('title')), lat=lat, lon=lon,
                category=CATEGORIES[category], content_type=category,
                address=clean(row.get('addr1')), updated_at=row.get('modifiedtime') or None,
                source='한국관광공사 TourAPI', source_url=SOURCE,
                description='', hours='', fee='', rest='', phone='', operating_status='확인 필요')

async def catalogue():
    if 'catalogue' not in _cache:
        try:
            saved = json.loads(CACHE_FILE.read_text(encoding='utf-8'))
            if isinstance(saved.get('places'), list) and 0 <= time.time()-saved['time'] < 86400:
                _cache['catalogue'] = saved
        except (OSError, ValueError, KeyError, TypeError):
            pass
    cached = _cache.get('catalogue')
    if cached and time.time()-cached['time'] < 3600:
        return cached['places'], cached['at'], False
    async with _lock:
        cached = _cache.get('catalogue')
        if cached and time.time()-cached['time'] < 3600:
            return cached['places'], cached['at'], False
        try:
            # Fixed pilot center: no user coordinates are sent upstream.
            rows, total = await asyncio.to_thread(fetch, 'locationBasedList2',
                mapX=CENTER[1], mapY=CENTER[0], radius=5000, arrange='E')
            places = {p['id']: p for row in rows if (p := normalize(row))}
            at = datetime.now(KST).isoformat()
            _cache['catalogue'] = dict(places=list(places.values()), at=at, time=time.time(), truncated=total > len(rows))
            try:
                CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
                temp = CACHE_FILE.with_suffix('.tmp')
                temp.write_text(json.dumps(_cache['catalogue'], ensure_ascii=False), encoding='utf-8')
                temp.replace(CACHE_FILE)
            except OSError:
                pass  # Read-only deployments retain in-memory caching.
            return list(places.values()), at, False
        except SourceError:
            if cached and time.time()-cached['time'] < 86400:
                return cached['places'], cached['at'], True
            raise

def operating_status(hours, rest, now=None):
    now = now or datetime.now(KST)
    match = re.fullmatch(r'\s*(\d{2}):(\d{2})\s*[~～-]\s*(\d{2}):(\d{2})\s*', hours or '')
    if not match or rest not in ('연중무휴', '없음'):
        return '확인 필요'
    h1, m1, h2, m2 = map(int, match.groups())
    if max(h1, h2) > 23 or max(m1, m2) > 59:
        return '확인 필요'
    start, end = h1*60+m1, h2*60+m2
    if end <= start:
        return '확인 필요'
    return '운영시간상 방문 가능' if start <= now.hour*60+now.minute < end else '운영시간상 방문 불가'

async def detail(place):
    key = 'detail:' + place['id']
    cached = _cache.get(key)
    if cached and time.time()-cached['time'] < 3600:
        value = dict(cached['value'])
        value['operating_status'] = operating_status(value['hours'], value['rest'])
        return attach_evidence(value)
    common, intro = await asyncio.gather(
        asyncio.to_thread(fetch, 'detailCommon2', contentId=place['id']),
        asyncio.to_thread(fetch, 'detailIntro2', contentId=place['id'], contentTypeId=place['content_type']))
    c, i = (common[0] or [{}])[0], (intro[0] or [{}])[0]
    value = dict(place)
    value.update(description=clean(c.get('overview')),
                 hours=clean(i.get('usetime') or i.get('usetimeculture') or i.get('usetimeleports')),
                 rest=clean(i.get('restdate') or i.get('restdateculture') or i.get('restdateleports')),
                 fee=clean(i.get('usefee') or i.get('usefeeleports')),
                 phone=clean(i.get('infocenter') or i.get('infocenterculture') or c.get('tel')),
                 checked_at=datetime.now(KST).isoformat())
    value['operating_status'] = operating_status(value['hours'], value['rest'])
    _cache[key] = dict(value=value, time=time.time())
    return attach_evidence(value)

def rank(places, lat, lon, radius, visited, excluded, category='전체'):
    results = []
    seen = set(visited) | set(excluded)
    for place in places:
        if place['id'] in seen or not supported(place['lat'], place['lon']):
            continue
        if category != '전체' and category != place['category']:
            continue
        d = distance((lat, lon), (place['lat'], place['lon']))
        state = operating_status(place.get('hours'), place.get('rest'))
        if d > radius or state == '운영시간상 방문 불가':
            continue
        results.append(dict(place, distance_km=round(d, 3), score=max(0, 1-d/radius),
                            operating_status=state, reasons=[f'기준 위치에서 직선거리 약 {d:.1f}km',
                            '비교 가능한 공통 지표인 거리로 추천했어요.']))
    return sorted(results, key=lambda p: (-p['score'], p['distance_km'], p['id']))
