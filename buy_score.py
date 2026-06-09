#!/usr/bin/env python3
# Connect AI · Buy Score 계산 (v5 §3~§6)
#
# 사용법:
#   py buy_score.py TICKER                     → Buy Score 전체 분석
#   py buy_score.py TICKER --no-regime         → 레짐 체크 생략 (RISK_ON 가정)
#   py buy_score.py TICKER --conviction 상     → Conviction Band 직접 지정
#   py buy_score.py TICKER --log               → backtest_log.json 에 BUY 신호 기록
#
# Conviction Band 는 watchlist.json 에서 자동 읽음.
# 없으면 '중'으로 기본 설정 (Conviction 하 → 매수 차단).
#
# 사용자 확정 파라미터 (2026-06-09):
#   BAND_HIGH=38, BAND_MID=28 (raw 0~50)
#   CAUTION_MULT=0.5, CAUTION_SCORE_REQ=5
#   THEME_CAP=0.25 (25%), SECTOR_CAP=0.35 (35%)

import sys, json, math, os
from datetime import datetime, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SCORING_VERSION   = "1.0.0"

# 사용자 확정 파라미터 (2026-06-09)
BAND_HIGH         = 38     # Conviction '상' 하한 (raw 0~50)
BAND_MID          = 28     # Conviction '중' 하한 (이 미만 = '하' → 매수 차단)
CAUTION_MULT      = 0.5    # CAUTION 시 사이즈 배율
CAUTION_SCORE_REQ = 5      # CAUTION 시 Buy Score 추가 요구점수
THEME_CAP         = 0.25   # 단일 테마 합계 비중 상한 (25%)
SECTOR_CAP        = 0.35   # 단일 섹터 합계 비중 상한 (35%)

_LOG_PATH = "backtest_log.json"


def _sanitize(obj):
    if isinstance(obj, float):
        return None if (math.isinf(obj) or math.isnan(obj)) else obj
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return obj


# ─────────────────────────────────────────────────────────────
# 레짐 판정
# ─────────────────────────────────────────────────────────────

def get_regime(yf):
    def _ma200(ticker):
        try:
            h = yf.Ticker(ticker).history(period="14mo", interval="1d")
            closes = [float(r["Close"]) for _, r in h.iterrows()]
            if len(closes) < 200:
                return None, None
            return closes[-1], sum(closes[-200:]) / 200
        except Exception:
            return None, None

    spy_p, spy_ma = _ma200("SPY")
    qqq_p, qqq_ma = _ma200("QQQ")

    if spy_p is None or qqq_p is None:
        return "RISK_ON", 1.0, "레짐 데이터 수집 실패 — RISK_ON 기본값 사용"

    spy_above = spy_p > spy_ma
    qqq_above = qqq_p > qqq_ma

    if spy_above and qqq_above:
        return "RISK_ON", 1.0, f"SPY {spy_p:.0f}>{spy_ma:.0f}, QQQ {qqq_p:.0f}>{qqq_ma:.0f}"
    elif spy_above or qqq_above:
        which = f"SPY {'위' if spy_above else '아래'}, QQQ {'위' if qqq_above else '아래'}"
        return "CAUTION", CAUTION_MULT, which
    else:
        return "RISK_OFF", 0.0, f"SPY {spy_p:.0f}<{spy_ma:.0f}, QQQ {qqq_p:.0f}<{qqq_ma:.0f}"


# ─────────────────────────────────────────────────────────────
# 데이터 수집 (screen.py fetch_metrics 동일 로직)
# ─────────────────────────────────────────────────────────────

def fetch_benchmarks(yf):
    result = {}
    for bm in ["SPY", "QQQ"]:
        try:
            h = yf.Ticker(bm).history(period="7mo", interval="1d")
            closes = [float(r["Close"]) for _, r in h.iterrows()]
            if len(closes) >= 126:
                result[bm] = (closes[-1] / closes[-126]) - 1
        except Exception:
            pass
    return result


