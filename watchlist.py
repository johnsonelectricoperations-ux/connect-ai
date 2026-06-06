#!/usr/bin/env python3
# Connect AI · 관심종목 DB + 실적 캘린더
#
# 사용법:
#   py watchlist.py                    → 전체 목록 + 실적 임박 알림
#   py watchlist.py add IONQ AAPL      → 종목 추가
#   py watchlist.py remove IONQ        → 종목 삭제
#   py watchlist.py calendar           → 실적 캘린더 (날짜순)
#   py watchlist.py sync               → yfinance로 earningsDate 일괄 갱신
#   py watchlist.py note IONQ "메모"   → 메모 설정
#
# 저장:
#   watchlist.json  — 메타데이터 DB (추가일·메모·실적일·마지막 스코어)
#   watchlist.txt   — screen.py 호환용 단순 목록 (자동 동기화)
#
# 실패 시 {"error": ...}. AI는 error/null이면 날조 금지.

import sys, json, os, re
from datetime import date, datetime, timezone, timedelta

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_DB_PATH  = "watchlist.json"
_TXT_PATH = "watchlist.txt"
_EARNINGS_ALERT_DAYS = 7   # 이 일수 이내면 "실적 임박" 경보


# ─────────────────────────────────────────────────────────────
# DB 읽기/쓰기
# ─────────────────────────────────────────────────────────────

