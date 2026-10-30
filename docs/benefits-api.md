# 여행 지원제도 확인 API (`/api/benefits`)

여행 일정과 사용자 조건을 받아 방문 지역의 여행 지원제도 후보를 찾고, 확인된 조건만 비교해 판정합니다.
범위는 **탐색과 조건 확인**까지입니다. 대체 지역 추천, 여행코스 생성, 실제 신청 제출은 포함하지 않습니다.

- 코드: `backend/app/team/benefits/`
- 테스트: `backend/tests/test_benefits.py`
- 설계·작업: `.kiro/specs/travel-benefit-check/`

## 1. 경로

| 메서드 | 경로 | 역할 |
| --- | --- | --- |
| POST | `/api/benefits/check` | 여행 일정·사용자 조건으로 지원제도 조회·판정 |
| GET | `/api/benefits/{benefit_id}` | 지원제도 상세·출처·신청 안내 |

경로 선택: 기존 경로(`/api/records`, `/api/ai/*`, `/api/team`, `/api/health`)와 충돌하지 않아 요청한 경로를 그대로 썼습니다.
프로젝트 규칙(팀 API는 `team/routes.py`에 추가, `main.py`는 이미 그 라우터를 등록)을 지키려고 `main.py`는 수정하지 않았습니다.
대신 `team/routes.py`의 최상위 라우터에서 prefix를 빼고, 기존 `/api/team` 라우터(`team_router`)와 `/api/benefits` 라우터를 함께 포함합니다.
다른 팀 API는 계속 `team_router`(`/api/team/...`)에 추가하면 됩니다.

`benefit_id` 형식:

- `manual:<slug>`: 수동 등록 자료(공고 검토용 보조 데이터)
- `gov24:<서비스ID>`: 행정안전부 공공서비스(혜택) API 레코드

## 2. 외부 API 조사 결과 (행정안전부_대한민국 공공서비스(혜택) 정보)

