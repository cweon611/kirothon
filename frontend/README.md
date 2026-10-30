# 갈랑가? 프론트

팀 확인용: https://kirothon-team-review-20261030.vercel.app

- 첫 화면 전체를 채우는 광주 5개 구·전남 22개 시군 여행지도, 드래그 새총, 지도 위 지역 선택 메뉴
- 여행일 기준 지역 축제 추천, 공식 출처와 종료·미확인 상태 표시
- 여행 혜택 목록·비교, 일정 초안, 준비 체크리스트
- 사진·영수증 정리 및 HTML 정리본 다운로드

## 로컬 실행

Node 24와 프로젝트 잠금 파일을 사용한다. 이 폴더에서:

```powershell
npm ci
$env:KIROTHON_API_TARGET = 'http://127.0.0.1:8001'
npm run dev -- --port 5174
```

기본 API 프록시는 `http://127.0.0.1:8000`이다. 지역 선택은 API 없이도 가능하다.
혜택·축제 조회에는 아래 백엔드 API가 필요하며, 해당 백엔드 구현과 DB는 이 프론트 커밋에 포함하지 않는다.

- `GET /api/team/benefits?limit=100` → `{ items: Benefit[] }`
- `GET /api/team/festivals?region=화순군` → `{ items: Festival[] }`
- 응답 타입: `src/lib/benefits.ts`, `src/lib/festivals.ts`

`VITE_REVIEW_PREVIEW=true`로 빌드하면 API 대신 `/review-data/benefits.json`과
`/review-data/festivals.json`의 수집 스냅샷을 사용한다. 위 Vercel 미리보기에는 2026-10-30
공개 데이터 스냅샷을 별도 제공했다. 일반 로컬 실행에서는 이 환경변수를 설정하지 않는다.

## 검증

```powershell
npm run build
node --test tests/*.test.mjs
```

사진·영수증은 현재 탭의 메모리에만 보관하고 서버로 업로드하지 않는다. 새로고침하면 사라지므로
정리본을 먼저 내려받아야 한다. OCR·공식 서류 제출·환급 자격 판정은 프론트 기능에 포함되지 않는다.
지도 출처와 가공 내역은 `src/data/MAP-SOURCES.md`를 참고한다.
