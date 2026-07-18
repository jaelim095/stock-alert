# 셋업 가이드 — 사용자가 직접 해야 하는 준비 작업

봇을 돌리기 전에 아래 1~4번(외부 서비스 키 발급)과 5~9번(로컬 설치·구동)을 순서대로 진행한다.
전체 소요시간은 처음 하는 기준으로 1.5~2시간 정도.

목차
1. 한국투자증권 Open API 신청 (30분 + 계좌 없으면 별도)
2. 카카오톡 나에게 보내기 설정 (20분)
3. 구글시트 + 서비스 계정 (20분)
4. Gmail 앱 비밀번호 (5분)
5. 로컬 설치와 .env 작성 (10분)
6. 시트 초기화 (1분)
7. 1회 실행 테스트 (5분)
8. 상시 구동 등록 — launchd (5분)
9. 맥 잠자기 방지 (5분)
10. 문제 해결

---

## 1. 한국투자증권 Open API 신청 (약 30분)

계좌가 이미 있으므로 신청만 하면 된다. 없다면 비대면 계좌 개설부터(앱에서 20분).

1. 한국투자증권 홈페이지 로그인 → 메뉴에서 `트레이딩 > Open API > KIS Developers` 이동
2. Open API 서비스 신청 → 실전투자용 앱키(App Key)/앱시크릿(App Secret) 발급
3. 모의투자도 신청한다. 먼저 모의투자 서비스에 가입한 뒤, 모의투자용 앱키/앱시크릿을 별도로 발급받는다. 처음에는 모의 키로 테스트할 것이므로 필수.
4. 발급받은 키 4개(실전 키/시크릿, 모의 키/시크릿)를 안전한 곳에 보관한다. 화면을 벗어나면 시크릿은 다시 볼 수 없는 경우가 있으니 그 자리에서 복사.

주의: KIS Developers 포털(apiportal.koreainvestment.com)의 공지사항에서
2026-03-20 게시된 "[중요] 신규 고객 초당 호출 제한 안내" 본문을 꼭 읽어볼 것.
신규 가입자에게 낮은 호출 한도가 적용될 수 있다. 이 봇은 5분 주기 소량 호출이라 보통 문제없지만, 한도 수치는 확인해두는 게 좋다.

발급된 키는 5번 단계에서 `.env`의 `KIS_APP_KEY`, `KIS_APP_SECRET`에 넣는다.
계좌번호(앞 8자리-뒤 2자리)는 `KIS_ACCOUNT_NO`에 넣는다. 예: `12345678-01`

## 2. 카카오톡 나에게 보내기 설정 (약 20분)

내 카카오톡으로 알림을 보내기 위한 설정. 심사 없이 개인 앱으로 가능하다.

1. https://developers.kakao.com 접속, 카카오 계정으로 로그인
2. `내 애플리케이션 > 애플리케이션 추가하기` → 앱 이름 예: `stock-alert` (아무거나 가능)
3. 만든 앱 선택 → `앱 키` 메뉴에서 REST API 키 복사 → `.env`의 `KAKAO_REST_API_KEY`에 사용
4. `제품 설정 > 카카오 로그인` → 활성화 ON
5. Redirect URI에 `http://localhost:8080` 등록 — 콘솔 개편 후 위치는 `앱 > 플랫폼 키`의
   REST API 키 섹션 안 "리다이렉트 URI" 영역이다 (끝에 `/` 붙이지 말 것, KOE006 원인)
6. `제품 설정 > 카카오 로그인 > 동의항목` → "카카오톡 메시지 전송(talk_message)" 을 선택 동의로 설정.
   반드시 8번(브라우저 로그인) 전에 끝낼 것 — 동의항목 설정 전에 로그인하면 메시지 권한 없이
   앱만 연결되고, 발송 시 403(-402 insufficient scopes)이 난다. 그 경우 다시 로그인해 추가 동의하면 된다
7. `제품 설정 > 카카오 로그인 > 보안`에서 Client Secret을 활성화했다면 그 값을 `.env`의
   `KAKAO_CLIENT_SECRET`에 넣는다 (활성화 상태에서 이 값 없이 토큰 요청하면 KOE010 에러)

이제 최초 1회 토큰을 발급받는다. 이 과정만 브라우저가 필요하고, 이후에는 봇이 자동 갱신한다.

8. 브라우저 주소창에 아래 URL을 넣는다 (REST_API_KEY 부분 교체):

```
https://kauth.kakao.com/oauth/authorize?client_id=REST_API_KEY&redirect_uri=http://localhost:8080&response_type=code&scope=talk_message
```

   동의 화면에 "카카오톡 메시지 전송" 체크가 보이는지 확인하고 동의한다.
