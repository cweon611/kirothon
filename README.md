# 전남대학교 Kirothon 공통 스타터 r2

## 갈랑가? 프론트

첫 화면은 **광주·전남 새총 여행지도**다. 지도 아래 노란 탄환을 뒤로 당겼다 놓으면,
당긴 반대 방향으로 발사되고 거리는 무작위로 정해진다. 착지점에서 가장 가까운 연결 지역을 고른다. 기존 취향 입력
폼은 제거했다. 광주 5개 구와 전남 22개 시군 전체가 선택 대상이다. 혜택이 없는 지역이나 API 장애 중에도 여행지를 고를 수 있다.

짧은 방향 안내, 다시 당기기, 직접 지역 선택, 키보드 방향키+Enter 발사를 지원한다.
당긴 길이는 비행 거리를 정하지 않는다. 놓을 때 거리와 소폭의 좌우 편차를 무작위로 정하므로 같은 방향도 다른 결과가 나올 수 있다. 지도는 geoBoundaries
공개 경계를 가공한 로컬 SVG로, 출처·라이선스는 `frontend/src/datasets/MAP-SOURCES.md`에 기록했다.
지역 선택 후 여행 정보 수정에서 날짜·여행 유형·인원을 바꿀 수 있다. 혜택 목록·비교,
일정 추천·혜택 상세·증빙 체크리스트는 기존 흐름과 연결된다.
입력과 체크 상태는 탭의 sessionStorage에 보관한다. 여행지 목록은 독립된 27개 지역 카탈로그이며, 혜택 카드만 `/api/team/benefits`를 사용한다.
환급 자격·금액은 미검증 상태를 표시한다. 여행지를 고르면 **일정 추천** 화면에서 여행 조건을 바로 고치고, `POST /api/team/courses`로 만든 지역 내 코스(최대 3개)와 상세 일정·장소 정보를 확인한다. 관광 데이터가 수집되지 않았으면 안내와 기본 시간표를 보여준다.

준비 체크리스트의 **사진·영수증으로 증빙 정리하기**에서 방문 사진·결제 영수증·숙박 증빙을
추가하고 장소·사용일·금액·메모를 작성할 수 있다. 미리보기 후 원본 이미지가 포함된 HTML
정리본을 다운로드한다. 파일을 브라우저에서 열어 인쇄할 수 있다. OCR·공식 신청서 생성·실제
지자체 제출은 연결하지 않았다. 입력한 지출 합계는 환급 예상액이 아니다.

첨부 파일은 서버나 sessionStorage에 저장하지 않고 현재 탭의 메모리에만 보관한다.
단계 이동 시 유지되지만 새로고침·탭 종료 시 사라지므로 정리본을 먼저 다운로드해야 한다.
지역·여행일·여행 유형별로 자료를 분리한다. JPG/PNG/WebP, 파일당 8MB, 최대 12개·총 32MB를 지원한다.

기본 실행은 아래 Windows 스크립트를 사용한다. 다른 앱이 5173/8000을 쓰는 경우:

```powershell
# 백엔드: 프로젝트 루트에서 실행
$env:KIROTHON_DB_PATH = (Resolve-Path .local-data/records.sqlite3).Path
$env:KIROTHON_AI_MODE = 'mock'
Push-Location backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
Pop-Location

# 프론트: 별도 창에서 실행
$env:KIROTHON_API_TARGET = 'http://127.0.0.1:8001'
Push-Location frontend
npm run dev -- --port 5174
Pop-Location
```

프론트 검증: `npm run build` (frontend에서), `node --test frontend/tests/*.test.mjs` (루트에서 Node 24 사용).
Figma 참고: https://www.figma.com/make/iuBglwT6bihXejhQULFX1k/

## 팀 확인용 Vercel 미리보기

https://kirothon-team-review-20261030.vercel.app

본 서버와 분리된 정적 UI 미리보기다. 로그인 없이 열리며, 2026-10-30에 수집한 공개 혜택 7건과
축제 54건의 스냅샷을 사용한다. 새총·전체 27개 지역·날짜별 축제·사진/영수증 정리 흐름을 확인할 수 있다.
실제 신청·서버 업로드·실시간 갱신은 연결하지 않았다. 사진은 브라우저 메모리에만 머문다.
Git 자동 배포는 연결하지 않았고 실제 백엔드·운영 DB·환경변수는 배포하지 않았다.

재생성: `VITE_REVIEW_PREVIEW=true` 환경변수로 frontend를 빌드한 뒤
`python ops/prepare_review_preview.py .local-data/<새 폴더>`를 실행하고 해당 정적 폴더만 Vercel에 배포한다.
일반 빌드는 기존 로컬 API를 사용한다. Vercel의 신규 프로젝트 첫 배포는 플랫폼상 production으로
분류되지만, 이 프로젝트 자체는 팀 UI 확인용이며 기존 공식 서비스와 연결되지 않는다.

