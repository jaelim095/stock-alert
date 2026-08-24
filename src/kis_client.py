"""Korea Investment & Securities open API client — read-only. No order-family APIs here.

Response field names were written from the official examples_llm and may need
correction against live-account measurements (see CLAUDE.md current status).
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

    # Token valid 24h / reissue capped at once per minute → file cache, refresh only within 10 min of expiry
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
        time.sleep(0.2)  # headroom for the rate limit (20 req/s on live)
        r.raise_for_status()
        d = r.json()
        if str(d.get("rt_cd")) != "0":
            raise RuntimeError(f"KIS API 오류 {d.get('msg_cd')}: {d.get('msg1')}")
        return r, d

    def fetch_executions(self, start=None, end=None):
        """Executions → list of trade dicts with internal keys. Default: US-local [yesterday, today].

        Queries a 2-day range by default to avoid date-boundary issues, then dedupes
        by order number (the caller's job). start/end are dates — the backfill script passes past ranges.
        """
        today = datetime.now(US_EASTERN).date()
        end_d = end or today
        start_d = start or (end_d - timedelta(days=1))
        params = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.prdt,
            "PDNO": "",
            "ORD_STRT_DT": start_d.strftime("%Y%m%d"),
            "ORD_END_DT": end_d.strftime("%Y%m%d"),
            "SLL_BUY_DVSN": "00",       # all
            "CCLD_NCCS_DVSN": "01",     # filled only
            "OVRS_EXCG_CD": "NASD",     # all US (NASDAQ+NYSE+AMEX)
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
                    # Verified live (2026-07): sll_buy_dvsn_cd 01=sell, 02=buy.
                    # Trust the name field first; the code is the fallback.
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
            if cont in ("F", "M"):  # continuation fetch
                params["CTX_AREA_FK200"] = d.get("ctx_area_fk200", "")
                params["CTX_AREA_NK200"] = d.get("ctx_area_nk200", "")
                tr_cont = "N"
                continue
            break
        return out

    def fetch_price(self, excd, symb):
        """Current overseas stock price. The free quote server throws intermittent 500s, so retry once."""
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
        """US holdings balance (read-only). Sorted by valuation, descending."""
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
        """Daily closing prices (newest first). For moving averages. Beyond 100 rows, paginate via BYMD."""
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
