#!/usr/bin/env python3
# Connect AI · 종목 발굴/스크리닝 도구 (yfinance 기반)
#
# 사용법:
#   py screen.py                        → watchlist.txt 를 value 전략으로 스크리닝
#   py screen.py value                  → 저평가/반등 전략
#   py screen.py momentum               → 성장모멘텀 전략
#   py screen.py tenbagger              → watchlist.txt 에서 텐배거 후보 발굴
#   py screen.py AAPL MSFT NVDA         → 티커 직접 지정
#   py screen.py suggest quantum        → 테마 유니버스 자동 발굴 (value 전략)
#   py screen.py suggest tenbagger      → 소형 고성장 텐배거 유니버스 발굴
#   py screen.py suggest ai momentum    → 테마 유니버스 + 전략 지정
#   py screen.py suggest               → 사용 가능한 테마 목록 출력
#
# 전략:
#   value     : 52주 저점 근접 + RSI 낮음(과매도) + P/S 낮음 → 반등/저평가 후보
#   momentum  : 정배열 추세 + 매출성장 + RSI 적정(과열 아님) → 성장 모멘텀 후보
#   tenbagger : 소형주($300M-$5B) + 고성장(30%+) + Rule of 40 + 낮은 부채 → 10배 후보
#
# 출력 JSON (점수 내림차순). UTF-8 강제, 이모지 금지, 계산은 Python.

import sys, json, os

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def load_watchlist(path):
    out = []
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            out.append(s.upper())
    return out


def rsi14(closes):
    n = 14
    if len(closes) <= n:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag = sum(gains[:n]) / n
    al = sum(losses[:n]) / n
    val = 100 - 100 / (1 + ag / al) if al != 0 else 100.0
    for i in range(n, len(gains)):
        ag = (ag * (n - 1) + gains[i]) / n
        al = (al * (n - 1) + losses[i]) / n
        val = 100 - 100 / (1 + ag / al) if al != 0 else 100.0
    return round(val, 1)


def fetch_metrics(yf, ticker):
    try:
        t = yf.Ticker(ticker)
        h = t.history(period="6mo", interval="1d")
        closes = [float(r["Close"]) for _, r in h.iterrows()]
        if len(closes) < 30:
            return None
        price = round(closes[-1], 2)
        ma20 = round(sum(closes[-20:]) / 20, 2)
        ma50 = round(sum(closes[-50:]) / 50, 2) if len(closes) >= 50 else None
        info = {}
        try:
            info = t.info or {}
        except Exception:
            info = {}
        high52 = info.get("fiftyTwoWeekHigh")
        low52 = info.get("fiftyTwoWeekLow")
        pos52 = None
        if high52 and low52 and high52 != low52:
            pos52 = round((price - low52) / (high52 - low52) * 100, 1)  # 0=저점,100=고점
        raw_pm = info.get("profitMargins")
        profit_margins = round(raw_pm, 4) if (raw_pm is not None and -10.0 <= raw_pm <= 1.0) else None
        raw_dte = info.get("debtToEquity")
        debt_to_equity = round(raw_dte / 100, 2) if (raw_dte is not None and 0 <= raw_dte <= 10000) else None
        return {
            "ticker": ticker, "price": price, "rsi14": rsi14(closes),
            "ma20": ma20, "ma50": ma50,
            "pos52": pos52,
            "fiftyTwoWeekHigh": round(high52, 2) if high52 else None,
            "fiftyTwoWeekLow": round(low52, 2) if low52 else None,
            "marketCap": info.get("marketCap"),
            "priceToSales": info.get("priceToSalesTrailing12Months"),
            "revenueGrowth": info.get("revenueGrowth"),
            "forwardPE": info.get("forwardPE"),
            "trailingPE": info.get("trailingPE"),
            "beta": info.get("beta"),
            "profitMargins": profit_margins,
            "debtToEquity": debt_to_equity,
            "name": info.get("shortName") or info.get("longName"),
            "trend": "up" if (ma50 and ma20 > ma50) else "down" if ma50 else None,
        }
    except Exception:
        return None