## 지역별 축제 추천

여행지 선택 후 **축제·여행 혜택** 화면에서 해당 지역의 축제를 확인한다.
여행일과 겹치는 축제 우선, 다른 일정·종료 행사·일정 미상을 구분한다. 확인된 행사가 없는
지역은 빈 상태와 공식 목록 링크를 제공한다. 7일 지난 수집은 재확인 필요로 표시한다.

- 공식 출처: https://www.mcst.go.kr/site/s_culture/festival/festivalList.jsp
- 2026-10-30 수집: 54건 / 24개 지역. 모든 27개 지역에서 추천 영역을 제공하며 전체 축제의 완전한 목록을 보장하지 않는다.
- DB: `.local-data/records.sqlite3`의 `regional_festival` 신규 테이블.
- API: `GET /api/team/festivals?region=화순군` (광주는 `광주 북구`처럼 정확한 이름).
- 수집: backend에서 `.\.venv\Scripts\python.exe -m app.team.festival_collector --year 2026`.
- 공개 목록의 일정·지역·제목만 수집하며 사진/소개문을 복제하지 않는다. robots 확인, 0.5초 간격, 최대 30페이지/목록, 원본/해시 보관.
- 자동 주기 수집은 설정하지 않았다. 재수집은 기존 ID를 갱신하고 실패 시 캐시를 덮어쓰지 않는다. 과거 기록은 삭제하지 않으며 취소/변경 여부는 방문 전 공식 안내에서 확인한다.
- `/api/team/benefits`는 기존 `refund_program` 표의 읽기 전용 화면 호환 API다. 새 `/api/benefits` 자격 판정 엔진과 별개이며 금액/자격을 추정하지 않는다.

## 여행 혜택 수집 (팀 확장)

대한민국 구석구석 반값여행 공식 HTML에서 광주·전남 지역 카드를 수집한다.
프로젝트 루트에서 다음을 실행한다. Python 3.12 가상환경과 기존 잠금 파일 의존성이 필요하다.

```powershell
Push-Location backend
.\.venv\Scripts\python.exe -m app.team.benefit_collector
Pop-Location
```

- 로컬 DB: `.local-data/records.sqlite3`의 `refund_program`, `benefit_collection` 테이블.
- 확인용 내보내기: `.local-data/refund-programs.json`. 수집 원본·robots.txt·해시는 `.local-data/crawl/`.
- 기존 로컬 백엔드 실행 후 `GET /api/team/benefits`, `GET /api/team/benefits/{id}`로 조회한다.
- 목록은 `region=장흥군`, `limit=50`, `offset=0` 필터·페이지 처리를 지원한다.
- `source_status`는 공식 페이지의 표기다. `status=확인 필요`, `verified_at=null`은 지자체 개별 공고의 조건 검증이 아직 안 됐다는 뜻이다.
- 환급률·한도·자격조건은 임의 추정하지 않는다. 검증 전에는 null이고 자동 환급 계산에 사용할 수 없다.
- 수집 시각과 공고 검증 시각은 별개다. 검증되지 않았거나 검증 후 7일이 지나면 API의 `needs_review=true`가 된다.
- 사이트 지역 코드는 법정동 코드가 아니다. `source_region_code_system`을 확인한다.
- 재실행은 중복 추가하지 않는다. 사실 변경·원문에서 누락 시 검증을 해제하며 기존 기록은 삭제하지 않는다.
- 원본 HTML, DB, JSON은 Git 제외 대상이다. 서버 배포·자동 주기 수집은 별도 작업이다.

현재 범위는 해당 페이지의 지역사랑 휴가지원이다. 무안 별도 사업·섬 반값여행·관광주민증 가맹점 할인 및 공공 API 관광 캐시는 아직 포함하지 않는다.
출처: https://korean.visitkorea.or.kr/dgtourcard/tour50.do

운영진 검증용 후보 버전이다. 학생 공지문이나 완성된 주제 서비스가 아니다.
원본 r1과 1조 운영 서버는 이 패키지를 만들면서 변경하지 않았다.

## 개발 방식

각자 Kiro에서 로컬 소스를 편집하고 로컬 화면·API로 확인한다.
로컬 AI는 표시가 있는 모의 응답이다. 실제 AI 품질 검증은 팀 서버에 배포한 뒤 수행한다.
통합 담당자 한 명이 Git으로 합친 소스를 Check → Deploy하며, 서버의 EC2 IAM 역할로 Bedrock을 호출한다.
PEM은 배포 담당자의 프로젝트 밖에만 둔다. 다른 팀원이 로컬 개발하려고 PEM·AWS 키를 받을 필요는 없다.
Git 저장소·브랜치·권한 연결은 아직 운영진이 별도로 준비해야 한다.