def fetch_metrics(yf, ticker, benchmarks=None):
    try:
        t = yf.Ticker(ticker)
        h = t.history(period="1y", interval="1d")
        closes = [float(r["Close"]) for _, r in h.iterrows()]
        if len(closes) < 30:
            return None

        price = round(closes[-1], 2)
        ma20  = round(sum(closes[-20:]) / 20, 2)  if len(closes) >= 20  else None
        ma50  = round(sum(closes[-50:]) / 50, 2)  if len(closes) >= 50  else None
        ma200 = round(sum(closes[-200:]) / 200, 2) if len(closes) >= 200 else None

        ma_alignment = None
        if ma20 and ma50 and ma200:
            if ma20 > ma50 > ma200:
                ma_alignment = 1
            elif ma20 < ma50 < ma200:
                ma_alignment = -1
            else:
                ma_alignment = 0

        ret_6m = (closes[-1] / closes[-126] - 1) if len(closes) >= 126 else None
        rs_combined = None
        if ret_6m is not None and benchmarks:
            spy_r = benchmarks.get("SPY")
            qqq_r = benchmarks.get("QQQ")
            rs_spy = (ret_6m - spy_r > 0) if spy_r is not None else None
            rs_qqq = (ret_6m - qqq_r > 0) if qqq_r is not None else None
            if rs_spy is not None and rs_qqq is not None:
                rs_combined = 1.0 if (rs_spy and rs_qqq) else (0.5 if (rs_spy or rs_qqq) else 0.0)

        info = {}
        try:
            info = t.info or {}
        except Exception:
            pass

        high52 = info.get("fiftyTwoWeekHigh")
        low52  = info.get("fiftyTwoWeekLow")
        pos52  = None
        if high52 and low52 and high52 != low52:
            pos52 = round((price - low52) / (high52 - low52) * 100, 1)

        mc   = info.get("marketCap")
        mc_b = mc / 1e9 if mc else None
        fcf  = info.get("freeCashflow")
        cash = info.get("totalCash")

        cash_runway_q = None
        if cash is not None and fcf is not None:
            if fcf >= 0:
                cash_runway_q = 99
            else:
                q_burn = abs(fcf) / 4
                if q_burn > 0:
                    cash_runway_q = round(cash / q_burn, 1)

        # 실적 D-day
        earnings_days = None
        try:
            import time as tm
            ed = info.get("earningsTimestamp") or info.get("earningsDate")
            if ed:
                if isinstance(ed, (list, tuple)):
                    ed = ed[0]
                days = (float(ed) - tm.time()) / 86400
                if -7 <= days <= 60:
                    earnings_days = int(days)
        except Exception:
            pass

        return {
            "ticker": ticker,
            "price": price,
            "ma20": ma20, "ma50": ma50, "ma200": ma200,
            "ma_alignment": ma_alignment,
            "ret_6m_pct": round(ret_6m * 100, 1) if ret_6m is not None else None,
            "rs_combined": rs_combined,
            "pos52": pos52,
            "high52": round(high52, 2) if high52 else None,
            "low52":  round(low52, 2)  if low52  else None,
            "marketCap": mc,
            "mc_b": mc_b,
            "revenueGrowth": info.get("revenueGrowth"),
            "grossMargins":  info.get("grossMargins"),
            "operatingMargins": info.get("operatingMargins"),
            "freeCashflow": fcf,
            "totalCash": cash,
            "cash_runway_q": cash_runway_q,
            "priceToSales": info.get("priceToSalesTrailing12Months"),
            "earningsDate_days": earnings_days,
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "name": info.get("shortName") or info.get("longName"),
        }
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────
# Fundamental Score (100점)
# ─────────────────────────────────────────────────────────────