def _load_db():
    """watchlist.json 읽기. 없으면 빈 dict."""
    if not os.path.exists(_DB_PATH):
        return {}
    try:
        with open(_DB_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_db(db):
    """watchlist.json 저장 + watchlist.txt 동기화."""
    with open(_DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)
    _sync_txt(db)


def _sync_txt(db):
    """watchlist.txt를 DB 티커 목록과 동기화.
    기존 txt의 주석(#)·빈줄은 보존하고, DB에 없는 티커 줄만 제거 후
    DB에 새로 추가된 티커를 맨 끝에 추가한다."""
    existing_lines = []
    existing_tickers = set()

    if os.path.exists(_TXT_PATH):
        with open(_TXT_PATH, encoding="utf-8-sig") as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith("#") or not stripped:
                    existing_lines.append(line.rstrip("\n"))
                else:
                    tk = stripped.upper()
                    if tk in db:
                        existing_lines.append(tk)
                        existing_tickers.add(tk)
                    # DB에 없는 티커는 제거 (삭제 동기화)

    # DB에 있지만 txt에 없는 새 티커 추가
    for tk in db:
        if tk not in existing_tickers:
            existing_lines.append(tk)

    with open(_TXT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(existing_lines))
        if existing_lines:
            f.write("\n")


# ─────────────────────────────────────────────────────────────
# watchlist.txt → DB 마이그레이션 (최초 1회)
# ─────────────────────────────────────────────────────────────

def _migrate_from_txt():
    """watchlist.txt가 있고 watchlist.json이 없으면 자동 마이그레이션."""
    if os.path.exists(_DB_PATH):
        return
    if not os.path.exists(_TXT_PATH):
        return
    db = {}
    today = date.today().isoformat()
    with open(_TXT_PATH, encoding="utf-8-sig") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            tk = s.upper()
            db[tk] = {"added": today, "note": "", "earningsDate": None, "lastScore": None}
    if db:
        with open(_DB_PATH, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=2)


# ─────────────────────────────────────────────────────────────
# earningsDate yfinance 조회
# ─────────────────────────────────────────────────────────────

def _fetch_earnings_date(ticker):
    """yfinance로 다음 실적 발표일 조회. 없거나 실패 시 None."""
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info
        ed = info.get("earningsDate") or info.get("earningsTimestamp")
        if ed is None:
            # calendar 시도
            cal = yf.Ticker(ticker).calendar
            if cal is not None and not cal.empty:
                row = cal.get("Earnings Date")
                if row is not None and len(row) > 0:
                    ed = row.iloc[0]
        if ed is None:
            return None
        # Timestamp → 문자열
        if hasattr(ed, "date"):
            return ed.date().isoformat()
        if isinstance(ed, (int, float)):
            return datetime.fromtimestamp(ed, tz=timezone.utc).date().isoformat()
        s = str(ed)[:10]
        if re.match(r'\d{4}-\d{2}-\d{2}', s):
            return s
        return None
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────
# 실적 임박 계산
# ─────────────────────────────────────────────────────────────

def _days_until(date_str):
    """'YYYY-MM-DD' → 오늘로부터 남은 일수. 과거면 음수. 파싱 실패면 None."""
    if not date_str:
        return None
    try:
        target = date.fromisoformat(date_str[:10])
        return (target - date.today()).days
    except ValueError:
        return None


def _earnings_alert(days):
    """남은 일수 → alert 문자열."""
    if days is None:
        return None
    if days < 0:
        return f"실적 발표 완료 ({abs(days)}일 전)"
    if days == 0:
        return "오늘 실적 발표"
    if days <= _EARNINGS_ALERT_DAYS:
        return f"실적 {days}일 후 임박"
    return None


# ─────────────────────────────────────────────────────────────
# 명령 구현
# ─────────────────────────────────────────────────────────────

def cmd_list(db):
    """전체 목록 + 실적 임박 알림."""
    items = []
    alerts = []
    today = date.today().isoformat()

    for tk, meta in sorted(db.items()):
        days = _days_until(meta.get("earningsDate"))
        alert = _earnings_alert(days)
        entry = {
            "ticker": tk,
            "added": meta.get("added"),
            "note": meta.get("note") or "",
            "earningsDate": meta.get("earningsDate"),
            "lastScore": meta.get("lastScore"),
        }
        if alert:
            entry["earningsAlert"] = alert
            if days is not None and 0 <= days <= _EARNINGS_ALERT_DAYS:
                alerts.append({"ticker": tk, "earningsAlert": alert, "earningsDate": meta.get("earningsDate")})
        items.append(entry)

    result = {
        "total": len(items),
        "as_of": today,
        "watchlist": items,
    }
    if alerts:
        result["urgent_alerts"] = alerts
    result["note"] = (
        "watchlist 관심종목 목록. earningsDate=다음 실적 발표일(YYYY-MM-DD). "
        "earningsAlert=실적 임박 경보(7일 이내). lastScore=마지막 screen.py 스코어. "
        "urgent_alerts=실적 7일 이내 종목. null이면 데이터 없음 — 지어내지 말 것."
    )
    return result


def cmd_add(db, tickers):
    """종목 추가."""
    today = date.today().isoformat()
    added = []
    already = []
    for tk in tickers:
        tk = tk.upper().strip()
        if not re.match(r'^[A-Z]{1,5}$', tk):
            continue
        if tk in db:
            already.append(tk)
        else:
            db[tk] = {"added": today, "note": "", "earningsDate": None, "lastScore": None}
            added.append(tk)
    _save_db(db)
    return {"added": added, "already_existed": already, "total": len(db)}


def cmd_remove(db, tickers):
    """종목 삭제."""
    removed = []
    not_found = []
    for tk in tickers:
        tk = tk.upper().strip()
        if tk in db:
            del db[tk]
            removed.append(tk)
        else:
            not_found.append(tk)
    _save_db(db)
    return {"removed": removed, "not_found": not_found, "total": len(db)}


def cmd_calendar(db):
    """실적 캘린더 — earningsDate 기준 정렬."""
    today_str = date.today().isoformat()
    items = []
    no_date = []

    for tk, meta in db.items():
        ed = meta.get("earningsDate")
        if ed:
            days = _days_until(ed)
            items.append({
                "ticker": tk,
                "earningsDate": ed,
                "days_until": days,
                "earningsAlert": _earnings_alert(days),
                "note": meta.get("note") or "",
            })
        else:
            no_date.append(tk)

    # 날짜 오름차순 정렬 (미래 → 과거)
    items.sort(key=lambda x: x["earningsDate"])

    # 미래/과거 분리
    upcoming = [i for i in items if (i["days_until"] or -999) >= 0]
    past = [i for i in items if (i["days_until"] or -999) < 0]

    result = {
        "as_of": today_str,
        "upcoming": upcoming,
        "past_recent": past[-5:],   # 최근 5건만
        "no_earnings_date": no_date,
        "note": (
            "실적 캘린더. upcoming=예정 실적 발표(날짜 오름차순). "
            "days_until=오늘로부터 남은 일수(0=오늘, 음수=과거). "
            "earningsAlert=7일 이내 경보. no_earnings_date=실적일 미확인 종목. "
            "null이면 데이터 없음 — 지어내지 말 것."
        ),
    }
    return result


def cmd_sync(db):
    """yfinance로 전 종목 earningsDate 일괄 갱신."""
    updated = []
    failed = []
    for tk in list(db.keys()):
        ed = _fetch_earnings_date(tk)
        if ed:
            db[tk]["earningsDate"] = ed
            updated.append({"ticker": tk, "earningsDate": ed})
        else:
            failed.append(tk)
    _save_db(db)
    return {
        "updated": updated,
        "failed": failed,
        "total_updated": len(updated),
        "note": "earningsDate가 null인 종목은 yfinance 미제공 또는 조회 실패.",
    }


def cmd_note(db, ticker, note_text):
    """메모 설정."""
    tk = ticker.upper().strip()
    if tk not in db:
        return {"error": f"{tk} 은 watchlist에 없습니다. 먼저 add 하세요."}
    db[tk]["note"] = note_text
    _save_db(db)
    return {"ticker": tk, "note": note_text}


# ─────────────────────────────────────────────────────────────
# 공개 API (screen.py 등 import 용)
# ─────────────────────────────────────────────────────────────

def load_watchlist_db():
    """watchlist.json 로드. 없으면 txt에서 마이그레이션 후 반환."""
    _migrate_from_txt()
    return _load_db()


def update_score(ticker, score):
    """screen.py가 스코어 계산 후 DB에 기록할 때 사용."""
    db = _load_db()
    tk = ticker.upper()
    if tk in db:
        db[tk]["lastScore"] = score
        _save_db(db)


def get_upcoming_earnings(days_ahead=7):
    """실적 임박 종목 목록 반환. Phase 7 알림 시스템에서 사용."""
    db = load_watchlist_db()
    result = []
    for tk, meta in db.items():
        d = _days_until(meta.get("earningsDate"))
        if d is not None and 0 <= d <= days_ahead:
            result.append({
                "ticker": tk,
                "earningsDate": meta["earningsDate"],
                "days_until": d,
            })
    result.sort(key=lambda x: x["days_until"])
    return result


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────

def main():
    _migrate_from_txt()
    db = _load_db()

    args = sys.argv[1:]

    if not args:
        result = cmd_list(db)
    elif args[0] == "add" and len(args) >= 2:
        result = cmd_add(db, args[1:])
    elif args[0] == "remove" and len(args) >= 2:
        result = cmd_remove(db, args[1:])
    elif args[0] == "calendar":
        result = cmd_calendar(db)
    elif args[0] == "sync":
        result = cmd_sync(db)
    elif args[0] == "note" and len(args) >= 3:
        result = cmd_note(db, args[1], " ".join(args[2:]))
    else:
        result = {"error": "사용법: py watchlist.py [add|remove|calendar|sync|note] [인수...]"}

    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
