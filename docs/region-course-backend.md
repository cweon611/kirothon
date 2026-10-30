# 지역 추천·코스 생성 백엔드 (F1·F2·S1)

브랜치 `feat/region-course-backend` · 2026-10-30

[기능정의서](../기능정의서.md)와 `.kiro/specs/refund-first-course/requirements.md` 중 아래 범위를 구현했다. 화면(프론트엔드)은 수정하지 않았다.

## 1. 범위 나누기

| 범위 | 담당 | 이 브랜치 |
| --- | --- | --- |
| 지원제도 조회·판정, 예상 지원액, 신청 기한 (`POST /api/benefits/check`, `GET /api/benefits/{id}`) | 지원제도 담당(`sale-check`, main에 병합됨) | 구현하지 않음. `benefit_bridge.py`가 그 판정 엔진을 그대로 불러 결과만 받는다(5절) |
| 지원제도 외부 데이터 자동 수집·갱신, 운영자 동기화 | 지원제도 담당 | 구현하지 않음 |
| 화면 | 프론트 담당 | 수정하지 않음. 아래 6절 API를 쓴다 |
| **S1 관광 데이터 수집·캐시** (KorService2, 중심 관광지, 연관 관광지) | 이 브랜치 | `tourapi.py`, `sync_tourism.py` |
| **F1 환급 우선 지역 추천** | 이 브랜치 | `recommend.py`, `POST /api/team/recommend` |
| **F2 이동순서 일정표·추천 이유**, 코스 저장·장소 바꾸기 | 이 브랜치 | `planner.py`, `reasons.py`, `/api/team/courses*` |
| 장소 상세, 화면 선택지 | 이 브랜치 | `GET /api/team/places/{id}`, `GET /api/team/meta` |

F3의 '여행 전·중·후 할 일 타임라인'은 지원제도의 기한 데이터(사전 신청·정산 기한)로 만드는 것이라 지원제도 담당 쪽과 누가 맡을지 정해야 한다. 이 브랜치는 만들지 않았다.

## 2. 변경 파일

```
backend/app/team/
  models.py            (수정) 지원제도 테이블과 관광·코스 테이블 둘 다 등록
  routes.py            (수정) 지원제도 담당의 라우터 구조 유지 + team_router 아래 course_routes, 판정 엔진 포트 등록
  benefit_bridge.py    (신규) benefit_port 구현: 지원제도 판정 엔진(app.team.benefits)을 프로세스 안에서 호출
  tourism_models.py    (신규) place · hub_rank · related_place · course · tourism_sync_run
  tourapi.py           (신규) 관광공사 API 클라이언트: 공통 파라미터, 페이지, 재시도, 오류 분류, 키 비노출
  sync_tourism.py      (신규) 수집 명령 7단계
  regions.py           (신규) 시군구·출발지·관심 분야 시드, 오늘(KST·TEAM_TODAY), 코드 매핑
  geo.py               (신규) 직선거리 이동시간 추정
  tourism_data.py      (신규) 요청마다 읽는 캐시 스냅샷, 관광지 후보, 시연 데이터 채우기
  benefit_port.py      (신규) 지원제도 모듈과의 경계(판정 결과·코스 조건만 받는다)
  recommend.py         (신규) F1 그룹·점수·이유 태그
  planner.py           (신규) F2 일정표
  reasons.py           (신규) 규칙 문장, AI 문장(코스당 2회), 출력 검사
  course_routes.py     (신규) /api/team/* 엔드포인트
  seeds/regions.json · origins.json · interest_map.json · place_overrides.json · demo_places.json
backend/.env.example   (수정) 지원제도 변수 + 관광 변수, 이름만
backend/tests/course_fixtures.py · test_tourapi_sync.py · test_recommend_planner.py · test_course_api.py · test_benefit_bridge.py
docs/region-course-backend.md
```

기존 `models.py`(Record)·`database.py`·`main.py`·잠금 파일은 바꾸지 않았다. 새 패키지는 없다(httpx 0.28.1은 lock에 있다). 테이블은 모두 신규라 `schema_check`를 통과한다.

## 3. 외부 API 확인 결과

공공데이터포털 각 페이지에 들어 있는 Swagger 명세(2026-10-30 내려받음)로 오퍼레이션·파라미터·응답 필드를 확인했다. 명세에 없는 엔드포인트·필드는 쓰지 않았다.

