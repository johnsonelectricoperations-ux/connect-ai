#!/usr/bin/env python3
# Connect AI · Exit Score (v5 §8)
#
# 사용법:
#   py exit_score.py                    → portfolio.csv 전 보유종목 일괄 체크
#   py exit_score.py IONQ               → 특정 종목만
#   py exit_score.py IONQ --entry 45.0  → 진입가 직접 지정 (portfolio.csv 없을 때)
#
# [A] 가격 손절 (매일, 펀더멘털과 독립) — 가장 우선
#   - 진입가 대비 -20% 하드 스톱
#   - MA50 이탈 + 거래량 2배 동반
#   - 고점(trailing_high) 대비 -25% 트레일링 스톱
#
# [B] 펀더멘털 악화 (주 1회 누적 감점)
#   - 매출 성장 둔화, GM 악화, FCF 전환, 기관보유율 감소, Dataroma 매도, RS 마이너스,
#     CEO/CFO 교체
#
# [C] 밸류에이션 과열
#   - Forward P/S > 40, P/S > 5년 평균 3배
#   - RS 1개월 +50%+ (경고만, 감점 없음)
#
# 판정:
#   [A] 발동          → 즉시 매도 검토
#   [B]+[C] <= -5     → Exit Review 알림
#   [B]+[C] <= -10    → 강력 매도 신호
#
# trailing_high 는 portfolio_state.json 에 저장·갱신.
# 실패 시 {"error": ...}. null 값은 날조 금지.
#
# 사용자 확정 파라미터 (2026-06-09):
#   HARD_STOP_PCT=0.80 (-20%), MA50_VOL_MULT=2.0, TRAILING_STOP_PCT=0.75 (-25%)

import sys, json, os, csv, math
from datetime import datetime, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# 사용자 확정 파라미터 (2026-06-09)
HARD_STOP_PCT     = 0.80   # 진입가 × 0.80 → -20% 하드 스톱
MA50_VOL_MULT     = 2.0    # MA50 이탈 시 거래량 배수 기준
TRAILING_STOP_PCT = 0.75   # 고점 × 0.75 → -25% 트레일링 스톱

_PORTFOLIO_CSV   = "portfolio.csv"
_STATE_PATH      = "portfolio_state.json"
_LOG_PATH        = "backtest_log.json"


def _sanitize(obj):
    if isinstance(obj, float):
        return None if (math.isinf(obj) or math.isnan(obj)) else obj
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return obj


# ─────────────────────────────────────────────────────────────
# portfolio_state.json (trailing_high 등 상태 관리)
# ─────────────────────────────────────────────────────────────

