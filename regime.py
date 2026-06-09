#!/usr/bin/env python3
# Connect AI · 시장 레짐 게이트 (v5 §5.5)
#
# 사용법:
#   py regime.py               → 현재 레짐 판정 JSON
#
# 출력:
#   regime: RISK_ON / CAUTION / RISK_OFF
#   RISK_ON  : SPY·QQQ 모두 MA200 위 → 정상 사이징 × 1.0
#   CAUTION  : 하나만 MA200 위 → 사이즈 50% 축소 + Buy Score +5 추가 요구
#   RISK_OFF : 둘 다 MA200 아래 → 신규 매수 차단 (기존 보유 Exit 로직만)
#
# 설계 근거 (v5):
#   RS는 상대강도다. 시장이 -30%일 때 -20%만 빠진 종목도 RS는 좋게 나온다.
#   RS만 믿으면 베어장에 신규 매수가 나간다. MA200 절대선이 이를 막는다.
#
# 사용자 확정 파라미터 (2026-06-09):
#   CAUTION_MULT=0.5, CAUTION_SCORE_REQ=5

import sys, json, math

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

CAUTION_MULT      = 0.5   # CAUTION 시 포지션 사이즈 배율
CAUTION_SCORE_REQ = 5     # CAUTION 시 Buy Score 추가 요구점수


def _get_price_and_ma200(yf, ticker):
    try:
        h = yf.Ticker(ticker).history(period="14mo", interval="1d")
        closes = [float(r["Close"]) for _, r in h.iterrows()]
        if len(closes) < 200:
            return None, None, len(closes)
        ma200 = sum(closes[-200:]) / 200
        price = closes[-1]
        return round(price, 2), round(ma200, 2), len(closes)
    except Exception:
        return None, None, 0


def evaluate(yf):
    spy_price, spy_ma200, spy_bars = _get_price_and_ma200(yf, "SPY")
    qqq_price, qqq_ma200, qqq_bars = _get_price_and_ma200(yf, "QQQ")

    details = {}

    if spy_price is None:
        details["SPY"] = {"error": f"데이터 수집 실패 (bars={spy_bars})"}
    else:
        spy_above = spy_price > spy_ma200
        details["SPY"] = {
            "price": spy_price,
            "ma200": spy_ma200,
            "above_ma200": spy_above,
            "gap_pct": round((spy_price / spy_ma200 - 1) * 100, 2),
        }

    if qqq_price is None:
        details["QQQ"] = {"error": f"데이터 수집 실패 (bars={qqq_bars})"}
    else:
        qqq_above = qqq_price > qqq_ma200
        details["QQQ"] = {
            "price": qqq_price,
            "ma200": qqq_ma200,
            "above_ma200": qqq_above,
            "gap_pct": round((qqq_price / qqq_ma200 - 1) * 100, 2),
        }

    if spy_price is None or qqq_price is None:
        return {
            "error": "레짐 판정 불가 — 데이터 수집 실패",
            "details": details,
        }

    spy_above = details["SPY"]["above_ma200"]
    qqq_above = details["QQQ"]["above_ma200"]

    if spy_above and qqq_above:
        regime       = "RISK_ON"
        regime_mult  = 1.0
        action       = "정상 사이징. 매수 신호 발생 시 전액 포지션 허용."
        score_adj    = 0
    elif spy_above or qqq_above:
        regime       = "CAUTION"
        regime_mult  = CAUTION_MULT
        action       = (f"포지션 {int(CAUTION_MULT*100)}%로 축소. "
                        f"Buy Score +{CAUTION_SCORE_REQ}점 추가 요구.")
        score_adj    = CAUTION_SCORE_REQ
    else:
        regime       = "RISK_OFF"
        regime_mult  = 0.0
        action       = "신규 매수 차단. 기존 보유종목 Exit 로직만 작동."
        score_adj    = 0

    return {
        "regime":       regime,
        "regime_mult":  regime_mult,
        "caution_score_req": score_adj,
        "action":       action,
        "details":      details,
        "note": ("레짐 게이트(v5 §5.5). "
                 "CAUTION 시 Buy Score 실효 임계값: 기존 기준+5점 상향. "
                 "RISK_OFF 시 기존 보유종목 손절·추적 로직은 계속 작동."),
    }


def main():
    try:
        import yfinance as yf
    except ImportError:
        print(json.dumps(
            {"error": "yfinance 미설치. 'py -m pip install yfinance' 실행."},
            ensure_ascii=False,
        ))
        return

    result = evaluate(yf)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