| API | 요청 주소 | 쓰는 오퍼레이션 | 확인한 응답 필드 | 개발계정 트래픽 |
| --- | --- | --- | --- | --- |
| 국문 관광정보 KorService2 (15101578) | `https://apis.data.go.kr/B551011/KorService2` | `ldongCode2`(lDongListYn=Y), `lclsSystmCode2`(lclsSystmListYn=Y), `areaBasedList2`, `searchFestival2`, `searchKeyword2`, `detailCommon2`, `detailIntro2`, `detailInfo2` | contentid, contenttypeid, title, addr1·2, mapx·mapy, firstimage·2, cpyrhtDivCd, lDongRegnCd·lDongSignguCd, lclsSystm1~3, modifiedtime, eventstartdate·eventenddate, overview, restdate·usetime·usefee(타입별 접미사), spendtime, roomoffseasonminfee1 | 1,000회/일 |
| 기초지자체 중심 관광지 LocgoHubTarService1 (15128559) | `https://apis.data.go.kr/B551011/LocgoHubTarService1` | `areaBasedList1` (baseYm·areaCd·signguCd 필수) | hubTatsCd, hubTatsNm, hubRank, mapX, mapY, hubCtgryLclsNm·MclsNm, signguCd | 1,000회/일 |
| 관광지별 연관 관광지 TarRlteTarService1 (15128560) | `https://apis.data.go.kr/B551011/TarRlteTarService1` | `areaBasedList1` | tAtsCd, tAtsNm, rlteTatsCd, rlteTatsNm, rlteSignguCd, rlteRank, rlteCtgryLclsNm·Mcls·Scls | 1,000회/일 |

- 인증: 모든 요청에 `serviceKey`(Decoding 키), `MobileOS=WEB`, `MobileApp`, `_type=json`.
- 결과 코드(명세): `03` 데이터 없음 → 빈 페이지로 처리, `05`·`02` → 재시도, `21` 등 → 인증 오류, `22` → 한도 초과. 성공 코드 `0000`은 기존 팀 코드 기준이라 첫 실제 호출로 확인해야 한다.
- 연관 관광지 제공 기간은 포털에 2024-05~2025-04로 적혀 있다. 기준연월은 `--base-ym`으로 정하거나, 수집 스크립트가 지난달부터 한 달씩 내려가며 응답이 있는 달을 찾는다.
- KorService2의 `areaCode`·`sigunguCode`·`cat1~3`는 명세에 '삭제 예정'으로 표시돼 쓰지 않는다. 법정동 코드와 분류체계(lclsSystm)만 쓴다.
- 분류체계 코드 값은 공식 표를 찾지 못해 코드에 적지 않았다. 수집 1단계가 `lclsSystmCode2` 응답의 분류명에서 키워드(자연, 역사·문화, 음식, 체험·레저, 공원·숲)를 찾아 코드로 바꾸고 결과를 출력한다. 그 전에는 관광타입 ID(12·14·28·39)로 관심 분야를 판정하고 응답에 `interest_basis: "content_type"`을 표시한다.
- 전국관광지정보표준데이터(15021141)는 이번에 연결하지 않았다. 좌표는 KorService2로 충분해 후속으로 남겼다.
- 관광 API는 관광지 조회에만 쓴다. 지원제도 자격 근거로 쓰지 않는다.

**인증키가 이 PC에 없어 실제 호출은 한 번도 하지 않았다.** 위 내용은 명세 확인이고, 실제 응답 형식·결과 코드·페이지 크기 상한은 키를 넣고 첫 수집을 돌려 확인해야 한다(9절).

## 4. 수집 실행 (S1)

화면 요청은 공공 API를 부르지 않고 SQLite 캐시만 읽는다. 장소 상세 한 건만 캐시에 없으면 그 자리에서 받는다(타임아웃 5초).

```powershell
cd backend
$env:TOURAPI_SERVICE_KEY = '<Decoding 키>'      # 비우면 KIROTHON_DATA_GO_KR_SERVICE_KEY를 쓴다. 서버는 서비스 환경변수로
$env:KIROTHON_DB_PATH = "$PWD\..\.local-data\records.sqlite3"
.\.venv\Scripts\python.exe -m app.team.sync_tourism --base-ym 202410
```

