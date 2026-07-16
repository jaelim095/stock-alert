# 사전조사 결과 — 한투 오픈API · 알림 채널 · 오픈소스

조사일: 2026-07-15.
방법: 병렬 웹 조사 3건(한투 오픈API / 알림 채널 / 오픈소스·사례). 공식 문서와 공식 GitHub 저장소를 우선하고, 블로그·커뮤니티 근거는 신뢰도를 낮춰 표기했다.
신뢰도 표기: confirmed(공식 문서/저장소로 확인) / likely(커뮤니티·블로그 다수 확인) / uncertain(상충하거나 미확인).

참고: 프로젝트는 이후 "미국 주식만"으로 확정됐다(2026-07-16, `docs/02-design.md`).
이 문서는 조사 기록이므로 국내주식 조사 내용도 그대로 보존한다. 나중에 국내 확장 시 참조.

---

## 1. 한국투자증권 오픈API (KIS Developers)

주요 근거는 공식 GitHub 저장소(koreainvestment/open-trading-api)의 샘플 코드(회사가 직접 관리, examples_llm 폴더).
포털(apiportal.koreainvestment.com)은 SPA라 크롤링이 제한되어 일부 수치는 커뮤니티 자료로 보강했다.

### 1.1 조회 전용 핵심 API (모두 REST GET)

국내주식:

| 용도 | API명 | 엔드포인트 | TR ID (실전/모의) |
|---|---|---|---|
| 기간 주문체결내역 | 주식일별주문체결조회 [v1_국내주식-005] | `/uapi/domestic-stock/v1/trading/inquire-daily-ccld` | 3개월 이내 `TTTC0081R`/`VTTC0081R`, 3개월 이전 `CTSC9215R`/`VTSC9215R` |
| 잔고 | 주식잔고조회 [v1_국내주식-006] | `/uapi/domestic-stock/v1/trading/inquire-balance` | `TTTC8434R`/`VTTC8434R` |
| 현재가 | 주식현재가 시세 [v1_국내주식-008] | `/uapi/domestic-stock/v1/quotations/inquire-price` | `FHKST01010100` (실전·모의 공통) |

국내 참고사항:

