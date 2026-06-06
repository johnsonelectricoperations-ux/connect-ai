#!/usr/bin/env python3
# Connect AI · Dataroma 슈퍼인베스터 13F 헬퍼
#
# 사용법:
#   py dataroma.py AAPL          → AAPL 보유 슈퍼인베스터 목록 + 전체 매수/매도 합산
#   py dataroma.py IONQ          → 보유자 없으면 {"holders": [], "summary": {...}}
#   py dataroma.py --top 20      → 슈퍼인베스터 전원 공통 보유 상위 20 종목
#
# 목적: 피터 린치·워런 버핏·척 아크만 등 검증된 투자자가 보유 중인 종목을
#       텐배거 발굴 보조 검증 소스로 활용.
#       "슈퍼인베스터 3명+ 보유" = 고급 검증 시그널.
#
# 데이터: Dataroma.com (무료, 13F 기반, 분기별 업데이트)
# 외부 라이브러리 없이 stdlib만 사용.
# 실패 시 {"error": ...}. AI는 error/null이면 날조 금지.

import sys, json, re, urllib.request, urllib.error, html as html_mod

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://www.dataroma.com/",
}

_BASE = "https://www.dataroma.com"


def _http_get(url, timeout=15):
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


# ─────────────────────────────────────────────────────────────
# 1. 슈퍼인베스터 목록 조회
# ─────────────────────────────────────────────────────────────

def _fetch_managers():
    """Dataroma 매니저 목록 페이지에서 {id: name} dict 반환."""
    url = f"{_BASE}/m/managers.php"
    try:
        html = _http_get(url)
    except Exception:
        return {}

    # <a href="m/holdings.php?m=BRK">Berkshire Hathaway</a>
    mgr = {}
    for m in re.finditer(
        r'href=["\']m/holdings\.php\?m=([^"\'&]+)["\'][^>]*>(.*?)</a>',
        html, re.IGNORECASE | re.DOTALL
    ):
        mid = m.group(1).strip()
        name = _unescape(re.sub(r'<[^>]+>', '', m.group(2)))
        if mid and name:
            mgr[mid] = name
    return mgr


# ─────────────────────────────────────────────────────────────
# 2. 특정 종목 보유 슈퍼인베스터 조회
# ─────────────────────────────────────────────────────────────

def _fetch_stock_holders(ticker):
    """Dataroma 종목 페이지 → 보유 매니저 목록."""
    url = f"{_BASE}/m/stock.php?s={ticker.upper()}"
    try:
        html = _http_get(url)
    except Exception:
        return None

    holders = []

    # 보유 매니저 테이블 파싱
    # <td><a href="m/holdings.php?m=BRK&amp;s=AAPL">Berkshire Hathaway</a></td>
    # <td>12.4%</td>  (포트폴리오 비중)
    # <td>915,560,382</td>  (보유 주수)
    # <td>$138,273,801,780</td>  (평가액)
    # <td>Q1 2024</td>  (마지막 신고)
    # <td>Buy / Add / Reduce / Sell</td>  (최근 액션)

    rows = re.findall(
        r'<tr[^>]*>\s*(<td>.*?</tr>)',
        html, re.IGNORECASE | re.DOTALL
    )

    for row in rows:
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.IGNORECASE | re.DOTALL)
        if len(cells) < 5:
            continue

        # 첫 번째 셀에 매니저 링크
        name_m = re.search(r'<a[^>]*>(.*?)</a>', cells[0], re.IGNORECASE | re.DOTALL)
        if not name_m:
            continue
        name = _unescape(re.sub(r'<[^>]+>', '', name_m.group(1)))
        if not name or len(name) < 3:
            continue

        mgr_id_m = re.search(r'[?&]m=([^&"\']+)', cells[0])
        mgr_id = mgr_id_m.group(1).strip() if mgr_id_m else ""

        def _clean(s):
            return _unescape(re.sub(r'<[^>]+>', '', s)).replace(',', '').replace('$', '').strip()

        pct_str = _clean(cells[1])
        shares_str = _clean(cells[2])
        value_str = _clean(cells[3])
        period_str = _clean(cells[4])
        action_str = _clean(cells[5]) if len(cells) > 5 else ""

        try:
            pct = float(pct_str.replace('%', '')) if pct_str and pct_str != "N/A" else None
        except ValueError:
            pct = None
        try:
            shares = int(float(shares_str)) if shares_str and shares_str.lstrip('-').replace('.', '').isdigit() else None
        except (ValueError, OverflowError):
            shares = None
        try:
            value = int(float(value_str)) if value_str and value_str.lstrip('-').replace('.', '').isdigit() else None
        except (ValueError, OverflowError):
            value = None

        holders.append({
            "manager_id": mgr_id,
            "manager": name,
            "portfolio_pct": pct,
            "shares": shares,
            "value_usd": value,
            "period": period_str,
            "action": action_str,
        })

    return holders