| 단계 | 호출 | 저장 | 실패 시 |
| --- | --- | --- | --- |
| codes | ldongCode2, lclsSystmCode2 | `<DB 폴더>/tourism-codes.json` (시군구 법정동 코드 대조, 통합특별시 출범 뒤 코드 변경 목록, 관심 분야 분류 코드) | 시드 코드 유지, 미해결 목록 출력 |
| places | areaBasedList2 × 27개 시군구 × 관광타입 12·14·28·39·32 | `place` upsert | 그 시군구·타입만 건너뜀, 기존 행 유지 |
| festivals | searchFestival2 (오늘 이후, 시도별) | `place`(타입 15, 행사 기간) | 건너뜀 |
| hubs | 중심 관광지 × 27 | `hub_rank` (기준연월·시군구 단위로 교체) | 오류·빈 응답이면 기존 행 유지 |
| related | 연관 관광지 × 27 | `related_place` | 같음 |
| match | 이름 정규화 + 같은 시군구(+좌표 0.5km) → 실패한 상위 10위 중심 관광지만 searchKeyword2 → `seeds/place_overrides.json` | `content_id` 채움, 매칭률 출력 | — |
| details | 시군구별 중심 관광지 상위 5곳 detailCommon2·detailIntro2 | 소개·쉬는날·이용시간·요금 | 한도 초과면 중단 |

- 기본 호출량은 약 500~600회로 API별 일일 1,000회 안에 들어오게 잡았다(`--details-top`, `--keyword-limit`로 조절).
- 호출 간격 0.2초, 타임아웃 10초, 재시도 2번. 키는 예외 메시지·로그·DB에 남지 않는다(httpx 요청 로그도 끈다).
- 실행 기록은 `tourism_sync_run` 테이블에 남고 `GET /api/team/meta`의 `tourism_data`로 보인다. 2시간 안에 시작된 실행이 있으면 새 실행을 막는다(`--force`로 해제).
- 일부만 다시: `--steps places,match --sigungu 46840`.

## 5. 지원제도 판정 엔진 연결

F1·F2는 지원 여부를 직접 판정하지 않는다. `team/routes.py`가 앱 시작 시 `benefit_bridge.BenefitsEnginePort`를 등록하고, 이 포트가 지원제도 담당의 판정 엔진(`app.team.benefits`)을 같은 프로세스 안에서 부른다. 외부 호출은 없다. `POST /api/benefits/check`와 같은 경로(수집·저장된 자료 + 수동 등록 자료 → `engine.evaluate`)를 탄다.

- F1: 여행 지역 후보 27곳 각각을 '그 시군구를 여행 기간에 방문하는 일정 1건'(숙박 수·체크인 날짜·인원·거주지 포함)으로 만들어 판정한다.
- F2: 고른 지원제도(`program_id` = 지원제도 API의 `benefit_id`, 예: `manual:muan-halfprice-2026`) 하나를 그 지역으로 다시 판정해 코스 조건만 꺼낸다.
- 판정 기준일은 `TEAM_TODAY`(없으면 한국시간 오늘)를 `reference_date`로 넘겨 두 모듈이 같은 '오늘'을 쓴다. 프론트가 `/api/benefits/check`를 직접 부를 때도 `reference_date`에 `meta.today`를 넣으면 같아진다.

| ProgramSummary 필드 | 지원제도 엔진에서 가져오는 값 |
| --- | --- |
| `program_id`, `round_id`, `name` | `benefit_id`, `round_id`, `name` |
| `judgment` | `verdict` 그대로 |
| `application_open` | `can_apply_now` (`null` = 접수 여부 미확인) |
| `posted_status` | `timeline.posted_status` (`open`·`closing_soon`·`closed`… 영문 값) |
| `rate`, `cap_krw` | `estimate.refund_rate`(없으면 제도 환급률), `estimate.cap_amount`(구간을 못 고르면 `null`) |
| `stale`, `last_verified_at`, `source_url` | 수집 신선도 또는 상태 확인 7일 경과, 공식 안내 URL |
| `reasons` | `불충족: …` / `확인 필요: …` 조건 이름만(사용자 입력값은 넣지 않음) |
| `constraints` | `visit_rule.must_include`·`min_total_places` → 필수 방문지·최소 장소 수, `stay_rule.min_nights`·`checkin_weekdays` → 숙박 조건 |

F1 그룹 규칙(지원제도 엔진 결과 기준):
- 1순위: `potentially_eligible`, 또는 불충족 조건 없이 확인할 것만 남은 `needs_verification`. 접수 마감(`can_apply_now=false`)이 아님.
- 2순위: 당일 일정인데 1박 이상 조건(`needs_stay`), 접수 마감(`closed`), 미검증 자료 기준으로 불충족 조건이 있음(`unmet_unverified`), 확인된 조건 불충족(`ineligible`).

수집 출처(공공서비스 API·반값여행 현황)가 미설정·오류·오래됨이면 `benefit_lookup.status = "partial"`과 `failed_sources`가 붙는다. 이때 판정은 저장된 이전 자료와 수동 등록 자료로 하고, 결과가 없는 지역은 '없음'이 아니라 '미확인'(`refund: null`)으로 둔다. `benefit_conditions` 형식이 틀리면 `status = "error"`와 틀린 필드명이 온다. 포트가 예외를 던져도 추천은 계속된다.