- 구버전 문서/블로그에는 일별주문체결 TR이 `TTTC8001R`/`CTSC9115R`로 나오나, 현재 공식 GitHub 샘플은 `TTTC0081R`/`CTSC9215R` 사용. 과도기 병행 상태로 보이므로 구현 시 최신 포털 문서 기준 확인 권장. (likely, https://wikidocs.net/239689)
- 일별주문체결은 당일 포함 기간 조회 가능(시작일=종료일=오늘). 실전 1회 최대 100건 + 연속조회(CTX_AREA_FK100/NK100), 모의 1회 최대 15건. (confirmed)
- 3개월 이전 조회 TR은 장중 DB 지연 이슈가 있어 공식 주석이 "장 종료(15:30) 이후, 짧은 기간으로 조회"를 권고. (confirmed)
- 잔고조회는 실전 1회 50건/모의 20건 + 연속조회. KRX/NXT(대체거래소)/SOR 구분 파라미터 존재. (confirmed)

해외주식(미국):

| 용도 | API명 | 엔드포인트 | TR ID (실전/모의) |
|---|---|---|---|
| 주문체결내역 | 해외주식 주문체결내역 [v1_해외주식-007] | `/uapi/overseas-stock/v1/trading/inquire-ccnl` | `TTTS3035R`/`VTTS3035R` |
| 미체결내역 | 해외주식 미체결내역 | `/uapi/overseas-stock/v1/trading/inquire-nccs` | `TTTS3018R` (참고) |
| 잔고 | 해외주식 잔고 [v1_해외주식-006] | `/uapi/overseas-stock/v1/trading/inquire-balance` | `TTTS3012R`/`VTTS3012R` |
| 현재가 | 해외주식 현재체결가 [v1_해외주식-009] | `/uapi/overseas-price/v1/quotations/price` | `HHDFS00000300` (공통) |
| 현재가 상세 | 해외주식 현재가상세 [v1_해외주식-029] | `/uapi/overseas-price/v1/quotations/price-detail` | `HHDFS76200200` |

해외 참고사항:

- 체결내역 조회 파라미터 `ORD_STRT_DT`/`ORD_END_DT`는 미국 현지시각 기준 YYYYMMDD (공식 샘플 docstring 명시). 거래소코드 `NASD`=미국 전체(나스닥+뉴욕+아멕스). 기간조회 + 연속조회(FK200/NK200) 지원. (confirmed, https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/overseas_stock/inquire_ccnl/inquire_ccnl.py)
- 모의계좌 제약: 해외 체결내역은 전종목·전체구분(`PDNO=""`, `SLL_BUY_DVSN="00"`, `CCLD_NCCS_DVSN="00"`)만 조회 가능, 정렬순서 지정 불가. (confirmed)

### 1.2 미국 시세의 실시간/지연 여부

- 공식 샘플 주석(2024-11-29 반영): 미국은 실시간무료(0분지연), 홍콩·베트남·중국·일본은 15분지연. (confirmed, https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/overseas_stock/delayed_ccnl/delayed_ccnl.py)
- 단, 무료 미국 시세는 나스닥 마켓센터 집계 기준이라 장중 당일 시가가 상이할 수 있고 익일 정정 표시된다는 공식 주석 있음. 거래소 통합(SIP) 시세가 필요하면 HTS [7781] 시세신청에서 유료 실시간 신청 후 API 수신 가능. (confirmed)
- 미국 주간거래(한국시간 10:00~16:00) 시세는 별도 시장구분코드(나스닥 BAQ, 뉴욕 BAY, 아멕스 BAA)로 조회 가능. (confirmed)

### 1.3 실시간 체결통보 웹소켓

- 존재 확인(공식 샘플 코드): 국내 `H0STCNI0`(실전)/`H0STCNI9`(모의), 해외 `H0GSCNI0`(실전)/`H0GSCNI9`(모의). 개인(custtype=P) 사용 가능. (confirmed, https://github.com/koreainvestment/open-trading-api/blob/main/legacy/websocket/python/ws_domestic%2Boverseas_stock.py)
- 등록 키(tr_key)는 종목코드가 아니라 HTS ID(고객 ID). 체결통보 데이터는 AES256 암호화 수신되어 복호화(key/iv) 구현 필요. (confirmed)
- 접속 URL: 실전 `ws://ops.koreainvestment.com:21000`, 모의 `:31000`. 별도 웹소켓 접속키(approval_key) 발급 필요(`/oauth2/Approval`). (confirmed)
- 통보에는 주문·정정·취소·거부 접수 통보와 체결 통보가 모두 수신됨(CNTG_YN 필드 2=체결, 1=접수). (confirmed)
- 세션당 실시간 등록 한도는 41건으로 알려짐. (likely, https://hky035.github.io/web/refact-kis-websocket/)
- 판단: 자기 계좌 매매내역 수집 + 시세 모니터링 목적이면 REST 폴링이 현실적. 웹소켓은 상시 연결 유지·재접속·AES 복호화·세션 제약 등 운영 부담이 크다. 체결 즉시성이 필수 요구가 될 때만 추가할 가치가 있다.

### 1.4 접근토큰 정책과 Rate Limit

- 접근토큰(`/oauth2/tokenP`) 유효기간 24시간(1일). 공식 kis_auth.py 주석: 6시간 이내 재발급 신청 시 기존 토큰값과 동일 반환, 발급 시 카카오 알림톡 발송. 토큰은 파일 캐싱해 재사용하는 것이 공식 권장 패턴. (confirmed, https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/kis_auth.py)
- 발급 빈도 제한: 1분당 1회 (초과 시 `EGW00133` 에러). (likely, https://velog.io/@seon7129/JAVA-한국투자증권-OpenAPI-사용-정리-Rest)
- REST 호출 유량: 실전 초당 20건 (초과 시 `EGW00201` 에러). (likely, https://hky035.github.io/web/kis-api-throttling/)
- 모의투자 호출 한도: 초당 2건으로 알려져 있으나 일부 자료는 5건으로 표기해 상충. 포털 FAQ 재확인 필요. (uncertain, https://tgparkk.github.io/robotrader/2025/10/09/robotrader-1-70stocks-problem.html)
- 중요: 포털에 "[중요] 한국투자증권 Open API 신규 고객 초당 호출 제한 안내" 공지 게시(2026-03-20). 신규 가입자에게 더 낮은 한도가 적용될 가능성. 공지 본문은 조사 시점에 확인 불가 — 신규 신청 시 반드시 포털에서 본문 확인할 것. (likely, https://apiportal.koreainvestment.com/intro)

### 1.5 모의투자

- 공식 지원. 실전(`prod`)/모의(`vps`) 환경 전환과 모의투자용 앱키/앱시크릿 별도 발급 전제. 조회 API 대부분에 모의 TR ID(V-prefix) 존재. (confirmed, https://github.com/koreainvestment/open-trading-api/blob/main/README.md)
- 모의투자도 한투 계좌 개설 + 모의투자 서비스 가입이 선행되어야 앱키 발급 가능(실계좌 전혀 없이는 불가). 모의 환경은 조회 건수·파라미터 제약 있음. 포털에 테스트베드 메뉴 존재. (confirmed)

### 1.6 신청 절차와 비용

1. 한국투자증권 위탁계좌 개설(비대면 앱 가능) + 홈페이지/앱 ID 등록
2. 홈페이지 또는 앱에서 Open API 서비스 신청 (경로: 트레이딩 > Open API > KIS Developers)
3. 앱키(App Key)/앱시크릿(App Secret) 발급 — 실전용
4. 모의투자 사용 시 모의투자 가입 후 모의투자용 앱키/앱시크릿 별도 발급

- 비용: 서비스 이용 자체는 무료. 해외 유료 실시간 시세만 별도 신청 시 과금 가능. (likely, https://apiportal.koreainvestment.com/about-howto)

### 1.7 미국 주식 체결내역 조회 시 주의점

- 날짜 기준: 조회 파라미터가 현지시각 기준. 한국시간 새벽(예: 7/15 새벽 KST) 체결은 현지 날짜(7/14)로 조회해야 한다. "당일 체결" 배치를 한국 날짜로 돌리면 하루 밀림. 미국 정규장 마감(KST 05:00/06:00) 이후 아침 배치에서 전일(현지) 날짜로 조회하는 설계가 안전. (confirmed)
- 주간거래: 한국시간 10:00~16:00 미국 주간거래(데이마켓) 세션이 별도 존재. 주간거래 체결이 체결내역 API에 어떻게 잡히는지(같은 TR로 통합 조회되는지)는 공식 문서로 확정하지 못함. 이용 시 실측 필요. (uncertain)
- 프리/애프터마켓: KIS는 미국 정규장 외 시간 주문을 지원하므로 해당 체결도 계좌 체결내역에 포함되는 것이 자연스러우나, 공식 명시 문구는 확인하지 못함. (uncertain)
- 시가 정정: 무료 시세 기준 당일 시가는 익일 정정될 수 있음(공식 주석). 체결가와 시세 대조 시 참고. (confirmed)
- 해외 잔고는 `inquire-balance` 외에 결제기준 잔고(`inquire_paymt_stdr_balance`), 체결기준 현재잔고(`inquire_present_balance`)도 있어 정산 시점(T+1 결제) 차이로 수치가 다를 수 있음. (confirmed)

### 1.8 주요 근거

- https://github.com/koreainvestment/open-trading-api — examples_llm/domestic_stock/{inquire_daily_ccld, inquire_balance, inquire_price, ccnl_notice}, examples_llm/overseas_stock/{inquire_ccnl, inquire_balance, price, price_detail, ccnl_notice, delayed_ccnl}, examples_llm/kis_auth.py, legacy/websocket/python/ws_domestic+overseas_stock.py

---

## 2. 알림 채널 비교 ("나 자신에게" 보내기)

### 2.1 카카오톡 나에게 보내기

가능 여부 / 심사:

- API: `POST https://kapi.kakao.com/v2/api/talk/memo/default/send` (기본 템플릿). 개인 개발자 앱으로 가능. (confirmed, https://developers.kakao.com/docs/ko/kakaotalk-message/rest-api)
- 나에게 보내기는 별도 사용 권한(심사) 신청 불필요. 사전 작업: ① 카카오 디벨로퍼스에서 앱 생성 ② 카카오 로그인 활성화 ③ 동의항목에서 `talk_message` 설정 ④ 본인 계정으로 1회 OAuth 로그인(브라우저 인가 코드) 후 토큰 발급. (confirmed)
- 쿼터: 카카오톡 메시지 전송 일 30,000건/앱, 발신자당 100건/일. 개인 주식 알림 용도로 충분. (confirmed, https://developers.kakao.com/docs/ko/getting-started/quota)

토큰 수명 / 무인 운용:

- access token 약 12시간(공식 예시 `expires_in: 43199`초), refresh token 약 2개월(60일, `refresh_token_expires_in: 5184000`초). (confirmed, https://developers.kakao.com/docs/ko/kakaologin/rest-api)
- 갱신: `POST /oauth/token` + `grant_type=refresh_token`. refresh token 만료가 1개월 미만으로 남았을 때만 응답에 새 refresh token이 함께 옴 — 새로 오면 저장 값을 교체해야 한다. (confirmed)
- 스크립트가 최소 월 1회 이상 돌면서 갱신 로직(새 refresh token 저장 포함)을 갖추면 재로그인 없이 무기한 유지 가능. 단 스크립트가 2개월 이상 죽어 있으면 refresh token 만료로 브라우저 수동 재로그인 필요. "완전 무인"은 아니고 "토큰 파일 관리를 잘 하면 사실상 무인". (likely, https://devtalk.kakao.com/t/rest-api/136443)

친구에게 보내기가 어려운 이유:

- ① 별도 사용 권한 신청(심사) + 비즈 앱 전환(사업자 정보 필요) ② 수신자인 친구도 같은 앱에 카카오 로그인하고 친구 목록 제공 동의 필요 ③ 1회 최대 5명, 발신자/수신자 쌍당 일 20건 쿼터. 개인 프로젝트에서는 사실상 비현실적. (confirmed, https://developers.kakao.com/docs/ko/kakaotalk-message/common)

### 2.2 텔레그램 봇

- @BotFather에게 `/newbot` → 토큰 즉시 발급(심사·계정 등록 없음). 발송은 HTTP 한 줄: `https://api.telegram.org/bot<TOKEN>/sendMessage?chat_id=<ID>&text=...`
- 토큰 무기한 유효(만료 없음), 완전 무료. 같은 채팅 초당 1건 수준 제한 — 개인 알림엔 무의미. (confirmed, https://core.telegram.org/bots/faq)
- 진입 장벽: 텔레그램 앱 설치 + 최초 1회 봇에게 말을 걸어 chat_id 확보.

### 2.3 이메일 (Gmail SMTP 앱 비밀번호)

- Google 계정 2단계 인증 활성화 → 앱 비밀번호 16자리 발급 → `smtplib`로 발송. 설정 10분 내외, 무료. (confirmed, https://support.google.com/mail/answer/185833?hl=ko)
- 앱 비밀번호는 만료 없음(계정 비밀번호 변경/보안 이벤트 시 무효화). 무인 운용 부담 낮음.
- 단점: 즉시성이 메일 앱 푸시 설정에 의존, 스팸함 우려. 패스키 전용 계정에서 발급이 번거로울 수 있다는 커뮤니티 사례 있음.

### 2.4 문자(SMS) — 유료

- 알리고: SMS 단문 8.4원/건, LMS 25원, MMS 60원 (선불 충전). (confirmed, https://smartsms.aligo.in/smsapi.html)
- 솔라피: SMS 기본 13원/건, LMS 29원 (월 기본료·API 무료, 발송량 할인 최대 약 58%).
- 공통 부담: 발신번호 사전 등록(본인 인증), 잔액 관리. 하루 10건 기준 월 2,500~4,000원. 개인 알림용으로는 비용 대비 장점 없음.

### 2.5 기타

- Discord 웹훅: 채널 설정에서 웹훅 URL 생성 → POST 한 번으로 발송. 인증 불필요, 무료, 만료 없음. (confirmed, https://discord.com/developers/docs/resources/webhook)
- Slack Incoming Webhook: 무료 워크스페이스로 가능하나 개인 알림용 워크스페이스를 따로 파야 하고(회사 Slack에 개인 주식 알림은 비권장), 무료 플랜 메시지 보존 제한.
- ntfy.sh: 계정·API 키 없이 `curl -d "메시지" ntfy.sh/내토픽` 한 줄로 폰 푸시. 앱 설치 필요. 공개 인스턴스라 토픽명을 추측 어려운 랜덤 문자열로 해야 함. 무료·오픈소스·셀프호스팅 가능. (confirmed, https://docs.ntfy.sh/)

### 2.6 추천 순위 (무인 자동화 유지보수 부담 최소 순)

1. 텔레그램 봇 — 토큰 만료 없음, 무료, 코드 3줄. 유지보수 사실상 0
2. ntfy — 계정조차 불필요. 공개 토픽 보안과 앱 설치가 전제
3. Discord 웹훅 — 만료 없는 URL 하나. 디스코드 사용자라면 1위와 동급
4. 이메일(Gmail 앱 비밀번호) — 만료 없음, 설정 쉬움. 즉시성만 아쉬움
5. 카카오톡 나에게 보내기 — 무료·심사 없음이지만 토큰 갱신 로직 + 파일 관리 필수, 2개월 공백 시 수동 재로그인
6. SMS(알리고/솔라피) — 유료 + 발신번호 등록. 비권장

(순위 자체는 조사 에이전트의 종합 판단, uncertain)

실무 제안: 카카오톡을 메인으로 하되 refresh token을 갱신 저장하는 로직을 넣고, 갱신 실패 시 폴백 채널로 "카카오 재로그인 필요" 경고를 보내는 이중 구조. 처음부터 최소 유지보수를 원하면 텔레그램 단독.

→ 프로젝트 확정안(02-design.md): 카카오 메인 + Gmail 상시 병행, 카카오 실패 시 이메일 경고.

---

## 3. 오픈소스 라이브러리와 유사 사례

### 3.1 파이썬 라이브러리 비교 (GitHub 실측, 2026-07-15 기준)

| 항목 | mojito (sharebook-kr) | python-kis / PyKis (Soju06) | korea-investment-stock (kenshin579) |
|---|---|---|---|
| 설치 | `pip install mojito2` (v0.1.6) | `pip install python-kis` (v2.1.6) | `pip install korea-investment-stock` (v0.19.0, 종료) |
| Stars | 91 | 283 | 소수 (mojito 포크에서 출발) |
| 마지막 커밋 | 2024-02-20 | 릴리스 v2.1.6 (2025-10-13), repo push 2026-02-21 | Go 버전만 활발 (v1.28.0, 2026-06-13) |
| PyPI 마지막 업로드 | 2023-02-23 | 2025-10 | Python은 v0.19.0에서 종료 |
| 미국주식 시세 | O (`fetch_oversea_price`) | O (`kis.stock("NVDA").quote()`) | O (Go 버전, 시세 전용) |
| 미국주식 잔고 | O (`fetch_balance_oversea`, `fetch_present_balance`) | O (`account.balance()` 국내외 통합) | X (스코프 외) |
| 미국주식 체결내역 | X — TTTS3035R 미구현 (소스 전체 grep 확인) | O — `account.daily_orders()`가 TTTS3035R/VTTS3035R 호출 | X (스코프 외) |
| 문서 | wikidocs 책 (https://wikidocs.net/book/7845), 해외 세부 문서 부족 | GitHub Wiki 상세, 전 함수 typing | README 상세하나 Go 문서 |
| 요구사항 | 제약 적음 | Python >= 3.10 | - |
| 라이선스 | MIT | MIT | - |

핵심 판단:

- korea-investment-stock은 2026-05-03부로 Python → Go 전환. Python은 `python-final` 태그 보존, 보안픽스만. 신규 파이썬 프로젝트에 부적합. (confirmed, https://github.com/kenshin579/korea-investment-stock)
- pjueon/pykis(별개 프로젝트, 이름 혼동 주의)는 2022-09 이후 커밋 없음. 사실상 중단.
- mojito는 유지보수 중단 상태이고 해외 체결내역 조회가 없어 이 프로젝트 요건에 미달. (confirmed, https://github.com/sharebook-kr/mojito)
- 라이브러리를 쓴다면 python-kis가 유일한 실질적 선택지. 해외 체결내역·잔고·시세 모두 충족, 유지보수 최상. 단 최근 릴리스가 9개월 전이라 초활발하진 않음. (confirmed, https://github.com/Soju06/python-kis/blob/main/pykis/api/account/daily_order.py)
- 공식 koreainvestment/open-trading-api(1,519 stars)는 라이브러리가 아닌 예제 모음이지만 2026-07-09에도 커밋될 만큼 가장 활발. kis_auth.py(토큰 관리 공용 모듈) + examples_llm(API 1개=파일 1개, LLM 친화) + MCP 디렉토리 제공. Claude로 개발 시 참조 소스로 최적. (confirmed, https://github.com/koreainvestment/open-trading-api)

### 3.2 직접 requests 호출 vs 라이브러리

직접 호출 시 스스로 처리해야 하는 것(라이브러리는 내장):

- 토큰 캐싱(24시간 유효, 재발급 1분당 1회 제한 → 파일 캐싱 필수. 공식 kis_auth.py가 이 패턴)
- 유량 제한(EGW00201), 주문 POST 시 hashkey(이 프로젝트는 조회 전용이라 해당 없음), 연속조회 페이지네이션, 거래소코드·TR ID 매핑, 응답 파싱

직접 호출 장점: 의존성 제로, 공식 예제 복붙 가능(가장 먼저 갱신되는 소스), 라이브러리 방치 리스크 없음. 조회 전용 봇이면 필요한 API가 3~5개라 코드량도 작음.
라이브러리(python-kis) 장점: 토큰/유량/파싱 내장, 국내·해외 동일 인터페이스, typing 자동완성, 웹소켓 자동 재연결. 단점: 추상화로 디버깅 난이도 상승, API 변경 시 업데이트 대기.

권장: 조회 위주 소규모 봇이면 둘 다 무방. 공식 examples_llm + 직접 requests 조합이 가장 통제가 쉽다.
→ 프로젝트 확정안: 직접 requests 호출 (`src/kis_client.py`).

### 3.3 구글시트 기록: gspread + 서비스 계정

- gspread가 파이썬 구글시트 사실상 표준. 봇 자동화에는 서비스 계정 방식이 정석(사용자 OAuth는 브라우저 동의 필요 → 무인 부적합). (confirmed, https://github.com/burnash/gspread)
- 절차(15~30분): GCP 프로젝트 생성 → Sheets API(+Drive API) 활성화 → 서비스 계정 생성 → JSON 키 다운로드 → 시트를 서비스 계정 이메일(xxx@yyy.iam.gserviceaccount.com)에 공유 → `gspread.service_account(filename="key.json")`. 시트 공유 누락이 최다 실수 포인트.
- 주의: gspread 저장소에 유지보수 인력 부재 공지가 있고 최신 릴리스는 v6.2.1(2025-05). 기능은 안정적이라 실사용 문제 없음. 대안은 공식 google-api-python-client(더 장황).

### 3.4 유사 개인 프로젝트 사례

1. geongi-im/kis-us-auto-trading (https://github.com/geongi-im/kis-us-auto-trading) — 한투 API 미국주식 자동매매 봇. requests 직접 래핑(kis_base/kis_order/kis_account/kis_price.py) + websockets. 상시 실행 단독 프로세스, 기본 1분 폴링, 미국시간 16:30 자동 종료. 텔레그램으로 장 시작/종료·체결·손절·에러 알림. (confirmed)
2. tofulim/auto_trade (https://github.com/tofulim/auto_trade) — 적립식(분할매수) 자동매매. FastAPI + Airflow, EC2 t2.micro 운영. Slack 알림 + "알림 후 최소 12시간 뒤 실제 매매"로 오매매 방지. 직접 API 호출. (confirmed)
3. 말춘이 블로그 trader-malchooni (https://malchooni.name/entry/한국투자증권-텔레그램-API-활용-잔고-조회) — 한투 API + 텔레그램 잔고알림. 매일 장 마감 후 잔고조회 TR 직접 호출 → 텔레그램 발송. 하루 1회 배치 경량 구조. (likely)
4. TG's RoboTrader 블로그 (https://tgparkk.github.io/robotrader/2025/10/09/robotrader-1-70stocks-problem.html) — 초당 20건 제한으로 70종목 폴링이 실패한 사례. 배치 크기·딜레이 동적 계산(asyncio)으로 해결. 다종목 폴링 시 유량 관리 필요성을 보여줌. (운영 참고)

- "물타기 알림" 명칭 그대로의 유명 공개 프로젝트는 발견하지 못함. "한투 체결내역 → gspread 매매일지" 완성형 공개 레포도 못 찾았으나, 구성요소별 사례가 모두 흔해 조합 난이도는 낮음. (uncertain)

---

## 4. 종합 판단

- 조회 전용(주문 미사용) 개인 프로젝트로 충분히 가능. 실계좌 개설 + 무료 앱키 발급이면 국내/해외 체결내역·잔고·시세 REST 조회가 모두 열리고, 미국 시세도 무료 0분 지연.
- 카카오톡 알림 파싱 방식은 배제. 개인 카톡 수신 메시지를 읽는 공식 API가 없고, 기기 의존·문구 변경에 취약.
- 아키텍처는 REST 폴링이 현실적. 웹소켓 체결통보는 실시간 요구가 생길 때 추가.
- 구현은 공식 examples_llm 참조 + 직접 requests 호출(또는 python-kis). 시트는 gspread + 서비스 계정.
- 알림은 카카오 나에게 보내기(메인) + 폴백 채널 이중화.
- 착수 전 확인 필수: 2026-03-20 신규 고객 초당 호출 제한 공지 본문, 모의투자 정확한 초당 한도. 주간거래 이용 시 체결내역 반영 방식 실측.
