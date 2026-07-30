#!/usr/bin/env python
"""봇 하트비트 감시 — launchd가 15분마다 실행 (com.jaewon.stock-alert-watchdog).

1) data/heartbeat.json 이 STALE_SEC 이상 묵으면: 봇 자동 재시작 + 이메일 경고
   (경고는 6시간 스로틀 — 재시작 자체는 매번 시도)
2) 하루 1회 잔고-lot 정합성 검사(scripts/reconcile.py) — 위반 시 이메일

결정론적·조회 전용. 실패는 다음 주기에 자연 재시도된다.
사용: watchdog.py [--dry-run]   (dry-run: 감지만 하고 재시작·이메일 생략)
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from src import config  # noqa: E402
from src.notifier import Notifier  # noqa: E402

KST = ZoneInfo("Asia/Seoul")
BOT_LABEL = "com.jaewon.stock-alert"
STALE_SEC = 90 * 60  # 봇 최장 사이클(장외 30분)의 3배
WARN_THROTTLE_SEC = 6 * 3600


def _log(msg):
    print(f"[{datetime.now(KST).strftime('%m-%d %H:%M:%S')}] {msg}", flush=True)


def _heartbeat_age():
    """하트비트 나이(초). 파일 없음/손상이면 None."""
    try:
        hb = json.loads(Path(config.HEARTBEAT_PATH).read_text())
        ts = datetime.fromisoformat(hb["ts"])
        return (datetime.now(KST) - ts).total_seconds()
    except (OSError, ValueError, KeyError):
        return None


def _throttled(name, limit):
    """마커 파일 기반 스로틀. True면 아직 조용히 있을 시간."""
    marker = ROOT / "data" / name
    try:
        last = float(marker.read_text())
    except (OSError, ValueError):
        last = 0.0
    if time.time() - last < limit:
        return True
    try:
        marker.write_text(str(time.time()))
    except OSError:
        pass
    return False


def check_heartbeat(dry):
    age = _heartbeat_age()
    if age is not None and age < STALE_SEC:
        return
    desc = "하트비트 파일 없음" if age is None else f"마지막 동작 {age / 60:.0f}분 전"
    if dry:
        _log(f"[dry-run] 봇 무응답 감지({desc}) — 재시작·이메일 생략")
        return
    r = subprocess.run(
        ["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{BOT_LABEL}"],
        capture_output=True, text=True)
    restarted = "성공" if r.returncode == 0 else f"실패: {(r.stderr or '').strip()}"
    _log(f"봇 무응답 감지({desc}) → 자동 재시작 {restarted}")
    if _throttled("watchdog_warn_last.txt", WARN_THROTTLE_SEC):
        return
    # 봇이 죽었을 때 카톡(봇 경유)도 같이 죽었을 수 있으므로 이메일로 직접 발송
    Notifier()._send_email(
        "[stock-alert] 봇 무응답 감지 — 자동 재시작",
        f"{desc}\n자동 재시작: {restarted}\n"
        "확인: tail -20 logs/stdout.log · logs/watchdog.log")


def daily_reconcile(dry):
    marker = ROOT / "data" / "reconcile_last.txt"
    today = datetime.now(KST).strftime("%Y-%m-%d")
    try:
        if marker.read_text().strip() == today:
            return
    except OSError:
        pass
    if dry:
        _log("[dry-run] 정합성 검사 생략")
        return
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "reconcile.py"), "--email-on-violation"],
        capture_output=True, text=True, timeout=180)
    first = r.stdout.strip().splitlines()[0] if r.stdout.strip() else ""
    _log(f"정합성 검사 exit={r.returncode}" + (f" — {first}" if first else ""))
    if r.returncode in (0, 1):  # 2(실행 오류)는 마킹 없이 다음 주기 재시도
        try:
            marker.write_text(today)
        except OSError:
            pass


def main():
    dry = "--dry-run" in sys.argv
    check_heartbeat(dry)
    daily_reconcile(dry)


if __name__ == "__main__":
    main()