## 6. API (프론트 담당에게)

모두 `/api/team` 아래 JSON이다. 오류는 `{"detail": "문장", "code": "영문_코드"}`이고 입력 검증 오류만 FastAPI 기본 422 형식이다. 거주지·생년월일 같은 값은 POST 본문으로만 보내고, 서버는 저장·응답하지 않는다.

| 메서드·경로 | 화면 | 요약 |
| --- | --- | --- |
| `GET /meta` | 헤더·① | 기준일, 출발지 9곳, 관심 분야 5개, 여행 지역 27곳, 거주지 선택지, 캐시 상태, 지원제도 연결 여부 |
| `POST /recommend` | ② | 추천 지역 3곳(1순위 환급 그룹 먼저), 관광지 후보, 안내 배너 |
| `POST /courses` | ③ | 일정표 생성·저장. 응답에 `id` |
| `GET /courses/{id}` | 저장본 | 저장된 코스(+저장된 추천 문장) |
| `POST /courses/{id}/reasons` | ③ | `{day}` 일차의 추천 문장(AI는 코스당 2회까지) |
| `GET /courses/{id}/candidates?day=&order=` | 바꾸기 시트 | 바꿀 후보 3곳 |
| `POST /courses/{id}/swap` | 바꾸기 | `{day, order, content_id}` → 다시 계산한 코스 |
| `GET /places/{content_id}?date=YYYY-MM-DD` | 장소 상세 | 소개·쉬는날·이용시간·근거, 그 날짜 휴무 여부 |

예시 값은 테스트용 합성 데이터다(장소명 '테스트…', 지원제도 `muan_test`). 실제 응답의 `program_id`는 지원제도 API의 `benefit_id`(예: `manual:muan-halfprice-2026`)라서 `GET /api/benefits/{program_id}`로 상세를 열 수 있다.

### POST /api/team/recommend

```json
{
  "trip_type": "1N2D",
  "start_date": "2026-11-10",
  "origin": "gj-buk",
  "interests": ["nature", "history"],
  "party_size": 2,
  "transport": "car",
  "residence_code": "29170",
  "benefit_conditions": {"birth_date": "1999-01-01"}
}
```

- 검증(422): `interests` 서로 다른 1~3개, `start_date` ≥ 오늘(meta.today), `origin`·`interests`는 meta 값, `party_size` 1~20, 모르는 필드 금지.
- `residence_code`(5자리)·`benefit_conditions`는 선택이며 지원제도 판정에만 쓰고 저장하지 않는다.
  - `residence_code`는 광주·전남 27개 시군구 코드(수집 1단계를 돌린 뒤에는 전국 법정동 코드)로 거주지를 만든다.
  - 광주·전남 밖 거주자는 `benefit_conditions.residence = {"sido": "서울특별시", "sigungu": "강남구"}`처럼 이름으로 보낸다.
  - `benefit_conditions`에서 쓰는 키: `residence`, `departure`, `birth_date`, `age`, `is_family`, `same_address`, `prior_participated_program_ids`, `expected_spend_total` (지원제도 API 입력과 같은 형식). 나머지 키는 버린다.

```json
{
  "query": {"trip_type": "1N2D", "start_date": "2026-11-10", "end_date": "2026-11-11", "origin": "gj-buk",
            "interests": ["nature", "history"], "party_size": 2, "transport": "car"},
  "today": "2026-11-02", "today_fixed": true,
  "regions": [{
    "sigungu_code": "46840", "name": "무안군", "sido": "전라남도",
    "group": 1, "score": 76,
    "score_breakdown": {"interest": 34, "access": 30, "hub": 12, "season": 0},
    "travel_min": 63, "travel_note": "직선거리 기반 추정치",
    "refund": {"program_id": "muan_test", "round_id": "muan_test-r1", "name": "muan_test 반값여행",
               "judgment": "potentially_eligible", "badge": "applicable", "posted_status": "open",
               "application_open": true, "rate": 0.5, "cap_krw": 200000, "stale": false,
               "last_verified_at": "2026-10-30T09:00:00+09:00", "source_url": "https://example.invalid/notice",
               "reasons": ["테스트 판정"]},
    "reason_tags": ["muan_test 반값여행 적용 예상", "자연·바다 일치 4곳", "중심 관광지 '테스트갯벌랜드'", "광주 북구에서 약 63분"],
    "photos": ["https://example.invalid/m1.jpg"], "photo_credit": "한국관광공사",
    "candidates": [{"content_id": "m3", "title": "테스트박물관", "category": "문화시설",
                    "summary": "테스트박물관 소개 문장", "evidence": "무안군 중심 관광지 2위",
                    "evidence_all": ["무안군 중심 관광지 2위"], "interest_labels": ["역사·문화"],
                    "image_url": "https://example.invalid/m3.jpg", "source": "kor"}],
    "demo_data": false
  }],
  "no_refund_notice": null,
  "excluded_by_travel_cap": 0, "excluded_no_data": 23,
  "interest_basis": "content_type",
  "benefit_lookup": {"status": "ok", "checked_at": "2026-10-30T09:00:00+09:00", "scope_note": "…",
                     "message": null, "failed_sources": [], "connected": true},
  "tourism_data": {"status": "ready", "places": 21, "hub_rows": 5, "related_rows": 2,
                   "last_attempt_at": "…", "last_attempt_status": "success", "last_success_at": "…",
                   "base_ym_hub": "202410", "base_ym_related": "202410"},
  "notice": null
}
```