def score_value(m):
    """저평가/반등: 52주 저점 근접 + 과매도 RSI + 낮은 P/S 일수록 고득점."""
    s, reasons = 0.0, []
    if m.get("pos52") is not None:
        if m["pos52"] <= 30:
            s += 3; reasons.append(f'52주 저점권({m["pos52"]}%)')
        elif m["pos52"] <= 50:
            s += 1.5
    if m.get("rsi14") is not None:
        if m["rsi14"] <= 35:
            s += 3; reasons.append(f'과매도 RSI {m["rsi14"]}')
        elif m["rsi14"] <= 45:
            s += 1.5
    ps = m.get("priceToSales")
    if ps is not None:
        if ps <= 5:
            s += 2; reasons.append(f'낮은 P/S {round(ps,1)}')
        elif ps <= 15:
            s += 1
    return round(s, 1), reasons


def score_momentum(m):
    """성장모멘텀: 정배열 추세 + 매출성장 + 과열 아닌 RSI 일수록 고득점."""
    s, reasons = 0.0, []
    if m.get("trend") == "up":
        s += 3; reasons.append("정배열 추세")
    rg = m.get("revenueGrowth")
    if rg is not None:
        if rg >= 0.30:
            s += 3; reasons.append(f'매출성장 {round(rg*100,1)}%')
        elif rg >= 0.10:
            s += 1.5; reasons.append(f'매출성장 {round(rg*100,1)}%')
    if m.get("rsi14") is not None:
        if 50 <= m["rsi14"] <= 68:
            s += 2; reasons.append(f'건강한 RSI {m["rsi14"]}')
        elif m["rsi14"] > 75:
            s -= 1; reasons.append(f'과매수 경계 RSI {m["rsi14"]}')
    return round(s, 1), reasons


def score_tenbagger(m):
    """텐배거 후보: 소형주 + 고성장 + Rule of 40 + 낮은 부채 + 아직 덜 오른 가격.

    피터 린치 스타일 — 시총 $300M-$5B 소형·중형주에서 고성장·저부채를 찾는다.
    정성 정보(경제적 해자·경영진)는 이 도구 밖이므로 정량 점수만 계산.
    점수가 높다고 추천이 아니라 심층 검증 후보 순위.
    """
    s, reasons = 0.0, []

    # 1. 시총 체크: $300M - $5B 소형·중형주 영역 (텐배거 가능 시총대)
    mc = m.get("marketCap")
    if mc is not None:
        mc_b = mc / 1e9  # 십억 달러
        if 0.3 <= mc_b <= 5.0:
            s += 3; reasons.append(f'텐배거 시총대 ${round(mc_b,1)}B')
        elif 5.0 < mc_b <= 15.0:
            s += 1; reasons.append(f'중형주 ${round(mc_b,1)}B')
        elif mc_b < 0.3:
            s -= 1; reasons.append(f'초소형주 유동성위험 ${round(mc_b*1000,0):.0f}M')

    # 2. 매출 성장: 고성장 기업이 텐배거 후보
    rg = m.get("revenueGrowth")
    if rg is not None:
        if rg >= 0.40:
            s += 4; reasons.append(f'초고성장 매출 {round(rg*100,1)}%')
        elif rg >= 0.25:
            s += 3; reasons.append(f'고성장 매출 {round(rg*100,1)}%')
        elif rg >= 0.10:
            s += 1; reasons.append(f'성장 매출 {round(rg*100,1)}%')
        else:
            s -= 1; reasons.append(f'저성장 매출 {round(rg*100,1)}%')

    # 3. Rule of 40: 매출성장% + 이익률% >= 40 → 고성장 SaaS/테크 건강 지표
    pm = m.get("profitMargins")
    if rg is not None and pm is not None:
        rule40 = rg * 100 + pm * 100
        if rule40 >= 40:
            s += 3; reasons.append(f'Rule of 40 통과({round(rule40,1)})')
        elif rule40 >= 20:
            s += 1.5; reasons.append(f'Rule of 40 부분({round(rule40,1)})')
        else:
            reasons.append(f'Rule of 40 미달({round(rule40,1)})')

    # 4. 부채비율: 소형 성장주는 낮은 부채가 생존 핵심
    dte = m.get("debtToEquity")
    if dte is not None:
        if dte <= 0.3:
            s += 2; reasons.append(f'무부채수준 D/E {dte}')
        elif dte <= 0.8:
            s += 1; reasons.append(f'적정 부채 D/E {dte}')
        elif dte > 2.0:
            s -= 1; reasons.append(f'고부채 위험 D/E {dte}')

    # 5. 52주 위치: 아직 급등 안 한 종목 (발굴 가치)
    pos = m.get("pos52")
    if pos is not None:
        if pos <= 40:
            s += 2; reasons.append(f'52주 저점권({pos}%) — 아직 덜 오름')
        elif pos <= 65:
            s += 1; reasons.append(f'52주 중간권({pos}%)')
        elif pos >= 85:
            s -= 1; reasons.append(f'52주 고점권({pos}%) — 이미 급등')

    # 6. RSI: 적정 구간 선호 (과매수면 단기 리스크)
    rsi = m.get("rsi14")
    if rsi is not None:
        if 40 <= rsi <= 65:
            s += 1; reasons.append(f'RSI 적정 {rsi}')
        elif rsi > 75:
            s -= 1; reasons.append(f'RSI 과매수 {rsi}')

    return round(s, 1), reasons


