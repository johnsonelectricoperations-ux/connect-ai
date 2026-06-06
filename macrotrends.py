#!/usr/bin/env python3
# Connect AI · Macrotrends 장기 재무 역사 헬퍼
#
# 사용법:
#   py macrotrends.py AAPL          → 매출/순이익/EPS/FCF 10년치 + 성장통계
#   py macrotrends.py IONQ revenue  → 매출만
#   py macrotrends.py TSLA netIncome fcf → 복수 지표
#
# 목적: yfinance가 4~8분기만 주는 한계를 극복.
#       10년 매출 CAGR + 연속 성장 연수 → 텐배거 성장 지속성 핵심 지표.
#       극소형주는 yfinance 신뢰도 낮으므로 Macrotrends가 주요 검증 소스.
#
# 데이터: Macrotrends.net (무료, 인증 불필요)
# 외부 라이브러리 없이 stdlib(urllib, re)만 사용.
# 실패 시 {"error": ...}. AI는 error/null이면 날조 금지.

import sys, json, re, urllib.request, urllib.error

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

# Macrotrends URL slug 매핑
METRIC_SLUGS = {
    "revenue":       "revenue",
    "netIncome":     "net-income",
    "eps":           "eps-earnings-per-share-diluted",
    "fcf":           "free-cash-flow",
    "grossProfit":   "gross-profit",
    "operatingIncome": "operating-income",
}


def _http_get(url, timeout=15):
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        # gzip 자동 처리
        try:
            import gzip
            if r.info().get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
        except Exception:
            pass
        return raw.decode("utf-8", errors="replace")


def _find_slug(ticker):
    """Macrotrends 검색 API로 company URL slug 조회.
    실패 시 티커 소문자를 slug로 사용(IONQ→ionq 등 단순 케이스 대응)."""
    try:
        url = (f"https://www.macrotrends.net/assets/php/ticker-search.php"
               f"?keyword={ticker}&type=stock")
        html = _http_get(url, timeout=10)
        data = json.loads(html)
        if isinstance(data, list):
            for item in data:
                s = (item.get("s") or item.get("ticker") or "").upper()
                if s == ticker.upper():
                    slug = (item.get("slug") or item.get("name") or "").lower()
                    slug = re.sub(r"[^a-z0-9-]", "-", slug).strip("-")
                    if slug:
                        return slug
    except Exception:
        pass
    return ticker.lower()


def _extract_js_value(html, varname):
    """JS 변수값을 브레이스/브래킷 깊이 추적으로 안전하게 추출.
    비-탐욕 정규식의 너무 일찍 끊김 문제를 해결."""
    m = re.search(rf'var\s+{re.escape(varname)}\s*=\s*([\[{{])', html)
    if not m:
        return None
    start = m.start(1)
    opener = m.group(1)
    closer = '}' if opener == '{' else ']'
    depth = 0
    in_str = False
    escape_next = False
    for i in range(start, len(html)):
        ch = html[i]
        if escape_next:
            escape_next = False
            continue
        if ch == '\\' and in_str:
            escape_next = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch in ('{', '['):
            depth += 1
        elif ch in ('}', ']'):
            depth -= 1
            if depth == 0:
                return html[start:i + 1]
    return None


def _parse_annual(html):
    """Macrotrends 페이지 HTML → {year: value} 연간 데이터 dict.

    Macrotrends는 JavaScript 변수에 데이터를 담는다. 알려진 패턴들:
    패턴 A: var originalData = [["2024/09/28", val1, val2], ...];
    패턴 B: var chartData = {"2024/09/28": {"v1": val}, ...};
    패턴 C: 같은 패턴이지만 값이 문자열로 감싸진 경우
    패턴 D: var chartDataArr = [...]; (변수명 변형)
    """
    # 시도할 배열형 변수명 목록
    for arr_var in ("originalData", "chartDataArr", "rowData", "tableData"):
        raw = _extract_js_value(html, arr_var)
        if raw:
            try:
                rows = json.loads(raw)
                result = _rows_to_annual(rows)
                if result:
                    return result
            except Exception:
                pass

    # 시도할 객체형 변수명 목록
    for obj_var in ("chartData", "chartDataObj", "data"):
        raw = _extract_js_value(html, obj_var)
        if raw:
            try:
                obj = json.loads(raw)
                if not isinstance(obj, dict):
                    continue
                annual = {}
                for date_str, vals in obj.items():
                    year = str(date_str)[:4]
                    if not year.isdigit():
                        continue
                    if isinstance(vals, dict):
                        for k in ("v1", "v2", "v3", "value"):
                            v = vals.get(k)
                            if v is not None and v != "":
                                try:
                                    annual[year] = float(str(v).replace(",", ""))
                                    break
                                except (TypeError, ValueError):
                                    pass
                    else:
                        try:
                            annual[year] = float(str(vals).replace(",", ""))
                        except (TypeError, ValueError):
                            pass
                if annual:
                    return annual
            except Exception:
                pass

    return None