| `refund.badge` | 뜻 | 그룹 |
| --- | --- | --- |
| `applicable` | 지원제도 모듈이 `potentially_eligible`이고 접수 중 | 1 |
| `needs_verification` | 판정이 `needs_verification`이거나 접수 상태 미확인 | 1(배지에 '확인 필요') |
| `needs_stay` | 1박 이상 조건인데 당일 일정 | 2 |
| `closed` | 접수 마감 | 2 |
| `unmet_unverified` | 미검증 자료 기준으로 불충족 조건이 있음(예: 보도상 여행 기간이 끝남). 공고 확인 필요 | 2 |
| `ineligible` | 확인된 필수 조건 불충족(예: 제외 거주지) | 2 |
| `unknown` (`refund: null`) | 지원제도 확인 실패·미연결·일부 실패로 이 시군구 미확인 | 2 |

| `no_refund_notice.code` | 화면 문구 방향 |
| --- | --- |
| `benefit_not_connected` | 지원제도 판정 포트가 등록되지 않음(정상 배포에서는 나오지 않음) |
| `benefit_lookup_failed` | 확인 실패. "환급제가 없다는 뜻은 아니에요" |
| `no_applicable_program_in_scope` | 조회한 범위(`scope_note`)에서 찾지 못함 + `nearest_program` |

`notice.code = "tourism_cache_empty"`이면 수집 전이라 `regions`가 비어 있다. 관광 캐시가 하나도 없는 시군구는 코스를 만들 수 없어 추천에서 빼고 `excluded_no_data`로 개수만 알린다.

### POST /api/team/courses

```json
{
  "trip_type": "1N2D", "start_date": "2026-11-10", "origin": "gj-buk",
  "interests": ["nature", "history"], "party_size": 2, "transport": "car",
  "sigungu_code": "46840", "program_id": "muan_test",
  "residence_code": "29170",
  "meal_cost_krw": 12000, "room_price_krw": null
}
```

