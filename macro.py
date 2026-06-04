#!/usr/bin/env python3
# Connect AI · 거시경제·시장심리 데이터 헬퍼 (yfinance 기반)
#
# 사용법:
#   py macro.py            → 핵심 거시지표 한 번에 (VIX·지수·금리·달러·환율·유가·금)
#   py macro.py TICKER     → 특정 지표 하나만 (예: py macro.py ^VIX)
#
# 출력은 항상 JSON 한 줄. 실패 시 {"error": "..."} 또는 항목별 null.
# AI는 null/error면 숫자를 지어내지 말고 "확인 실패"라고 답해야 한다.
#
# [주의] stock.py 교훈 적용: UTF-8 출력 강제, 출력에 이모지·특수문자 금지,
#    판단(과열/공포 등)은 여기서 계산해 라벨로 제공.

import sys, json

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# (티커, 한글명, 종류) — 종류는 해석 라벨링에 사용
INDICATORS = [
    ("^VIX",     "VIX 변동성지수",   "vix"),
    ("^GSPC",    "S&P 500",          "index"),
    ("^IXIC",    "나스닥 종합",      "index"),
    ("^DJI",     "다우존스",         "index"),
    ("DX-Y.NYB", "달러인덱스(DXY)",  "dollar"),
    ("^TNX",     "미 10년물 국채금리","yield"),
    ("KRW=X",    "원달러 환율",      "fx"),
    ("CL=F",     "WTI 유가",         "commodity"),
    ("GC=F",     "금 선물",          "commodity"),
    ("BTC-USD",  "비트코인",         "crypto"),
]


def fetch_one(yf, ticker):
    """현재값·전일종가·변동률을 반환. 실패하면 None들."""
    try:
        t = yf.Ticker(ticker)
        h = t.history(period="5d", interval="1d")
        closes = [float(r["Close"]) for _, r in h.iterrows()]
        if len(closes) < 1:
            return None
        cur = round(closes[-1], 2)
        prev = round(closes[-2], 2) if len(closes) >= 2 else None
        chg = None
        chg_pct = None
        if prev is not None and prev != 0:
            chg = round(cur - prev, 2)
            chg_pct = round((cur - prev) / prev * 100, 2)
        return {"value": cur, "prev": prev, "change": chg, "change_pct": chg_pct}
    except Exception:
        return None


def label_for(kind, value):
    """지표 종류별 해석 라벨 (영문 — 인코딩 안전)."""
    if value is None:
        return None
    if kind == "vix":
        if value >= 30:
            return "high_fear(>=30)"
        if value >= 20:
            return "elevated(20-30)"
        if value <= 13:
            return "complacent(<=13)"
        return "calm(13-20)"
    if kind == "yield":
        if value >= 5.0:
            return "high_yield(>=5%)"
        if value >= 4.0:
            return "elevated(4-5%)"
        if value <= 3.0:
            return "low(<=3%)"
        return "moderate(3-4%)"
    return None


def main():
    try:
        import yfinance as yf
    except ImportError:
        print(json.dumps({"error": "yfinance 미설치. 'py -m pip install yfinance' 실행 필요."}, ensure_ascii=False))
        return

    # 단일 티커 모드
    if len(sys.argv) > 1:
        ticker = sys.argv[1].strip()
        data = fetch_one(yf, ticker)
        if data is None:
            print(json.dumps({"error": f"{ticker} 조회 실패 — 티커/네트워크 확인."}, ensure_ascii=False))
            return
        print(json.dumps({"ticker": ticker, **data}, ensure_ascii=False))
        return

    # 전체 거시 스냅샷
    out = {}
    for ticker, name, kind in INDICATORS:
        d = fetch_one(yf, ticker)
        if d is None:
            out[ticker] = {"name": name, "value": None, "note": "조회 실패"}
            continue
        entry = {"name": name, **d}
        lbl = label_for(kind, d["value"])
        if lbl:
            entry["state"] = lbl
        out[ticker] = entry

    # 간단한 시장 국면 요약 (VIX + S&P 방향 기반)
    regime = None
    try:
        vix = out.get("^VIX", {}).get("value")
        spx_chg = out.get("^GSPC", {}).get("change_pct")
        if vix is not None and spx_chg is not None:
            if vix >= 30:
                regime = "risk_off_high_fear"
            elif vix >= 20:
                regime = "cautious"
            elif spx_chg >= 0 and vix < 20:
                regime = "risk_on_calm"
            else:
                regime = "neutral"
    except Exception:
        pass

    print(json.dumps({
        "indicators": out,
        "regime": regime,
        "note": "value=현재값, change_pct=전일대비%, state=해석라벨. 모든 수치는 실데이터이며 null이면 확인 실패로 답할 것. VIX>=20 경계, >=30 공포. 10년물 yield 단위는 %.",
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
