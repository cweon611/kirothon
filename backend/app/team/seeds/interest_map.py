"""Interest categories mapped to lclsSystm keywords and KorService2 content types."""

DATA = {
  "_note": "분류체계(lclsSystm) 코드는 이 파일에 적지 않는다. sync_tourism이 lclsSystmCode2(lclsSystmListYn=Y) 응답의 분류명에서 keywords를 찾아 코드로 바꾸고 tourism-codes.json에 저장한다. 코드가 아직 없으면 content_types(KorService2 관광타입 ID)로만 판정한다.",
  "interests": [
    {"key": "nature", "label": "자연·바다", "level": 1, "keywords": ["자연"], "content_types": ["12"]},
    {"key": "history", "label": "역사·문화", "level": 1, "keywords": ["역사", "문화"], "content_types": ["14"]},
    {"key": "food", "label": "맛집", "level": 1, "keywords": ["음식"], "content_types": ["39"]},
    {"key": "activity", "label": "체험·레저", "level": 1, "keywords": ["체험", "레저"], "content_types": ["28"]},
    {"key": "healing", "label": "힐링·산책", "level": 2, "keywords": ["공원", "숲", "산책", "휴양"], "content_types": ["12"]}
  ]
}
