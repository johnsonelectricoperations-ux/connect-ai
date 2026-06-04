#!/usr/bin/env python3
# Connect AI · 간단 백테스팅 도구 (yfinance 기반)
#
# 사용법:
#   py backtest.py TICKER             → MA 골든/데드크로스 전략 (기본: 20/50일)
#   py backtest.py TICKER ma 10 30    → MA 크로스 (단기10/장기30)
#   py backtest.py TICKER rsi         → RSI 과매도 매수·과매수 매도 (30/70)
#   py backtest.py TICKER rsi 25 75   → RSI 임계값 지정
#
# 기간: 최근 2년 일봉. 매매비용 0.1% 가정. 룩어헤드 편향 없음(신호 다음날 체결).
# 출력은 JSON 한 줄. 전략 수익률 vs 단순보유(buy&hold) 비교.
#
# 교훈 적용: UTF-8 출력 강제, 이모지 금지, 계산은 전부 Python에서.

import sys, json

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

FEE = 0.001  # 편도 매매비용 0.1%


def sma(data, n, i):
    if i + 1 < n:
        return None
    return sum(data[i + 1 - n:i + 1]) / n


def compute_rsi(closes, n=14):
    rsis = [None] * len(closes)
    if len(closes) <= n:
        return rsis
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag = sum(gains[:n]) / n
    al = sum(losses[:n]) / n
    rsis[n] = 100 - 100 / (1 + ag / al) if al != 0 else 100.0
    for i in range(n, len(gains)):
        ag = (ag * (n - 1) + gains[i]) / n
        al = (al * (n - 1) + losses[i]) / n
        rsis[i + 1] = 100 - 100 / (1 + ag / al) if al != 0 else 100.0
    return rsis


def run_backtest(closes, signals):
    """signals[i] in {1=목표보유, 0=현금}. 신호 i는 i+1일 종가에 체결(룩어헤드 방지)."""
    cash, shares, position = 1.0, 0.0, 0
    trades = 0
    for i in range(len(closes) - 1):
        want = signals[i]
        price_next = closes[i + 1]
        if want == 1 and position == 0:
            shares = (cash * (1 - FEE)) / price_next
            cash = 0.0
            position = 1
            trades += 1
        elif want == 0 and position == 1:
            cash = shares * price_next * (1 - FEE)
            shares = 0.0
            position = 0
            trades += 1
    equity = cash + shares * closes[-1]
    return equity, trades


def max_drawdown(equity_curve):
    peak = equity_curve[0]
    mdd = 0.0
    for v in equity_curve:
        peak = max(peak, v)
        mdd = min(mdd, (v - peak) / peak)
    return round(mdd * 100, 2)


def equity_curve_from_signals(closes, signals):
    cash, shares, position = 1.0, 0.0, 0
    curve = [1.0]
    for i in range(len(closes) - 1):
        want = signals[i]
        price_next = closes[i + 1]
        if want == 1 and position == 0:
            shares = (cash * (1 - FEE)) / price_next
            cash = 0.0
            position = 1
        elif want == 0 and position == 1:
            cash = shares * price_next * (1 - FEE)
            shares = 0.0
            position = 0
        curve.append(cash + shares * price_next)
    return curve


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "ticker 필요. 예: py backtest.py AAPL"}, ensure_ascii=False))
        return
    ticker = sys.argv[1].upper().strip()
    strat = sys.argv[2].lower() if len(sys.argv) > 2 else "ma"

    try:
        import yfinance as yf
    except ImportError:
        print(json.dumps({"error": "yfinance 미설치. 'py -m pip install yfinance' 실행 필요."}, ensure_ascii=False))
        return

    try:
        h = yf.Ticker(ticker).history(period="2y", interval="1d")
        closes = [float(r["Close"]) for _, r in h.iterrows()]
    except Exception as e:
        print(json.dumps({"error": f"{ticker} 데이터 조회 실패: {e}"}, ensure_ascii=False))
        return

    if len(closes) < 60:
        print(json.dumps({"error": f"{ticker} 데이터 부족(거래일 {len(closes)}일)."}, ensure_ascii=False))
        return

    signals = [0] * len(closes)
    params = {}

    if strat == "rsi":
        low = float(sys.argv[3]) if len(sys.argv) > 3 else 30.0
        high = float(sys.argv[4]) if len(sys.argv) > 4 else 70.0
        params = {"strategy": "rsi", "buy_below": low, "sell_above": high}
        rsis = compute_rsi(closes, 14)
        holding = 0
        for i in range(len(closes)):
            r = rsis[i]
            if r is None:
                signals[i] = holding
                continue
            if r <= low:
                holding = 1
            elif r >= high:
                holding = 0
            signals[i] = holding
    else:  # ma cross
        short_n = int(sys.argv[3]) if len(sys.argv) > 3 else 20
        long_n = int(sys.argv[4]) if len(sys.argv) > 4 else 50
        params = {"strategy": "ma_cross", "short": short_n, "long": long_n}
        for i in range(len(closes)):
            s = sma(closes, short_n, i)
            l = sma(closes, long_n, i)
            signals[i] = 1 if (s is not None and l is not None and s > l) else 0

    strat_equity, trades = run_backtest(closes, signals)
    bh_equity = (closes[-1] / closes[0])  # buy & hold (비용 무시 근사)
    curve = equity_curve_from_signals(closes, signals)

    years = len(closes) / 252.0
    def cagr(mult):
        return round((mult ** (1 / years) - 1) * 100, 2) if mult > 0 and years > 0 else None

    print(json.dumps({
        "ticker": ticker,
        "params": params,
        "period_days": len(closes),
        "period_years": round(years, 2),
        "strategy_return_pct": round((strat_equity - 1) * 100, 2),
        "buyhold_return_pct": round((bh_equity - 1) * 100, 2),
        "strategy_cagr_pct": cagr(strat_equity),
        "buyhold_cagr_pct": cagr(bh_equity),
        "strategy_max_drawdown_pct": max_drawdown(curve),
        "num_trades": trades,
        "verdict": "strategy_beat_buyhold" if strat_equity > bh_equity else "buyhold_better",
        "note": "신호 다음날 종가 체결(룩어헤드 없음), 편도수수료 0.1%. 과거성과는 미래보장 아님. 표본기간 2년 한정.",
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