9. 동의하고 계속하기를 누르면 `http://localhost:8080/?code=XXXX...` 로 이동하며 "연결할 수 없음" 페이지가 뜬다. 정상이다. 주소창에서 `code=` 뒤의 값을 복사한다.
   (코드를 손으로 옮기다 글자를 잘못 읽으면 KOE320이 난다. 실수를 피하려면 8080 포트에
   임시 수신 서버를 띄워 자동으로 받는 방법도 있다 — 최초 세팅 때 그렇게 진행했다)
10. 터미널에서 인가 코드를 토큰으로 교환한다 (코드는 발급 후 몇 분 안에 1회만 사용 가능,
    Client Secret 활성화 시 `-d client_secret=값` 줄 추가):

```
curl -X POST https://kauth.kakao.com/oauth/token \
  -d grant_type=authorization_code \
  -d client_id=REST_API_KEY \
  -d client_secret=CLIENT_SECRET값_활성화시에만 \
  -d redirect_uri=http://localhost:8080 \
  -d code=복사한_코드
```

11. 응답 JSON의 access_token과 refresh_token을 `data/kakao_tokens.json` 파일로 저장한다:

```
{
  "access_token": "응답의 access_token 값",
  "refresh_token": "응답의 refresh_token 값"
}
```

```
mkdir -p data && vi data/kakao_tokens.json   # 위 내용 붙여넣기
```

참고: access token은 12시간, refresh token은 60일 유효하다.
봇이 돌아가는 동안에는 자동으로 갱신하며 파일도 알아서 덮어쓴다.
단, 봇이 2개월 이상 꺼져 있었다면 refresh token이 만료되므로 8~11번을 다시 하면 된다.
그 경우 봇이 이메일로 "[stock-alert] 카카오 재로그인 필요" 경고를 보내준다.

## 3. 구글시트 + 서비스 계정 (약 20분)

봇이 사람 로그인 없이 시트에 쓰게 하려면 서비스 계정이 필요하다.

1. https://console.cloud.google.com 접속 → 새 프로젝트 생성 (이름 예: stock-alert)
2. `API 및 서비스 > 라이브러리`에서 Google Sheets API 검색 → 사용 설정. 같은 방법으로 Google Drive API도 사용 설정
3. `API 및 서비스 > 사용자 인증 정보 > 사용자 인증 정보 만들기 > 서비스 계정` → 이름 입력 후 생성 (역할은 비워도 됨)
4. 만든 서비스 계정 클릭 → `키` 탭 → `키 추가 > 새 키 만들기 > JSON` → 다운로드
5. 다운로드한 파일을 프로젝트로 옮긴다:

```
mkdir -p secrets
mv ~/Downloads/stock-alert-*.json secrets/service_account.json
```

6. https://sheets.google.com 에서 새 스프레드시트를 만든다 (이름 예: 주식 매매기록)
7. 시트 우측 상단 `공유` → 서비스 계정 이메일(`xxx@프로젝트ID.iam.gserviceaccount.com`, JSON 파일 안 client_email 값)을 편집자 권한으로 추가

이 7번 공유를 빼먹는 것이 가장 흔한 실수다. 공유하지 않으면 봇이 시트를 찾지 못한다.

8. 시트 URL에서 SHEET_ID를 복사한다. `/d/` 와 `/edit` 사이 문자열이다:

```
https://docs.google.com/spreadsheets/d/1AbCdEfGh.../edit   ← 1AbCdEfGh... 부분
```

## 4. Gmail 앱 비밀번호 (약 5분)

1. https://myaccount.google.com → 보안 → 2단계 인증이 꺼져 있으면 켠다
2. https://myaccount.google.com/apppasswords 접속 → 앱 이름 입력 (예: stock-alert) → 생성
3. 표시되는 16자리 비밀번호를 복사 → `.env`의 `GMAIL_APP_PASSWORD`에 사용 (공백 제거)

## 5. 로컬 설치와 .env 작성 (약 10분)

