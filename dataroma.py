#!/usr/bin/env python3
# Connect AI · Dataroma 슈퍼인베스터 최근 활동 헬퍼
#
# 사용법:
#   py dataroma.py AAPL          → AAPL 관련 슈퍼인베스터 최근 활동
#   py dataroma.py IONQ          → 활동 없으면 {"holders": [], "summary": {...}}
#   py dataroma.py --top 20      → 최근 분기 가장 많이 거래된 상위 20 종목
#
# 목적: 피터 린치·워런 버핏 등 검증된 투자자가 최근 분기에 사고 판 종목을
#       텐배거 발굴 보조 검증 소스로 활용.
#       "슈퍼인베스터 3명+ 최근 매수" = 고급 검증 시그널.
#
# 데이터: Dataroma.com allact.php (무료, 13F 기반, 분기별 업데이트)
#         stock.php는 JS 렌더링 필요 → allact.php(최근 활동 전체) 사용.
# 외부 라이브러리 없이 stdlib만 사용.
# 실패 시 {"error": ...}. AI는 error/null이면 날조 금지.

import sys, json, re, urllib.request, urllib.error, html as html_mod

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Referer": "https://www.dataroma.com/",
    "Connection": "keep-alive",
}

_BASE = "https://www.dataroma.com"
_ALLACT_URL = f"{_BASE}/m/allact.php?typ=a"


def _http_get(url, timeout=20):
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        try:
            import gzip
            if r.info().get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
        except Exception:
            pass
        return raw.decode("utf-8", errors="replace")


def _unescape(s):
    return html_mod.unescape(s).strip()


def _strip_tags(s):
    return _unescape(re.sub(r'<[^>]+>', '', s))


# ─────────────────────────────────────────────────────────────
# allact.php 파싱
# HTML 구조:
#   <tr>
#     <td class="firm"><a href="...">Manager Name</a></td>
#     <td class="period">Q1 2026</td>
#     <td class="sym">
#       <div ...>
#         <a class="buy|sell|add|reduce" href="/m/activity.php?sym=TICKER&typ=a">TICKER</a>
#         <div class="tooltip_container">...</div>
#       </div>
#     </td>
#     ...
#   </tr>
# ─────────────────────────────────────────────────────────────

def _fetch_allact():
    """allact.php 전체 파싱 → 행 목록.

    각 행: {firm, period, tickers: [{ticker, action}]}
    실패 시 None.
    """
    try:
        html = _http_get(_ALLACT_URL)
    except Exception:
        return None

    rows = []
    for tr_m in re.finditer(r'<tr[^>]*>([\s\S]*?)</tr>', html, re.IGNORECASE):
        tr_html = tr_m.group(1)

        # firm 셀
        firm_m = re.search(r'<td[^>]*class=["\']firm["\'][^>]*>([\s\S]*?)</td>', tr_html, re.IGNORECASE)
        if not firm_m:
            continue
        firm = _strip_tags(firm_m.group(1))
        if not firm:
            continue

        # period 셀
        period_m = re.search(r'<td[^>]*class=["\']period["\'][^>]*>([\s\S]*?)</td>', tr_html, re.IGNORECASE)
        period = _strip_tags(period_m.group(1)) if period_m else ""

        # sym 셀들 — 각 셀에 ticker 링크
        tickers = []
        for sym_m in re.finditer(r'<td[^>]*class=["\']sym["\'][^>]*>([\s\S]*?)</td>', tr_html, re.IGNORECASE):
            sym_html = sym_m.group(1)
            # <a class="buy|sell|add|reduce" href="...sym=TICKER...">TICKER</a>
            for a_m in re.finditer(
                r'<a[^>]*class=["\']([^"\']+)["\'][^>]*href=["\'][^"\']*sym=([A-Z]{1,5})[^"\']*["\'][^>]*>([^<]+)</a>',
                sym_html, re.IGNORECASE
            ):
                action_cls = a_m.group(1).strip().lower()
                ticker = a_m.group(2).strip().upper()
                if ticker:
                    tickers.append({"ticker": ticker, "action": action_cls})

        if tickers:
            rows.append({"firm": firm, "period": period, "tickers": tickers})

    return rows if rows else None


# ─────────────────────────────────────────────────────────────
# 공개 API
# ─────────────────────────────────────────────────────────────

