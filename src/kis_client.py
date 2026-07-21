"""한국투자증권 오픈API 클라이언트 — 조회 전용. 주문 계열 API는 두지 않는다.

응답 필드명은 공식 examples_llm 기준으로 작성했으며 실계좌 실측으로 보정이
필요할 수 있다 (CLAUDE.md 현재 상태 참고).
"""
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

US_EASTERN = ZoneInfo("America/New_York")
KST = ZoneInfo("Asia/Seoul")

BASE_URL = {
    "prod": "https://openapi.koreainvestment.com:9443",
    "vps": "https://openapivts.koreainvestment.com:29443",
}
TR_CCNL = {"prod": "TTTS3035R", "vps": "VTTS3035R"}
TR_PRICE = "HHDFS00000300"
_EXMAP = {"NASD": "NAS", "NAS": "NAS", "NYSE": "NYS", "NYS": "NYS",
          "AMEX": "AMS", "AMS": "AMS"}


def _fmt_date(yyyymmdd):
    s = str(yyyymmdd)
    if len(s) == 8:
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s


class KISClient:
    def __init__(self, app_key, app_secret, account_no, env="vps",
                 token_path="./data/kis_token.json"):
        self.app_key = app_key
        self.app_secret = app_secret
        cano, _, prdt = str(account_no).partition("-")
        self.cano = cano
        self.prdt = prdt or "01"
        self.env = env
        self.base = BASE_URL[env]
        self.token_path = Path(token_path)

    # 토큰 24시간 유효 / 재발급 1분당 1회 제한 → 파일 캐싱, 만료 10분 전에만 갱신
    def _token(self):
        tok = {}
        if self.token_path.exists():
            try:
                tok = json.loads(self.token_path.read_text())
            except (ValueError, OSError):
                tok = {}
        if tok.get("access_token") and time.time() < tok.get("expires_at", 0) - 600:
            return tok["access_token"]
        if time.time() - tok.get("issued_at", 0) < 65:
            raise RuntimeError("토큰 재발급 1분당 1회 제한 — 잠시 후 재시도")
        r = requests.post(
            f"{self.base}/oauth2/tokenP",
            json={"grant_type": "client_credentials",
                  "appkey": self.app_key, "appsecret": self.app_secret},
            timeout=10)
        r.raise_for_status()
        d = r.json()
        tok = {
            "access_token": d["access_token"],
            "issued_at": time.time(),
            "expires_at": time.time() + int(d.get("expires_in", 86400)),
        }
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text(json.dumps(tok))
        return tok["access_token"]

    def _get(self, path, tr_id, params, tr_cont=""):
        headers = {
            "authorization": f"Bearer {self._token()}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id,
            "custtype": "P",
        }
        if tr_cont:
            headers["tr_cont"] = tr_cont
        r = requests.get(self.base + path, headers=headers, params=params, timeout=10)
        time.sleep(0.2)  # 유량 제한(실전 초당 20건) 여유
        r.raise_for_status()
        d = r.json()
        if str(d.get("rt_cd")) != "0":
            raise RuntimeError(f"KIS API 오류 {d.get('msg_cd')}: {d.get('msg1')}")
        return r, d

    def fetch_executions(self):
        """미국 현지 [어제, 오늘] 범위의 체결내역 → 내부 키 trade dict 목록.

        날짜 경계 문제를 피하려고 항상 2일 범위로 조회하고 주문번호로 dedupe 한다
        (dedupe는 호출자 몫).
        """
        today = datetime.now(US_EASTERN).date()
        params = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.prdt,
            "PDNO": "",
            "ORD_STRT_DT": (today - timedelta(days=1)).strftime("%Y%m%d"),
            "ORD_END_DT": today.strftime("%Y%m%d"),
            "SLL_BUY_DVSN": "00",       # 전체
            "CCLD_NCCS_DVSN": "01",     # 체결만
            "OVRS_EXCG_CD": "NASD",     # 미국 전체(나스닥+뉴욕+아멕스)
            "SORT_SQN": "DS",
            "ORD_DT": "",
            "ORD_GNO_BRNO": "",
            "ODNO": "",
            "CTX_AREA_NK200": "",
            "CTX_AREA_FK200": "",
        }
        out = []
        tr_cont = ""
        while True:
            r, d = self._get("/uapi/overseas-stock/v1/trading/inquire-ccnl",
                             TR_CCNL[self.env], params, tr_cont)
            for row in d.get("output") or []:
                qty = int(float(row.get("ft_ccld_qty") or 0))
                if qty <= 0:
                    continue
                price = float(row.get("ft_ccld_unpr3") or 0)
                out.append({
                    "recorded_at": datetime.now(KST).isoformat(timespec="seconds"),
                    "trade_date": _fmt_date(row.get("ord_dt", "")),
                    "ticker": str(row.get("pdno", "")).upper(),
                    "name": row.get("prdt_name", ""),
                    # 실측 확인(2026-07): sll_buy_dvsn_cd 01=매도, 02=매수.
                    # 이름 필드를 우선 신뢰하고 코드는 폴백.
                    "side": "매도" if "매도" in str(row.get("sll_buy_dvsn_cd_name") or "")
                            or str(row.get("sll_buy_dvsn_cd")) == "01" else "매수",
                    "price": price,
                    "qty": qty,
                    "amount": float(row.get("ft_ccld_amt3") or 0) or round(price * qty, 2),
                    "order_no": str(row.get("odno", "")),
                    "matched_lots": "",
                    "note": "",
                })
            cont = (r.headers.get("tr_cont") or "").strip()
            if cont in ("F", "M"):  # 연속조회
                params["CTX_AREA_FK200"] = d.get("ctx_area_fk200", "")
                params["CTX_AREA_NK200"] = d.get("ctx_area_nk200", "")
                tr_cont = "N"
                continue
            break
        return out

    def fetch_price(self, excd, symb):
        """해외주식 현재체결가. 무료 시세 서버가 간헐 500을 내므로 1회 재시도."""
        for attempt in (1, 2):
            try:
                _, d = self._get("/uapi/overseas-price/v1/quotations/price", TR_PRICE,
                                 {"AUTH": "", "EXCD": excd, "SYMB": symb})
                return float((d.get("output") or {}).get("last") or 0)
            except requests.HTTPError:
                if attempt == 2:
                    raise
                time.sleep(2)

    def fetch_holdings(self):
        """미국 보유 종목 잔고 (조회 전용). 평가액 내림차순."""
        params = {"CANO": self.cano, "ACNT_PRDT_CD": self.prdt,
                  "OVRS_EXCG_CD": "NASD", "TR_CRCY_CD": "USD",
                  "CTX_AREA_FK200": "", "CTX_AREA_NK200": ""}
        _, d = self._get("/uapi/overseas-stock/v1/trading/inquire-balance",
                         {"prod": "TTTS3012R", "vps": "VTTS3012R"}[self.env], params)
        out = []
        for row in d.get("output1") or []:
            qty = float(row.get("ovrs_cblc_qty") or 0)
            if qty <= 0:
                continue
            out.append({
                "ticker": row.get("ovrs_pdno", ""),
                "name": row.get("ovrs_item_name", ""),
                "excd": _EXMAP.get((row.get("ovrs_excg_cd") or "").strip(), "NAS"),
                "qty": qty,
                "avg": float(row.get("pchs_avg_pric") or 0),
                "now": float(row.get("now_pric2") or 0),
                "value": float(row.get("ovrs_stck_evlu_amt") or 0),
                "pnl_pct": float(row.get("evlu_pfls_rt") or 0),
            })
        return sorted(out, key=lambda x: -x["value"])

    def fetch_daily_closes(self, excd, symb, need=130):
        """일봉 종가 목록(최신순). 이동평균 계산용. 100건 초과는 BYMD 페이지네이션."""
        closes = {}
        bymd = ""
        for _ in range(4):
            _, d = self._get("/uapi/overseas-price/v1/quotations/dailyprice",
                             "HHDFS76240000",
                             {"AUTH": "", "EXCD": excd, "SYMB": symb,
                              "GUBN": "0", "BYMD": bymd, "MODP": "1"})
            rows = d.get("output2") or []
            added = 0
            for r in rows:
                x, c = r.get("xymd"), float(r.get("clos") or 0)
                if x and c > 0 and x not in closes:
                    closes[x] = c
                    added += 1
            if len(closes) >= need or added == 0:
                break
            bymd = min(closes)
        return [closes[x] for x in sorted(closes, reverse=True)]
