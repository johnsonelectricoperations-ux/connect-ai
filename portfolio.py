#!/usr/bin/env python3
# Connect AI · 보유 종목 관리 도구 (yfinance 기반)
#
# 보유 종목을 portfolio.csv 에 기록해두면, 현재가를 가져와 손익·손절거리·
# 목표거리·비중을 계산하고 매매 액션(보유/추가/익절/손절)을 플래그한다.
#
# portfolio.csv 형식 (워크스페이스에 위치, 헤더 포함):
#   ticker,shares,avg_cost,stop,target
#   IONQ,10,45.00,40.00,90.00
#   AAPL,5,180.00,165.00,220.00
#   (stop/target 비워도 됨)
#
# 사용법:
#   py portfolio.py             → 전체 보유 현황 + 액션 플래그
#   py portfolio.py FILE.csv    → 다른 파일 지정
#
# 출력 JSON. 모든 금액 USD. 교훈 적용: UTF-8 강제, 이모지 금지, 계산은 Python.

import sys, json, os, csv

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def load_holdings(path):
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for r in reader:
            t = (r.get("ticker") or "").strip().upper()
            if not t:
                continue
            def num(key):
                v = (r.get(key) or "").strip()
                try:
                    return float(v) if v else None
                except Exception:
                    return None
            rows.append({
                "ticker": t,
                "shares": num("shares") or 0.0,
                "avg_cost": num("avg_cost"),
                "stop": num("stop"),
                "target": num("target"),
            })
    return rows


def price_of(yf, ticker):
    try:
        t = yf.Ticker(ticker)
        try:
            p = t.fast_info["lastPrice"]
            if p:
                return float(p)
        except Exception:
            pass
        h = t.history(period="5d", interval="1d")
        closes = [float(r["Close"]) for _, r in h.iterrows()]
        return round(closes[-1], 2) if closes else None
    except Exception:
        return None


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "portfolio.csv"
    if not os.path.exists(path):
        print(json.dumps({
            "error": f"{path} 파일이 없습니다. 워크스페이스에 portfolio.csv 를 만들어주세요.",
            "template": "ticker,shares,avg_cost,stop,target\nIONQ,10,45.00,40.00,90.00",
        }, ensure_ascii=False))
        return

    try:
        holdings = load_holdings(path)
    except Exception as e:
        print(json.dumps({"error": f"CSV 읽기 실패: {e}"}, ensure_ascii=False))
        return

    if not holdings:
        print(json.dumps({"error": "보유 종목이 없습니다 (CSV 비어있음)."}, ensure_ascii=False))
        return

    try:
        import yfinance as yf
    except ImportError:
        print(json.dumps({"error": "yfinance 미설치. 'py -m pip install yfinance' 실행."}, ensure_ascii=False))
        return

    positions = []
    total_value = 0.0
    total_cost = 0.0
    for h in holdings:
        price = price_of(yf, h["ticker"])
        pos = {"ticker": h["ticker"], "shares": h["shares"], "avg_cost": h["avg_cost"],
               "stop": h["stop"], "target": h["target"], "price": price}
        if price is None:
            pos["action"] = "price_unavailable"
            positions.append(pos)
            continue

        value = round(price * h["shares"], 2)
        pos["value"] = value
        total_value += value

        if h["avg_cost"]:
            cost = h["avg_cost"] * h["shares"]
            total_cost += cost
            pos["unrealized_pl"] = round(value - cost, 2)
            pos["unrealized_pl_pct"] = round((price - h["avg_cost"]) / h["avg_cost"] * 100, 2)

        if h["stop"]:
            pos["to_stop_pct"] = round((price - h["stop"]) / price * 100, 2)
        if h["target"]:
            pos["to_target_pct"] = round((h["target"] - price) / price * 100, 2)

        # 액션 플래그 (우선순위 순)
        action = "hold"
        if h["stop"] and price <= h["stop"]:
            action = "STOP_BREACHED_sell"
        elif h["target"] and price >= h["target"]:
            action = "TARGET_HIT_take_profit"
        elif h["stop"] and pos.get("to_stop_pct") is not None and pos["to_stop_pct"] <= 3:
            action = "near_stop_watch"
        elif h["target"] and pos.get("to_target_pct") is not None and pos["to_target_pct"] <= 3:
            action = "near_target_watch"
        pos["action"] = action
        positions.append(pos)

    # 비중 계산
    for p in positions:
        if p.get("value") and total_value > 0:
            p["weight_pct"] = round(p["value"] / total_value * 100, 1)

    summary = {
        "total_value": round(total_value, 2),
        "total_cost": round(total_cost, 2) if total_cost else None,
        "total_unrealized_pl": round(total_value - total_cost, 2) if total_cost else None,
        "total_unrealized_pl_pct": round((total_value - total_cost) / total_cost * 100, 2) if total_cost else None,
        "num_positions": len(positions),
        "alerts": [f'{p["ticker"]}:{p["action"]}' for p in positions
                   if p.get("action") not in ("hold", None)],
    }

    print(json.dumps({
        "portfolio": positions,
        "summary": summary,
        "note": "모든 금액 USD. action: hold/near_stop_watch/near_target_watch/STOP_BREACHED_sell/TARGET_HIT_take_profit. to_stop_pct=손절가까지 하락여유%, to_target_pct=목표까지 상승여유%. 수치는 실데이터, 매매판단은 리스크규칙과 함께.",
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