```
cd ~/stock-alert
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

`.env`를 열어 1~4번에서 준비한 값을 채운다.
처음에는 `KIS_ENV=vps`(모의투자) + 모의투자용 앱키로 시작하는 것을 권장한다.
모의 계좌에서 미국 주식을 한두 건 사보고 봇이 잘 기록하는지 확인한 뒤 실전으로 바꾼다.

감시 종목 임계값(기본 10%)을 바꾸고 싶으면 `DEFAULT_DROP_PCT`, `DEFAULT_RISE_PCT`를 수정한다.
종목별로 다르게 하려면 나중에 시트의 설정 탭에서 조정하면 된다.

## 6. 시트 초기화 (1분)

```
.venv/bin/python scripts/init_sheet.py
```

시트에 거래내역 / 활성감시 / 알림로그 / 설정 4개 탭과 헤더가 생긴다.
끝나면 시트를 열어 설정 탭에 감시할 종목을 입력한다. 예:

| 종목코드 | 거래소 | 하락임계% | 상승임계% | 감시 | 메모 |
|---|---|---|---|---|---|
| TSLA | NAS | | | Y | |
| PLTR | NYS | 15 | 10 | Y | 변동 큰 종목이라 15% |

거래소는 NAS(나스닥) / NYS(뉴욕) / AMS(아멕스). 임계값을 비우면 .env 기본값을 쓴다.

## 7. 1회 실행 테스트 (약 5분)

```
.venv/bin/python -m src.main --once
```

확인 포인트:
- 에러 없이 한 사이클이 끝나는지
- 최근 체결이 있다면 거래내역 탭에 행이 생기고, 활성감시 탭에 lot이 생기는지
- 알림 조건을 이미 충족한 lot이 있으면 카카오톡과 메일이 실제로 오는지

이 단계에서 KIS 응답 필드명이 예상과 달라 에러가 날 수 있다 (코드가 실계정 없이 작성된 초안이라).
그 경우 에러 메시지를 Claude에게 보여주면 바로 보정할 수 있다.

## 8. 상시 구동 등록 — launchd (약 5분)

맥 재부팅 후에도 자동 시작되고, 죽으면 자동 재시작되게 등록한다.

```
cp deploy/com.jaewon.stock-alert.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.jaewon.stock-alert.plist
```

상태 확인 / 로그:

```
launchctl list | grep stock-alert
tail -f logs/stdout.log
```

중지와 재시작:

```
launchctl bootout gui/$(id -u)/com.jaewon.stock-alert      # 중지(등록 해제)
launchctl kickstart -k gui/$(id -u)/com.jaewon.stock-alert  # 강제 재시작
```

## 9. 맥 잠자기 방지 (약 5분)

미국 정규장은 한국시간 밤 22:30~새벽 5시(서머타임 기준, 겨울은 23:30~6시)다.
맥이 잠들면 봇도 같이 멈추므로 이 설정이 없으면 알림이 오지 않는다.

이 프로젝트는 launchd plist가 `caffeinate -i`로 봇을 실행한다. 봇이 도는 동안에만
유휴 잠자기를 막고, 봇을 끄면 원래 잠자기 설정으로 돌아온다. sudo도 필요 없다.
확인:

```
pmset -g assertions | grep caffeinate
```

("asserting on behalf of ... python" 이 보이면 잠자기 방지가 걸린 것)

주의:
- 전원 어댑터를 항상 연결해둔다 (배터리만으로는 macOS가 잠들 수 있음).
- 노트북 뚜껑을 닫으면 caffeinate로도 못 막고 잠든다. 밤새 돌리려면 뚜껑을 열어두거나,
  외장 모니터를 연결한 클램셸 모드로 쓴다. 디스플레이는 꺼져도 되고 시스템만 깨어 있으면 된다.

(caffeinate 방식 대신 시스템 전체 잠자기를 끄고 싶으면 `sudo pmset -c sleep 0 disksleep 0`)

## 10. 문제 해결

- `EGW00133` (토큰 발급 실패): 접근토큰 재발급은 1분당 1회 제한이다. 1분 기다렸다 다시 실행. 봇은 토큰을 data/kis_token.json에 캐싱하므로 평소에는 발생하지 않는다. 여러 프로그램이 같은 앱키를 쓰면 충돌하니 주의.
- `EGW00201` (초당 호출 초과): 감시 종목이 아주 많을 때 발생 가능. POLL_INTERVAL_MIN을 늘리거나 종목 수를 줄인다. 신규 고객 한도(1번 공지)도 확인.
- `SpreadsheetNotFound` 또는 `PERMISSION_DENIED` (gspread): 3-7번 시트 공유 누락이 원인의 대부분. 서비스 계정 이메일에 편집자로 공유했는지, SHEET_ID가 맞는지 확인.
- 카카오 401 에러: access token 만료인데 갱신도 실패한 상태. data/kakao_tokens.json 이 있는지, 2개월 이상 봇을 꺼두지 않았는지 확인. 만료됐으면 2단계 7~10번 재수행.
- 시세가 0으로 나옴: 장외 시간이거나 거래소 코드(NAS/NYS/AMS)가 틀린 경우. 설정 탭의 거래소 값을 확인.