def _load_state():
    if not os.path.exists(_STATE_PATH):
        return {}
    try:
        with open(_STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(state):
    with open(_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _update_trailing_high(state, ticker, current_price):
    """trailing_high 갱신: 현재가가 기존 고점보다 높으면 갱신."""
    prev = state.get(ticker, {}).get("trailing_high")
    if prev is None or current_price > prev:
        if ticker not in state:
            state[ticker] = {}
        state[ticker]["trailing_high"] = round(current_price, 2)
        state[ticker]["trailing_high_date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return state[ticker]["trailing_high"]


# ─────────────────────────────────────────────────────────────
# 데이터 수집
# ─────────────────────────────────────────────────────────────

def fetch_price_data(yf, ticker):
    """가격 + 거래량 + MA50 + 52주 위치 + 1개월 수익률."""
    try:
        t = yf.Ticker(ticker)
        h = t.history(period="1y", interval="1d")
        if len(h) < 10:
            return None

        closes  = [float(r["Close"])  for _, r in h.iterrows()]
        volumes = [float(r["Volume"]) for _, r in h.iterrows()]

        price   = round(closes[-1], 2)
        ma50    = round(sum(closes[-50:]) / 50, 2)  if len(closes) >= 50 else None
        ma200   = round(sum(closes[-200:]) / 200, 2) if len(closes) >= 200 else None

        # 거래량 20일 평균
        avg_vol = sum(volumes[-20:]) / min(len(volumes), 20)
        vol_ratio = round(volumes[-1] / avg_vol, 2) if avg_vol > 0 else None

        # 1개월 수익률
        ret_1m = round((closes[-1] / closes[-22] - 1) * 100, 1) if len(closes) >= 22 else None

        # 52주 위치
        high52 = max(closes[-252:]) if len(closes) >= 252 else max(closes)
        low52  = min(closes[-252:]) if len(closes) >= 252 else min(closes)
        pos52  = round((price - low52) / (high52 - low52) * 100, 1) if high52 != low52 else None

        return {
            "price":    price,
            "ma50":     ma50,
            "ma200":    ma200,
            "vol_ratio": vol_ratio,
            "ret_1m":   ret_1m,
            "pos52":    pos52,
            "high52":   round(high52, 2),
            "low52":    round(low52, 2),
        }
    except Exception:
        return None


def fetch_fundamental_data(yf, ticker):
    """펀더멘털 현재값 — 델타 감지는 backtest_log 스냅샷과 비교."""
    try:
        info = {}
        try:
            info = yf.Ticker(ticker).info or {}
        except Exception:
            pass

        rg  = info.get("revenueGrowth")
        gm  = info.get("grossMargins")
        fcf = info.get("freeCashflow")
        ps  = info.get("priceToSalesTrailing12Months")
        mc  = info.get("marketCap")

        return {
            "revenueGrowth":    rg,
            "grossMargins":     gm,
            "freeCashflow":     fcf,
            "priceToSales":     ps,
            "marketCap":        mc,
        }
    except Exception:
        return {}


def fetch_benchmarks_rs(yf, ticker):
    """종목 + SPY·QQQ 6M RS."""
    try:
        closes = {}
        for sym in [ticker, "SPY", "QQQ"]:
            h = yf.Ticker(sym).history(period="7mo", interval="1d")
            c = [float(r["Close"]) for _, r in h.iterrows()]
            if len(c) >= 126:
                closes[sym] = (c[-1] / c[-126]) - 1
        if ticker not in closes:
            return None
        sym_ret = closes[ticker]
        rs_spy = (sym_ret - closes["SPY"] > 0) if "SPY" in closes else None
        rs_qqq = (sym_ret - closes["QQQ"] > 0) if "QQQ" in closes else None
        if rs_spy is not None and rs_qqq is not None:
            if rs_spy and rs_qqq:
                return 1.0
            elif rs_spy or rs_qqq:
                return 0.5
            else:
                return 0.0
        return None
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────
# 손절 체크 [A]
# ─────────────────────────────────────────────────────────────

def check_price_stops(ticker, entry_price, current_price, trailing_high, pd):
    """[A] 가격 기반 손절 체크. returns (triggers, stop_details)."""
    triggers = []
    details  = {}

    # 하드 스톱: 진입가 × HARD_STOP_PCT
    hard_line = round(entry_price * HARD_STOP_PCT, 2)
    details["hard_stop"] = {
        "entry_price": round(entry_price, 2),
        "stop_level":  hard_line,
        "current":     current_price,
        "gap_pct":     round((current_price / entry_price - 1) * 100, 2),
    }
    if current_price <= hard_line:
        triggers.append(f"하드 스톱 발동 (진입가 {entry_price:.2f} × {HARD_STOP_PCT:.0%} = {hard_line:.2f}, 현재 {current_price:.2f})")

    # MA50 이탈 + 거래량 2배
    ma50      = pd.get("ma50")
    vol_ratio = pd.get("vol_ratio")
    if ma50 is not None and current_price < ma50:
        details["ma50_break"] = {
            "ma50": ma50,
            "current": current_price,
            "vol_ratio": vol_ratio,
        }
        if vol_ratio is not None and vol_ratio >= MA50_VOL_MULT:
            triggers.append(f"MA50 이탈 + 거래량 {vol_ratio:.1f}배 동반 (MA50={ma50:.2f})")

    # 트레일링 스톱: trailing_high × TRAILING_STOP_PCT
    if trailing_high is not None:
        trail_line = round(trailing_high * TRAILING_STOP_PCT, 2)
        pct_from_high = round((current_price / trailing_high - 1) * 100, 2)
        details["trailing_stop"] = {
            "trailing_high": trailing_high,
            "stop_level":    trail_line,
            "current":       current_price,
            "from_high_pct": pct_from_high,
        }
        if current_price <= trail_line:
            triggers.append(f"트레일링 스톱 발동 (고점 {trailing_high:.2f} × {TRAILING_STOP_PCT:.0%} = {trail_line:.2f}, 현재 {current_price:.2f})")
    else:
        details["trailing_stop"] = {"note": "trailing_high 없음 — portfolio_state.json 초기화 후 추적 시작"}

    return triggers, details


# ─────────────────────────────────────────────────────────────
# 펀더멘털 악화 [B] + 밸류에이션 과열 [C]
# ─────────────────────────────────────────────────────────────

def check_fundamental_deterioration(ticker, fd, rs_combined, snapshot=None):
    """[B] 펀더멘털 악화 감점. snapshot = backtest_log 진입 시점 데이터.

    snapshot이 없으면 델타 기반 항목을 산출 불가로 표시.
    절대값 기준 항목(FCF 전환, RS 마이너스, P/S 과열)은 snapshot 없이도 확인 가능.
    """
    score = 0
    flags = []
    notes = []

    # FCF 흑자→적자 전환 (절대값 확인 가능)
    fcf = fd.get("freeCashflow")
    if fcf is not None and fcf < 0:
        score -= 2; flags.append("FCF 적자 (-2)")
    elif fcf is None:
        notes.append("FCF 데이터 미제공")

    # RS 6개월 SPY·QQQ 모두 마이너스 전환 (절대값 확인 가능)
    if rs_combined is not None:
        if rs_combined == 0.0:
            score -= 2; flags.append("RS 6M SPY·QQQ 모두 언더퍼폼 (-2)")
    else:
        notes.append("RS 데이터 미제공")

    # 매출성장 둔화 (델타 필요)
    if snapshot and snapshot.get("revenueGrowth") is not None and fd.get("revenueGrowth") is not None:
        rg_delta = (fd["revenueGrowth"] - snapshot["revenueGrowth"]) * 100
        if rg_delta <= -10:
            score -= 3; flags.append(f"매출성장 -{abs(rg_delta):.1f}%p 둔화 (-3)")
    else:
        notes.append("매출성장 둔화: 진입 스냅샷 없음 — backtest_log.json 기록 후 추적 가능")

    # Gross Margin 악화 (델타 필요)
    if snapshot and snapshot.get("grossMargins") is not None and fd.get("grossMargins") is not None:
        gm_delta = (fd["grossMargins"] - snapshot["grossMargins"]) * 100
        if gm_delta <= -5:
            score -= 2; flags.append(f"GM -{abs(gm_delta):.1f}%p 악화 (-2)")
    else:
        notes.append("GM 악화: 진입 스냅샷 없음 — backtest_log.json 기록 후 추적 가능")

    # 기관보유율 감소 — SEC 13F 데이터 필요 (선택적)
    inst = fd.get("inst_holding_change_pctpt")
    if inst is not None and inst <= -10:
        score -= 2; flags.append(f"기관보유율 -{abs(inst):.1f}%p 감소 (-2)")
    else:
        notes.append("기관보유율 변화: sec.py 결과 별도 확인 필요")

    # Dataroma 슈퍼인베스터 매도 — 선택적
    dt_sell = fd.get("dt_sell")
    if dt_sell:
        score -= 2; flags.append("Dataroma 슈퍼인베스터 매도 (-2)")
    else:
        notes.append("Dataroma 매도: dataroma.py 결과 별도 확인 필요")

    # CEO/CFO 교체 — 뉴스 기반 선택적 입력
    ceo_change = fd.get("ceo_change")
    cfo_change = fd.get("cfo_change")
    dilution   = fd.get("secondary_offering")
    if ceo_change:
        score -= 5; flags.append("CEO 교체 (-5)")
    if cfo_change and dilution:
        score -= 8; flags.append("CFO 교체 + 유상증자 동시 발생 (-8)")
    elif cfo_change:
        score -= 4; flags.append("CFO 교체 (-4)")

    return score, flags, notes


def check_valuation_overheat(fd, pd):
    """[C] 밸류에이션 과열 감점."""
    score = 0
    flags = []
    warnings = []

    ps = fd.get("priceToSales")
    if ps is not None:
        if ps > 40:
            score -= 3; flags.append(f"Forward P/S {round(ps,1)} > 40 (-3)")

    # RS 1개월 +50%+ → 경고만 (감점 없음, 텐배거 과정에서 정상)
    ret_1m = pd.get("ret_1m")
    if ret_1m is not None and ret_1m >= 50:
        warnings.append(f"RS 1개월 +{ret_1m:.1f}% — 경고만 (텐배거 과정 정상, 감점 없음)")

    return score, flags, warnings


# ─────────────────────────────────────────────────────────────
# 종합 판정
# ─────────────────────────────────────────────────────────────

def evaluate_exit(ticker, entry_price, yf, state):
    pd_data = fetch_price_data(yf, ticker)
    if pd_data is None:
        return {"ticker": ticker, "error": "가격 데이터 수집 실패"}

    current_price = pd_data["price"]
    trailing_high = _update_trailing_high(state, ticker, current_price)

    fd_data = fetch_fundamental_data(yf, ticker)
    rs_comb = fetch_benchmarks_rs(yf, ticker)

    # backtest_log에서 진입 스냅샷 탐색
    snapshot = None
    try:
        if os.path.exists(_LOG_PATH):
            with open(_LOG_PATH, encoding="utf-8") as f:
                log = json.load(f)
            for entry in reversed(log):
                if entry.get("ticker") == ticker and entry.get("action") in ("BUY", "BUY_SIGNAL"):
                    snapshot = entry.get("snapshot_metrics")
                    break
    except Exception:
        pass

    # [A] 가격 손절
    a_triggers, a_details = check_price_stops(
        ticker, entry_price, current_price, trailing_high, pd_data
    )

    # [B] 펀더멘털 악화
    b_score, b_flags, b_notes = check_fundamental_deterioration(
        ticker, fd_data, rs_comb, snapshot
    )

    # [C] 밸류에이션 과열
    c_score, c_flags, c_warnings = check_valuation_overheat(fd_data, pd_data)

    bc_score = b_score + c_score

    # 판정
    if a_triggers:
        verdict = "즉시 매도 검토 (가격 손절 발동)"
        urgency = "HIGH"
    elif bc_score <= -10:
        verdict = "강력 매도 신호 ([B][C] 누적 -10 이하)"
        urgency = "HIGH"
    elif bc_score <= -5:
        verdict = "Exit Review 알림 ([B][C] 누적 -5 이하)"
        urgency = "MEDIUM"
    else:
        verdict = "보유 유지 — 모니터링 계속"
        urgency = "LOW"

    unrealized_pct = round((current_price / entry_price - 1) * 100, 2) if entry_price else None

    return {
        "ticker":           ticker,
        "current_price":    current_price,
        "entry_price":      round(entry_price, 2),
        "unrealized_pct":   unrealized_pct,
        "trailing_high":    trailing_high,
        "verdict":          verdict,
        "urgency":          urgency,
        "section_A": {
            "label":    "[A] 가격 손절",
            "triggers": a_triggers,
            "triggered": bool(a_triggers),
            "params": {
                "hard_stop_pct":     f"-{int((1-HARD_STOP_PCT)*100)}%",
                "ma50_vol_mult":     f"×{MA50_VOL_MULT}",
                "trailing_stop_pct": f"-{int((1-TRAILING_STOP_PCT)*100)}%",
            },
            "details": a_details,
        },
        "section_BC": {
            "label":       "[B]+[C] 펀더멘털·밸류에이션",
            "score":       bc_score,
            "b_score":     b_score,
            "c_score":     c_score,
            "b_flags":     b_flags,
            "c_flags":     c_flags,
            "c_warnings":  c_warnings,
            "data_notes":  b_notes,
        },
        "market_data": {
            "ma50":      pd_data.get("ma50"),
            "ma200":     pd_data.get("ma200"),
            "vol_ratio": pd_data.get("vol_ratio"),
            "ret_1m":    pd_data.get("ret_1m"),
            "pos52":     pd_data.get("pos52"),
            "rs_combined_6m": rs_comb,
        },
        "note": (
            "[A] 가격 손절은 매일 독립적으로 작동. "
            "[B][C] 델타 기반 항목은 buy_score.py --log 로 진입 시 스냅샷 기록 필요. "
            "기관보유율·Dataroma·CEO 교체는 외부 소스(sec.py·dataroma.py·news.py) 별도 확인."
        ),
    }


# ─────────────────────────────────────────────────────────────
# portfolio.csv 읽기
# ─────────────────────────────────────────────────────────────

def load_portfolio(path):
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for r in reader:
            t = (r.get("ticker") or "").strip().upper()
            if not t:
                continue
            def _num(k):
                v = (r.get(k) or "").strip()
                try:
                    return float(v) if v else None
                except Exception:
                    return None
            avg_cost = _num("avg_cost")
            if avg_cost:
                rows.append({"ticker": t, "avg_cost": avg_cost})
    return rows


# ─────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]

    try:
        import yfinance as yf
    except ImportError:
        print(json.dumps({"error": "yfinance 미설치. 'py -m pip install yfinance' 실행."}, ensure_ascii=False))
        return

    state = _load_state()

    # 특정 종목 + 진입가 직접 지정
    if args and not args[0].startswith("-"):
        ticker = args[0].upper()
        entry_price = None
        for i, a in enumerate(args):
            if a == "--entry" and i + 1 < len(args):
                try:
                    entry_price = float(args[i + 1])
                except ValueError:
                    pass

        # portfolio.csv에서 진입가 읽기
        if entry_price is None and os.path.exists(_PORTFOLIO_CSV):
            try:
                for row in load_portfolio(_PORTFOLIO_CSV):
                    if row["ticker"] == ticker:
                        entry_price = row["avg_cost"]
                        break
            except Exception:
                pass

        if entry_price is None:
            print(json.dumps({
                "error": f"{ticker} 진입가를 찾을 수 없습니다. "
                         "--entry 45.0 으로 직접 지정하거나 portfolio.csv 를 확인하세요.",
            }, ensure_ascii=False))
            return

        result = evaluate_exit(ticker, entry_price, yf, state)
        _save_state(state)
        print(json.dumps(_sanitize(result), ensure_ascii=False))
        return

    # portfolio.csv 전체 일괄 체크
    if not os.path.exists(_PORTFOLIO_CSV):
        print(json.dumps({
            "error": f"{_PORTFOLIO_CSV} 없음. 'py exit_score.py TICKER --entry 가격' 으로 개별 실행.",
        }, ensure_ascii=False))
        return

    try:
        holdings = load_portfolio(_PORTFOLIO_CSV)
    except Exception as e:
        print(json.dumps({"error": f"portfolio.csv 읽기 실패: {e}"}, ensure_ascii=False))
        return

    if not holdings:
        print(json.dumps({"error": "portfolio.csv 보유종목 없음."}, ensure_ascii=False))
        return

    results = []
    for h in holdings:
        r = evaluate_exit(h["ticker"], h["avg_cost"], yf, state)
        results.append(r)

    _save_state(state)

    high_urgency = [r["ticker"] for r in results if r.get("urgency") == "HIGH"]
    med_urgency  = [r["ticker"] for r in results if r.get("urgency") == "MEDIUM"]

    print(json.dumps(_sanitize({
        "exit_report": results,
        "summary": {
            "total": len(results),
            "immediate_action": high_urgency,
            "review_needed":    med_urgency,
            "hold":             [r["ticker"] for r in results if r.get("urgency") == "LOW"],
        },
        "params": {
            "hard_stop_pct":     f"-{int((1-HARD_STOP_PCT)*100)}%",
            "ma50_vol_mult":     f"×{MA50_VOL_MULT}",
            "trailing_stop_pct": f"-{int((1-TRAILING_STOP_PCT)*100)}%",
        },
    }), ensure_ascii=False))


if __name__ == "__main__":
    main()
