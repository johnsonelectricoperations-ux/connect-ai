#!/usr/bin/env python3
# Connect AI · 미국 주식 데이터 헬퍼 (yfinance 기반)
#
# 사용법:
#   py stock.py IONQ          → 현재가 + 밸류에이션(시총·PER·P/S·EPS·52주) JSON
#   py stock.py IONQ hist     → 최근 60거래일 일봉(날짜,종가) — 기술적 분석용
#   py stock.py IONQ risk     → 손절·포지션 사이징 (리스크 관리용)
#   py stock.py IONQ analyst  → 애널리스트 등급변경 이력 + 추천 의견 추세
#
# 출력은 항상 JSON 한 줄. 실패 시 {"error": "..."} 를 출력하므로,
# AI는 error가 오면 숫자를 지어내지 말고 "데이터 확인 실패"라고 답해야 한다.

import sys, json

# Windows 콘솔(cp949) 인코딩 충돌 방지 — 한글·기호 출력 시 UnicodeEncodeError로
# 크래시하던 문제 차단. 항상 UTF-8로 출력 강제.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

def analyst_extras(t):
    """등급변경 이력 + stale 플래그 + 의견추세를 dict로 반환.
    analyst 모드와 기본 모드 양쪽에서 재사용 (9B가 명령 하나만 써도 데이터 확보)."""
    out = {"recent_rating_changes": [], "ratings_latest_date": None,
           "ratings_days_old": None, "ratings_stale": None,
           "recommendation_trend": [], "trend_direction": None,
           "buy_ratio_pct": None}
    # 최근 등급 변경 이력
    latest_change_date = None
    try:
        ud = t.upgrades_downgrades
        if ud is not None and not ud.empty:
            ud = ud.sort_index(ascending=False).head(12)
            for idx, row in ud.iterrows():
                d = str(idx.date()) if hasattr(idx, "date") else str(idx)
                if latest_change_date is None:
                    latest_change_date = d
                out["recent_rating_changes"].append({
                    "date": d,
                    "firm": str(row.get("Firm", "")),
                    "action": str(row.get("Action", "")),
                    "from": str(row.get("FromGrade", "")),
                    "to": str(row.get("ToGrade", "")),
                })
    except Exception:
        pass
    # 오래됨(>180일) 플래그
    if latest_change_date:
        try:
            import datetime as _dt
            ld = _dt.date.fromisoformat(latest_change_date)
            days_old = (_dt.date.today() - ld).days
            out["ratings_latest_date"] = latest_change_date
            out["ratings_days_old"] = days_old
            out["ratings_stale"] = days_old > 180
        except Exception:
            pass
    # 추천 의견 분포 추세
    try:
        rec = t.recommendations
        if rec is not None and not rec.empty:
            for _, row in rec.iterrows():
                out["recommendation_trend"].append({
                    "period": str(row.get("period", "")),
                    "strongBuy": int(row.get("strongBuy", 0)),
                    "buy": int(row.get("buy", 0)),
                    "hold": int(row.get("hold", 0)),
                    "sell": int(row.get("sell", 0)),
                    "strongSell": int(row.get("strongSell", 0)),
                })
    except Exception:
        pass

    # 추세 방향·매수비율 미리 계산 (9B 산수·요약 오류 차단 — AI는 읽기만)
    tr = out["recommendation_trend"]
    if tr:
        def bull_score(r):  # 매수(strongBuy+buy) - 매도(sell+strongSell)
            return (r["strongBuy"] + r["buy"]) - (r["sell"] + r["strongSell"])

        # 현재(0m) 매수비율 = (strongBuy+buy) / 전체 의견수
        cur = tr[0]
        total = cur["strongBuy"] + cur["buy"] + cur["hold"] + cur["sell"] + cur["strongSell"]
        if total > 0:
            out["buy_ratio_pct"] = round((cur["strongBuy"] + cur["buy"]) / total * 100, 1)

        # 추세 방향: 현재(0m) vs 가장 오래된 기간 비교
        oldest = tr[-1]
        diff = bull_score(cur) - bull_score(oldest)
        if diff > 0:
            out["trend_direction"] = "improving"   # 매수 우위 강화
        elif diff < 0:
            out["trend_direction"] = "worsening"    # 매수 우위 약화
        else:
            out["trend_direction"] = "stable"
    return out


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

    # analyst 모드: 애널리스트 등급 변경 이력 + 추천 의견 추세
    # 사용법: py stock.py TICKER analyst
    if mode == "analyst":
        info = {}
        try:
            info = t.info or {}
        except Exception:
            info = {}
        price = fast("lastPrice") or info.get("currentPrice")

        out = {
            "ticker": ticker,
            "name": info.get("shortName") or info.get("longName"),
            "price": price,
            # 현재 컨센서스 (요약)
            "consensus": {
                "recommendation": info.get("recommendationKey"),
                "targetMean": info.get("targetMeanPrice"),
                "targetHigh": info.get("targetHighPrice"),
                "targetLow": info.get("targetLowPrice"),
                "numAnalysts": info.get("numberOfAnalystOpinions"),
                "upside_pct": round((info.get("targetMeanPrice")/price - 1)*100, 1)
                              if price and info.get("targetMeanPrice") else None,
            },
        }

        # 등급변경 이력·stale·의견추세 (헬퍼 재사용)
        out.update(analyst_extras(t))

        out["note"] = ("recent_rating_changes=최근 등급변경(firm=증권사, action=up/down/init/main, from/to=등급). "
                       "ratings_stale=true면 등급변경 이력이 180일 이상 오래됨(ratings_days_old=경과일) → "
                       "'최근 변경'이라 말하지 말고 'X일 전 이력'으로 명시하고 신뢰도 낮음을 안내할 것. "
                       "buy_ratio_pct=매수비율%(미리계산), trend_direction=improving/worsening/stable(미리계산) — "
                       "그대로 쓰고 직접 산수·임의 판단 말 것. recommendation_trend은 원자료, 최신이라 신뢰 가능. "
                       "consensus.upside_pct=평균목표가 대비 상승여력%. "
                       "데이터 없으면 빈 배열 — 지어내지 말 것. 컨센서스는 참고지표일 뿐 매수신호 아님.")
        print(json.dumps(out, ensure_ascii=False))
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

        # 총자산·위험% (인자 없으면 기본값). 미국 주식이므로 총자산도 USD 기준.
        try:
            capital = float(sys.argv[3]) if len(sys.argv) > 3 else 10000.0  # 기본 $10,000
        except Exception:
            capital = 10000.0
        try:
            risk_pct = float(sys.argv[4]) if len(sys.argv) > 4 else 1.0
        except Exception:
            risk_pct = 1.0

        # 다음 실적 발표일 (환각 방지 — 실제 값 제공)
        earnings_date = None
        try:
            cal = t.calendar
            if isinstance(cal, dict):
                ed = cal.get("Earnings Date")
                if ed:
                    earnings_date = str(ed[0]) if isinstance(ed, (list, tuple)) and ed else str(ed)
        except Exception:
            pass

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
            "high52": high52, "low52": low52, "earningsDate": earnings_date,
            "assumed_capital_usd": capital, "currency": "USD", "risk_pct": risk_pct,
            "weight_cap_pct": weight_cap,
            "position_sizing": sizing,
            "note": "모든 금액 USD. assumed_capital_usd=가정 총자산($), shares=매수가능수량, position_cost=매수금액($), max_loss=손절시손실액($), target_1to2_RR=손익비1:2목표가($). 총자산/위험% 변경: py stock.py TICKER risk 달러총자산 위험%",
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

    # 데이터 품질 검증 — yfinance가 비현실적 값을 내보낼 때 차단 (날조 방지).
    # 예: IONQ(적자기업)에 profitMargins=1.7488(=174.88%) 같은 명백한 오류값.
    # 순이익률은 net income/revenue라 +100% 초과는 사실상 데이터 오류.
    data_warnings = []
    pm = out.get("profitMargin")
    if pm is not None and (pm > 1.0 or pm < -10.0):
        data_warnings.append(f"profitMargin({pm}) 비현실적 → 미제공 처리")
        out["profitMargin"] = None
    if data_warnings:
        out["data_warnings"] = data_warnings

    # 애널리스트 등급변경 이력·stale·의견추세를 기본 출력에도 병합
    # (9B 모델이 analyst 서브명령을 안 쓰고 기본 명령만 써도 데이터 확보되도록)
    out.update(analyst_extras(t))
    out["note"] = ("targetMean/recommendation/numAnalysts=현재 애널리스트 컨센서스. "
                   "buy_ratio_pct=매수(strongBuy+buy) 비율%(미리계산됨, 직접 산수 말 것). "
                   "trend_direction=improving/worsening/stable(미리계산됨) — 이 값을 그대로 쓰고 추세를 임의 판단 말 것. "
                   "recommendation_trend=월별 의견분포 원자료(period 0m=현재,-1m=한달전). "
                   "recent_rating_changes=증권사별 등급변경 이력. "
                   "ratings_stale=true면 등급변경이 ratings_days_old일 전이라 오래됨 → '최근 변경'이라 하지 말고 "
                   "'X일 전 이력, 신뢰도 낮음'으로 명시(단 trend_direction/recommendation_trend은 최신이라 신뢰 가능). "
                   "roe/profitMargin/revenueGrowth/dividendYield는 소수값 → ×100 해서 %로. null이면 '데이터 미제공', 지어내지 말 것. "
                   "data_warnings가 있으면 해당 필드는 신뢰 불가로 걸러진 것 — 그 수치를 복원·추정하지 말 것.")
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