def fetch_holders(ticker):
    """특정 종목의 슈퍼인베스터 최근 활동.

    반환: {
        ticker, holders: [
            {firm, period, action}
        ],
        summary: {
            total_holders, buy_add_count, reduce_sell_count,
            latest_period, signal
        }
    }
    실패 시 None (graceful).
    """
    try:
        rows = _fetch_allact()
        if rows is None:
            return None

        tk = ticker.upper().strip()
        holders = []
        for row in rows:
            for t in row["tickers"]:
                if t["ticker"] == tk:
                    holders.append({
                        "firm": row["firm"],
                        "period": row["period"],
                        "action": t["action"],
                    })
                    break  # 같은 행에서 같은 종목 중복 방지

        buy_add = sum(1 for h in holders if h["action"] in ("buy", "add"))
        reduce_sell = sum(1 for h in holders if h["action"] in ("reduce", "sell"))
        periods = [h["period"] for h in holders if h.get("period")]
        latest_period = periods[0] if periods else None

        n = len(holders)
        if n >= 5:
            signal = "strong_conviction"
        elif n >= 3:
            signal = "multi_holder"
        elif n >= 1:
            signal = "single_holder"
        else:
            signal = "no_holder"

        return {
            "ticker": tk,
            "holders": holders,
            "summary": {
                "total_holders": n,
                "buy_add_count": buy_add,
                "reduce_sell_count": reduce_sell,
                "latest_period": latest_period,
                "signal": signal,
            },
        }
    except Exception:
        return None


def fetch_top_stocks(limit=20):
    """최근 분기 슈퍼인베스터 활동 기준 상위 종목.

    반환: {stocks: [{ticker, count, buy_count, sell_count}], count: int}
    실패 시 None.
    """
    try:
        rows = _fetch_allact()
        if rows is None:
            return None

        from collections import Counter
        total_c = Counter()
        buy_c = Counter()
        sell_c = Counter()
        for row in rows:
            for t in row["tickers"]:
                tk = t["ticker"]
                total_c[tk] += 1
                if t["action"] in ("buy", "add"):
                    buy_c[tk] += 1
                elif t["action"] in ("reduce", "sell"):
                    sell_c[tk] += 1

        stocks = []
        for tk, cnt in total_c.most_common(limit):
            stocks.append({
                "ticker": tk,
                "count": cnt,
                "buy_count": buy_c.get(tk, 0),
                "sell_count": sell_c.get(tk, 0),
            })

        return {"stocks": stocks, "count": len(stocks)}
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(json.dumps(
            {"error": "사용법: py dataroma.py TICKER  또는  py dataroma.py --top [N]"},
            ensure_ascii=False))
        return

    arg = sys.argv[1]

    if arg == "--top":
        limit = 20
        if len(sys.argv) >= 3:
            try:
                limit = int(sys.argv[2])
            except ValueError:
                pass
        result = fetch_top_stocks(limit)
        if not result:
            print(json.dumps(
                {"error": "Dataroma allact.php 조회 실패 — 네트워크 점검"},
                ensure_ascii=False))
            return
        result["note"] = (
            "슈퍼인베스터 최근 분기 활동 기준 상위 종목(allact.php). "
            "count=해당 종목 등장 매니저 수. buy_count=매수/추가 매니저 수. "
            "sell_count=매도/축소 매니저 수. "
            "13F 분기 신고 기반 — 최근 분기 이전 활동은 포함되지 않음. "
            "null이면 데이터 미제공 — 지어내지 말 것."
        )
        print(json.dumps(result, ensure_ascii=False))
        return

    ticker = arg.upper().strip()
    result = fetch_holders(ticker)
    if result is None:
        print(json.dumps(
            {"error": f"{ticker} Dataroma 조회 실패 — 네트워크 오류"},
            ensure_ascii=False))
        return

    result["note"] = (
        "슈퍼인베스터 최근 분기 활동(allact.php 기준). "
        "holders=해당 종목을 거래한 매니저 목록. "
        "action: buy=신규매수, add=추가매수, reduce=축소, sell=매도. "
        "signal: strong_conviction=5명+, multi_holder=3~4명, "
        "single_holder=1~2명, no_holder=활동 없음. "
        "13F 분기 신고 기반 — 직전 분기 이전 활동은 포함되지 않음. "
        "no_holder여도 과거 보유자가 있을 수 있음. "
        "null이면 데이터 미제공 — 지어내지 말 것."
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