출처: [data.go.kr 15113968](https://www.data.go.kr/data/15113968/openapi.do), 페이지가 링크하는 공식 Swagger 문서(`https://infuser.odcloud.kr/api/stages/44436/api-docs`). 2026-10-30 확인.

| 항목 | 확인 내용 |
| --- | --- |
| 요청 주소 | `https://api.odcloud.kr/api/gov24/v3` |
| 오퍼레이션 | `GET /serviceList`(목록), `GET /serviceDetail`(상세), `GET /supportConditions`(지원조건) |
| 인증 | 쿼리 `serviceKey` 또는 헤더 `Authorization` (이 구현은 쿼리 사용, Decoding 키) |
| 검색 조건 | `serviceList`: `cond[서비스ID::EQ]`, `cond[서비스명::LIKE]`, `cond[등록일시::LT/LTE/GT/GTE]`, `cond[수정일시::LT/LTE/GT/GTE]`. 상세·지원조건은 `cond[서비스ID::EQ]`만 |
| 페이지 처리 | `page`(기본 1), `perPage`(기본 10). 응답 `page, perPage, totalCount, currentCount, matchCount, data[]` |
| 목록 필드 | 서비스ID, 지원유형, 서비스명, 서비스목적요약, 지원대상, 선정기준, 지원내용, 신청방법, 신청기한, 상세조회URL, 소관기관코드·명, 부서명, 조회수, 소관기관유형, 사용자구분, 서비스분야, 접수기관, 전화문의, 등록일시, 수정일시, 신청기한유형 |
| 상세 필드 | 위 일부 + 서비스목적, 구비서류, 접수기관명, 문의처, 온라인신청사이트URL, 행정규칙, 자치법규, 법령, 공무원확인구비서류, 본인확인필요구비서류 |
| 지원조건 필드 | JA0110/JA0111 대상연령(시작/종료), 성별, 중위소득 구간, 직업·가구 유형 등 Y/N 플래그 |
| 갱신 기준 | 포털 표기 "업데이트 주기: 실시간", 레코드별 `수정일시` |
| 트래픽 | 개발계정 10,000건(일), 자동승인 |
| 키 없이 호출 | HTTP 401 `{"code":-401,"msg":"인증키는 필수 항목 입니다."}` (실제 호출로 확인) |

### 이 API로 확인할 수 없는 것

- 지역·분야로 거르는 검색 조건이 없습니다. 서비스명 LIKE 검색(`여행`, `관광`, `휴가`) 결과에서 기관명·본문에 방문 시군구가 나오는 레코드만 후보로 씁니다. 이 연결은 `match_basis: "text_hint"`로 표시하며 자격 근거로 쓰지 않습니다.
- 여행 인정 기간, 환급률, 지원 상한, 최소 소비액, 인정·제외 지출, 필수 방문지, 숙박 조건, 사전 신청 기한, 정산 기한, 지급 방식, 접수 상태, 예산 잔액, 개인 자격 확인은 구조화 필드가 없습니다. `신청기한`·`지원내용` 등 원문은 `raw_text`에 그대로 담고 해석하지 않습니다.
- 지역 반값여행·휴가지원 사업이 이 API에 수록돼 있는지는 **인증키가 없어 실제 응답으로 확인하지 못했습니다**.
- 중앙부처의 전국 단위 사업은 본문에 방문 지역명이 없으면 후보에서 빠질 수 있습니다.

그래서 공식 공고를 검토해 등록하는 보조 데이터(`registry.py`)를 함께 씁니다. 응답의 `data_origin`과 `source_type`으로 두 출처를 구분합니다.
현재 보조 데이터 4건은 `docs/feature-definition.md`(보도 기사 인용)에서 옮긴 값이라 모두 `verification_status: "unverified"`입니다.
공식 공고 검토 절차는 `registry.py` 상단 주석을 따릅니다.

## 3. POST /api/benefits/check

### 요청

| 필드 | 형식 | 필수 | 설명 |
| --- | --- | --- | --- |
| `departure` | Region | - | 출발지. 거주지 판정에 쓰지 않음 |
| `residence` | Region | - | 주민등록상 거주지. 없으면 `missing_fields`에 `residence` |
| `trip_start`, `trip_end` | date | O | 여행 시작·종료일 (최대 60일) |
| `visits[]` | Visit | O | 지역별 방문 일정 (1~20개, 여행 기간 안) |
| `party_size` | int | - | 여행 인원 |
| `expected_spend_total` | int | - | 전체 예상 지출. 환급률을 곱하는 데 쓰지 않음 |
| `birth_date` | date | - | 생년월일. 청년·연령 판정 |
| `age` | int | - | `birth_date`가 없을 때 기준일 현재 만 나이 |
| `is_family`, `same_address` | bool | - | 가족 여부, 동일 주소 여부 |
| `prior_participated_program_ids` | string[] | - | 참여한 사업 ID. `[]` = 이력 없음, `null` = 미입력 |
| `reference_date` | date | - | 판정 기준일(신청일로 간주). 기본 오늘(KST) |
| `include_external` | bool | - | 기본 `true`. `false`면 공공서비스 API를 조회하지 않음 |

Region: `{ "sido": "전라남도", "sigungu": "무안군" }` (둘 중 하나 이상. `전남`·`전남광주` 등 별칭 허용)

Visit:

| 필드 | 설명 |
| --- | --- |
| `region` | 방문 지역 |
| `start_date`, `end_date` | 그 지역 방문 첫날·마지막 날 |
| `nights` | 그 지역 숙박 수. `null`이면 숙박 조건을 판정하지 않음 |
| `checkin_dates` | 연속 숙박이 아닐 때만 필요 |
| `places` | 방문 장소 이름 목록 (필수 방문 조건 판정) |
| `expected_spend.by_category` | 항목별 예상 지출. 키: `lodging, food, cafe, experience, admission, local_product, shopping, transport, other` |

예시 (이 값으로 실제 실행한 결과가 아래 응답):

```json
{
  "departure": {"sido": "광주광역시", "sigungu": "북구"},
  "residence": {"sido": "광주광역시", "sigungu": "북구"},
  "trip_start": "2026-11-10",
  "trip_end": "2026-11-12",
  "party_size": 2,
  "birth_date": "1995-03-01",
  "prior_participated_program_ids": [],
  "reference_date": "2026-10-30",
  "visits": [
    {
      "region": {"sido": "전라남도", "sigungu": "무안군"},
      "start_date": "2026-11-10", "end_date": "2026-11-11", "nights": 1,
      "places": ["무안황토갯벌랜드", "회산백련지"],
      "expected_spend": {"by_category": {"lodging": 100000, "food": 96000, "transport": 30000}}
    },
    {
      "region": {"sido": "전라남도", "sigungu": "장흥군"},
      "start_date": "2026-11-11", "end_date": "2026-11-12", "nights": 1
    }
  ]
}
```

### 응답 최상위

| 필드 | 설명 |
| --- | --- |
| `success` | 요청한 모든 출처를 조회했는지. 외부 API 키 미설정·오류면 `false` |
| `outcome` | `candidates_found` / `no_match_in_scope`(조회 범위 안에 일치 없음) / `source_unavailable`(외부 API 오류로 확인 못함, 수동 자료에도 없음) / `insufficient_information`(후보는 있으나 사용자 정보 부족) |
| `scope` | 조회 기간, 기준일, 지역별 방문 날짜, 사용한 검색어 |
| `sources[]` | 출처별 상태. `gov24_api`: `ok/partial/error/not_configured/skipped`, `data_origin`: `live_api/cache/mixed`, 페이지 수, 잘림 여부, 오류 코드 |
| `coverage_note` | 수록 범위 한계. "결과가 없어도 지원제도가 없다는 뜻이 아님" 포함 |
| `missing_fields` | 판정·계산에 필요한데 입력되지 않은 필드 |
| `results[]` | 제도별 판정 (아래) |
| `combined_estimate` | 중복 적용이 확인된 제도만 합산. 확인 안 되면 `amount: null` |
| `checked_at`, `disclaimer` | 판정 시각, 고지 문구 |

### `results[]` 항목

| 필드 | 설명 |
| --- | --- |
| `verdict` | `potentially_eligible` / `ineligible` / `needs_verification` |
| `can_apply_now` | `false`: 접수 마감·조기 마감·예산 소진·사전 신청 기한 경과. `true`: 검증된 자료로 접수 가능 확인. `null`: 미확인. **`false`인 제도는 신청 가능한 혜택으로 보여 주지 마세요.** |
| `data_origin`, `source_type`, `verification_status` | 외부 API / 수동 등록 / 병합, 출처 유형, 공고 검토 여부 |
| `matched_visits[]` | 이 제도와 연결된 방문 일정, `match_basis`(`target_region` / `text_hint`) |
| `met_conditions[]`, `unmet_conditions[]`, `unresolved_conditions[]` | 조건별 `code, label, status, detail, rule_confirmed, user_fields, program_fields` |
| `missing_user_fields[]` | 이 제도에 필요한 미입력 정보 |
| `official_checks_needed[]` | 공식 확인이 필요한 항목 |
| `timeline` | 접수 기간, 접수 마감 여부, 사전 신청 기한(날짜)·경과 여부, 여행 인정 기간, 정산 기한, 게시 상태·확인 시각 (각각 별도 필드) |
| `estimate` | `benefit_type`(`cash_refund`/`local_voucher`/`onsite_discount`), `amount`, `amount_kind`(`calculated`/`upper_bound`), 인정 지출, 환급률, 적용 상한, 최소 소비액·부족액, `unavailable_reasons`(금액이 `null`인 이유), `notes` |
| `how_to_apply` | 신청 URL, 공식 안내 URL, 사전 신청 채널, 결제수단, 증빙, 지급 방식 |
| `sources[]`, `last_verified_at`, `conflicts[]` | 출처 목록, 마지막 검토 시각, 출처 간 충돌(모든 값 보존) |

판정 규칙:

- 검증된 출처의 조건을 충족하지 못하면 `ineligible`
- 정보 부족, 제도 조건 미확인, 출처 충돌, 미검증 자료에서의 불충족은 `needs_verification`
- 모든 조건이 확인되고 충족될 때만 `potentially_eligible` (최종 승인 보장 아님)
- `null`인 제도 조건은 "제한 없음"이나 "0원"으로 해석하지 않음

예상액 규칙:

- 인정 항목 지출만 합산합니다. 숙박 1박 한도를 적용하고, 최소 소비액을 먼저 확인합니다. 그다음 환급률과 상한 구간을 적용하고 절사합니다.
- 전체 예산(`expected_spend_total`)에 환급률을 곱하지 않습니다.
- 환급률, 상한, 최소 소비액, 인정 항목, 상한 구간을 판단하는 정보(인원·숙박 수·청년 여부·가족 여부) 중 하나라도 없으면 `amount: null`입니다.
- 절사 규칙이나 숙박 한도 여부만 모르면 금액을 내되 `amount_kind: "upper_bound"`입니다.
- 청년 기준일(신청일/여행 시작일/연 나이)에 따라 결과가 달라지면 청년 환급률을 적용하지 않고 `null`입니다.

### 응답 예시 (위 요청, 키 미설정 상태의 실제 실행 결과, 첫 결과만 축약)

```json
{
  "success": false,
  "outcome": "insufficient_information",
  "message": "후보 제도를 찾았지만 자격 판단에 필요한 정보가 부족합니다.",
  "scope": {"trip_start": "2026-11-10", "trip_end": "2026-11-12", "reference_date": "2026-10-30",
            "visits": [{"region": {"sido": "전라남도", "sigungu": "무안군"}, "dates": ["2026-11-10", "2026-11-11"]},
                       {"region": {"sido": "전라남도", "sigungu": "장흥군"}, "dates": ["2026-11-11", "2026-11-12"]}],
            "gov24_keywords": []},
  "sources": [
    {"source": "gov24_api", "status": "not_configured", "error_code": "missing_service_key",
     "message": "서버에 공공데이터포털 인증키가 설정되지 않아 외부 API를 조회하지 않았습니다.", "pages_fetched": 0},
    {"source": "manual_registry", "status": "ok", "data_origin": "local_registry", "records_seen": 4}
  ],
  "missing_fields": ["is_family"],
  "results": [
    {
      "benefit_id": "manual:muan-halfprice-2026",
      "name": "2026 갯벌愛 무안 반값여행",
      "data_origin": "manual_registry", "source_type": "project_doc", "verification_status": "unverified",
      "verdict": "needs_verification",
      "can_apply_now": null,
      "matched_visits": [{"region": {"sido": "전라남도", "sigungu": "무안군"},
                          "start_date": "2026-11-10", "end_date": "2026-11-11", "match_basis": "target_region"}],
      "met_conditions": [
        {"code": "residence", "status": "met", "detail": "거주지 광주광역시 북구는 제외 지역(전라남도 무안군) 아님", "rule_confirmed": false},
        {"code": "stay", "status": "met", "detail": "체크인 2026-11-10(화), 허용 요일 월화수목금", "rule_confirmed": false}
      ],
      "unmet_conditions": [],
      "unresolved_conditions": [
        {"code": "application_period", "status": "unconfirmed_program_rule",
         "detail": "접수 시작 2026-09-14, 마감일 미확인(예산 소진 시 마감 가능)"},
        {"code": "pre_apply", "status": "unconfirmed_program_rule", "detail": "사전 신청 필요, 기한(여행 N일 전) 미확인"},
        {"code": "source_verification", "status": "unconfirmed_program_rule",
         "detail": "공식 공고로 검토되지 않은 자료(project_doc) — 공식 공고 확인 필요"}
      ],
      "timeline": {"application_period": {"start": "2026-09-14", "end": null}, "application_closed": null,
                   "pre_apply_deadline": null, "trip_period": null, "settlement_deadline": "2026-11-18",
                   "posted_status": null},
      "estimate": {"benefit_type": "local_voucher", "amount": 98000, "amount_kind": "upper_bound",
                   "recognized_spend": 196000, "refund_rate": 0.5, "cap_label": "1박형 팀", "cap_amount": 200000,
                   "min_spend": 100000,
                   "notes": ["transport 30,000원은 인정 항목이 아니어서 제외",
                             "절사 규칙 미확인 — 실제 지급액은 이보다 적을 수 있음",
                             "숙박 1박 한도 여부 미확인 — 실제 지급액은 이보다 적을 수 있음",
                             "공식 공고로 검토되지 않은 자료 기준 계산(참고용)"]},
      "how_to_apply": {"application_url": null, "official_info_url": null,
                       "proof_items": ["숙박 자료", "방문 사진", "영수증"], "payout": {"method": "모바일 무안사랑상품권"}},
      "sources": [{"source_type": "news_report", "title": "MTN 보도",
                   "url": "https://news.mtn.co.kr/news-detail/2026091118124235889"}]
    }
  ],
  "combined_estimate": {"amount": 98000, "benefit_ids": ["manual:muan-halfprice-2026"],
                        "note": "계산 가능한 제도가 1건입니다. 확인 필요 항목이 있는 참고값입니다."}
}
```

두 번째 결과(장흥 휴가지원)는 `estimate.amount: null`, `unavailable_reasons: ["인정 지출 항목 미확인", "가족 여부 미입력"]`입니다.

## 4. GET /api/benefits/{benefit_id}

```
GET /api/benefits/manual:jn-island-halfprice-2026
```

응답: `benefit`(위 데이터 구조 전체: 제공기관, 외부 서비스 ID, 사업·차수 ID, 기간, 조건, 혜택, 증빙, URL, 출처, `unverified_fields`, `conflicts`, `raw_text`), `data_origin`, `source_status`, `stale_status`(접수 상태 확인 후 7일 경과 여부), `disclaimer`.

| 상태 코드 | 경우 |
| --- | --- |
| 200 | 조회 성공 |
| 404 | 해당 ID 없음 |
| 422 | ID 형식 오류 (`manual:` 또는 `gov24:` + 영숫자·`_.-`) |
| 503 | `gov24:` ID인데 서버에 인증키 미설정 |
| 502 | `gov24:` ID 조회 중 외부 API 오류 (`detail`에 오류 코드만, 키·URL 미포함) |

## 5. 서버 설정

- `KIROTHON_DATA_GO_KR_SERVICE_KEY`: 공공데이터포털 Decoding 키. 서버 환경변수로만 읽습니다(`backend/.env.example`에 이름만 있음).
- 선택: `KIROTHON_GOV24_CACHE_TTL_SECONDS`(기본 21600), `KIROTHON_GOV24_MAX_PAGES`(검색어당, 기본 5), `KIROTHON_GOV24_DAILY_CALL_LIMIT`(프로세스당, 기본 9000)
- 외부 호출: httpx(잠금 파일에 있음), 연결 5초·전체 10초 타임아웃, 성공 응답 6시간·오류 60초 메모리 캐시, 키는 로그·응답·오류 메시지에 넣지 않음(httpx INFO 로그 억제)
- 사용자 입력(거주지·생년월일 등)은 판정에만 쓰고 저장하지 않습니다. 새 DB 테이블은 없습니다.
