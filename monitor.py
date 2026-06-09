#!/usr/bin/env python3
# Connect AI · 운영 스케줄러 + 알림 (v5 §9)
#
# 사용법:
#   py monitor.py --daily          → 매일 작업 (레짐·가격손절·Market Score)
#   py monitor.py --weekly         → 주 1회 작업 (Exit Score [B][C])
#   py monitor.py --biweekly       → 주 2회 작업 (Screen Score·Buy Score 재계산)
#   py monitor.py --daemon         → 데몬 모드 (스케줄러 상시 실행, 장 마감 후 자동)
#   py monitor.py --run-now TASK   → 즉시 실행 (daily|weekly|biweekly)
#   py monitor.py --status         → 마지막 실행 시각 확인
#
# v5 운영 스케줄 (§9):
#   매일    (장 마감 후)  Market Score 갱신 · 레짐 게이트 · 가격 손절 체크
#   주 2회  (월/목)      Screen Score · Buy Score 재계산
#   주 1회  (월)         Exit Score [B][C] 체크
#   분기                 Fundamental Score 강제 갱신 · Deep Analysis
#
# 텔레그램 알림:
#   환경변수 TELEGRAM_TOKEN + TELEGRAM_CHAT_ID 설정 시 활성화.
#   없으면 콘솔 출력만.
#
# 상태 파일: monitor_state.json (마지막 실행 시각 기록)

import sys, json, os, subprocess, datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_DIR          = Path(__file__).resolve().parent
_STATE_FILE   = _DIR / "monitor_state.json"
_WATCHLIST_TXT = _DIR / "watchlist.txt"

# 텔레그램
_TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
_TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# 스크리닝 유니버스 (tenbagger 기본)
_DEFAULT_SCREEN_THEME = "tenbagger"

# 스케줄 (UTC 기준, 미국 동부 장 마감 오후 4시 = UTC 21:00)
_DAILY_HOUR_UTC = 21   # 장 마감 후 (서머타임 조정 없음 — 운영자 확인)


# ─────────────────────────────────────────────────────────────
# 상태 관리
# ─────────────────────────────────────────────────────────────

