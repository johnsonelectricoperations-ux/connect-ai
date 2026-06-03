#!/usr/bin/env python3
# Connect AI · 미국 주식 데이터 헬퍼 (yfinance 기반)
#
# 사용법:
#   py stock.py IONQ          → 현재가 + 밸류에이션(시총·PER·P/S·EPS·52주) JSON
#   py stock.py IONQ hist     → 최근 60거래일 일봉(날짜,종가) — 기술적 분석용
#
# 출력은 항상 JSON 한 줄. 실패 시 {"error": "..."} 를 출력하므로,
# AI는 error가 오면 숫자를 지어내지 말고 "데이터 확인 실패"라고 답해야 한다.

import sys, json

def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "ticker 인자가 필요합니다. 예: py stock.py AAPL"}))
        return
    ticker = sys.argv[1].upper().strip()
    mode = sys.argv[2].lower() if len(sys.argv) > 2 else "quote"

    try:
        import yfinance as yf
    except ImportError:
        print(json.dumps({"error": "yfinance 미설치. 터미널에서 'py -m pip install yfinance' 실행 필요."}))
        return

    t = yf.Ticker(ticker)

    # 안전 헬퍼 ── fast_info / info 둘 다 실패해도 죽지 않게
    def fast(key):
        try:
            return t.fast_info[key]
        except Exception:
            return None

    if mode in ("hist", "history", "chart"):
        try:
            h = t.history(period="6mo", interval="1d")
            closes = [float(r["Close"]) for _, r in h.iterrows()]
            highs = [float(r["High"]) for _, r in h.iterrows()]
            lows = [float(r["Low"]) for _, r in h.iterrows()]
            volumes = [int(r["Volume"]) for _, r in h.iterrows()]
            dates = [str(idx.date()) for idx in h.index]

            # ATR(14): 평균진폭. True Range = max(고-저, |고-전일종가|, |저-전일종가|)
            def atr(n=14):
                trs = []
                for i in range(1, len(closes)):
                    tr = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
                    trs.append(tr)
                if len(trs) < n:
                    return None
                return round(sum(trs[-n:])/n, 2)

            def sma(data, n):
                return [round(sum(data[i-n:i])/n, 2) if i >= n else None for i in range(len(data))]

            def ema(data, n):
                result, k = [], 2/(n+1)
                for i, v in enumerate(data):
                    if i == 0:
                        result.append(round(v, 2))
                    else:
                        result.append(round(v*k + result[-1]*(1-k), 2))
                return result

            def rsi(data, n=14):
                result = [None]*n
                gains, losses = [], []
                for i in range(1, len(data)):
                    d = data[i] - data[i-1]
                    gains.append(max(d, 0))
                    losses.append(max(-d, 0))
                if len(gains) < n:
                    return result
                ag = sum(gains[:n])/n
                al = sum(losses[:n])/n
                result.append(round(100 - 100/(1 + ag/al), 2) if al != 0 else 100.0)
                for i in range(n, len(gains)):
                    ag = (ag*(n-1) + gains[i])/n
                    al = (al*(n-1) + losses[i])/n
                    result.append(round(100 - 100/(1 + ag/al), 2) if al != 0 else 100.0)
                return result

            ma20 = sma(closes, 20)
            ma50 = sma(closes, 50)
            ema12 = ema(closes, 12)
            ema26 = ema(closes, 26)
            macd_line = [round(a-b, 2) if a and b else None for a, b in zip(ema12, ema26)]
            macd_vals = [v for v in macd_line if v is not None]
            signal_raw = ema(macd_vals, 9)
            signal_line = [None]*(len(macd_line)-len(macd_vals)) + signal_raw
            rsi14 = rsi(closes, 14)

            # 최근 60일만 출력
            n = min(60, len(dates))
            rows = []
            for i in range(len(dates)-n, len(dates)):
                rows.append({
                    "date": dates[i],
                    "close": round(closes[i], 2),
                    "volume": volumes[i],
                    "ma20": ma20[i],
                    "ma50": ma50[i],
                    "rsi14": rsi14[i],
                    "macd": macd_line[i],
                    "signal": signal_line[i],
                })

            last = rows[-1]
            summary = {
                "price": last["close"],
                "ma20": last["ma20"],
                "ma50": last["ma50"],
                "rsi14": last["rsi14"],
                "macd": last["macd"],
                "macd_signal": last["signal"],
                "macd_hist": round(last["macd"]-last["signal"], 2) if last["macd"] and last["signal"] else None,
                "trend": "bullish_aligned(MA20>MA50)" if last["ma20"] and last["ma50"] and last["ma20"] > last["ma50"] else "bearish_aligned(MA20<MA50)" if last["ma20"] and last["ma50"] else None,
                "rsi_state": "overbought(>=70)" if last["rsi14"] and last["rsi14"] >= 70 else "oversold(<=30)" if last["rsi14"] and last["rsi14"] <= 30 else "neutral" if last["rsi14"] else None,
                "atr14": atr(14),
            }

            print(json.dumps({"ticker": ticker, "summary": summary, "history": rows}))
        except Exception as e:
            print(json.dumps({"error": f"history 조회 실패: {e}"}, ensure_ascii=False))
        return

    # risk 모드: 리스크 관리용 데이터 + 손절가·포지션 사이징 사전계산
    # 사용법: py stock.py TICKER risk           → 총자산 1000만원·위험 1% 기본 가정
    #         py stock.py TICKER risk 5000000 2 → 총자산 500만원·위험 2%
    if mode == "risk":
        info = {}
        try:
            info = t.info or {}
        except Exception:
            info = {}
        price = fast("lastPrice") or info.get("currentPrice")
        if price is None:
            print(json.dumps({"error": f"{ticker} 가격 조회 실패."}, ensure_ascii=False))
            return
        beta = info.get("beta")
        high52 = fast("yearHigh") or info.get("fiftyTwoWeekHigh")
        low52 = fast("yearLow") or info.get("fiftyTwoWeekLow")

        # ATR(14) 계산
        atr_val = None
        try:
            h = t.history(period="3mo", interval="1d")
            cl = [float(r["Close"]) for _, r in h.iterrows()]
            hi = [float(r["High"]) for _, r in h.iterrows()]
            lo = [float(r["Low"]) for _, r in h.iterrows()]
            trs = [max(hi[i]-lo[i], abs(hi[i]-cl[i-1]), abs(lo[i]-cl[i-1])) for i in range(1, len(cl))]
            if len(trs) >= 14:
                atr_val = round(sum(trs[-14:])/14, 2)
        except Exception:
            pass

        # 총자산·위험% (인자 없으면 기본값)
        try:
            capital = float(sys.argv[3]) if len(sys.argv) > 3 else 10000000.0
        except Exception:
            capital = 10000000.0
        try:
            risk_pct = float(sys.argv[4]) if len(sys.argv) > 4 else 1.0
        except Exception:
            risk_pct = 1.0

        # 베타 기반 권장 비중 상한
        if beta is None:
            weight_cap = 5.0
        elif beta >= 2:
            weight_cap = 2.5   # 고변동 → 절반
        elif beta > 1:
            weight_cap = 4.0
        else:
            weight_cap = 5.0

        # 손절 후보: ① 고정 -8%  ② ATR×2
        stops = {}
        stop_fixed = round(price * 0.92, 2)
        stops["fixed_-8pct"] = stop_fixed
        if atr_val:
            stops["atr_2x"] = round(price - atr_val*2, 2)

        # 각 손절 기준별 포지션 사이징
        risk_amount = capital * (risk_pct/100.0)
        sizing = []
        for label, stop in stops.items():
            dist = round(price - stop, 2)
            if dist <= 0:
                continue
            shares = int(risk_amount // dist)
            cost = round(shares * price, 0)
            weight = round(cost/capital*100, 1)
            # 비중 상한 초과 시 상한으로 조정
            capped = False
            max_cost = capital * (weight_cap/100.0)
            if cost > max_cost:
                shares = int(max_cost // price)
                cost = round(shares * price, 0)
                weight = round(cost/capital*100, 1)
                capped = True
            sizing.append({
                "stop_type": label, "stop_price": stop, "stop_distance": dist,
                "stop_pct": round(dist/price*100, 1),
                "shares": shares, "position_cost": cost, "weight_pct": weight,
                "max_loss": round(shares*dist, 0), "weight_capped": capped,
                "target_1to2_RR": round(price + dist*2, 2),
            })

        print(json.dumps({
            "ticker": ticker, "name": info.get("shortName") or info.get("longName"),
            "price": price, "beta": beta, "atr14": atr_val,
            "high52": high52, "low52": low52,
            "assumed_capital": capital, "risk_pct": risk_pct,
            "weight_cap_pct": weight_cap,
            "position_sizing": sizing,
            "note": "shares=매수가능수량, max_loss=손절시손실액, target_1to2_RR=손익비1:2목표가. capital/risk는 인자로 변경가능: py stock.py TICKER risk 총자산 위험%",
        }, ensure_ascii=False))
        return

    # 기본: 현재가 + 밸류에이션
    info = {}
    try:
        info = t.info or {}
    except Exception:
        info = {}

    def g(key):
        try:
            return info.get(key)
        except Exception:
            return None

    out = {
        "ticker": ticker,
        "name": g("shortName") or g("longName"),
        "price": fast("lastPrice") or g("currentPrice"),
        "currency": fast("currency") or g("currency"),
        "marketCap": fast("marketCap") or g("marketCap"),
        "trailingPE": g("trailingPE"),
        "forwardPE": g("forwardPE"),
        "priceToSales": g("priceToSalesTrailing12Months"),
        "eps": g("trailingEps"),
        "high52": fast("yearHigh") or g("fiftyTwoWeekHigh"),
        "low52": fast("yearLow") or g("fiftyTwoWeekLow"),
        "sector": g("sector"),
        # 리스크매니저용: 변동성 지표
        "beta": g("beta"),
        # 펀더멘털분석가용: 재무 건전성·수익성
        "roe": g("returnOnEquity"),               # 자기자본이익률 (소수, 0.15 = 15%)
        "debtToEquity": g("debtToEquity"),         # 부채비율
        "profitMargin": g("profitMargins"),        # 순이익률 (소수)
        "revenueGrowth": g("revenueGrowth"),       # 매출성장률 (소수, YoY)
        "freeCashflow": g("freeCashflow"),         # 잉여현금흐름
        # 애널리스트 컨센서스: 목표가·투자의견
        "targetMean": g("targetMeanPrice"),        # 평균 목표가
        "targetHigh": g("targetHighPrice"),
        "targetLow": g("targetLowPrice"),
        "recommendation": g("recommendationKey"),  # buy/hold/sell 등
        "numAnalysts": g("numberOfAnalystOpinions"),
        # 포트폴리오매니저용: 일정·배당
        "dividendYield": g("dividendYield"),       # 배당수익률
        "earningsDate": None,                      # 아래에서 별도 조회
    }

    # 다음 실적 발표일 (포트폴리오매니저용)
    try:
        cal = t.calendar
        if cal is not None:
            ed = None
            if isinstance(cal, dict):
                ed = cal.get("Earnings Date")
            if ed:
                if isinstance(ed, (list, tuple)) and ed:
                    out["earningsDate"] = str(ed[0])
                else:
                    out["earningsDate"] = str(ed)
    except Exception:
        pass

    if out["price"] is None:
        print(json.dumps({"error": f"{ticker} 가격 조회 실패 — 티커 확인 또는 네트워크 점검."}, ensure_ascii=False))
        return
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
