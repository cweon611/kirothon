# 작업

- [x] 1. 공식 Swagger로 gov24 v3 엔드포인트·파라미터·필드 확인, 키 없는 호출 응답 확인
- [x] 2. 제도 데이터 구조·요청·응답 모델 (`schemas.py`)
- [x] 3. 보조 데이터 등록 구조와 문서 기반 4건(미검증 표시) (`registry.py`)
- [x] 4. gov24 클라이언트: 타임아웃, 페이지 반복, 캐시, 일일 호출 상한, 오류 분류 (`gov24.py`)
- [x] 5. 후보 수집·병합·충돌 기록 (`search.py`)
- [x] 6. 판정·예상액 엔진 (`engine.py`)
- [x] 7. `/api/benefits/check`, `/api/benefits/{id}` (`routes.py`, `team/routes.py`)
- [x] 8. 테스트 52건 (`tests/test_benefits.py`, 외부 API는 MockTransport)
- [ ] 9. 서버에 인증키 설정 후 실제 호출로 여행·관광 사업 수록 여부와 필드 값 확인
- [ ] 10. 무안·장흥·섬·상반기 휴가지원 공식 공고 검토 후 `registry.py` 갱신(verified, URL, 접수 상태, 확인 시각)
- [ ] 11. 실제 응답에서 gov24 서비스ID를 찾으면 보조 데이터 `external_service_id` 연결
