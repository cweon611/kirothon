"""Explicit offline enrichment import: python -m app.team.sync_tourism --month 202504.

Sources: https://www.data.go.kr/data/15128559/openapi.do and /15128560/openapi.do.
Monthly navigation-based ranks are evidence, not satisfaction or observed visit sequence.
"""
import argparse
import asyncio
from datetime import datetime
import json
from pathlib import Path
import re

from .tourism import catalogue, fetch, distance, KST

def name_key(name):
    return re.sub(r'[^가-힣a-zA-Z0-9]', '', name).lower()

def match_hub(hub, places):
    try:
        point = (float(hub['mapY']), float(hub['mapX']))
        matches = [p for p in places if name_key(p['name']) == name_key(hub['hubTatsNm'])
                   and distance(point, (p['lat'], p['lon'])) <= .25]
        return matches[0] if len(matches) == 1 else None
    except (KeyError, ValueError, TypeError):
        return None

def pages(service, month, district):
    rows, total = fetch('areaBasedList1', service=service, baseYm=month, areaCd='29', signguCd=district)
    for page in range(2, (total+499)//500+1):
        extra, _ = fetch('areaBasedList1', service=service, baseYm=month, areaCd='29', signguCd=district, pageNo=page)
        rows.extend(extra)
    return rows

async def sync(month):
    places, _, _ = await catalogue()
    hubs, relations = [], []
    for district in ('29110', '29155'):
        hubs.extend(await asyncio.to_thread(pages, 'LocgoHubTarService1', month, district))
        relations.extend(await asyncio.to_thread(pages, 'TarRlteTarService1', month, district))
    matches = {str(h['hubTatsCd']): (h, p) for h in hubs if (p := match_hub(h, places))}
    evidence = {}
    for source_id, (hub, place) in matches.items():
        related = []
        for row in relations:
            target = matches.get(str(row.get('rlteTatsCd')))
            if str(row.get('tAtsCd')) == source_id and target and target[1]['id'] != place['id']:
                related.append(dict(id=target[1]['id'], name=target[1]['name'], rank=int(row['rlteRank'])))
        evidence[place['id']] = dict(month=month, district=hub['signguNm'], hub_rank=int(hub['hubRank']),
            related=related, hub_source='https://www.data.go.kr/data/15128559/openapi.do',
            related_source='https://www.data.go.kr/data/15128560/openapi.do',
            definition='내비게이션 기반 중심·연관 순위. 만족도 또는 실제 방문 순서를 뜻하지 않습니다.')
    out = Path(__file__).resolve().parents[3] / '.local-data' / 'tourism-enrichment.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(month=month, collected_at=datetime.now(KST).isoformat(), places=evidence,
                   hub_rows=len(hubs), relation_rows=len(relations), matched=len(evidence))
    temp = out.with_suffix('.tmp')
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(out)
    print(json.dumps({k:v for k,v in payload.items() if k != 'places'}, ensure_ascii=True))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--month', required=True, help='Source month, YYYYMM; no silent latest-month assumption')
    args = parser.parse_args()
    if not re.fullmatch(r'\d{4}(0[1-9]|1[0-2])', args.month):
        parser.error('month must be YYYYMM')
    asyncio.run(sync(args.month))
