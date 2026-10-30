# 설계 — 여행 지원제도 확인

API 계약·외부 API 조사·요청/응답 예시: `docs/benefits-api.md`

## 구조

```
POST /api/benefits/check
  → search.collect(): gov24 serviceList(LIKE 여행·관광·휴가, 페이지 반복)
                      → 방문 시군구가 기관명·본문에 나오는 레코드만 후보
                      → 후보 10건까지 serviceDetail + supportConditions
                      + registry.manual_programs() (external_service_id 일치 시 병합·충돌 기록)
  → engine.evaluate(): 지역 매칭 → 조건별 검사 → verdict → estimate
  → 응답(출처 상태, 범위, 누락 필드, 결과, 합산)
```

| 파일 | 역할 |
| --- | --- |
| `team/benefits/schemas.py` | 제도 데이터 구조, 요청·응답 모델, null 규칙 |
| `team/benefits/regions.py` | 시도 별칭(전남광주통합특별시 포함), 정확 일치 매칭 |
| `team/benefits/registry.py` | 수동 등록 보조 데이터와 공고 검토 절차 |
| `team/benefits/gov24.py` | httpx 클라이언트, 캐시, 호출 상한, 오류 분류 |
| `team/benefits/search.py` | 후보 수집, gov24 → 내부 구조 변환, 병합 |
| `team/benefits/engine.py` | 판정·예상액 (네트워크·AI 없음) |
| `team/benefits/routes.py` | `/api/benefits` |
| `team/routes.py` | `team_router`(/api/team)와 benefits 라우터 포함 (main.py 수정 없음) |

## 결정

- 보조 데이터는 SQLite 테이블이 아니라 Python 모듈로 둔다. 배포 스크립트는 `backend/app` 아래 `.py`만 올리고(JSON 불가), 한 번 만든 테이블은 컬럼 변경이 막힌다. 공고 검토 결과를 Git 리뷰로 남기는 편이 맞다. 운영 중 관리자 입력이 필요해지면 그때 테이블을 검토한다.
- 캐시는 프로세스 메모리. Redis 금지 규칙과 단일 서버 구성에 맞춘다. 재시작하면 비워진다.
- 판정 근거의 확인 여부를 조건마다 `rule_confirmed`로 남긴다. 검증된 출처(공고 검토 완료 또는 API 구조화 필드)의 조건만 `ineligible`을 만든다.
- 연령 기준일이 공고에 없으면 신청일·여행 시작일·연 나이를 모두 계산해, 결과가 같을 때만 판정한다.
- 사전 신청 기한은 "여행 시작일 − N일(당일 포함)". 전체 여행 시작과 해당 지역 방문 시작이 다르고 결과가 갈리면 `needs_verification`.
- 정산 기한은 해당 지역 마지막 방문일 + N일로 계산하고 공고 확인 대상으로 둔다.

## 오류 처리

| 상황 | `sources[0].status` | `outcome`(결과 없을 때) |
| --- | --- | --- |
| 키 미설정 | `not_configured` | `source_unavailable` |
| 401/403, 429, 5xx, 타임아웃, 연결 실패, JSON 오류 | `error` (`auth_error`, `rate_limited`, `upstream_error`, `timeout`, `network_error`, `bad_response`) | `source_unavailable` |
| 일부 검색어 실패·페이지 상한·상세 조회 실패 | `partial` | `no_match_in_scope` + 범위 안내 |
| 빈 응답 | `ok`, `records_seen: 0` | `no_match_in_scope` |