def _rows_to_annual(rows):
    """[[date, val, ...], ...] → {year: value} 연간 집계."""
    annual = {}
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        date_str = str(row[0])
        year = date_str[:4]
        if not year.isdigit():
            continue
        for v in row[1:]:
            if v is not None and v != "" and v != "null":
                try:
                    val = float(str(v).replace(",", ""))
                    annual[year] = val
                    break
                except (TypeError, ValueError):
                    pass
    return annual if annual else None


def _cagr(data, years):
    """최근 N년 연평균성장률(CAGR). 데이터 부족 또는 음수 기저면 None."""
    sorted_y = sorted(data.keys(), reverse=True)
    if len(sorted_y) <= years:
        return None
    v_end = data[sorted_y[0]]
    v_start = data[sorted_y[years]]
    if v_start is None or v_end is None:
        return None
    if v_start <= 0 or v_end <= 0:
        return None
    return round((v_end / v_start) ** (1.0 / years) - 1, 4)


def _growth_stats(data):
    """연간 데이터 dict → 성장 통계 dict. 데이터 없으면 None."""
    if not data:
        return None
    sorted_y = sorted(data.keys())
    # 최근 10년 이하
    recent = sorted_y[-10:]
    series = [{"year": y, "value": data[y]} for y in recent]

    yoy = []
    for i in range(1, len(recent)):
        prev = data[recent[i - 1]]
        curr = data[recent[i]]
        if prev and prev != 0:
            yoy.append(round((curr - prev) / abs(prev), 4))
        else:
            yoy.append(None)

    # 최근 연속 성장 연수 (역순으로 카운트)
    consecutive = 0
    for i in range(len(recent) - 1, 0, -1):
        if data[recent[i]] is not None and data[recent[i - 1]] is not None:
            if data[recent[i]] > data[recent[i - 1]]:
                consecutive += 1
            else:
                break

    valid_yoy = [g for g in yoy if g is not None]
    positive = sum(1 for g in valid_yoy if g > 0)

    return {
        "series": series,
        "cagr_3yr": _cagr(data, 3),
        "cagr_5yr": _cagr(data, 5),
        "cagr_10yr": _cagr(data, 10),
        "consecutive_growth_years": consecutive,
        "positive_growth_years": positive,
        "total_years": len(valid_yoy),
        "latest_yoy": yoy[-1] if yoy else None,
        "yoy_series": yoy,
    }


def fetch_history(ticker, metrics=None):
    """Macrotrends 장기 재무 역사 조회.

    반환: {ticker, slug, revenue: {...}, netIncome: {...}, ...}
    각 지표는 _growth_stats 결과 dict 또는 None.
    전체 실패 시 None (graceful — 예외 삼킴).
    screen.py·collector.py에서 import해 쓴다.
    """
    if metrics is None:
        metrics = ["revenue", "netIncome", "eps", "fcf"]
    try:
        slug = _find_slug(ticker)
        result = {"ticker": ticker.upper(), "slug": slug}
        for metric in metrics:
            ms = METRIC_SLUGS.get(metric)
            if not ms:
                result[metric] = None
                continue
            url = (f"https://www.macrotrends.net/stocks/charts"
                   f"/{ticker.upper()}/{slug}/{ms}?freq=A")
            try:
                html = _http_get(url)
                annual = _parse_annual(html)
                result[metric] = _growth_stats(annual)
            except Exception:
                result[metric] = None
        return result
    except Exception:
        return None


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "ticker 필요. 예: py macrotrends.py AAPL"},
                         ensure_ascii=False))
        return
    ticker = sys.argv[1].upper().strip()

    # 나머지 인자 중 지표명만 추출
    metric_args = [a.lower() for a in sys.argv[2:] if a.lower() in METRIC_SLUGS]
    metrics = metric_args if metric_args else None

    try:
        result = fetch_history(ticker, metrics)
    except urllib.error.URLError as e:
        print(json.dumps({"error": f"네트워크 오류: {e}"}, ensure_ascii=False))
        return
    except Exception as e:
        print(json.dumps({"error": f"조회 실패: {e}"}, ensure_ascii=False))
        return

    if not result:
        print(json.dumps(
            {"error": f"{ticker} Macrotrends 조회 실패 — 티커 확인 또는 네트워크 점검"},
            ensure_ascii=False))
        return

    result["note"] = (
        "series=연도별 실적(value 단위: USD 절대값, 백만 달러 기준). "
        "cagr_3yr/5yr/10yr=연평균성장률(소수, 0.15=15%). null이면 데이터 부족 또는 음수 기저. "
        "consecutive_growth_years=최근 연속 성장 연수. "
        "positive_growth_years/total_years=전체 기간 중 성장 연수/전체 연수. "
        "latest_yoy=가장 최근 YoY 성장률. "
        "null이면 데이터 미제공 — 지어내지 말 것. "
        "성장 지속성 판단: consecutive_growth_years>=5이면 안정 성장, "
        "cagr_5yr>=0.20이면 고성장(연 20%+)으로 분류."
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