```json
{
  "id": "yy58e999",
  "trip_type": "1N2D", "start_date": "2026-11-10", "end_date": "2026-11-11", "origin": "gj-buk",
  "interests": ["nature", "history"], "party_size": 2, "transport": "car",
  "region": {"sigungu_code": "46840", "name": "무안군", "refund_program_id": "muan_test",
             "refund_program": {"program_id": "muan_test", "round_id": "muan_test-r1", "name": "muan_test 반값여행",
                                "posted_status": "open", "application_open": true, "rate": 0.5, "cap_krw": 200000,
                                "stale": false, "last_verified_at": "2026-10-30T09:00:00+09:00",
                                "source_url": "https://example.invalid/notice"},
             "benefit_status": "ok"},
  "days": [{
    "day": 1, "date": "2026-11-10", "start_point": "광주 북구", "depart": "09:00",
    "items": [{
      "order": 2, "start": "11:10", "end": "12:40", "kind": "spot",
      "place": {"content_id": "m5", "title": "테스트생태공원", "lat": 35.01, "lng": 126.52, "category": "관광지",
                "sigungu_code": "46840", "source": "kor", "image_url": "https://example.invalid/m5.jpg"},
      "move_min_from_prev": 57, "move_warning": true, "transit_note": null,
      "meal": null, "label": null, "required": false, "swappable": true,
      "reason_tags": ["환급 지역", "관심 분야: 자연·바다", "테스트갯벌랜드 방문객이 함께 찾는 곳 1위"],
      "reason_text": "환급 지역 · 관심 분야: 자연·바다", "reason_by": "rule",
      "in_refund_region": true, "refund_note": null,
      "check_before_visit": false, "check_reasons": []
    }, {
      "order": 3, "start": "12:47", "end": "13:47", "kind": "meal", "meal": "lunch",
      "place": {"content_id": "f3", "title": "테스트한정식", "…": "…"},
      "move_min_from_prev": 7, "move_warning": false, "required": false, "swappable": false,
      "reason_tags": ["무안군 음식점", "이전 장소에서 7분"], "reason_text": "무안군 음식점", "reason_by": "rule",
      "in_refund_region": true, "refund_note": "영수증 보관",
      "check_before_visit": true, "check_reasons": ["쉬는 날 정보 없음"]
    }, {
      "order": 6, "start": "19:15", "end": null, "kind": "stay",
      "place": {"content_id": "s1", "title": "테스트펜션", "…": "…"}, "refund_note": "영수증 보관", "…": "…"
    }]
  }, {
    "day": 2, "date": "2026-11-11", "start_point": "테스트펜션", "depart": "09:30",
    "items": ["…"],
    "return_move_min": 69, "return_depart": "15:55", "home_arrival": "17:04"
  }],
  "estimated_spend_krw": 176000,
  "spend_breakdown": {
    "total_krw": 176000,
    "items": [{"label": "1일차 점심 2명 × 12,000원", "krw": 24000, "sigungu_code": "46840", "basis": "default"},
              {"label": "숙박 1박(객실 1개 기준)", "krw": 100000, "sigungu_code": "46840", "basis": "default"},
              {"label": "테스트박물관 이용요금 2명", "krw": 4000, "sigungu_code": "46840", "basis": "tourapi_usefee"}],
    "by_sigungu": {"46840": 176000},
    "fees_not_parsed": []
  },
  "spend_inputs": {"meal_cost_krw": null, "room_price_krw": null},
  "estimated_refund_krw": null,
  "refund_estimate_note": "예상 지원액은 지원제도 확인 API(POST /api/benefits/check)에 spend_breakdown.by_sigungu를 넘겨 계산해요. …",
  "warnings": [],
  "notes": [],
  "generated_at": "2026-10-30T21:21:46+09:00",
  "ai_calls": 0, "ai_calls_left": 2, "reasons_done": {}
}
```

- 화면 흐름: 코스를 먼저 그린 뒤 일차마다 `POST /courses/{id}/reasons {"day": n}`를 불러 문장을 바꿔 끼운다. `reason_by`가 `mock`이면 '모의 AI' 칩, `ai`면 AI 표시, `rule`이면 표시 없음.
- 예상 지원액은 이 응답이 계산하지 않는다. `spend_breakdown.by_sigungu`를 지원제도 API의 지역별 예상 지출로 넘긴다.
- 저장되는 코스(공유 링크)에는 거주지·생년월일과 사용자별 판정(`judgment`)이 없다. 열람자는 지원제도 API로 자기 조건을 다시 확인한다.
- 같은 요청을 토요일(2026-11-14) 출발로 보내면 `"warnings": [{"code": "stay_weekday", "message": "muan_test 반값여행은(는) 월·화·수·목·금요일 체크인 숙박만 인정돼요.", "suggested_date": "2026-11-13"}]`가 붙는다.
- `warnings[].code`: `stay_weekday`(`suggested_date` 포함), `needs_stay`, `required_place_unmatched`, `not_enough_spots`, `time_trimmed`, `time_limit`, `meal_not_found`, `stay_not_found`, `benefit_unchecked`, `program_not_found`.
- 오류: `422 program_region_mismatch`, `503 tourism_cache_empty`, `404 course_not_found`.

### 나머지

```http
POST /api/team/courses/yy58e999/reasons
{"day": 1}
→ {"day": 1, "status": "mock", "ai_calls": 1,
   "items": [{"order": 1, "content_id": "g1", "reason_text": "광주 문화관광 · 관심 분야: 역사·문화", "reason_by": "mock"}]}
```

`status`: `ai` · `mock` · `stored`(이미 만든 일차, AI 재호출 없음) · `failed`(429·502 → 규칙 문장) · `quota`(코스당 2회 소진).

```http
GET /api/team/courses/yy58e999/candidates?day=1&order=2
→ {"day": 1, "order": 2, "candidates": [{"content_id": "m7", "title": "테스트레저파크", "category": "레포츠",
     "move_min_from_prev": 62, "evidence": "무안군 관광 정보", "interest_labels": [],
     "image_url": "…", "source": "kor"}]}

POST /api/team/courses/yy58e999/swap
{"day": 1, "order": 2, "content_id": "m7"}
→ 다시 계산한 코스 전체 (식사·숙소·시각 재계산, 다른 장소의 저장된 문장 유지)
```