## 유지하는 기술

- Python 3.12 + FastAPI + SQLModel/SQLite + boto3.
- React + Vite + TypeScript + Tailwind CSS 4 + shadcn/ui Nova + Lucide.
- 서버용 backend/requirements.lock, 프론트 package.json 및 package-lock.json은 검증된 r1 그대로다.
- Docker, RDS, Redis, 벡터DB, CI/CD를 추가하지 않았다.

## r2의 변경점

- Vite /api → 로컬 FastAPI 8000 프록시. __dirname 경고를 import.meta.dirname으로 수정.
- POST /api/ai/generate: 기록 생성·저장 없이 AI 호출. 기존 기록 CRUD/AI 경로 유지.
- KIROTHON_AI_MODE=mock: 실제 AWS 호출이 없는 로컬 개발 모드. 기본 서버 모드는 bedrock.
- 공통 API 두 경로 모두 기존 분당 20회/한국시간 하루 600회, 출력 256토큰 제한 유지.
- app/team/models.py와 team/routes.py를 팀별 신규 테이블·API 확장 지점으로 등록.
- 이미 배포된 테이블의 컬럼 변경은 사전 검사/앱 시작 시 중단. 데이터를 지우거나 자동 변환하지 않음.
- ops/deploy.py r2: 배포 전 백엔드 import·기존 DB 컬럼 호환성 검사 추가.
- Windows용 로컬 설치·API 실행·프론트 실행 스크립트 추가.

## Windows 로컬 준비

사전 설치: Python 3.12와 Node.js 24.x. 설치되어 있는지는 먼저 조회한다.
이 스크립트는 Python/Node나 관리자 권한을 자동 설치·요청하지 않는다.

```powershell
py -3.12 --version
node --version
```

압축은 r1과 다른 새 폴더에 푼다. scripts/verify-template.ps1은 받은 원본의 해시를 확인하는 용도다.
코드를 수정한 뒤 이 검사를 실행하면 달라졌다고 나오는 것이 정상이다.
서명/실행 정책 오류가 나면 정책을 끄지 말고 운영진이 해시와 적용 정책부터 확인한다.

최초 설치:

```powershell
.\scripts\setup-local.ps1
```

프로젝트 backend/.venv에만 Python 패키지를 설치하고, 프론트는 npm ci를 사용한다.
requirements.local.lock은 서버 잠금 파일에 uvloop의 Windows 제외 조건과 Windows 전용 colorama의 버전·해시를 반영한 파일이다.
Windows에서는 uvloop를 설치하지 않으며 uvicorn은 기본 asyncio로 동작한다.
서버용 requirements.lock은 바꾸지 않는다.

PowerShell 창 두 개에서 각각 실행:

```powershell
.\scripts\dev-backend.ps1
```

```powershell
.\scripts\dev-frontend.ps1
```

접속: http://127.0.0.1:5173. 로컬 DB는 프로젝트 .local-data/에만 저장한다.

### 로컬 데이터 준비 (일정 추천·축제·지원제도)

1. `backend\.env.example`을 `backend\.env`로 복사하고 공공데이터포털 Decoding 키를 넣는다
   (`TOURAPI_SERVICE_KEY`: 관광공사 국문 관광정보·중심/연관 관광지, `KIROTHON_DATA_GO_KR_SERVICE_KEY`: 공공서비스(혜택)).
   `backend\.env`는 git에 올리지 않는다.
2. 한 번에 준비: `.\scripts\prepare-data.ps1`
   - 1단계 관광 수집(`app.team.sync_tourism`): 관광지·음식점·숙소·축제·중심/연관 관광지
   - 2단계 지원제도 수집(`app.team.benefits.cli sync`): 반값여행 현황 페이지(키 불필요) + 공공서비스 API
   - 3단계 준비 상태 보고(`app.team.data_readiness`): 시군구별 관광지·음식점·숙소 수, 일정 생성 가능 여부, 출처별 마지막 정상 수집 시각
   - 마지막 요약에서 단계별 `ok`/`failed`와 `course_data`(27개 시군구 모두 관광지 보유 여부)를 확인한다. 하나라도 실패하면 종료 코드 1.
   - 기존 데이터는 지우지 않는다. 실패한 출처는 이전 정상 자료를 유지하고, 화면에 '이전 자료 사용 중'으로 표시된다.
3. 상태만 다시 보기: backend 폴더에서 `.\.venv\Scripts\python.exe -m app.team.data_readiness` (dev-backend.ps1과 같은 DB를 보려면 `$env:KIROTHON_DB_PATH`를 `.local-data\records.sqlite3`로 지정).

`prepare-date-data.ps1`은 이전 이름으로 남겨 두었고 같은 준비 명령을 실행한다. 데이터 준비 후 dev-backend.ps1을 다시 시작할 필요는 없다.

