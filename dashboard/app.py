"""Jaewon's Stock Dashboard (Streamlit) — 표시 전용 층.

실행 (반드시 저장소 루트에서):
  .venv/bin/streamlit run dashboard/app.py
접속: http://localhost:8501

- 조회 전용: 주문 관련 기능 없음. 봇·스킬이 만든 데이터를 보여주기만 한다.
- localhost 전용(.streamlit/config.toml): 계좌 전체가 표시되므로 외부 배포 금지.
- 색상: 한국 관례(상승 빨강·하락 파랑) + 부호 병기(색만으로 구분하지 않음).
- "분석 갱신" 버튼: scripts/run_checkup.sh 로 /checkup 을 헤드리스 재실행 (수 분 소요).
"""
import json
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
    st.cache_data.clear()
    st.rerun()

st.sidebar.divider()
st.sidebar.markdown("**분석 갱신**")
running, run_info = checkup_status()
if running:
    st.sidebar.info(f"체크업 실행 중 ({run_info.get('started_at', '')} 시작)\n\n"
                    "완료까지 수 분 걸립니다. 잠시 후 '데이터 새로고침'을 누르세요.")
else:
    if st.sidebar.button("판정 새로 받기 (/checkup)", width="stretch"):
        if not shutil.which("claude"):
            st.sidebar.error("claude CLI를 찾을 수 없습니다. 터미널에서 /checkup을 실행하세요.")
        else:
            subprocess.Popen(["bash", str(ROOT / "scripts/run_checkup.sh")],
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
checkup_text = checkup_file.read_text() if checkup_file else ""


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
            (verdict_of(report_section(checkup_text, t))[0] or "") for t in df["ticker"]]
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

    sec = report_section(checkup_text, sel)
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
            st.caption(f"출처: {checkup_file.name}")
            st.markdown(sec)
        else:
            st.caption("판정 없음 — 사이드바 '판정 새로 받기' 또는 /checkup 실행 시 생성됩니다.")
        er = latest_report(f"earnings-{sel}-")
        if er:
            with st.expander(f"실적 리뷰: {er.name}"):
                st.markdown(er.read_text())

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
    if files:
        pick = st.selectbox("리포트 선택", files, format_func=lambda p: p.name)
        st.markdown(pick.read_text())
    else:
        st.caption("저장된 리포트 없음 — /checkup 또는 /earnings 실행 시 생성됩니다.")
