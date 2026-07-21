"""Jaewon's Stock Dashboard (Streamlit) — 표시 전용 층.

실행 (반드시 저장소 루트에서):
  .venv/bin/streamlit run dashboard/app.py
접속: http://localhost:8501

- 조회 전용: 주문 관련 기능 없음. 봇·스킬이 만든 데이터를 보여주기만 한다.
- localhost 전용(.streamlit/config.toml): 계좌 전체가 표시되므로 외부 배포 금지.
- 색상: 한국 관례(상승 빨강·하락 파랑) + 부호 병기(색만으로 구분하지 않음).
- "분석 갱신" 버튼: scripts/run_checkup.sh 로 /checkup 을 헤드리스 재실행 (수 분 소요).
"""
import html as html_mod
import json
from concurrent.futures import ThreadPoolExecutor
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd
import streamlit as st

from src import config
from src.kis_client import KISClient
from src.sheet_client import SheetClient

KST = ZoneInfo("Asia/Seoul")
REPORTS = ROOT / "reports"
UP, DOWN, FLAT = "#C0392B", "#2B6CB0", "#666B7E"  # 상승 빨강 / 하락 파랑
INK, MUTED, LINE = "#1A1D27", "#6A6E85", "#E7E8F0"

VERDICT_PILL = {  # 상태색 + 텍스트 병기 (색 단독 구분 금지)
    "계속보유": ("#1E7F4F", "#E6F4EC"),
    "축소 검토": ("#9A6700", "#FFF3DC"),
    "추가 검토": ("#2B6CB0", "#E8F0FB"),
    "판단 보류": ("#555B6E", "#EEEFF4"),
}

st.set_page_config(page_title="Jaewon's Stock Dashboard", page_icon="📈", layout="wide")

st.markdown(f"""
<style>
.block-container {{ padding-top: 3.6rem; max-width: 1250px; }}  /* 고정 헤더에 제목이 가리지 않게 */
.stTabs [data-baseweb="tab"] p {{ font-size: .98rem; font-weight: 600; }}
[data-testid="stSidebar"] {{ border-right: 1px solid {LINE}; }}
h3 {{ letter-spacing: -.01em; }}
</style>
""", unsafe_allow_html=True)


# ── 데이터 로딩 (캐시로 API 호출 최소화) ─────────────────────

@st.cache_resource
def kis():
    return KISClient(config.KIS_APP_KEY, config.KIS_APP_SECRET,
                     config.KIS_ACCOUNT_NO, config.KIS_ENV, config.KIS_TOKEN_PATH)


@st.cache_resource
def sheets():
    return SheetClient(config.GOOGLE_SERVICE_ACCOUNT_JSON, config.SHEET_ID)


@st.cache_data(ttl=60)
def load_holdings():
    return kis().fetch_holdings()


@st.cache_data(ttl=120)
def load_sheet():
    sc = sheets()
    return {
        "settings": sc.read_settings(),
        "lots": sc.read_lots(),
        "thesis": {t["ticker"].upper(): t for t in sc.read_thesis()},
        "alerts": sc.read_alerts(),
        "trades": sc.read_trades(),
    }


def ma_stats(closes):
    """종가(최신순) → 이동평균 지표. 데이터 부족 항목은 None. 순수 함수."""
    def _ma(n, off=0):
        seg = closes[off:off + n]
        return sum(seg) / n if len(seg) == n else None
    now = closes[0] if closes else None
    m = {n: _ma(n) for n in (5, 20, 60, 120)}
    arr = "-"
    if all(m.values()):
        if m[5] > m[20] > m[60] > m[120]:
            arr = "정배열"
        elif m[5] < m[20] < m[60] < m[120]:
            arr = "역배열"
        else:
            arr = "혼조"
    cross = ""
    p20, p60 = _ma(20, 9), _ma(60, 9)
    if m[20] and m[60] and p20 and p60:
        if p20 - p60 <= 0 < m[20] - m[60]:
            cross = "골든크로스"
        elif p20 - p60 >= 0 > m[20] - m[60]:
            cross = "데드크로스"
    return {"now": now, "ma": m, "arr": arr, "cross": cross}