def compute_fundamental_score(m):
    s = 0
    reasons = []

    # 1. 매출성장률 (25점)
    rg = m.get("revenueGrowth")
    if rg is not None:
        if rg >= 0.40:
            s += 25; reasons.append(f"초고성장 매출 {round(rg*100,1)}% (+25)")
        elif rg >= 0.25:
            s += 18; reasons.append(f"고성장 매출 {round(rg*100,1)}% (+18)")
        elif rg >= 0.10:
            s += 10; reasons.append(f"성장 매출 {round(rg*100,1)}% (+10)")
        else:
            reasons.append(f"저성장 매출 {round(rg*100,1)}% (0)")
    else:
        reasons.append("매출성장 데이터 미제공 (0)")

    # 2. Gross Margin (20점)
    gm = m.get("grossMargins")
    if gm is not None:
        if gm >= 0.60:
            s += 20; reasons.append(f"고마진 GM {round(gm*100,1)}% (+20)")
        elif gm >= 0.40:
            s += 13; reasons.append(f"양호 GM {round(gm*100,1)}% (+13)")
        elif gm < 0.20:
            s -= 5;  reasons.append(f"저마진 GM {round(gm*100,1)}% (-5)")
        else:
            reasons.append(f"GM {round(gm*100,1)}% (0)")
    else:
        reasons.append("Gross Margin 데이터 미제공 (0)")

    # 3. FCF (15점)
    fcf = m.get("freeCashflow")
    cr  = m.get("cash_runway_q")
    if fcf is not None:
        if fcf > 0:
            s += 15; reasons.append("FCF 흑자 (+15)")
        elif cr is not None and cr >= 4:
            s += 8;  reasons.append(f"FCF 전환 중 (Cash {cr:.1f}분기) (+8)")
        else:
            reasons.append("FCF 적자 (0)")
    else:
        reasons.append("FCF 데이터 미제공 (0)")

    # 4. Cash Runway (15점)
    if cr is not None:
        if cr >= 99:
            s += 15; reasons.append("Cash Runway: FCF 흑자 (+15)")
        elif cr >= 8:
            s += 15; reasons.append(f"Cash Runway {cr:.1f}분기 2년+ (+15)")
        elif cr >= 4:
            s += 8;  reasons.append(f"Cash Runway {cr:.1f}분기 1~2년 (+8)")
        else:
            s -= 15; reasons.append(f"Cash Runway {cr:.1f}분기 부족 — 희석 위험 (-15)")
    else:
        reasons.append("Cash Runway 산출 불가 (0)")

    # 5. 기관보유율 변화 (13점) — 선택적 외부 입력
    inst = m.get("inst_holding_change_pctpt")
    if inst is not None:
        if inst >= 10:
            s += 13; reasons.append(f"기관보유율 +{inst:.1f}%p (+13)")
        elif inst >= 5:
            s += 8;  reasons.append(f"기관보유율 +{inst:.1f}%p (+8)")
        elif inst < 0:
            s -= 5;  reasons.append(f"기관보유율 감소 {inst:.1f}%p (-5)")
        else:
            reasons.append(f"기관보유율 변화 미미 {inst:.1f}%p (0)")
    else:
        reasons.append("기관보유율 변화 데이터 미제공 — SEC 13F 별도 확인 (0)")

    # 6. Dataroma 슈퍼인베스터 (12점) — 선택적 외부 입력
    dt = m.get("dt_signal")
    if dt:
        if dt == "strong_conviction":
            s += 12; reasons.append("슈퍼인베스터 5명+ 보유 (+12)")
        elif dt == "multi_holder":
            s += 8;  reasons.append("슈퍼인베스터 3~4명 보유 (+8)")
        elif dt == "single_holder":
            s += 4;  reasons.append("슈퍼인베스터 1~2명 보유 (+4)")
    else:
        reasons.append("Dataroma 데이터 미제공 (0)")

    return max(0, min(100, round(s))), reasons


# ─────────────────────────────────────────────────────────────
# Market Score (100점, 역배열·RS열위 시 음수 가능)
# ─────────────────────────────────────────────────────────────

def compute_market_score(m):
    s = 0
    reasons = []

    # 1. RS 6M 종합 — SPY·QQQ (20점)
    rs_c = m.get("rs_combined")
    if rs_c is not None:
        if rs_c == 1.0:
            s += 20; reasons.append("RS 종합 양호 SPY·QQQ 모두 아웃퍼폼 (+20)")
        elif rs_c == 0.5:
            s += 10; reasons.append("RS 부분 양호 하나만 아웃퍼폼 (+10)")
        else:
            reasons.append("RS 열위 SPY·QQQ 모두 언더퍼폼 (0)")
    else:
        reasons.append("RS 데이터 부족 (0)")

    # 2. MA 정배열 20>50>200 (20점, §0 PASS)
    ma = m.get("ma_alignment")
    if ma is not None:
        if ma == 1:
            s += 20; reasons.append("MA 정배열(20>50>200) (+20)")
        elif ma == -1:
            s -= 10; reasons.append("MA 역배열(20<50<200) (-10)")
        else:
            reasons.append("MA 혼합 배열 (0)")
    else:
        reasons.append("MA 정배열 데이터 부족 (0)")

    # 3. 52주 위치 (20점, §0 PASS)
    pos = m.get("pos52")
    if pos is not None:
        if pos >= 65:
            s += 20; reasons.append(f"52주 상단 {pos}% (+20)")
        elif pos >= 40:
            s += 13; reasons.append(f"52주 중단 {pos}% (+13)")
        elif pos <= 25:
            s -= 5;  reasons.append(f"52주 하단 {pos}% (-5)")
        else:
            reasons.append(f"52주 하중단 {pos}% (0)")
    else:
        reasons.append("52주 위치 데이터 없음 (0)")

    # 4. Forward P/S (20점)
    # v5 경고: 고성장 섹터에서 낮은 P/S = 저평가가 아닐 수 있음. §0 IC 부호 미확인.
    ps = m.get("priceToSales")
    if ps is not None:
        if ps < 5:
            s += 20; reasons.append(f"낮은 P/S {round(ps,1)} (+20) — 고성장 섹터에서 저평가 함정 가능")
        elif ps < 10:
            s += 15; reasons.append(f"P/S {round(ps,1)} (+15)")
        elif ps < 20:
            s += 10; reasons.append(f"P/S {round(ps,1)} (+10)")
        elif ps < 40:
            s += 5;  reasons.append(f"P/S {round(ps,1)} (+5)")
        else:
            reasons.append(f"고평가 P/S {round(ps,1)} (0)")
    else:
        reasons.append("P/S 데이터 미제공 (0)")

    # 5. 실적 D-Day + EPS 예상 상향 (20점)
    ed = m.get("earningsDate_days")
    eps_rev = m.get("eps_revision_pct")
    if ed is not None and isinstance(ed, int):
        if 0 <= ed <= 30:
            if eps_rev is not None and eps_rev > 0:
                s += 20; reasons.append(f"실적 D-{ed}일 + EPS 상향 +{eps_rev}% (+20)")
            else:
                s += 8;  reasons.append(f"실적 D-{ed}일 (EPS 상향 데이터 없음) (+8)")
        elif -7 <= ed < 0:
            reasons.append(f"실적 발표 직후 ({abs(ed)}일 경과) (0)")

    return round(s), reasons