운영 방식 실행(개발 프록시 없이 API가 빌드된 화면까지 제공, DB는 코드 폴더 밖 `$HOME\kirothon-data`), 환경변수 전체 목록,
자동 갱신 주기와 서버(systemd·nginx) 적용 방법은 [docs/operations.md](docs/operations.md)에 정리했다.
창을 닫거나 Ctrl+C를 누르면 로컬 개발 프로세스만 종료된다. 서버 서비스는 영향을 받지 않는다.
setup-local.ps1은 버전 확인 후 기존 로컬 의존성 환경을 설치/동기화하므로 본인 작업 복사본에서만 실행한다.

## 주제별 확장

- 화면: frontend/src. 기존 shadcn/ui 컴포넌트를 재사용한다.
- 신규 테이블: backend/app/team/models.py. 신규 API: team/routes.py. 둘 다 main.py에 등록돼 있다.
- 별도의 team 모델 파일을 만들면 team/models.py에서 import해 create_all 전에 등록해야 한다.
- 선택형 Record 예제를 쓰지 않아도 독립 AI API를 활용할 수 있다. 기존 운영 데이터는 자동 삭제하지 않는다.
- models.py의 기본 Record와 database.py의 운영 경로는 보호한다. 팀 주제 모델을 이 파일에 억지로 넣지 않는다.
- 최초의 신규 테이블 생성은 지원하지만, 이미 생성된 컬럼·타입·NULL/PK를 바꾸면 멈춘다.
- 컬럼 검사는 완전한 마이그레이션/제약조건 변경 검증기가 아니다. 인덱스·고유/FK/기본값 변경도 멘토 검토가 필요하다.
- 필요하면 멘토가 백업 후 명시적인 데이터 보존 마이그레이션을 검토한다. DB 삭제로 우회하지 않는다.
- 새 라이브러리와 잠금 파일 변경은 멘토가 별도로 준비한다.

독립 AI 예시 요청 형식:

```json
{"text":"사용자 입력", "instruction":"한국어로 간결하게 정리해줘."}
```

model_id 생략 시 Haiku 4.5가 기본값이다. 모의 응답에는 mode=mock이 명시된다.
API는 입력·결과를 Record에 저장하지 않지만 별도 DB에 호출 횟수는 기록한다.
서버의 AWS 제공자 처리·보관까지 무저장을 보장하는 의미는 아니다.

## 서버 배포

Windows SSH/SCP 배포·롤백 방식은 r1과 같다. PEM은 소스 폴더 밖에 둔다.

```powershell
.\scripts\deploy.ps1 -ServerHost TEAM_IP -KeyPath PEM_PATH -Mode Check
.\scripts\deploy.ps1 -ServerHost TEAM_IP -KeyPath PEM_PATH -Mode Deploy
```

위의 TEAM_IP/PEM_PATH는 실제 값으로 바꿔야 한다. 인증을 끄거나 호스트키 검증을 건너뛰지 않는다.
DB·.env·키·로컬 데이터·설치 폴더는 업로드하지 않는다. 서버 빌드 후 API를 잠깐 재시작한다.
코드 롤백은 DB 복원이 아니다. 새로 생성된 테이블이나 이미 저장한 레코드는 자동 삭제하지 않는다.

서버의 ops/deploy.py r2 적용은 운영자용 별도 단계다. 기존 서버 도구를 이 ZIP만으로 자동 갱신하지 않는다.
운영자 지침은 ops/README.md를 참고한다. 지금은 1조 서버가 자동으로 r2로 바뀐 상태가 아니다.

## 검증과 남은 단계

Linux 격리 환경에서 자동 테스트, 실제 프론트 빌드, Vite↔FastAPI HTTP 통합,
모의 AI·기록 저장·프로세스 재시작 후 유지, 팀 전용 모델/API 추가를 검사한다.
실제 AWS 호출을 이 패키지 검사에서 재실행하지 않는다.

- r1 Windows Check/Deploy/Rollback와 1조 웹·데이터 유지는 운영자 실행으로 확인됨.
- r2 Windows 로컬 설치·실행, r2 1조 실제 배포·Bedrock 호출, 2조 신규 설치는 아직 별도 검증 필요.
- 2~6조는 서로 다른 리전이다. EC2 리전, Bedrock 호출 리전, S3 버킷 리전을 구분한다.
- KIROTHON_BEDROCK_REGION 기본값은 기존 검증값 ap-northeast-1. 다른 리전으로 임의 치환하지 않는다.
- 다른 허용 모델 5개는 실제 호출 검증 완료로 간주하지 않는다.
- 외부 공개/HTTPS와 S3 자동 백업은 이 버전에서 추가하지 않는다.