@st.cache_data(ttl=21600, show_spinner=False)
def load_ma(holdings_key):
    """보유 전 종목 이동평균. 일봉 기반이라 6시간 캐시, 보유 구성이 바뀌면
    캐시 키가 달라져 자동 재계산 (매수 시 추가·전량 매도 시 제외).
    4스레드 병렬 수집 — 호출당 0.2s 대기가 있어 유량 한도(초당 20건) 내."""
    def one(tk, pref):
        closes = []
        for excd in [pref] + [e for e in ("NAS", "NYS", "AMS") if e != pref]:
            try:
                closes = kis().fetch_daily_closes(excd, tk)
            except Exception:
                closes = []
            if len(closes) >= 20:
                break
        return tk, ma_stats(closes)
    with ThreadPoolExecutor(max_workers=4) as ex:
        return dict(ex.map(lambda p: one(*p), holdings_key))


# ── 순수 헬퍼 ────────────────────────────────────────────────

def aggregate_exposure(holdings):
    """레버리지 ETF를 기초자산으로 합산한 실질 노출."""
    total = sum(h["value"] for h in holdings) or 1.0
    agg = {}
    for h in holdings:
        base = config.UNDERLYING_MAP.get(h["ticker"], h["ticker"])
        a = agg.setdefault(base, {"value": 0.0, "parts": set()})
        a["value"] += h["value"]
        a["parts"].add(h["ticker"])
    rows = [{"방향": k, "실질비중%": round(v["value"] / total * 100, 1),
             "평가액$": round(v["value"]), "구성": " + ".join(sorted(v["parts"]))}
            for k, v in agg.items()]
    return sorted(rows, key=lambda r: -r["실질비중%"])


def report_section(text, ticker):
    """체크업 리포트에서 해당 종목 섹션만 추출."""
    m = re.search(rf"^## {re.escape(ticker)}\b.*?(?=^## |\Z)", text, re.M | re.S)
    return m.group(0).strip() if m else None


def latest_report(prefix):
    files = sorted(REPORTS.glob(f"{prefix}*.md"))
    return files[-1] if files else None


def checkup_texts():
    """체크업 리포트 전부 (최신순) [(파일명, 내용)]."""
    return [(f.name, f.read_text())
            for f in sorted(REPORTS.glob("checkup-*.md"), reverse=True)]


def latest_section(texts, ticker):
    """종목별 가장 최근 판정 섹션 — 부분 갱신 리포트들을 병합해 찾는다."""
    for name, text in texts:
        sec = report_section(text, ticker)
        if sec:
            return sec, name
    return None, None


def verdict_of(section):
    """섹션 헤더에서 '판정: X (확신도: Y)' 추출 → (판정, 확신도)."""
    if not section:
        return None, None
    v = re.search(r"판정:\s*([^\(（\n]+)", section)
    c = re.search(r"확신도:\s*([^\)）\n]+)", section)
    return (v.group(1).strip() if v else None), (c.group(1).strip() if c else None)


def verdict_pill(verdict, conf=None):
    key = next((k for k in VERDICT_PILL if verdict and verdict.startswith(k)), None)
    if not key:
        return ""
    fg, bg = VERDICT_PILL[key]
    conf_html = (f"<span style='color:{MUTED};font-size:.8rem;margin-left:8px'>"
                 f"확신도 {conf}</span>" if conf else "")
    return (f"<span style='background:{bg};color:{fg};border-radius:999px;"
            f"padding:4px 14px;font-size:.9rem;font-weight:700'>판정: {verdict}</span>"
            + conf_html)


def md_safe(text):
    """리포트 마크다운 안전 렌더링: 335~384 같은 범위 표기가 취소선(~)으로 깨지는 것 방지."""
    return text.replace("~", "\\~")


def _esc(s, limit=None):
    s = html_mod.escape(str(s or ""))
    return (s[:limit] + "…") if limit and len(s) > limit else s


HEALTH_PILL = {"우수": ("#1E7F4F", "#E6F4EC"), "양호": ("#2B6CB0", "#E8F0FB"),
               "조정": ("#9A6700", "#FFF3DC"), "위험": ("#B42318", "#FEE4E2")}


