# 요구사항 — 여행 지원제도 확인 (백엔드)

범위: 여행 일정·사용자 조건으로 지원제도를 찾고 확인된 조건만 비교해 판정한다.
제외: 대체 지역 추천, 여행코스 생성, 실제 신청 제출, 화면(프론트 담당 별도), 자유 형식 일정 해석(기존 기능 없음).

## R1. 입력

1. THE SYSTEM SHALL 출발지와 주민등록상 거주지를 별도 필드로 받고, 거주지 판정에는 거주지만 쓴다.
2. THE SYSTEM SHALL 여행 시작·종료일, 지역별 방문 일정(날짜·숙박 수·장소·항목별 예상 지출), 인원, 생년월일 또는 나이, 가족·동일 주소 여부, 과거 참여 사업 ID를 구조화된 JSON으로 받는다.
3. IF 판정에 필요한 사용자 정보가 없으면, THEN THE SYSTEM SHALL 추측하지 않고 `missing_fields`로 반환한다.

## R2. 지원제도 조회

1. THE SYSTEM SHALL 행정안전부 공공서비스(혜택) API(gov24 v3)를 공식 Swagger에 있는 오퍼레이션·파라미터로만 호출한다.
2. THE SYSTEM SHALL API에 없는 사업·조건은 공식 공고 검토용 보조 데이터로 관리하고, 응답에서 출처(`data_origin`, `source_type`, `verification_status`)를 구분한다.
3. WHEN API와 보조 데이터가 다르면, THE SYSTEM SHALL 두 값을 모두 `conflicts`에 보존하고 `needs_verification`으로 판정한다.
4. THE SYSTEM SHALL 관광지 정보 API를 지원금 자격 근거로 쓰지 않는다.

## R3. 판정

1. THE SYSTEM SHALL AI 없이 규칙으로 `potentially_eligible` / `ineligible` / `needs_verification`을 정한다.
2. THE SYSTEM SHALL 제도 조건 `null`을 "제한 없음"이나 "0원"으로 해석하지 않는다.
3. THE SYSTEM SHALL 접수 기간, 사전 신청 기한, 여행 인정 기간을 따로 판정하고, 접수가 끝난 제도는 `can_apply_now: false`로 표시한다.
4. THE SYSTEM SHALL 결과 없음을 `no_match_in_scope` / `source_unavailable` / `insufficient_information`으로 구분하고 "지원제도 없음"으로 단정하지 않는다.

## R4. 예상 지원액

1. THE SYSTEM SHALL 인정 지출, 최소 소비액, 상한 구간, 숙박 1박 한도, 절사를 반영하고 전체 예산에 환급률을 바로 곱하지 않는다.
2. IF 계산 조건이 부족하면, THEN THE SYSTEM SHALL 금액을 `null`로 하고 이유를 반환한다.
3. THE SYSTEM SHALL 현금 환급·지역상품권·현장 할인을 구분하고, 중복 적용이 확인되지 않은 혜택은 합산하지 않는다.

## R5. 외부 호출·보안

1. THE SYSTEM SHALL 인증키를 서버 환경변수에서만 읽고 코드·응답·로그·문서에 넣지 않는다.
2. THE SYSTEM SHALL 타임아웃, 페이지 처리, 캐시, 호출 상한, 오류 코드 분류를 적용한다.
3. IF 키가 없거나 호출이 실패하면, THEN THE SYSTEM SHALL 그 상태를 `sources`에 표시하고 예시 데이터로 성공을 가장하지 않는다.
4. THE SYSTEM SHALL 사용자 입력을 저장하지 않는다.
