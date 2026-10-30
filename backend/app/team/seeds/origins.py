"""Departure points (gu offices, stations) with approximate coordinates."""

DATA = {
  "_note": "출발지 9곳. 좌표는 구청·역 위치의 근사값(소수 넷째 자리)이며 직선거리 기반 이동시간 추정에만 쓴다. 공식 좌표로 검증하지 않았다.",
  "origins": [
    {"key": "gj-dong", "name": "광주 동구", "sigungu_code": "29110", "lat": 35.1462, "lng": 126.9230},
    {"key": "gj-seo", "name": "광주 서구", "sigungu_code": "29140", "lat": 35.1520, "lng": 126.8902},
    {"key": "gj-nam", "name": "광주 남구", "sigungu_code": "29155", "lat": 35.1329, "lng": 126.9026},
    {"key": "gj-buk", "name": "광주 북구", "sigungu_code": "29170", "lat": 35.1740, "lng": 126.9120},
    {"key": "gj-gwangsan", "name": "광주 광산구", "sigungu_code": "29200", "lat": 35.1395, "lng": 126.7937},
    {"key": "st-gwangjusongjeong", "name": "광주송정역", "sigungu_code": "29200", "lat": 35.1376, "lng": 126.7911},
    {"key": "st-mokpo", "name": "목포역", "sigungu_code": "46110", "lat": 34.7913, "lng": 126.3864},
    {"key": "st-suncheon", "name": "순천역", "sigungu_code": "46150", "lat": 34.9456, "lng": 127.5035},
    {"key": "st-yeosuexpo", "name": "여수엑스포역", "sigungu_code": "46130", "lat": 34.7531, "lng": 127.7484}
  ]
}
