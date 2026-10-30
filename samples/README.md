# 프론트 작업용 샘플 데이터

공공데이터 인증키 없이 화면을 만들 수 있도록, 로컬에서 수집한 실제 데이터와 그 데이터로 백엔드 API를 호출한 응답을 그대로 담았다.

- 만든 날: 2026-10-30, 서비스 기준일(`today`) 2026-10-30. 생성 정보는 `manifest.json`에 있다.
- 키는 들어 있지 않다. 생성 스크립트가 키 환경변수를 지운 채 로컬 DB **복사본**만 읽었고, 외부 API는 한 번도 부르지 않았다. 생성 뒤 `backend/.env`의 키 값과 키 패턴으로 모든 파일을 검사했다.
- 이 폴더는 서버 배포물에 들어가지 않는다(배포는 `backend/app`, `frontend/src`, `frontend/public`만 올린다). 프론트에서 쓰려면 필요한 파일을 `frontend/src` 아래로 복사하되, **폴더 이름을 `data`로 짓지 않는다**. 배포 도구가 `data`라는 이름의 폴더를 통째로 빼서 서버 빌드가 실패한다.

## api/ — 백엔드 API 실제 응답

파일마다 `{"request": {method, path, params, body}, "status", "response"}` 형식이다. 서버에 배포되면 같은 요청에 같은 모양의 응답이 온다. 요청 계약 전체는 `api/openapi.json`, 필드 설명은 `docs/region-course-backend.md` 6절과 `docs/benefits-api.md`에 있다.

| 파일 | API | 화면 |
| --- | --- | --- |
| 01-team-meta | `GET /api/team/meta` | 입력 폼 선택지(출발지·관심 분야·거주지), 기준일, 캐시 상태 |
| 02-team-programs | `GET /api/team/programs` | 환급제 한눈에 목록 |
| 03-team-recommend | `POST /api/team/recommend` | 추천 지역 3곳 카드, 관광지 후보 |
| 04-team-course-create | `POST /api/team/courses` | 일정표 생성(응답의 `id`로 아래 호출) |
| 05-team-course-get | `GET /api/team/courses/{id}` | 저장된 일정표 |
| 06-team-course-reasons | `POST /api/team/courses/{id}/reasons` | 장소별 추천 문장 |
| 07-team-course-candidates | `GET /api/team/courses/{id}/candidates` | 장소 바꾸기 후보 |
| 08-team-place-detail | `GET /api/team/places/{content_id}` | 장소 상세 |
| 09-team-course-swap | `POST /api/team/courses/{id}/swap` | 장소 바꾼 뒤 다시 계산한 일정표 |
| 10-team-course-refund | `POST /api/team/courses/{id}/refund` | 환급 패널(판정·예상액·할 일 타임라인) |
| 11-team-date-recommendations | `POST /api/team/date-recommendations` | 날짜 기반 축제·여행지원 지역 추천 |
| 12-benefits-check | `POST /api/benefits/check` | 지원제도 판정(여러 지역 일정) |
| 13-benefits-sources | `GET /api/benefits/sources` | 지원제도 출처·갱신 상태 |
| 14-benefits-detail | `GET /api/benefits/{benefit_id}` | 지원제도 상세·출처·신청 안내 |

요청 값은 합성 예시다: 광주 북구 출발·거주, 2명, 1995-03-01생, 기준일 11일 뒤 출발 1박2일.

주의할 점:

- `06`의 추천 문장은 로컬 **mock** 문장이다(`status: "mock"`). 서버에서는 Bedrock 문장(`status: "ai"`)이 온다. 모양은 같다.
- 코스 `id`는 실행할 때마다 바뀐다. 화면에 고정값으로 쓰지 않는다.
- 지원제도 판정은 모두 `needs_verification`까지만 나온다. 공고 원문 검토 전 자료라서다. 화면은 '확인 필요' 상태를 기본으로 설계한다.
- 지원제도 조회 상태가 `partial`로 나온다. 행정안전부 공공서비스(혜택) API는 키가 없어 한 번도 수집되지 않았고(`gov24_api:never_synced`), 반값여행 현황 자료는 마지막 수집 뒤 갱신 주기가 지나 '오래됨'(`stale`)으로 표시돼서다. 이 상태의 안내 문구(`message`, `failed_sources`)도 화면에서 다뤄야 한다.

## tables/ — 수집 원본

배열 하나에 한 줄당 한 행이다. DB 파일 자체는 규칙상 Git에 올리지 않고, 표를 JSON으로 내보냈다.

| 파일 | 행 | 내용 |
| --- | --- | --- |
| places.json | 3,369 | 광주·전남 27개 시군구의 관광지 1,608 · 음식점 975 · 숙박 289 · 문화시설 270 · 레포츠 195 · 축제 30 · 쇼핑 2. 이름·주소·좌표·이미지·분류·소개(`intro_json`). `source`: `kor`(KorService2) / `std`(전국관광지정보표준데이터) |
| hub_rank.json | 2,338 | 시군구별 중심 관광지 순위(기준연월 202606) |
| related_place.json | 13,571 | 관광지별 연관 관광지 쌍과 순위(기준연월 202606) |
| benefit_records.json | 50 | 한국관광공사 반값여행 현황 페이지에서 수집한 차수별 기록. 47건 `needs_review`, 3건 `conflict`. 수동 등록 지원제도(`manual:…`)는 DB가 아니라 코드(`backend/app/team/benefits/registry.py`)에 있어 여기 없다 |

## 출처와 이용 조건

- 관광 데이터: 한국관광공사(국문 관광정보 KorService2, 중심 관광지, 연관 관광지), 전국관광지정보표준데이터. 화면에 출처 '한국관광공사'를 표기한다.
- 이미지: `cpyright_type`을 따른다. `Type1`(991곳)은 출처 표시, `Type3`(1,642곳)은 출처 표시 + 변경 금지(자르기·필터 등 편집 금지)다. 값이 없는 곳은 이미지가 없다.
- 지원제도: 한국관광공사 대한민국 반값여행 현황 페이지. 판정·금액은 참고용이며 최종 승인은 지자체 심사를 따른다는 문구를 화면에 둔다.

## 다시 만들기

로컬 DB(`.local-data/records.sqlite3`)가 있는 사람만 실행할 수 있다. 수집은 `scripts/sync-tourism.ps1`, 방법은 `docs/region-course-backend.md` 4절.

```powershell
backend\.venv\Scripts\python.exe scripts\export_samples.py
```

`--today 2026-11-02`처럼 기준일을 고정할 수 있다. 요청 날짜는 기준일 11일 뒤로 맞춰진다.