# 테마별 내장 유니버스 (suggest 모드용)
UNIVERSES = {
    "quantum":     ["IONQ", "RGTI", "QBTS", "QUBT", "IBM", "GOOGL", "MSFT"],
    "ai":          ["NVDA", "AMD", "INTC", "MSFT", "GOOGL", "META", "AMZN", "TSM", "AVGO", "QCOM"],
    "ev":          ["TSLA", "RIVN", "LCID", "NIO", "XPEV", "LI", "GM", "F", "CHPT", "BLNK"],
    "biotech":     ["MRNA", "BNTX", "REGN", "BIIB", "VRTX", "ILMN", "CRSP", "EDIT", "NTLA", "BEAM"],
    "defense":     ["LMT", "RTX", "NOC", "GD", "BA", "HII", "LDOS", "CACI", "SAIC", "KTOS"],
    "semiconductor": ["NVDA", "AMD", "INTC", "TSM", "AVGO", "QCOM", "AMAT", "LRCX", "KLAC", "MRVL"],
    "cloud":       ["AMZN", "MSFT", "GOOGL", "CRM", "SNOW", "DDOG", "NET", "ZS", "MDB", "TEAM"],
    "fintech":     ["V", "MA", "PYPL", "SQ", "SOFI", "AFRM", "UPST", "COIN", "HOOD", "NU"],
    "energy":      ["XOM", "CVX", "COP", "SLB", "EOG", "PXD", "OXY", "MPC", "VLO", "PSX"],
    "clean":       ["ENPH", "FSLR", "RUN", "SEDG", "NEE", "BEP", "PLUG", "BLDP", "CWEN", "AES"],
    "healthcare":  ["UNH", "JNJ", "ABT", "TMO", "DHR", "MDT", "SYK", "BSX", "EW", "ISRG"],
    "consumer":    ["AMZN", "COST", "WMT", "TGT", "HD", "LOW", "NKE", "SBUX", "MCD", "YUM"],
    "crypto":      ["COIN", "MSTR", "MARA", "RIOT", "HUT", "CLSK", "BTBT", "WGMI", "HOOD", "SQ"],
    "space":       ["RKLB", "ASTS", "LUNR", "MNTS", "SPCE", "SATL", "KTOS", "AJRD", "LMT", "NOC"],
    "robotics":    ["ISRG", "ABB", "FANUC", "BRKS", "NXPI", "TER", "ONTO", "CGNX", "IRBT", "NVDA"],
    # 텐배거 후보 전용 유니버스: 소형·중형 고성장주 크로스섹터 (시총 $300M~$5B 대상)
    # 대형주(NVDA·MSFT 등) 제외. 심층 검증 후 진입 결정할 것.
    "tenbagger":   ["IONQ", "RGTI", "RKLB", "ASTS", "SOFI", "AFRM", "UPST",
                    "HIMS", "CELH", "DUOL", "SOUN", "RXRX", "TMDX", "NUVL",
                    "GTLB", "BILL", "AXON", "KTOS", "APP", "SMCI"],
}


