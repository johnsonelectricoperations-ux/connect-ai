#!/usr/bin/env python3
# Connect AI · SEC EDGAR 공시·재무 데이터 헬퍼 (미국 공식 소스)
#
# 사용법:
#   py sec.py TICKER              → 최근 공시 목록 (10-K/10-Q/8-K + 날짜 + 원문 링크)
#   py sec.py TICKER financials   → 핵심 재무 (매출·순이익·자산·부채·자본·EPS 최근치)
#   py sec.py TICKER 10-K         → 특정 양식만 필터 (예: 10-K, 10-Q, 8-K)
#
# 데이터 출처: SEC EDGAR 공식 API (data.sec.gov) — 인증/키 불필요.
# SEC 규칙상 User-Agent 헤더 필수. 외부 라이브러리 없이 stdlib(urllib)만 사용.
# 출력은 JSON 한 줄. 실패 시 {"error": ...}. AI는 error/null이면 날조 금지.
#
# 교훈 적용: UTF-8 출력 강제, 출력에 이모지·특수문자 금지.

import sys, json, urllib.request, urllib.error

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# SEC는 식별 가능한 User-Agent를 요구한다 (연락처 포함 권장).
HEADERS = {"User-Agent": "Connect AI Investment Tool admin@example.com"}


def _get_json(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def ticker_to_cik(ticker):
    """티커 → 10자리 zero-padded CIK 문자열. 못 찾으면 None."""
    data = _get_json("https://www.sec.gov/files/company_tickers.json")
    tu = ticker.upper()
    for _, row in data.items():
        if str(row.get("ticker", "")).upper() == tu:
            return str(row["cik_str"]).zfill(10), row.get("title")
    return None, None


def recent_filings(cik, form_filter=None, limit=15):
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    data = _get_json(url)
    rec = data.get("filings", {}).get("recent", {})
    forms = rec.get("form", [])
    dates = rec.get("filingDate", [])
    rdates = rec.get("reportDate", [])
    accs = rec.get("accessionNumber", [])
    docs = rec.get("primaryDocument", [])
    descs = rec.get("primaryDocDescription", [])

    out = []
    cik_int = str(int(cik))  # 링크엔 zero-padding 없는 CIK
    for i in range(len(forms)):
        f = forms[i]
        if form_filter and f.upper() != form_filter.upper():
            continue
        acc = accs[i] if i < len(accs) else ""
        acc_nodash = acc.replace("-", "")
        doc = docs[i] if i < len(docs) else ""
        link = (f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}/{doc}"
                if acc_nodash and doc else None)
        out.append({
            "form": f,
            "filingDate": dates[i] if i < len(dates) else None,
            "reportDate": rdates[i] if i < len(rdates) else None,
            "description": descs[i] if i < len(descs) else None,
            "url": link,
        })
        if len(out) >= limit:
            break
    return out, data.get("name")


# 핵심 재무 항목 — 회사마다 태그가 달라 후보를 여러 개 시도
CONCEPTS = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax",
                "Revenues", "SalesRevenueNet"],
    "netIncome": ["NetIncomeLoss", "ProfitLoss"],
    "operatingIncome": ["OperatingIncomeLoss"],
    "assets": ["Assets"],
    "liabilities": ["Liabilities"],
    "equity": ["StockholdersEquity",
               "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue"],
    "epsDiluted": ["EarningsPerShareDiluted"],
}


def _latest_fact(facts_usgaap, concept_names):
    """후보 태그 중 존재하는 것에서 가장 최근 값 1건 반환."""
    for name in concept_names:
        node = facts_usgaap.get(name)
        if not node:
            continue
        units = node.get("units", {})
        # USD 우선, 없으면 첫 단위
        ukey = "USD" if "USD" in units else (next(iter(units)) if units else None)
        if not ukey:
            continue
        rows = [x for x in units[ukey] if x.get("end")]
        if not rows:
            continue
        rows.sort(key=lambda x: x["end"])
        last = rows[-1]
        return {
            "value": last.get("val"),
            "end": last.get("end"),
            "form": last.get("form"),
            "fy": last.get("fy"),
            "fp": last.get("fp"),
            "unit": ukey,
            "concept": name,
        }
    return None


def financials(cik):
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    data = _get_json(url)
    usgaap = data.get("facts", {}).get("us-gaap", {})
    out = {}
    for key, names in CONCEPTS.items():
        out[key] = _latest_fact(usgaap, names)
    return out, data.get("entityName")


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "ticker 필요. 예: py sec.py AAPL"}, ensure_ascii=False))
        return
    ticker = sys.argv[1].upper().strip()
    mode = sys.argv[2].strip() if len(sys.argv) > 2 else "filings"

    try:
        cik, title = ticker_to_cik(ticker)
    except urllib.error.URLError as e:
        print(json.dumps({"error": f"SEC 연결 실패: {e}. 네트워크 확인."}, ensure_ascii=False))
        return
    except Exception as e:
        print(json.dumps({"error": f"CIK 조회 실패: {e}"}, ensure_ascii=False))
        return

    if not cik:
        print(json.dumps({"error": f"{ticker}의 CIK를 SEC에서 찾지 못함 (미국 상장사 티커인지 확인)."}, ensure_ascii=False))
        return

    try:
        if mode.lower() in ("financials", "fin", "재무"):
            fin, name = financials(cik)
            print(json.dumps({
                "ticker": ticker, "cik": cik, "name": name or title,
                "financials": fin,
                "note": "SEC EDGAR XBRL 공식 데이터. value=금액(unit 단위), end=기준일, form=출처양식, fp=회계기간(FY=연간/Q1~Q4=분기). null이면 해당 태그 미제공.",
            }, ensure_ascii=False))
        else:
            form_filter = None if mode.lower() in ("filings", "list", "공시") else mode
            filings, name = recent_filings(cik, form_filter=form_filter)
            print(json.dumps({
                "ticker": ticker, "cik": cik, "name": name or title,
                "filings": filings,
                "note": "SEC EDGAR 최근 공시. url은 원문 링크. 10-K=연간보고서, 10-Q=분기보고서, 8-K=수시공시. 내용 분석은 url을 read_url로 열어 확인.",
            }, ensure_ascii=False))
    except urllib.error.HTTPError as e:
        print(json.dumps({"error": f"SEC HTTP 오류 {e.code}: {e.reason}"}, ensure_ascii=False))
    except urllib.error.URLError as e:
        print(json.dumps({"error": f"SEC 연결 실패: {e}. 네트워크 확인."}, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"error": f"조회 실패: {e}"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
