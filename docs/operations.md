# 설치·데이터 준비·운영 실행 안내

API 키와 DB는 Git·배포 묶음에 넣지 않는다. 키는 환경변수(로컬: `backend/.env`, 서버: `/home/ubuntu/kirothon-config/team.env`)로만 전달한다.

## 1. 환경변수

| 이름 | 필수 | 용도 |
|---|---|---|
| `TOURAPI_SERVICE_KEY` | 관광 수집에 필수 | 공공데이터포털 Decoding 키. 관광공사 국문 관광정보(KorService2)·중심 관광지·연관 관광지·관광지 표준데이터. 비우면 아래 키를 씀 |
| `KIROTHON_DATA_GO_KR_SERVICE_KEY` | 공공서비스 수집에 필수 | 행정안전부 공공서비스(혜택) API Decoding 키 |
| `KIROTHON_DB_PATH` | 권장 | SQLite 경로. 기본 `~/kirothon-data/records.sqlite3`(코드 폴더 밖). 관광 코드 파일 `tourism-codes.json`도 같은 폴더에 저장 |
| `KIROTHON_AI_MODE` | 선택 | 서버 `bedrock`(기본, EC2 역할), 로컬 `mock` |
| `KIROTHON_BENEFIT_SYNC_MODE` | 선택 | `auto`(bedrock일 때만 켬) / `on` / `off`. 지원제도 주기 갱신 스케줄러 |
| `KIROTHON_BENEFIT_SYNC_TOUR50_SECONDS` / `..._GOV24_SECONDS` | 선택 | 갱신 주기(기본 30분 / 6시간) |
| `KIROTHON_GOV24_DAILY_CALL_LIMIT` | 선택 | 공공서비스 API 일일 호출 상한(기본 9000) |
| `KIROTHON_FRONTEND_DIST` | 선택 | 지정하면 API 프로세스가 빌드된 프론트(`frontend/dist`)를 같은 주소에서 제공. nginx가 있는 서버는 쓰지 않음 |
| `TEAM_TODAY` | 시연용 | 기준일 고정(YYYY-MM-DD) |

반값여행 현황 페이지(kto_tour50) 수집은 키가 필요 없다.

## 2. 새 환경 설치 (Windows, 로컬·단일 PC 운영)

```powershell
.\scripts\setup-local.ps1                       # Python 3.12 / Node 24 확인, .venv 생성, 잠금 파일로 설치
Copy-Item backend\.env.example backend\.env     # 키 입력 (git 제외 파일)
```

### 개발 실행
```powershell
.\scripts\prepare-data.ps1                      # .local-data DB에 관광·축제·지원제도 수집 + 준비 상태 보고
.\scripts\dev-backend.ps1                       # 창 1
.\scripts\dev-frontend.ps1                      # 창 2 → http://127.0.0.1:5173 (Vite 개발 프록시 사용)
```

### 운영 방식 실행 (개발 프록시 없음)
```powershell
.\scripts\prepare-data.ps1 -DataDir $HOME\kirothon-data   # 최초 1회
.\scripts\run-production.ps1                              # 프론트 빌드 → API가 dist와 /api를 같은 주소로 제공
# → http://127.0.0.1:8000   (DB: $HOME\kirothon-data\records.sqlite3, 코드 폴더를 지우거나 바꿔도 유지)
```
`run-production.ps1`은 `--reload` 없이 실행하고, 지원제도 주기 갱신(`KIROTHON_BENEFIT_SYNC_MODE=on`)을 켠다.
시작할 때 관광 전체 수집은 하지 않는다.

## 3. 데이터 준비·갱신

`prepare-data.ps1`(Windows)·`ops/team-data-sync.sh`(서버)가 같은 기존 수집 로직을 순서대로 실행한다.

1. 관광 수집 `python -m app.team.sync_tourism`: 시군구 코드, 관광지·음식점·숙소, 관광지 표준데이터, 축제(오늘 120일 전부터 시작한 행사 포함), 중심·연관 관광지, 이름 대조, 상세
2. 지원제도 수집 `python -m app.team.benefits.cli sync`: 반값여행 현황 페이지 + 공공서비스 API
3. 준비 상태 `python -m app.team.data_readiness`: 시군구별 관광지·음식점·숙소 수, 일정 생성 가능 여부, 축제·지원제도 출처별 상태·마지막 정상 수집 시각. 27개 시군구 모두 관광지가 있으면 종료 코드 0