def parse_checkup(text):
    """체크업 리포트 → 판정 카드용 구조 데이터 (LLM 산출물이라 best-effort 추출)."""
    items = []
    for m in re.finditer(r"^## ([A-Z]{2,6})\b", text, re.M):
        tk = m.group(1)
        sec = report_section(text, tk)
        v, c = verdict_of(sec)
        if not v:
            continue
        reason = re.search(r"^-\s*근거[^:：\n]*[:：]\s*(.+)$", sec, re.M)
        counter = re.search(r"반대 논거[:：]\s*(.+)$", sec, re.M)
        buy = re.search(r"오늘[^\n]*사겠는가[:：]?\s*\**\s*(예|아니오)", sec)
        items.append({"ticker": tk, "verdict": v, "conf": c, "sec": sec,
                      "reason": reason.group(1).strip() if reason else "",
                      "counter": counter.group(1).strip() if counter else "",
                      "buy": buy.group(1) if buy else None})
    # 리포트마다 헤더 레벨(#/##)이 달라서 같은 레벨의 다음 헤더 전까지 매칭
    port = re.search(r"^(#{1,2}) 포트폴리오.*?(?=^\1 |\Z)", text, re.M | re.S)
    health = re.search(r"건강도[:：]\s*\**\s*([^\n*#]+)", text)
    action = re.search(r"최우선 조치[^:：\n]*[:：]\s*\**\s*([^\n]+)", text)
    return items, (port.group(0).strip() if port else None), \
        (health.group(1).strip() if health else None), \
        (action.group(1).strip() if action else None)


def verdict_card(v):
    key = next((k for k in VERDICT_PILL if v["verdict"].startswith(k)), None)
    fg, bg = VERDICT_PILL.get(key, ("#555B6E", "#EEEFF4"))
    buy = {"예": "🟢 예", "아니오": "⚪ 아니오"}.get(v["buy"], "-")
    return (
        f"<div style='flex:1 1 300px;max-width:430px;background:#fff;border:1px solid {LINE};"
        f"border-left:5px solid {fg};border-radius:12px;padding:13px 16px;"
        f"box-shadow:0 1px 3px rgba(20,24,60,.05)'>"
        f"<div style='display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:5px'>"
        f"<span style='font-weight:800;font-size:1.05rem;color:{INK}'>{_esc(v['ticker'])}</span>"
        f"<span style='background:{bg};color:{fg};border-radius:999px;padding:2px 11px;"
        f"font-size:.78rem;font-weight:700;white-space:nowrap'>{_esc(v['verdict'], 22)}</span></div>"
        f"<div style='color:{MUTED};font-size:.76rem;margin-bottom:7px'>"
        f"확신도 {_esc(v['conf'] or '-')} · 오늘 처음 봐도 산다: {buy}</div>"
        f"<div style='font-size:.84rem;color:{INK};line-height:1.5'>{_esc(v['reason'], 95)}</div>"
        f"<div style='font-size:.78rem;color:{MUTED};margin-top:7px;line-height:1.45'>"
        f"반대 논거: {_esc(v['counter'], 85)}</div></div>")


def pnl_style(v):
    try:
        x = float(str(v).replace("%", "").replace("+", ""))
    except (ValueError, TypeError):
        return ""
    if x > 0:
        return f"color:{UP};font-weight:600"
    if x < 0:
        return f"color:{DOWN};font-weight:600"
    return f"color:{FLAT}"


def pnl_html(v, suffix="%"):
    color = UP if v > 0 else DOWN if v < 0 else FLAT
    return f"<span style='color:{color};font-weight:700'>{v:+,.2f}{suffix}</span>"


def stat_card(label, value_html):
    return (f"<div style='flex:1;min-width:160px;background:#fff;border:1px solid {LINE};"
            f"border-radius:14px;padding:13px 17px;box-shadow:0 1px 3px rgba(20,24,60,.05)'>"
            f"<div style='color:{MUTED};font-size:.8rem;margin-bottom:3px'>{label}</div>"
            f"<div style='font-size:1.4rem;font-weight:700;color:{INK}'>{value_html}</div></div>")