def _load_state():
    if _STATE_FILE.exists():
        try:
            with open(_STATE_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_state(state):
    with open(_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _mark_run(task_name, state):
    state[task_name] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _save_state(state)


# ─────────────────────────────────────────────────────────────
# Python 실행 헬퍼
# ─────────────────────────────────────────────────────────────

def _run_py(script_name, *args, capture=True):
    """py {script_name} {args} 실행. 결과 JSON 반환 or None."""
    cmd = [sys.executable, str(_DIR / f"{script_name}.py")] + list(args)
    try:
        r = subprocess.run(cmd, capture_output=capture, text=True, timeout=120,
                           cwd=str(_DIR), encoding="utf-8")
        if capture and r.stdout.strip():
            try:
                return json.loads(r.stdout.strip())
            except json.JSONDecodeError:
                return {"raw": r.stdout.strip()}
        return {"returncode": r.returncode}
    except subprocess.TimeoutExpired:
        return {"error": f"{script_name} 실행 타임아웃"}
    except Exception as e:
        return {"error": str(e)}


# ─────────────────────────────────────────────────────────────
# 텔레그램 알림
# ─────────────────────────────────────────────────────────────

def _send_telegram(msg):
    """텔레그램 메시지 전송. 환경변수 미설정 시 콘솔 출력."""
    if not _TELEGRAM_TOKEN or not _TELEGRAM_CHAT_ID:
        print(f"[알림] {msg}")
        return
    try:
        import urllib.request, urllib.parse
        url = f"https://api.telegram.org/bot{_TELEGRAM_TOKEN}/sendMessage"
        payload = json.dumps({
            "chat_id":    _TELEGRAM_CHAT_ID,
            "text":       msg,
            "parse_mode": "HTML",
        }).encode()
        req = urllib.request.Request(url, data=payload,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            pass
    except Exception as e:
        print(f"[텔레그램 실패] {e}")
        print(f"[알림 폴백] {msg}")


# ─────────────────────────────────────────────────────────────
# 태스크: 매일 (Daily)
# ─────────────────────────────────────────────────────────────

def task_daily(state, verbose=True):
    """매일 장 마감 후: 레짐 게이트 + 가격 손절 체크 + 알림."""
    today = datetime.date.today().isoformat()
    alerts = []

    # 1. 레짐 게이트
    regime_result = _run_py("regime")
    regime = regime_result.get("regime", "UNKNOWN") if isinstance(regime_result, dict) else "UNKNOWN"

    if regime == "RISK_OFF":
        alerts.append("시장 레짐: RISK_OFF — 신규 매수 차단")
    elif regime == "CAUTION":
        alerts.append("시장 레짐: CAUTION — 사이즈 50% 축소, Buy Score +5 요구")

    if verbose:
        print(f"[Daily] 레짐: {regime}")

    # 2. 가격 손절 체크 (portfolio.csv가 있을 때)
    if (_DIR / "portfolio.csv").exists():
        exit_result = _run_py("exit_score")
        if isinstance(exit_result, dict):
            summary = exit_result.get("summary", {})
            immediate = summary.get("immediate_action", [])
            review    = summary.get("review_needed", [])
            if immediate:
                alerts.append(f"즉시 매도 검토: {', '.join(immediate)}")
            if review:
                alerts.append(f"Exit Review 필요: {', '.join(review)}")
            if verbose:
                print(f"[Daily] 가격 손절 체크 완료: 즉시={immediate}, 검토={review}")
    else:
        if verbose:
            print("[Daily] portfolio.csv 없음 — 가격 손절 체크 생략")

    # 알림 발송
    if alerts:
        msg_lines = [f"<b>Connect AI Daily ({today})</b>"] + [f"• {a}" for a in alerts]
        _send_telegram("\n".join(msg_lines))
    else:
        if verbose:
            print(f"[Daily] 이상 없음 — 레짐 {regime}, 손절 미발동")

    _mark_run("daily", state)
    return {"date": today, "regime": regime, "alerts": alerts}


# ─────────────────────────────────────────────────────────────
# 태스크: 주 2회 (Biweekly — 월·목)
# ─────────────────────────────────────────────────────────────

def task_biweekly(state, verbose=True):
    """주 2회 (월/목): Screen Score 실행 → 관심종목 자동 등록."""
    today = datetime.date.today().isoformat()
    alerts = []

    screen_result = _run_py("screen", "suggest", "tenbagger")
    if isinstance(screen_result, dict) and "ranked" in screen_result:
        ranked = screen_result["ranked"]
        top5 = ranked[:5]
        top_tickers = [r.get("ticker") for r in top5 if r.get("ticker")]
        if top_tickers:
            alerts.append(f"Screen 상위 5: {', '.join(top_tickers)}")
        if verbose:
            print(f"[Biweekly] Screen 완료: 상위5={top_tickers}")
    else:
        if verbose:
            print(f"[Biweekly] Screen 결과 이상: {screen_result}")

    if alerts:
        msg_lines = [f"<b>Connect AI Biweekly ({today})</b>"] + [f"• {a}" for a in alerts]
        _send_telegram("\n".join(msg_lines))

    _mark_run("biweekly", state)
    return {"date": today, "alerts": alerts}


# ─────────────────────────────────────────────────────────────
# 태스크: 주 1회 (Weekly — 월)
# ─────────────────────────────────────────────────────────────

def task_weekly(state, verbose=True):
    """주 1회 (월): Exit Score [B][C] 펀더멘털 악화 체크."""
    today = datetime.date.today().isoformat()
    alerts = []

    if not (_DIR / "portfolio.csv").exists():
        if verbose:
            print("[Weekly] portfolio.csv 없음 — 건너뜀")
        _mark_run("weekly", state)
        return {"date": today, "alerts": []}

    exit_result = _run_py("exit_score")
    if isinstance(exit_result, dict):
        for pos in exit_result.get("exit_report", []):
            urgency  = pos.get("urgency", "LOW")
            ticker   = pos.get("ticker", "")
            bc_score = pos.get("section_BC", {}).get("score", 0)
            b_flags  = pos.get("section_BC", {}).get("b_flags", [])
            if urgency in ("HIGH", "MEDIUM") and b_flags:
                alerts.append(f"{ticker} [B][C] {bc_score}점: {'; '.join(b_flags)}")
        if verbose:
            print(f"[Weekly] Exit [B][C] 체크 완료: 알림 {len(alerts)}건")

    if alerts:
        msg_lines = [f"<b>Connect AI Weekly ({today})</b>"] + [f"• {a}" for a in alerts]
        _send_telegram("\n".join(msg_lines))

    _mark_run("weekly", state)
    return {"date": today, "alerts": alerts}


# ─────────────────────────────────────────────────────────────
# 상태 출력
# ─────────────────────────────────────────────────────────────

def print_status(state):
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    print(json.dumps({
        "now_utc":   now,
        "last_daily":    state.get("daily",    "미실행"),
        "last_biweekly": state.get("biweekly", "미실행"),
        "last_weekly":   state.get("weekly",   "미실행"),
        "telegram_enabled": bool(_TELEGRAM_TOKEN and _TELEGRAM_CHAT_ID),
        "portfolio_exists": (_DIR / "portfolio.csv").exists(),
    }, ensure_ascii=False))


# ─────────────────────────────────────────────────────────────
# 데몬 모드
# ─────────────────────────────────────────────────────────────

def run_daemon():
    """스케줄러 데몬 모드. schedule 라이브러리 사용, 없으면 간단 루프 실행."""
    try:
        import schedule, time

        state = _load_state()

        # 매일 UTC 21:00 (미국 동부 장 마감 오후 4시)
        schedule.every().day.at(f"{_DAILY_HOUR_UTC:02d}:05").do(
            lambda: task_daily(_load_state())
        )
        # 월요일·목요일 Screen
        schedule.every().monday.at(f"{_DAILY_HOUR_UTC:02d}:15").do(
            lambda: task_biweekly(_load_state())
        )
        schedule.every().thursday.at(f"{_DAILY_HOUR_UTC:02d}:15").do(
            lambda: task_biweekly(_load_state())
        )
        # 월요일 Exit [B][C]
        schedule.every().monday.at(f"{_DAILY_HOUR_UTC:02d}:30").do(
            lambda: task_weekly(_load_state())
        )

        print(f"[Daemon] 스케줄러 시작 (UTC {_DAILY_HOUR_UTC:02d}:xx). Ctrl+C로 종료.")
        while True:
            schedule.run_pending()
            time.sleep(60)

    except ImportError:
        print(json.dumps({
            "error": "schedule 라이브러리 미설치. 'pip install schedule' 실행.",
            "alternative": "py monitor.py --run-now daily  # 즉시 개별 실행",
        }, ensure_ascii=False))


# ─────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    state = _load_state()

    if not args:
        print(json.dumps({
            "usage": {
                "--daily":         "매일 작업 즉시 실행 (레짐·가격손절)",
                "--weekly":        "주 1회 작업 즉시 실행 (Exit [B][C])",
                "--biweekly":      "주 2회 작업 즉시 실행 (Screen Score)",
                "--daemon":        "데몬 모드 (schedule 라이브러리 필요: pip install schedule)",
                "--status":        "마지막 실행 시각 확인",
                "--run-now TASK":  "즉시 실행 (daily|weekly|biweekly)",
            },
            "telegram": {
                "setup": "환경변수 TELEGRAM_TOKEN, TELEGRAM_CHAT_ID 설정 시 알림 활성화",
                "enabled": bool(_TELEGRAM_TOKEN and _TELEGRAM_CHAT_ID),
            },
        }, ensure_ascii=False))
        return

    if "--status" in args:
        print_status(state)
        return

    if "--daemon" in args:
        run_daemon()
        return

    if "--daily" in args or ("--run-now" in args and "daily" in args):
        result = task_daily(state)
        print(json.dumps(result, ensure_ascii=False))
        return

    if "--biweekly" in args or ("--run-now" in args and "biweekly" in args):
        result = task_biweekly(state)
        print(json.dumps(result, ensure_ascii=False))
        return

    if "--weekly" in args or ("--run-now" in args and "weekly" in args):
        result = task_weekly(state)
        print(json.dumps(result, ensure_ascii=False))
        return

    print(json.dumps({"error": f"알 수 없는 인수: {args}. py monitor.py 로 사용법 확인."}, ensure_ascii=False))


if __name__ == "__main__":
    main()