### 안전장치(기존 수집 로직에 있는 것)
- 중복 실행 방지: 관광 수집은 DB의 실행 중 표시(2시간 안에 시작된 실행이 있으면 거부), 지원제도는 출처별 잠금+DB 임대(15분). 서버 스크립트는 `flock`으로 한 번 더 막는다.
- 호출 제한: 관광 API 호출 간격 0.2초·재시도 2회·인증/한도 오류 시 해당 단계 중단, 공공서비스 API 일일 호출 상한(기본 9000/일), 상세 수집 상한.
- 실패 시: 실패한 시군구·출처의 기존 행을 지우지 않는다. 빈 결과는 정상 수집으로 기록하지 않는다. 실행 결과는 `tourism_sync_run`, `benefit_sync_run`, `benefit_sync_state`에 남고 화면에는 '이전 자료 사용 중'으로 표시된다.

### 갱신 주기
| 데이터 | 방법 | 주기 |
|---|---|---|
| 반값여행 현황·공공서비스 | API 프로세스 안 스케줄러(`KIROTHON_BENEFIT_SYNC_MODE`) | 30분 / 6시간, 마지막 시도 시각 기준이라 재시작해도 몰아서 수집하지 않음 |
| 축제 | 서버: `kirothon-festival-sync.timer` / Windows: 작업 스케줄러 | 매일 |
| 관광지·중심/연관 관광지(+지원제도) | 서버: `kirothon-tourism-sync.timer` / Windows: 작업 스케줄러 | 매주 |

Windows 작업 스케줄러 예(등록은 사용자가 직접):
```powershell
schtasks /Create /TN kirothon-festivals /SC DAILY /ST 05:10 /TR "powershell -NoProfile -ExecutionPolicy Bypass -File C:\path\kirothon\scripts\prepare-data.ps1 -DataDir C:\Users\me\kirothon-data -TourismSteps codes,festivals -SkipBenefits"
schtasks /Create /TN kirothon-weekly /SC WEEKLY /D MON /ST 04:20 /TR "powershell -NoProfile -ExecutionPolicy Bypass -File C:\path\kirothon\scripts\prepare-data.ps1 -DataDir C:\Users\me\kirothon-data"
```

## 4. 기존 서버(EC2) 배포 구조

코드 배포는 기존 `scripts/deploy.ps1 -Mode Check|Deploy` 그대로다(`backend/app`의 .py, `frontend/src·public`, 설정 파일만 전송, 서버에서 빌드).

- 프론트: 서버가 `frontend/dist`를 빌드해 `/var/www/kirothon-preview`에 게시하고, nginx(127.0.0.1:8080, Basic Auth)가 정적 파일과 `/api` 프록시(127.0.0.1:8000)를 같은 주소로 제공한다. 프론트는 상대 경로 `/api/...`만 호출하므로 Vite 프록시가 필요 없다. 참고 설정: `ops/nginx-kirothon.conf.example`(기존 설정과 비교만, 인증·포트 변경 금지).
- DB: `/home/ubuntu/kirothon-data/records.sqlite3`(+`tourism-codes.json`). 배포 도구는 이 폴더를 건드리지 않고, 매시간 백업 타이머가 이미 있다. 코드 롤백은 DB를 되돌리지 않는다.
- 키: `/home/ubuntu/kirothon-config/team.env`(권한 600, 배포 대상 폴더 밖). 형식은 `backend/.env.example`과 같다.

### 운영자가 한 번 적용할 것 (배포 도구가 자동으로 하지 않음)
```bash
install -d -m 700 /home/ubuntu/kirothon-config /home/ubuntu/kirothon-tools
if [ ! -e /home/ubuntu/kirothon-config/team.env ]; then install -m 600 /dev/null /home/ubuntu/kirothon-config/team.env; fi  # 기존 키 파일은 보존; 없을 때만 생성 후 키 입력
install -m 755 ops/team-data-sync.sh /home/ubuntu/kirothon-tools/team-data-sync.sh
sudo install -D -m 644 ops/kirothon-api-team-env.conf /etc/systemd/system/kirothon-api.service.d/team-env.conf
sudo install -m 644 ops/kirothon-tourism-sync.{service,timer} ops/kirothon-festival-sync.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl restart kirothon-api.service
sudo systemctl start kirothon-tourism-sync.service          # 최초 전체 수집 1회 (수 분)
sudo systemctl enable --now kirothon-tourism-sync.timer kirothon-festival-sync.timer
```

## 5. 상태 확인

- API: `GET /api/health`, `GET /api/team/meta`(`tourism_data`), `GET /api/benefits/sources`
- 준비 상태: 서버 `ops/team-data-sync.sh status`, Windows `backend\.venv\Scripts\python.exe -m app.team.data_readiness`(같은 `KIROTHON_DB_PATH` 지정)
- 수집 기록: `python -m app.team.benefits.cli status|history`, 서버 `journalctl -u kirothon-tourism-sync.service`