# ─────────────────────────────────────────────────────────────
# Buy Score + 판정
# ─────────────────────────────────────────────────────────────

def compute_buy_score(f_score, m_score, mc_b):
    if mc_b is not None and mc_b < 5:
        f_w, m_w = 0.8, 0.2
        weight_label = f"소형주 ${mc_b:.1f}B → F:M = 0.8:0.2"
    else:
        f_w, m_w = 0.6, 0.4
        mc_str = f"${mc_b:.1f}B" if mc_b else "N/A"
        weight_label = f"중대형주 {mc_str} → F:M = 0.6:0.4"
    return round(f_score * f_w + m_score * m_w), f_w, m_w, weight_label


def get_buy_decision(buy_score, conviction, regime, caution_req):
    """매수 판정 매트릭스 (v5 §5). 레짐 CAUTION 시 실효 점수 차감 적용."""
    if regime == "RISK_OFF":
        return "매수 차단 (RISK_OFF)"
    if conviction == "하":
        return "매수 차단 (Conviction 하)"

    eff = buy_score - (caution_req if regime == "CAUTION" else 0)

    if eff >= 85:
        return "적극 매수" if conviction == "상" else "분할 매수"
    elif eff >= 75:
        return "분할 매수" if conviction == "상" else "소량 진입"
    elif eff >= 65:
        return "소량 진입" if conviction == "상" else "관찰"
    else:
        return "관찰" if conviction == "상" else "보류"


def get_max_position_pct(buy_score, conviction, regime_mult):
    if buy_score >= 85 and conviction == "상":
        base = 0.10
    elif buy_score >= 80 and conviction in ("상", "중"):
        base = 0.07
    elif buy_score >= 75:
        base = 0.05
    else:
        base = 0.02
    return round(base * regime_mult * 100, 1)


# ─────────────────────────────────────────────────────────────
# Backtest 로그 기록
# ─────────────────────────────────────────────────────────────

def _log_buy_signal(ticker, result):
    try:
        if os.path.exists(_LOG_PATH):
            with open(_LOG_PATH, encoding="utf-8") as f:
                log = json.load(f)
        else:
            log = []
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        entry_id = f"{ticker}-{today}"
        for e in log:
            if e.get("id") == entry_id:
                print(json.dumps({"info": f"{entry_id} 이미 로그에 있음 — 덮어쓰지 않음."}, ensure_ascii=False))
                return
        m = result.get("metrics", {})
        log.append({
            "id":                entry_id,
            "date":              today,
            "ticker":            ticker,
            "action":            "BUY_SIGNAL",
            "signal_price":      m.get("price"),
            "fill_price":        None,
            "slippage_pct":      None,
            "buy_score":         result.get("buy_score"),
            "effective_score":   result.get("effective_buy_score"),
            "fundamental_score": result.get("fundamental_score"),
            "market_score":      result.get("market_score"),
            "conviction_band":   result.get("conviction"),
            "regime":            result.get("regime"),
            "position_size_pct": result.get("max_position_pct"),
            "f_weight":          result.get("f_weight"),
            "m_weight":          result.get("m_weight"),
            "buy_decision":      result.get("buy_decision"),
            "sector":            m.get("sector"),
            "exit_score_at_buy": 0,
        })
        with open(_LOG_PATH, "w", encoding="utf-8") as f:
            json.dump(log, f, ensure_ascii=False, indent=2)
        print(json.dumps({"logged": entry_id}, ensure_ascii=False), file=sys.stderr)
    except Exception as e:
        print(json.dumps({"log_error": str(e)}, ensure_ascii=False), file=sys.stderr)