# ─────────────────────────────────────────────────────────────
# 3. 슈퍼인베스터 공통 상위 보유 종목 조회
# ─────────────────────────────────────────────────────────────

def _fetch_aggregated(limit=20):
    """Dataroma 집계 페이지(aggregated.php) → 상위 종목 랭킹."""
    url = f"{_BASE}/m/aggregated.php"
    try:
        html = _http_get(url)
    except Exception:
        return None

    stocks = []
    rows = re.findall(
        r'<tr[^>]*class=["\']?[^"\']*["\']?[^>]*>\s*(<td>.*?)</tr>',
        html, re.IGNORECASE | re.DOTALL
    )

    for row in rows:
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.IGNORECASE | re.DOTALL)
        if len(cells) < 4:
            continue

        def _c(s):
            return _unescape(re.sub(r'<[^>]+>', '', s)).replace(',', '').strip()

        ticker_m = re.search(r'[?&]s=([A-Z]{1,5})', cells[0])
        if not ticker_m:
            # 첫 셀 텍스트에서 티커 추출
            ticker_raw = _c(cells[0]).split()[0] if _c(cells[0]) else ""
            if not re.match(r'^[A-Z]{1,5}$', ticker_raw):
                continue
            ticker = ticker_raw
        else:
            ticker = ticker_m.group(1)

        name = _c(cells[1]) if len(cells) > 1 else ""

        try:
            num_holders = int(_c(cells[2])) if len(cells) > 2 and _c(cells[2]).isdigit() else None
        except ValueError:
            num_holders = None

        try:
            pct_str = _c(cells[3]).replace('%', '') if len(cells) > 3 else ""
            pct = float(pct_str) if pct_str else None
        except ValueError:
            pct = None

        if not ticker:
            continue
        stocks.append({
            "ticker": ticker,
            "name": name,
            "num_holders": num_holders,
            "avg_portfolio_pct": pct,
        })

    # limit 적용
    return stocks[:limit] if stocks else stocks


# ─────────────────────────────────────────────────────────────
# 4. 공개 API
# ─────────────────────────────────────────────────────────────

def fetch_holders(ticker):
    """특정 종목의 슈퍼인베스터 보유 현황.

    반환: {
        ticker, holders: [...], summary: {
            total_holders, buy_add_count, reduce_sell_count,
            latest_period, signal
        }
    }
    실패 시 None (graceful).
    """
    try:
        holders = _fetch_stock_holders(ticker)
        if holders is None:
            return None

        buy_add = sum(1 for h in holders if re.search(r'buy|add', h.get("action", ""), re.I))
        reduce_sell = sum(1 for h in holders if re.search(r'reduce|sell', h.get("action", ""), re.I))
        periods = [h["period"] for h in holders if h.get("period")]
        latest_period = periods[0] if periods else None

        # 신호 판단
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
            "ticker": ticker.upper(),
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
    """슈퍼인베스터 공통 상위 보유 종목 목록.

    반환: {stocks: [...], count: int}
    실패 시 None.
    """
    try:
        stocks = _fetch_aggregated(limit)
        if stocks is None:
            return None
        return {"stocks": stocks, "count": len(stocks)}
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────
# 5. CLI
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
                {"error": "Dataroma 집계 조회 실패 — 네트워크 점검"},
                ensure_ascii=False))
            return
        result["note"] = (
            "슈퍼인베스터 13F 공통 보유 상위 종목. "
            "num_holders=보유 매니저 수. avg_portfolio_pct=평균 포트폴리오 비중(%). "
            "분기별 업데이트(13F 신고 주기). 최신 보유가 아닐 수 있음. "
            "null이면 데이터 미제공 — 지어내지 말 것."
        )
        print(json.dumps(result, ensure_ascii=False))
        return

    ticker = arg.upper().strip()
    result = fetch_holders(ticker)
    if result is None:
        print(json.dumps(
            {"error": f"{ticker} Dataroma 조회 실패 — 네트워크 또는 미상장 종목 확인"},
            ensure_ascii=False))
        return

    result["note"] = (
        "슈퍼인베스터 13F 보유 현황. holders=보유 매니저 목록. "
        "portfolio_pct=해당 매니저 포트폴리오 내 비중(%). "
        "action=최근 분기 액션(Buy/Add/Reduce/Sell). "
        "signal: strong_conviction=5명+, multi_holder=3~4명, "
        "single_holder=1~2명, no_holder=보유자 없음. "
        "분기별 업데이트(13F 신고 주기). null이면 데이터 미제공 — 지어내지 말 것."
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
