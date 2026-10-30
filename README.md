# 전남대학교 Kirothon 공통 스타터 r2

## 관광 추천 MVP 구현 (2026-10-30)

현재 기본 화면은 광주 도심 관광 추천 서비스입니다. 기존 Record/AI API와 데이터베이스 스키마는 유지했습니다.

- 수동 시작점/좌표 입력, 요청 시 현재 위치, 지원 구역 검증, 3/5km 선택.
- 실제 TourAPI의 관광명소·문화공간·야외활동을 서버에서 필터링하고 거리로 상위 5개 추천.
- 장소 상세/출처/갱신일/운영정보, OpenStreetMap 지도와 Kakao 외부 길찾기.
- 장소 선택·길찾기·방문 완료·건너뛰기를 분리. 방문 완료 후 GPS 실패 시 사용자 확인 후 직전 방문지 사용.
- 탭 세션의 방문·제외 목록 유지 및 초기화. 정밀 위치는 세션 저장소와 분석 DB에 저장하지 않음.
- 별도 tourism-events.sqlite3에 익명 이벤트를 기록하고 쓰기 시 30일 경과 기록 삭제.
- 외부 장애는 오류/재시도를 표시. 관광 기본정보는 1시간 캐시, 장애 시 최대 24시간 캐시 사용을 표시. 시연용 허구 데이터로 대체하지 않음.

### 실행

기존 설치 이후 프로젝트 루트에서 PowerShell 두 창을 사용합니다.

```powershell
.\scripts\dev-backend.ps1
```

```powershell
.\scripts\dev-frontend.ps1
```

접속: http://127.0.0.1:5173. 이번 검증은 설치된 Python 3.13.12와 Node 24.18.0에서 수행했습니다. 스타터의 최초 setup-local.ps1은 여전히 Python 3.12를 요구합니다. 기존 버전 정책과 잠금 파일은 변경하지 않았습니다.

서버는 TOUR_API_KEY 환경변수 또는 backend/.env.local의 동일 변수만 읽습니다. 제공된 키는 로컬에서 Git 제외 파일에 저장했습니다. 다른 환경에서는 backend/.env.example을 참고해 설정하세요. VITE_ 접두사나 클라이언트 코드에 키를 넣지 마세요. 서버 배포 시 키는 별도 환경변수로 설정해야 합니다.

### 데이터와 보강 자료

공식 명세: [국문 관광정보](https://www.data.go.kr/data/15101578/openapi.do), [중심 관광지](https://www.data.go.kr/data/15128559/openapi.do), [연관 관광지](https://www.data.go.kr/data/15128560/openapi.do).

위치 기반 원천 조회에는 사용자 위치 대신 고정된 시연 중심점을 사용합니다. 지원 경계는 북위 35.115~35.180, 동경 126.885~126.955의 임시 사각 구역으로 행정경계가 아닙니다. 목록 요청은 최대 500건이며 잘린 결과에는 제한을 표시합니다. 이미지 이용허락 유형을 별도 검수하지 않았으므로 사진 대신 자체 도형을 사용합니다.

중심·연관 통계는 추천 요청과 분리해서 수집합니다. 확인된 원천 제공월인 2025년 4월 자료를 대상으로 실행했습니다. 최신 통계라고 표시하지 않습니다.

```powershell
cd backend
.\.venv\Scripts\python.exe -m app.team.sync_tourism --month 202504
```

동구·남구의 중심 123건, 연관 423건을 수집했습니다. 현재 관광 후보와 이름 정규화 일치 + 250m 이내 좌표 + 단일 후보 조건으로 확인된 매칭은 0건입니다. 임의로 합치지 않았습니다. 보강 정보가 검증된 경우 상세에 출처/기간/순위를 표시할 수 있으며, 현재 랭킹은 거리 100%입니다. 중심 순위를 만족도/인기도로 바꾸거나 연관 관계를 실제 순차 방문으로 설명하지 않습니다. 보강 캐시는 .local-data/tourism-enrichment.json에 저장됩니다.

운영시간은 명시된 연중무휴와 단일 당일 시간구간만 해석합니다. 계절·요일·공휴일·야간 영업·임시 휴무 등은 확인 필요입니다. 상세에서 방문 불가로 확인되면 현재 목록과 이후 추천에서 제외합니다. 아직 조회하지 않은 운영정보는 확인 필요이며 개장으로 단정하지 않습니다.

### 검증 및 남은 배포 조건

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
cd ../frontend
npm run build
```

추천 개수 0/1/2/5, 중복·방문·제외·지역 필터, 결정적 동점 정렬, 보수적인 운영시간 해석, 데이터 매칭, API 장애/캐시 대체, 분석 이벤트 구분 및 좌표 거부를 테스트합니다. 실제 TourAPI 목록/상세와 두 보강 API의 인증·응답을 확인했습니다. 모바일 브라우저에서 목록·지도·상세·선택·방문 후 다음 추천을 확인했습니다.

정식 배포 전 지원 경계와 장소 매칭을 검수하고, 외부 지도 이용 조건/트래픽 정책과 개인정보 안내를 확정해야 합니다. 분석 데이터는 사용자 자기보고이며 사용자 테스트나 성능 목표 달성을 입증하지 않습니다. 자동 방문 감지, 예약, 학습 모델, 전국 최적화는 구현 범위에 포함하지 않습니다.

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