# ─────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]

    if not args or args[0].startswith("-"):
        print(json.dumps({
            "error": "티커를 첫 번째 인수로 입력하세요. 예: py buy_score.py IONQ",
            "usage": "py buy_score.py TICKER [--no-regime] [--conviction 상|중|하] [--log]",
        }, ensure_ascii=False))
        return

    ticker       = args[0].upper()
    skip_regime  = "--no-regime" in args
    do_log       = "--log" in args
    conviction   = None

    for i, a in enumerate(args):
        if a == "--conviction" and i + 1 < len(args):
            conviction = args[i + 1]

    # watchlist.json 에서 Conviction Band 읽기
    if conviction is None:
        try:
            with open("watchlist.json", encoding="utf-8") as f:
                wl = json.load(f)
            entry = wl.get(ticker, {})
            conviction = entry.get("conviction_band")
        except Exception:
            pass
    if conviction is None:
        conviction = "중"

    try:
        import yfinance as yf
    except ImportError:
        print(json.dumps({"error": "yfinance 미설치. 'py -m pip install yfinance' 실행."}, ensure_ascii=False))
        return

    benchmarks = fetch_benchmarks(yf)
    m = fetch_metrics(yf, ticker, benchmarks)
    if m is None:
        print(json.dumps({"error": f"{ticker} 데이터 수집 실패"}, ensure_ascii=False))
        return

    if skip_regime:
        regime, regime_mult, regime_detail = "RISK_ON", 1.0, "레짐 체크 생략"
    else:
        regime, regime_mult, regime_detail = get_regime(yf)

    caution_req = CAUTION_SCORE_REQ if regime == "CAUTION" else 0

    f_score, f_reasons = compute_fundamental_score(m)
    ms_score, ms_reasons = compute_market_score(m)

    mc_b = m.get("mc_b")
    buy_score, f_w, m_w, weight_label = compute_buy_score(f_score, ms_score, mc_b)
    effective_score = buy_score - caution_req

    buy_decision = get_buy_decision(buy_score, conviction, regime, caution_req)
    max_pos_pct  = get_max_position_pct(buy_score, conviction, regime_mult)

    result = {
        "ticker":           ticker,
        "name":             m.get("name"),
        "scoring_version":  SCORING_VERSION,
        "regime":           regime,
        "regime_mult":      regime_mult,
        "regime_detail":    regime_detail,
        "conviction":       conviction,
        "fundamental_score": f_score,
        "market_score":      ms_score,
        "f_weight":          f_w,
        "m_weight":          m_w,
        "weight_label":      weight_label,
        "buy_score":         buy_score,
        "caution_score_req": caution_req,
        "effective_buy_score": effective_score,
        "buy_decision":      buy_decision,
        "max_position_pct":  max_pos_pct,
        "fundamental_reasons": f_reasons,
        "market_reasons":    ms_reasons,
        "metrics": {
            "price":            m.get("price"),
            "sector":           m.get("sector"),
            "mc_b":             round(mc_b, 2) if mc_b else None,
            "revenueGrowth_pct": round(m["revenueGrowth"]*100, 1) if m.get("revenueGrowth") is not None else None,
            "grossMargins_pct": round(m["grossMargins"]*100, 1) if m.get("grossMargins") is not None else None,
            "pos52":            m.get("pos52"),
            "ma_alignment":     m.get("ma_alignment"),
            "rs_combined":      m.get("rs_combined"),
            "cash_runway_q":    m.get("cash_runway_q"),
            "priceToSales":     m.get("priceToSales"),
            "earningsDate_days": m.get("earningsDate_days"),
        },
        "concentration_limits": {
            "theme_cap_pct":  THEME_CAP * 100,
            "sector_cap_pct": SECTOR_CAP * 100,
            "note": "단일 테마(25%) · 섹터(35%) 상한 초과 시 사이즈 축소 또는 보류",
        },
        "note": (
            "기관보유율 변화(13점)·Dataroma(12점)·EPS 상향(20점)은 외부 데이터 필요 — "
            "dataroma.py·sec.py 결과를 --conviction 등으로 보완. "
            "Forward P/S 가점: 고성장 섹터 저평가 함정 가능(v5 §4 경고). "
            "Conviction Band는 watchlist.json 자동 참조 또는 --conviction 직접 지정."
        ),
    }

    if do_log:
        _log_buy_signal(ticker, result)

    print(json.dumps(_sanitize(result), ensure_ascii=False))


if __name__ == "__main__":
    main()
