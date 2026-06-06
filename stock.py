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

import sys, json, math

# Windows 콘솔(cp949) 인코딩 충돌 방지 — 한글·기호 출력 시 UnicodeEncodeError로
# 크래시하던 문제 차단. 항상 UTF-8로 출력 강제.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def _sanitize_floats(obj):
    """float inf/nan → None, 문자열 "Infinity"/"NaN" → None (JSON 직렬화 불가 값 제거)."""
    if isinstance(obj, float):
        return None if (math.isinf(obj) or math.isnan(obj)) else obj
    if isinstance(obj, str) and obj in ("Infinity", "-Infinity", "NaN"):
        return None
    if isinstance(obj, dict):
        return {k: _sanitize_floats(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_floats(v) for v in obj]
    return obj


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

            def _classify_trend(price, ma20, ma50):
                """MA 순서뿐 아니라 현재가 위치까지 반영한다. MA20>MA50(정배열)이어도
                현재가가 MA50 아래로 이탈하면 상승추세가 아니라 '하락 전환 경고'다.
                (TSLA 오판 사례: 현재가<MA50인데 MA순서만 보고 '상승추세'라 한 버그 수정)"""
                if not (price and ma20 and ma50):
                    return None
                if ma20 > ma50:  # MA 정배열
                    if price >= ma20:
                        return "bullish(정배열·현재가 MA20 위 — 상승추세 확인)"
                    if price >= ma50:
                        return "pullback(정배열이나 현재가 MA20 아래 — 단기 눌림목)"
                    return "weakening(정배열이나 현재가 MA50 이탈 — 하락 전환 경고)"
                else:            # MA 역배열
                    if price <= ma20:
                        return "bearish(역배열·현재가 MA20 아래 — 하락추세)"
                    if price <= ma50:
                        return "rebound(역배열이나 현재가 MA20 위 — 단기 반등)"
                    return "recovering(역배열이나 현재가 MA50 회복 — 상승 전환 가능)"

            summary = {
                "price": last["close"],
                "ma20": last["ma20"],
                "ma50": last["ma50"],
                "rsi14": last["rsi14"],
                "macd": last["macd"],
                "macd_signal": last["signal"],
                "macd_hist": round(last["macd"]-last["signal"], 2) if last["macd"] and last["signal"] else None,
                "trend": _classify_trend(last["close"], last["ma20"], last["ma50"]),
                "rsi_state": "overbought(>=70)" if last["rsi14"] and last["rsi14"] >= 70 else "oversold(<=30)" if last["rsi14"] and last["rsi14"] <= 30 else "neutral" if last["rsi14"] else None,
                "atr14": atr(14),
            }

            summary["note"] = ("trend=미리계산된 추세 레이블 — 이 문자열을 그대로 인용할 것. "
                               "임의로 'Pullback', '상승추세', '눌림목' 같은 다른 단어로 바꾸지 말 것. "
                               "예: trend가 'weakening(...)' 이면 'weakening'으로 제시, 절대 'Pullback'으로 바꾸지 말 것. "
                               "rsi_state=overbought(>=70)/oversold(<=30)/neutral 중 하나(미리계산됨) — 그대로 쓸 것. "
                               "atr14=최근 14일 평균 변동폭(ATR, 달러). null이면 데이터 미제공.")
            print(json.dumps({"ticker": ticker, "summary": summary, "history": rows}, ensure_ascii=False))
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
        "sharesOutstanding": g("sharesOutstanding") or g("impliedSharesOutstanding"),
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
    # 저장·재인용 시 오염을 막으려면 입력 단계에서 거른다. 거른 필드는 None으로
    # 바꾸고 data_warnings에 사유를 남겨, 모델이 복원·추정하지 못하게 한다.
    data_warnings = []

    def _reject(field, low, high, reason):
        """out[field]가 [low, high] 밖이면 None으로 차단하고 경고 기록."""
        v = out.get(field)
        if v is None:
            return
        try:
            fv = float(v)
        except (TypeError, ValueError):
            return
        if fv < low or fv > high:
            data_warnings.append(f"{field}({v}) {reason} → 미제공 처리")
            out[field] = None

    # yfinance가 소수형(0.039=3.9%)과 퍼센트형(3.9=3.9%)을 일관되지 않게 반환.
    # _reject 전에 정규화: |값| > 2.0 이면 퍼센트형으로 간주해 ÷100 → 소수형으로.
    # 실제 순이익률·ROE·성장률이 ±200%를 넘는 경우는 사실상 없으므로 안전.
    for _pct_field in ("profitMargin", "roe", "revenueGrowth"):
        _v = out.get(_pct_field)
        if _v is not None:
            try:
                _fv = float(_v)
                if abs(_fv) > 2.0:
                    out[_pct_field] = _fv / 100
            except (TypeError, ValueError):
                pass

    # 순이익률: +100%(1.0) 초과·-1000%(-10.0) 미만은 정규화 후에도 비현실적.
    _reject("profitMargin", -10.0, 1.0, "비현실적")
    # ROE: 적자/자본잠식 기업에서 폭주값. ±1000%(=±10.0) 밖이면 신뢰 불가.
    _reject("roe", -10.0, 10.0, "비현실적")
    # 매출성장률(YoY): 하한 -100%(-1.0)는 매출 0 수렴이 한계, 그 아래는 불가능.
    # 상한 +5000%(50.0)는 사실상 데이터 오류(기저효과여도 과도).
    _reject("revenueGrowth", -1.0, 50.0, "비현실적")
    # 배당수익률: 소수값(0.025=2.5%). yfinance가 가끔 퍼센트형(2.5)을 섞어 내보냄.
    # 1.0(=100%) 초과는 단위 혼동/오류 → 신뢰 불가.
    _reject("dividendYield", 0.0, 1.0, "단위 혼동/비현실적")
    # 베타: 정상 범위는 대략 -3~3. ±10 밖이면 데이터 오류.
    _reject("beta", -10.0, 10.0, "비현실적")
    # 시가총액: 음수·0은 불가, 상한 1e14($100조)는 사실상 데이터 오류(현존 최대 ~$4조대).
    _reject("marketCap", 1.0, 1e14, "비현실적")

    # 시가총액 자체 검증: price × sharesOutstanding 계산값과 비교.
    # yfinance marketCap이 종종 10배 오류를 내므로(IONQ 사례), KIS 교차검증 전에
    # 먼저 자체 데이터로 이상값을 잡는다. 3배 이상 차이면 계산값을 채택.
    _price = out.get("price")
    _shares = out.get("sharesOutstanding")
    _mc_raw = out.get("marketCap")
    if _price and _shares and _mc_raw:
        try:
            computed_mc = float(_price) * float(_shares)
            actual_mc = float(_mc_raw)
            if computed_mc > 0:
                ratio = actual_mc / computed_mc
                if ratio > 3.0 or ratio < 0.33:
                    data_warnings.append(
                        f"시가총액 오류 감지: yfinance {actual_mc:.0f} vs 주가×주식수 {computed_mc:.0f} "
                        f"(비율 {ratio:.1f}x) → 계산값으로 교체")
                    out["marketCap"] = computed_mc
        except (TypeError, ValueError):
            pass

    # 시가총액 표시용 텍스트를 Python에서 미리 계산 — 9B 모델의 단위 변환(억/조) 실수를
    # 원천 차단한다(buy_ratio_pct와 동일 원칙: 모델에게 산수를 맡기지 않는다).
    mc = out.get("marketCap")
    if mc:
        try:
            mc = float(mc)
            jo = mc / 1e12          # 조 단위
            if jo >= 1:
                jo_int = int(jo)
                eok = round((mc - jo_int * 1e12) / 1e8)
                out["marketCapText"] = (f"{jo_int}조 {eok:,}억 달러" if eok
                                        else f"{jo_int}조 달러")
            elif mc >= 1e8:         # 1억 달러 이상: 억 단위 정수
                out["marketCapText"] = f"{round(mc / 1e8):,}억 달러"
            else:                   # 1억 달러 미만(극소형주): 만 달러로 정밀 표시
                out["marketCapText"] = f"{round(mc / 1e4):,}만 달러"
        except (TypeError, ValueError):
            pass

    # 잉여현금흐름(FCF)도 원본 달러 정수라 9B 모델이 억/조 변환을 틀린다(AAPL FCF를
    # 10배 과대표시한 사례). marketCap과 동일하게 Python에서 미리 포맷한다. 음수(현금
    # 유출)도 부호를 살려 표시 — 적자/성장기업 판단에 중요.
    fcf = out.get("freeCashflow")
    if fcf is not None:
        try:
            fcf = float(fcf)
            neg = "-" if fcf < 0 else ""
            a = abs(fcf)
            jo = a / 1e12
            if jo >= 1:
                jo_int = int(jo)
                eok = round((a - jo_int * 1e12) / 1e8)
                body = f"{jo_int}조 {eok:,}억 달러" if eok else f"{jo_int}조 달러"
            elif a >= 1e8:
                body = f"{round(a / 1e8):,}억 달러"
            else:
                body = f"{round(a / 1e4):,}만 달러"
            out["freeCashflowText"] = neg + body
        except (TypeError, ValueError):
            pass

    # D/E(부채비율) 표시 문자열 사전계산.
    # yfinance가 비율형(0.61 = 61%)과 퍼센트형(18.74 = 18.74%)을 혼용.
    # |값| > 5이면 퍼센트형으로 간주해 ÷100 → 비율형으로 정규화.
    de = out.get("debtToEquity")
    if de is not None:
        try:
            de_val = float(de)
            if abs(de_val) > 5:
                de_ratio = de_val / 100
                de_pct = de_val
            else:
                de_ratio = de_val
                de_pct = de_val * 100
            out["debtToEquityText"] = f"{de_ratio:.2f}x ({de_pct:.1f}%)"
        except (TypeError, ValueError):
            pass

    # 배당수익률 표시용 텍스트 사전계산.
    # yfinance는 버전별로 소수형(0.0039=0.39%)과 퍼센트형(0.39=0.39%)을 혼용.
    # 휴리스틱: 값 >= 0.1이면 이미 % 형식으로 간주(그대로 사용), < 0.1이면 ×100.
    dy = out.get("dividendYield")
    if dy is not None:
        try:
            dy_val = float(dy)
            pct = round(dy_val if dy_val >= 0.1 else dy_val * 100, 2)
            out["dividendYieldPct"] = f"{pct}%"
        except (TypeError, ValueError):
            pass

    # 교차 일관성 검증 — 단일 필드는 정상 범위라도 필드 간 모순이면 신뢰 불가.
    # 부호가 연동된 지표(순이익에서 파생)끼리 어긋나면 한쪽이 오류 → 차단/경고.
    # IONQ 사례: "ROE 양수 vs 순이익률 적자/미제공" 같은 모순을 잡는다.
    def _sign(x):
        try:
            fx = float(x)
        except (TypeError, ValueError):
            return None
        return 1 if fx > 0 else (-1 if fx < 0 else 0)

    # trailingPE = 주가(>0)/EPS → 부호가 반드시 같아야 한다. 어긋나면 한쪽이 손상.
    # 어느 쪽이 틀린지 알 수 없으므로 둘 다 차단(모델 복원 방지).
    spe, seps = _sign(out.get("trailingPE")), _sign(out.get("eps"))
    if spe and seps and spe != seps:
        data_warnings.append(
            f"trailingPE({out['trailingPE']})와 EPS({out['eps']}) 부호 불일치 "
            "→ 한쪽이 데이터 오류, 둘 다 미제공 처리")
        out["trailingPE"] = None
        out["eps"] = None

    # ROE·순이익률은 둘 다 순이익에서 파생. 순이익률 분모(매출)는 항상 양수라
    # 부호가 신뢰 가능하지만, ROE 분모(자기자본)는 자본잠식 시 음수가 되어 부호가
    # 뒤집힌다. 둘이 어긋나면 ROE를 신뢰 불가로 보고 차단(순이익률은 유지).
    sroe, spm = _sign(out.get("roe")), _sign(out.get("profitMargin"))
    if sroe and spm and sroe != spm:
        data_warnings.append(
            f"ROE({out['roe']})와 순이익률({out['profitMargin']}) 부호 불일치 "
            "→ ROE 신뢰 불가(자본잠식 가능성), 미제공 처리")
        out["roe"] = None

    # 현재 PER 양수(흑자)인데 Forward PER 음수(향후 적자 전망)면 비정상 조합.
    # 차단까진 아니나 모델이 수익성을 단정하지 못하게 경고만 남긴다.
    # forwardPE가 진짜 음수(향후 EPS 적자 전망)인 경우만 경고.
    # trailingPE 양수라도 forwardPE 음수는 적법한 조합(일회성 흑자 후 적자 전망).
    fpe = out.get("forwardPE")
    tpe = out.get("trailingPE")
    if fpe is not None and tpe is not None:
        try:
            if float(tpe) > 0 and float(fpe) < 0:
                data_warnings.append(
                    f"현재 PER 양수(흑자)인데 Forward PER {fpe}(향후 EPS 적자 전망) "
                    "— 수익성 전환 불확실, 흑자 지속을 단정하지 말 것")
        except (TypeError, ValueError):
            pass

    # 한투(KIS) 교차검증 — yfinance가 시총·PER을 종종 10배 틀리게 준다(IONQ 사례).
    # 증권사급 한투 값(=실제 체결 소스)과 대조해 큰 차이가 나면 한투를 신뢰한다.
    # 자격증명 없거나 비미국 티커·API 실패 시 조용히 yfinance만 사용(graceful).
    try:
        from kis import fetch_quote
        kq = fetch_quote(ticker)
    except Exception:
        kq = None
    if kq:
        def _diverge(field, tol):
            """yfinance값(yv)과 한투값(kv)의 상대오차가 tol 초과면 (yv, kv) 반환, 아니면 None."""
            try:
                yv, kv = float(out.get(field)), float(kq.get(field))
            except (TypeError, ValueError):
                return None
            if kv == 0:
                return None
            return (yv, kv) if abs(yv - kv) / abs(kv) > tol else None

        # 현재가: 3% 초과 차이면 한투(체결가) 채택. 손절·진입 계산의 기준이라 엄격히.
        d = _diverge("price", 0.03)
        if d:
            data_warnings.append(
                f"현재가 불일치: yfinance ${d[0]} vs 한투 ${d[1]} → 한투(체결소스) 채택")
            out["price"] = d[1]
        # PER: 20% 초과 차이면 한투 채택.
        d = _diverge("trailingPE", 0.20)
        if d:
            data_warnings.append(
                f"PER 불일치: yfinance {d[0]} vs 한투 {d[1]} → 한투 채택")
            out["trailingPE"] = d[1]
        # 시가총액: yfinance 미제공이면 한투로 채움, 20% 초과 차이면 한투 채택.
        km = kq.get("marketCap")
        if km:
            if out.get("marketCap") is None:
                out["marketCap"] = km
                out["marketCapText"] = kq.get("marketCapText")
                data_warnings.append(
                    f"시가총액 yfinance 미제공 → 한투값 사용({kq.get('marketCapText')})")
            else:
                d = _diverge("marketCap", 0.20)
                if d:
                    data_warnings.append(
                        f"시가총액 불일치: yfinance vs 한투({kq.get('marketCapText')}) → 한투 채택")
                    out["marketCap"] = km
                    out["marketCapText"] = kq.get("marketCapText")
        out["kis_price"] = kq.get("price")
        out["kis_exchange"] = kq.get("exchange")

    # 애널리스트 컨센서스 정합성 — 의견 수가 0/없음이면 목표가는 신뢰 불가.
    na = out.get("numAnalysts")
    if not na:  # None 또는 0
        for f in ("targetMean", "targetHigh", "targetLow"):
            if out.get(f) is not None:
                out[f] = None
        if out.get("recommendation") is not None:
            data_warnings.append("애널리스트 의견 0명 → 목표가·추천 신뢰 불가, 미제공 처리")
            out["recommendation"] = None

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
                   "marketCapText=시가총액 표시용 문자열(미리계산됨) — 이 값만 사용할 것. marketCap 원본 수치(정수)는 보고서에 절대 표시하지 말 것. 직접 억/조 환산 산수도 금지. marketCapText 없으면 '데이터 미제공'. "
                   "freeCashflowText=잉여현금흐름(FCF) 표시용 문자열(미리계산됨, 음수는 현금유출) — 이 값을 그대로 쓰고 freeCashflow 원본으로 직접 환산 산수 하지 말 것. freeCashflowText 없으면 '데이터 미제공'. "
                   "debtToEquityText=부채비율 표시 문자열(미리계산됨, 예: '0.61x (61.0%)') — 이 값을 그대로 쓸 것. debtToEquity 원본으로 직접 '배'/'%' 변환 금지. debtToEquityText 없으면 '데이터 미제공'. "
                   "roe/profitMargin/revenueGrowth는 소수값 → ×100 해서 %로. "
                   "dividendYieldPct=배당수익률 표시용 문자열(미리계산됨, 예: '0.45%') — 이 값을 그대로 표시. dividendYield 원본으로 직접 계산 금지. "
                   "null이면 '데이터 미제공', 지어내지 말 것. "
                   "targetMean(애널리스트 목표가)와 손익비(R:R) 계산용 목표가는 전혀 다른 것 — 절대 한 문장에서 합치거나 '평균 X에서 Y까지'식으로 혼용하지 말 것. 애널리스트 목표가는 컨센서스로, R:R 목표가는 손절 기반 계산으로 따로 제시. "
                   "kis_price=한투(체결 소스) 현재가, kis_exchange=거래소. 한투와 대조해 큰 차이가 나면 data_warnings에 '한투 채택'으로 기록되며 해당 값은 이미 한투값으로 교체됨 — 교체된 값을 신뢰. "
                   "data_warnings가 있으면 해당 필드는 신뢰 불가로 걸러진 것 — 그 수치를 복원·추정하지 말 것. "
                   "그리고 data_warnings의 각 항목은 보고서 맨 위(① 결론 직전 또는 직후)에 '⚠️ 데이터 경고:'로 반드시 명시할 것 — 묻거나 생략 금지.")
    # 내부 계산용 원본값은 출력에서 제거 — 모델이 직접 환산 시도하는 것을 원천 차단.
    # marketCapText/freeCashflowText/debtToEquityText로 대체됨.
    for _k in ("marketCap", "freeCashflow", "sharesOutstanding", "debtToEquity"):
        out.pop(_k, None)
    print(json.dumps(_sanitize_floats(out), ensure_ascii=False))


if __name__ == "__main__":
    main()