필수 방문지·식사·숙소는 `422 not_swappable`, 다른 지역·이미 쓴 장소는 `422 invalid_replacement`.

```http
GET /api/team/places/m1?date=2026-11-09
→ {"content_id": "m1", "title": "테스트갯벌랜드", "category": "관광지", "rest_text": "매주 월요일",
   "opening_window": {"open": "09:00", "close": "18:00"}, "closed_on_visit_date": true,
   "check_before_visit": false, "evidence": ["무안군 중심 관광지 1위"],
   "image_url": "…", "image_credit": "한국관광공사", "cpyright_type": "Type1",
   "detail_status": "cached", "…": "…"}
```

`detail_status`: `cached` · `fetched`(방금 받음) · `not_fetched`(키 없음) · `unavailable`(조회 실패, 목록 정보만) · `demo_data`.

## 7. 규칙 요약

**F1** (`recommend.py`)
- 출발지 → 시군구 대표 좌표(중심 관광지 상위 5곳 평균, 없으면 캐시 장소 평균) 이동시간이 당일 150분·1박2일 240분을 넘으면 뺀다.
- 그룹: 위 배지표. 그룹 안 점수 100점 = 취향 40(관광지·문화시설·레포츠 중 관심 분야 비율, 맛집 선택 시 음식점 포함) + 접근성 30(60분 이하 만점, 상한까지 선형) + 대표 관광지 20(중심 관광지 상위 5곳 중 관심 분야 1곳당 4점) + 시기 10(여행 기간 축제·행사). 동점은 지원 상한 큰 순 → 시군구 코드 순.
- 이유 태그 2~4개, 관광지 후보는 중심 관광지 상위 10 → 그 연관 관광지(같은 시군구 먼저) → 나머지 캐시 순, 관심 분야로 거른다. 시군구 관광지가 5곳 미만이면 `seeds/demo_places.json`으로 채우고 `source: "demo"`.

**F2** (`planner.py`)
- 체류: 관광지 90·문화시설 60(관람 소요시간 있으면 그 값)·레포츠 120·식사 60분. 이동: 20km 이상 ×1.3÷60km/h, 미만 ×1.4÷35km/h, +5분, 대중교통 ×1.5. 40분 초과 구간 `move_warning`.
- 출발 09:00(2일차 숙소 09:30). 최근접 이웃 + 2-opt. 점심 12:00(1박2일 1일차 12:30)·저녁 17:30(선택)/18:30에 가장 가까운 자리에 끼운다.
- 당일은 마지막 일정 19:00, 1박2일 2일차는 귀가 출발 17:00까지. 넘으면 바꿀 수 있는 관광지를 뒤에서부터 뺀다.
- 광주 출발이고(1박2일이거나 당일 편도 90분 이하) 광주 문화시설 중심 관광지 1곳을 첫 장소로 둔다.
- 쉬는날 텍스트에 그날 요일이 있으면 뺀다. 못 읽거나 '공휴일 다음날' 같은 조건이 붙으면 넣고 `check_before_visit`. 이용시간이 한 구간으로 읽히면 일찍 도착할 때 개장 시각까지 기다리고, 그래도 닫는 시각을 넘기는 코스 지역 관광지는 다른 후보로 바꾼다(여러 구간이면 판정하지 않음). 바꿀 수 없는 장소(광주 연결·필수 방문지)는 `check_reasons`에 '이용시간 밖 일정'을 단다.
- 식당은 코스 지역 안 음식점 중 직전 장소 5km 안, 연관 관광지에 함께 나온 곳 먼저. 숙소는 코스 지역 안에서 1일차 마지막 장소와 가장 가까운 곳. 1일차 저녁 전 2시간 넘게 비면 근처 관광지 1곳을 더 넣는다.
- 예상 지출 = 식사 × 인원 × 1인 식비(기본 12,000원) + 숙박 1박(입력값 → 관광공사 비수기 주중 최소 요금 → 기본 100,000원) + 이용요금이 금액 하나로 읽히는 관광지. 근거는 항목별 `basis`.
- AI 문장: 관광지만, 하루 1회·코스당 2회, 입력 4,000자·지시문 300자 안. 30자 초과, 숫자+원·시·%, '환급'·'무료'가 들어간 줄은 버리고 규칙 문장을 쓴다.

