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
            volumes = [int(r["Volume"]) for _, r in h.iterrows()]
            dates = [str(idx.date()) for idx in h.index]

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
                "trend": "정배열" if last["ma20"] and last["ma50"] and last["ma20"] > last["ma50"] else "역배열" if last["ma20"] and last["ma50"] else None,
                "rsi_state": "과매수" if last["rsi14"] and last["rsi14"] >= 70 else "과매도" if last["rsi14"] and last["rsi14"] <= 30 else "중립" if last["rsi14"] else None,
            }

            print(json.dumps({"ticker": ticker, "summary": summary, "history": rows}, ensure_ascii=False))
        except Exception as e:
            print(json.dumps({"error": f"history 조회 실패: {e}"}, ensure_ascii=False))
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
    }
    if out["price"] is None:
        print(json.dumps({"error": f"{ticker} 가격 조회 실패 — 티커 확인 또는 네트워크 점검."}, ensure_ascii=False))
        return
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