def stat_row(cards):
    st.markdown("<div style='display:flex;gap:12px;flex-wrap:wrap;margin-bottom:6px'>"
                + "".join(cards) + "</div>", unsafe_allow_html=True)


# ── 분석 갱신 (헤드리스 /checkup) 상태 ───────────────────────

def checkup_status():
    lock, status = ROOT / "data/checkup_run.lock", ROOT / "data/checkup_run.status"
    running = False
    if lock.exists():
        try:
            pid = int(lock.read_text().split(":")[0])
            import os
            os.kill(pid, 0)
            running = True
        except (ValueError, OSError, ProcessLookupError):
            running = False
    info = {}
    if status.exists():
        try:
            info = json.loads(status.read_text())
        except ValueError:
            pass
    return running, info


# ── 사이드바 ─────────────────────────────────────────────────

st.sidebar.markdown(f"<div style='font-weight:800;font-size:1.15rem;color:{INK}'>"
                    "📈 Stock Dashboard</div>", unsafe_allow_html=True)
st.sidebar.caption("조회 전용 · localhost")

if st.sidebar.button("데이터 새로고침", width="stretch"):
    load_holdings.clear()   # 이동평균(일봉)은 6시간 캐시 유지 — 시세·시트만 갱신
    load_sheet.clear()
    st.rerun()

st.sidebar.divider()
st.sidebar.markdown("**분석 갱신**")
running, run_info = checkup_status()
if running:
    target = run_info.get("tickers") or "자동 선정"
    st.sidebar.info(f"체크업 실행 중 — 대상: {target}\n\n({run_info.get('started_at', '')} 시작) "
                    "완료까지 수 분 걸립니다. 잠시 후 '데이터 새로고침'을 누르세요.")