## 8. 테스트

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
```

결과(2026-10-30, Windows, Python 3.12.10, `sale-check` 병합 후): **164 passed, 3 skipped** (기존 템플릿·지원제도 테스트 포함, skipped 3건은 `KIROTHON_LIVE_TESTS=1`일 때만 도는 지원제도 실호출 테스트). `test_benefit_bridge.py`와 `test_course_api.py`의 일부는 지원제도 담당의 실제 판정 엔진·수동 등록 자료로 F1·F2를 끝까지 돌린다. 실제 외부 API는 부르지 않았고 httpx MockTransport·가짜 클라이언트·합성 데이터만 썼다. 템플릿의 `test_team_extension`이 하위 프로세스 출력을 cp949로 읽으면서 경고 1건을 내지만 테스트는 통과한다.

| 파일 | 확인한 것 |
| --- | --- |
| `test_tourapi_sync.py` | 빈 items·단건 dict·`03` 데이터 없음, 인증·한도·XML 게이트웨이 오류 분류, 3페이지 수집, `max_pages` 잘림 표시, 타임아웃·500 재시도 후 실패, 오류 문구에 키 없음, 키 없을 때 즉시 실패, 법정동 코드 변경 감지, 이름 매칭(유일·좌표·수동), 재수집 시 중복 없음·실패/빈 응답 시 기존 행 유지, 실행 중복 방지, 기준연월 탐색 |
| `test_recommend_planner.py` | 환급 그룹이 점수와 관계없이 먼저, 제외 거주지·접수 마감·1박 조건·확인 필요 배지, 확인 실패와 '찾지 못함' 구분, 일부 실패, 이동 상한, 태그 2개 이상, 결과 재현성, 관심 분야 필터, 시연 데이터 채우기, 19:00·17:00 제한, 40분 경고, 휴무일 제외·'방문 전 확인', 개장 전 도착 시 대기·이용시간 밖 관광지 교체, 환급 지역 숙소, 필수 방문지 고정, 숙박 요일 경고·대안 날짜, 대중교통 ×1.5, 지출 계산, 2-opt, 텍스트 해석, AI 문장 필터·mock·429·횟수 제한·재사용 |
| `test_course_api.py` | meta, 422 검증 8종, 거주지가 포트로만 가고 응답·DB에 없음, 포트 예외 시 추천 계속, 코스 저장·조회, 다른 지역 지원제도 거절, 바꾸기 후보·필수 방문지 거절·바꾸기, 추천 문장 API 횟수 제한, 장소 상세 휴무 판정, 빈 캐시 안내 |

## 9. 아직 확인하지 못한 것

- [ ] **실제 API 호출 0회.** 인증키(`TOURAPI_SERVICE_KEY`)가 없어 수집을 돌리지 못했다. 키를 넣고 `--sigungu 46840`처럼 한 시군구로 먼저 돌려 성공 코드(`0000`), `numOfRows` 상한(500 사용), 매칭률을 확인해야 한다.
- [ ] `lDongSignguCd`가 3자리인지 5자리인지, 통합특별시 출범 뒤 시도 코드가 바뀌었는지 — 수집 1단계 출력(`changed_from_seed`)으로 확인한다. 둘 다 처리하도록 짰다.
- [ ] 분류체계 키워드가 실제 분류명과 맞는지 — 1단계 출력 `interest_codes`를 사람이 본다.
- [ ] 중심·연관 관광지가 baseYm 202410에 광주·전남 응답을 주는지, 매칭률이 얼마인지.
- [ ] `seeds/origins.json` 좌표는 구청·역 위치 근사값이다(이동시간 추정용).
- [ ] `seeds/demo_places.json`은 비어 있다. 실제 장소를 팀이 확인해 넣어야 한다.
- [ ] 지원제도 수동 등록 자료가 모두 미검증(공고 원문 미검토)이라, 지금은 무안·장흥 등도 `needs_verification`(1순위, '확인 필요')까지만 나온다. 지원제도 담당이 공고를 검증하면 `applicable`로 바뀐다. 수집 출처가 서버에서 돌기 전에는 `benefit_lookup.status`가 항상 `partial`이다.
- [ ] 지원제도의 '대상 섬 중 1곳 이상'(`visit_rule.any_of`) 조건은 F2가 아직 코스에 넣지 않는다. 필수 방문지(`must_include`)·최소 장소 수만 반영한다.
- [ ] 서버(Bedrock)에서 실제 AI 문장 품질과 30자·금지어 필터 통과율. 로컬은 mock만 확인했다.
- [ ] 휴무·이용시간 해석은 단순 규칙이다. 공휴일·격주·계절 운영은 `방문 전 확인`으로만 표시한다.
- [ ] 1박2일은 두 날 중 하루라도 휴무인 관광지를 아예 뺀다(보수적).
- [ ] 전국관광지정보표준데이터(15021141) 연결, 숙박 요금 상세(`detailInfo2`)를 숙소 후보 전체로 넓히기는 후속.