def main():
    args = sys.argv[1:]
    strat = "value"
    tickers = []
    suggest_mode = False
    suggest_theme = None

    # suggest 모드 감지
    if args and args[0].lower() == "suggest":
        suggest_mode = True
        args = args[1:]
        # 테마 인자 (전략명 제외)
        remaining = []
        for a in args:
            if a.lower() in ("value", "momentum", "tenbagger"):
                strat = a.lower()
            elif a.lower() in UNIVERSES:
                suggest_theme = a.lower()
            else:
                remaining.append(a)

        # "suggest tenbagger" → 전략=tenbagger, 테마=tenbagger 유니버스
        if strat == "tenbagger" and suggest_theme is None:
            suggest_theme = "tenbagger"

        if suggest_theme is None:
            # 테마 없이 suggest만 쓰면 목록 출력
            print(json.dumps({
                "available_themes": list(UNIVERSES.keys()),
                "usage": "py screen.py suggest [theme] [value|momentum|tenbagger]",
                "example": "py screen.py suggest tenbagger",
            }, ensure_ascii=False))
            return

        tickers = UNIVERSES[suggest_theme]
    else:
        # 첫 인자가 전략명이면 분리, 아니면 티커로 간주
        if args and args[0].lower() in ("value", "momentum", "tenbagger"):
            strat = args[0].lower()
            args = args[1:]
        if args:
            tickers = [a.upper() for a in args]
        else:
            path = "watchlist.txt"
            if not os.path.exists(path):
                print(json.dumps({
                    "error": "watchlist.txt 가 없습니다. 워크스페이스에 후보 티커를 한 줄씩 넣어주세요.",
                    "template": "IONQ\nRGTI\nQBTS",
                }, ensure_ascii=False))
                return
            try:
                tickers = load_watchlist(path)
            except Exception as e:
                print(json.dumps({"error": f"watchlist 읽기 실패: {e}"}, ensure_ascii=False))
                return

    if not tickers:
        print(json.dumps({"error": "스크리닝할 티커가 없습니다."}, ensure_ascii=False))
        return

    try:
        import yfinance as yf
    except ImportError:
        print(json.dumps({"error": "yfinance 미설치. 'py -m pip install yfinance' 실행."}, ensure_ascii=False))
        return

    if strat == "momentum":
        scorer = score_momentum
    elif strat == "tenbagger":
        scorer = score_tenbagger
    else:
        scorer = score_value
    results = []
    failed = []
    for tk in tickers:
        m = fetch_metrics(yf, tk)
        if m is None:
            failed.append(tk)
            continue
        score, reasons = scorer(m)
        m["score"] = score
        m["reasons"] = reasons
        results.append(m)

    results.sort(key=lambda x: x["score"], reverse=True)

    out = {
        "strategy": strat,
        "ranked": results,
        "failed": failed,
        "note": "score 높을수록 해당 전략에 부합. reasons=가점 근거. 이것은 1차 스크리닝(객관 지표 랭킹)이며, 상위 후보는 반드시 기술/펀더멘털 심층분석으로 검증할 것. 추천이 아니라 후보 정렬.",
        "fields_only": "이 JSON에 있는 필드(price·rsi14·ma20·ma50·pos52·52주고저·marketCap·priceToSales·revenueGrowth·forwardPE·trailingPE·beta·profitMargins·debtToEquity·trend)만 인용하라. 매출액·파트너십·기술방식(trapped ion 등)·시장점유율 같은 정성 정보는 이 도구가 제공하지 않으므로 절대 지어내지 말 것. 없는 값은 'N/A' 또는 '데이터 미제공'으로 표기.",
    }
    if suggest_mode and suggest_theme:
        out["theme"] = suggest_theme
        out["universe_size"] = len(tickers)
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