else:
    try:
        _opts = [x["ticker"] for x in load_holdings()]
    except Exception:
        _opts = []
    sel_tickers = st.sidebar.multiselect(
        "갱신할 종목 (비우면 자동 선정: 상위 6 + 감시)", _opts)
    if st.sidebar.button("판정 새로 받기 (/checkup)", width="stretch"):
        if not shutil.which("claude"):
            st.sidebar.error("claude CLI를 찾을 수 없습니다. 터미널에서 /checkup을 실행하세요.")
        else:
            subprocess.Popen(["bash", str(ROOT / "scripts/run_checkup.sh"), *sel_tickers],
                             cwd=ROOT, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
            time.sleep(1)
            st.rerun()
    if run_info.get("state") == "done":
        ok = run_info.get("exit") == 0
        st.sidebar.caption(("최근 갱신 완료: " if ok else f"최근 갱신 실패(코드 {run_info.get('exit')}): ")
                           + str(run_info.get("finished_at", "")))
checkup_file = latest_report("checkup-")
st.sidebar.caption(f"최근 판정 리포트: {checkup_file.name if checkup_file else '없음'}")
st.sidebar.caption(f"갱신: {datetime.now(KST).strftime('%m-%d %H:%M:%S')} KST")


# ── 데이터 준비 ──────────────────────────────────────────────

try:
    holdings = load_holdings()
except Exception as e:
    st.error(f"한투 잔고 조회 실패: {e}")
    st.stop()
try:
    sheet = load_sheet()
except Exception as e:
    st.warning(f"구글시트 연결 실패 — 잔고만 표시합니다: {e}")
    sheet = {"settings": {}, "lots": [], "thesis": {}, "alerts": [], "trades": []}

total_value = sum(h["value"] for h in holdings)
total_cost = sum(h["avg"] * h["qty"] for h in holdings)
total_pnl = (total_value / total_cost - 1) * 100 if total_cost else 0.0
checkup_docs = checkup_texts()  # 종목별 최신 판정을 리포트들에서 병합


# ── 헤더 ─────────────────────────────────────────────────────

st.markdown(f"""
<div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
  <span style="font-size:1.9rem;font-weight:800;letter-spacing:-.02em;color:{INK}">Jaewon's Stock Dashboard</span>
  <span style="background:#EEF0FB;color:#4A4FB5;border-radius:999px;padding:3px 12px;font-size:.76rem;font-weight:700">실전 계좌 · 조회 전용</span>
</div>
<div style="color:{MUTED};margin:2px 0 16px">미국주식 자동 기록·알림 봇 + 다관점 체크업 · {datetime.now(KST).strftime('%Y-%m-%d %H:%M')} KST</div>
""", unsafe_allow_html=True)

tab_pf, tab_detail, tab_report = st.tabs(["포트폴리오", "종목 상세", "리포트"])


# ── 탭 1: 포트폴리오 ────────────────────────────────────────

with tab_pf:
    watch_n = sum(1 for s in sheet["settings"].values() if s.get("enabled"))
    stat_row([
        stat_card("총 평가액", f"${total_value:,.0f}"),
        stat_card("총 매입액", f"${total_cost:,.0f}"),
        stat_card("총 손익", pnl_html(total_pnl)),
        stat_card("보유 / 감시", f"{len(holdings)} / {watch_n} 종목"),
    ])

    st.subheader("보유 종목")
    df = pd.DataFrame(holdings)
    if not df.empty:
        df["비중%"] = (df["value"] / (total_value or 1) * 100).round(1)
        df["판정"] = [
            (verdict_of(latest_section(checkup_docs, t)[0])[0] or "") for t in df["ticker"]]
        view = df.rename(columns={"ticker": "종목", "name": "이름", "qty": "수량",
                                  "avg": "평단$", "now": "현재$", "value": "평가$",
                                  "pnl_pct": "손익%"})
        view = view[["종목", "이름", "수량", "평단$", "현재$", "평가$", "손익%", "비중%", "판정"]]
        styled = (view.style
                  .map(pnl_style, subset=["손익%"])
                  .format({"수량": "{:,.0f}", "평단$": "{:,.2f}", "현재$": "{:,.2f}",
                           "평가$": "{:,.0f}", "손익%": "{:+.2f}", "비중%": "{:.1f}"}))
        st.dataframe(styled, width="stretch", height=530, hide_index=True)

    st.subheader("실질 노출 (레버리지 ETF → 기초자산 합산)")
    exp = aggregate_exposure(holdings)
    st.dataframe(
        pd.DataFrame(exp), width="stretch", hide_index=True,
        column_config={"실질비중%": st.column_config.ProgressColumn(
            "실질비중%", min_value=0, max_value=100, format="%.1f%%")})
    over = [r for r in exp if r["실질비중%"] > 40]
    if over:
        st.warning("실질 노출 40% 초과: "
                   + ", ".join(f"{r['방향']} {r['실질비중%']}%" for r in over)
                   + " — 체크업 자동 규칙 기준 축소 검토 대상")

    st.subheader("이동평균 현황 (일봉 종가)")
    ma_key = tuple((h["ticker"], h.get("excd", "NAS")) for h in holdings)
    with st.spinner("이동평균 계산 중 — 최초 로딩만 수 초 걸립니다"):
        ma_map = load_ma(ma_key)
    ma_rows = []
    for h in holdings:
        s = ma_map.get(h["ticker"]) or {"now": None}
        if not s["now"]:
            ma_rows.append({"종목": h["ticker"], "종가$": None, "vs 5일%": None,
                            "vs 20일%": None, "vs 60일%": None, "vs 120일%": None,
                            "배열": "데이터 부족", "크로스(10일)": "-"})
            continue
        rel = lambda n: round((s["now"] / s["ma"][n] - 1) * 100, 1) if s["ma"].get(n) else None
        ma_rows.append({"종목": h["ticker"], "종가$": round(s["now"], 2),
                        "vs 5일%": rel(5), "vs 20일%": rel(20),
                        "vs 60일%": rel(60), "vs 120일%": rel(120),
                        "배열": s["arr"], "크로스(10일)": s["cross"] or "-"})
    pct_cols = ["vs 5일%", "vs 20일%", "vs 60일%", "vs 120일%"]
    st.dataframe(pd.DataFrame(ma_rows).style.map(pnl_style, subset=pct_cols)
                 .format({c: "{:+.1f}" for c in pct_cols} | {"종가$": "{:,.2f}"}, na_rep="--"),
                 width="stretch", height=530, hide_index=True)
    st.caption("보유 종목 자동 추적 — 새 종목은 매수하면 자동 추가, 전량 매도하면 자동 제외됩니다. "
               "양수(빨강)=이평선 위 · 음수(파랑)=아래. 일봉 기반이라 6시간 캐시로 동작합니다.")

    with st.expander("봇 감시 설정"):
        if sheet["settings"]:
            st.dataframe(pd.DataFrame([
                {"종목": t, "감시": "Y" if s["enabled"] else "N",
                 "하락임계%": s["drop_pct"] or config.DEFAULT_DROP_PCT,
                 "상승임계%": s["rise_pct"] or config.DEFAULT_RISE_PCT}
                for t, s in sheet["settings"].items()]), hide_index=True)
        else:
            st.caption("설정 없음")


# ── 탭 2: 종목 상세 ─────────────────────────────────────────

with tab_detail:
    tickers = [h["ticker"] for h in holdings]
    sel = st.selectbox("종목 선택", tickers)
    h = next(x for x in holdings if x["ticker"] == sel)
    weight = h["value"] / (total_value or 1) * 100

    sec, sec_src = latest_section(checkup_docs, sel)
    verdict, conf = verdict_of(sec)
    title_html = (f"<span style='font-size:1.5rem;font-weight:800;color:{INK}'>{sel}</span>"
                  f"<span style='color:{MUTED};margin-left:10px'>{h['name']}</span>")
    pill = verdict_pill(verdict, conf)
    st.markdown(f"<div style='display:flex;align-items:center;gap:14px;flex-wrap:wrap;"
                f"margin:4px 0 10px'>{title_html}{pill}</div>", unsafe_allow_html=True)

    stat_row([
        stat_card("현재가", f"${h['now']:,.2f}"),
        stat_card("평단", f"${h['avg']:,.2f}"),
        stat_card("손익", pnl_html(h["pnl_pct"])),
        stat_card("평가액", f"${h['value']:,.0f}"),
        stat_card("비중", f"{weight:.1f}%"),
    ])

    base = config.UNDERLYING_MAP.get(sel)
    if base:
        st.caption(f"레버리지 2x ETF — 기초자산: {base}. 장기 보유 시 일일 리밸런싱 감쇠 주의.")

    s_ma = load_ma(tuple((h2["ticker"], h2.get("excd", "NAS")) for h2 in holdings)).get(sel)
    if s_ma and s_ma["now"]:
        parts = " · ".join(
            f"{n}일선 {(s_ma['now'] / s_ma['ma'][n] - 1) * 100:+.1f}%"
            for n in (5, 20, 60, 120) if s_ma["ma"].get(n))
        st.caption("이동평균 대비: " + parts + f" · {s_ma['arr']}"
                   + (f" · {s_ma['cross']}" if s_ma["cross"] else ""))

    left, right = st.columns(2)
    with left:
        st.subheader("투자논리 (시트 기록)")
        t = sheet["thesis"].get(sel)
        if t:
            st.markdown(f"- **매수 이유**: {t['reason']}\n"
                        f"- **핵심 가정**: {t['assumption']}\n"
                        f"- **무효화 조건**: {t['invalidation']}\n"
                        f"- 작성 {t['created_at']} · 최근 점검 {t['last_checked'] or '-'}")
        else:
            st.caption("논리 미기록 — 시트 투자논리 탭에 추가하세요.")

        st.subheader("활성 감시 lot")
        lots = [l for l in sheet["lots"]
                if l["ticker"] == sel and l["status"] == "감시중"]
        if lots:
            st.dataframe(pd.DataFrame([
                {"lot": l["lot_id"], "유형": l["kind"], "기준$": l["base_price"],
                 "수량": l["qty"], "등락%": l["change_pct"]} for l in lots]),
                hide_index=True)
        else:
            st.caption("감시 중인 lot 없음 (봇 미감시 종목)")

    with right:
        st.subheader("최근 판정 (체크업)")
        if sec:
            st.caption(f"출처: {sec_src} (이 종목의 가장 최근 판정)")
            st.markdown(md_safe(sec))
        else:
            st.caption("판정 없음 — 사이드바 '판정 새로 받기' 또는 /checkup 실행 시 생성됩니다.")
        er = latest_report(f"earnings-{sel}-")
        if er:
            with st.expander(f"실적 리뷰: {er.name}"):
                st.markdown(md_safe(er.read_text()))

    st.subheader("이 종목의 알림 이력")
    al = [a for a in sheet["alerts"] if a.get("ticker") == sel]
    if al:
        st.dataframe(pd.DataFrame(al)[["sent_at", "lot_id", "condition",
                                       "base_price", "price", "change_pct"]]
                     .rename(columns={"sent_at": "발송시각", "lot_id": "lot",
                                      "condition": "조건", "base_price": "기준$",
                                      "price": "현재$", "change_pct": "등락%"})
                     .tail(20), hide_index=True)
    else:
        st.caption("알림 이력 없음")

    st.subheader("이 종목의 매매 기록")
    tr = [t for t in sheet["trades"] if t.get("ticker") == sel]
    if tr:
        st.dataframe(pd.DataFrame(tr)[["trade_date", "side", "qty", "price", "note"]]
                     .rename(columns={"trade_date": "체결일", "side": "구분",
                                      "qty": "수량", "price": "단가$", "note": "비고"})
                     .tail(20), hide_index=True)
    else:
        st.caption("시트 기록 없음 (봇 가동 이후 체결만 기록됨)")


# ── 탭 3: 리포트 ────────────────────────────────────────────

with tab_report:
    files = sorted(REPORTS.glob("*.md"), reverse=True)
    if not files:
        st.caption("저장된 리포트 없음 — /checkup 또는 /earnings 실행 시 생성됩니다.")
    else:
        pick = st.selectbox("리포트 선택", files, format_func=lambda p: p.name)
        text = pick.read_text()
        items, port, health, action = ([], None, None, None)
        if pick.name.startswith("checkup-"):
            items, port, health, action = parse_checkup(text)
        if items:
            hkey = next((k for k in HEALTH_PILL if health and health.startswith(k)), None)
            hfg, hbg = HEALTH_PILL.get(hkey, ("#555B6E", "#EEEFF4"))
            counts = {}
            for v in items:
                key = next((k for k in VERDICT_PILL if v["verdict"].startswith(k)), "기타")
                counts[key] = counts.get(key, 0) + 1
            chips = " · ".join(f"{k} {n}" for k, n in counts.items())
            st.markdown(
                f"<div style='background:#fff;border:1px solid {LINE};border-radius:14px;"
                f"padding:15px 18px;margin:6px 0 14px;box-shadow:0 1px 3px rgba(20,24,60,.05)'>"
                f"<div style='display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:8px'>"
                f"<span style='font-weight:800;font-size:1.15rem;color:{INK}'>판정 요약 — {len(items)}종목</span>"
                f"<span style='background:{hbg};color:{hfg};border-radius:999px;padding:4px 14px;"
                f"font-weight:700;font-size:.88rem'>건강도: {_esc(health or '미기재')}</span>"
                f"<span style='color:{MUTED};font-size:.82rem'>{chips}</span></div>"
                f"<div style='color:{INK};font-size:.9rem'><b>최우선 조치</b> · "
                f"{_esc(action or '미기재', 170)}</div></div>",
                unsafe_allow_html=True)
            st.markdown("<div style='display:flex;gap:12px;flex-wrap:wrap'>"
                        + "".join(verdict_card(v) for v in items) + "</div>",
                        unsafe_allow_html=True)
            st.markdown("")
            if port:
                with st.expander("포트폴리오 차원 진단 (전문)"):
                    st.markdown(md_safe(port))
            sel_t = st.selectbox("종목별 상세 판정 펼쳐보기",
                                 ["선택 안 함"] + [v["ticker"] for v in items])
            if sel_t != "선택 안 함":
                st.markdown(md_safe(next(v["sec"] for v in items if v["ticker"] == sel_t)))
            with st.expander("리포트 원문 전체"):
                st.markdown(md_safe(text))
        else:
            st.markdown(md_safe(text))
