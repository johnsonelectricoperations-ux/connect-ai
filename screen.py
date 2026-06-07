#!/usr/bin/env python3
# Connect AI · 종목 발굴/스크리닝 도구 (yfinance 기반)
#
# 사용법:
#   py screen.py                        → watchlist.txt 를 value 전략으로 스크리닝
#   py screen.py value                  → 저평가/반등 전략
#   py screen.py momentum               → v5 성장모멘텀 전략 (MA정배열·RS·52주위치)
#   py screen.py tenbagger              → watchlist.txt 에서 텐배거 후보 발굴
#   py screen.py AAPL MSFT NVDA         → 티커 직접 지정
#   py screen.py suggest quantum        → 테마 유니버스 자동 발굴 (value 전략)
#   py screen.py suggest tenbagger      → 소형~중형 고성장 텐배거 유니버스 발굴
#   py screen.py suggest microcap       → 극소형주($30M~$300M) 텐배거 발굴 (고위험)
#   py screen.py suggest ai momentum    → 테마 유니버스 + 전략 지정
#   py screen.py suggest               → 사용 가능한 테마 목록 출력
#
# 전략:
#   value     : 52주 저점 근접 + RSI 낮음(과매도) + P/S 낮음 → 반등/저평가 후보
#   momentum  : MA정배열(20>50>200) + RS 종합(SPY·QQQ) + 52주 위치 + 매출성장 → v5 성장 모멘텀 후보
#   tenbagger : 극소형~중형주($30M~$50B) + 고성장 + Rule of 40(영업이익률) + RS + MA정배열 → 10배 후보
#
# 출력 JSON (점수 내림차순). UTF-8 강제, 이모지 금지, 계산은 Python.
#
# v2.0.0 변경:
#   - §0 백테스트 PASS 팩터 반영: MA정배열(20>50>200), RS 6M 종합, 52주 위치 모멘텀
#   - fetch_metrics: period="1y"(ma200), ma_alignment, rs_combined, grossMargins,
#                    operatingMargins, cash_runway_q 추가
#   - score_momentum: v5 검증 팩터 기반으로 전면 재작성
#   - score_tenbagger: RS·MA·Cash Runway 추가, Rule of 40 영업이익률 기준으로 수정,
#                      시총 상한 $50B로 확장

import sys, json, os, math

# 스코어링 알고리즘 버전 — docs/investment/SCORING.md와 항상 동기화.
# 항목·가중치·임계값 변경 시 반드시 버전 올리고 SCORING.md 변경이력 추가.
SCORING_VERSION = "2.0.0"

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


def load_watchlist(path):
    out = []
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            out.append(s.upper())
    return out


def rsi14(closes):
    n = 14
    if len(closes) <= n:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag = sum(gains[:n]) / n
    al = sum(losses[:n]) / n
    val = 100 - 100 / (1 + ag / al) if al != 0 else 100.0
    for i in range(n, len(gains)):
        ag = (ag * (n - 1) + gains[i]) / n
        al = (al * (n - 1) + losses[i]) / n
        val = 100 - 100 / (1 + ag / al) if al != 0 else 100.0
    return round(val, 1)


def fetch_benchmark_returns(yf):
    """SPY/QQQ 6개월 수익률 계산 (종목별 RS 계산 기준)."""
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
        h = t.history(period="1y", interval="1d")   # 1년 — ma200 계산에 필요
        closes = [float(r["Close"]) for _, r in h.iterrows()]
        if len(closes) < 30:
            return None

        price = round(closes[-1], 2)
        ma20  = round(sum(closes[-20:]) / 20, 2)  if len(closes) >= 20  else None
        ma50  = round(sum(closes[-50:]) / 50, 2)  if len(closes) >= 50  else None
        ma200 = round(sum(closes[-200:]) / 200, 2) if len(closes) >= 200 else None

        # MA 정배열 / 역배열 (§0 PASS — IC 0.021, t=3.9)
        ma_alignment = None
        if ma20 and ma50 and ma200:
            if ma20 > ma50 > ma200:
                ma_alignment = 1    # 정배열
            elif ma20 < ma50 < ma200:
                ma_alignment = -1   # 역배열
            else:
                ma_alignment = 0    # 혼합

        # RS 6개월 (§0 PASS — IC 0.023, t=3.7)
        ret_6m = (closes[-1] / closes[-126] - 1) if len(closes) >= 126 else None
        rs_spy_positive = rs_qqq_positive = rs_combined = None
        if ret_6m is not None and benchmarks:
            spy_ret = benchmarks.get("SPY")
            qqq_ret = benchmarks.get("QQQ")
            if spy_ret is not None:
                rs_spy_positive = (ret_6m - spy_ret) > 0
            if qqq_ret is not None:
                rs_qqq_positive = (ret_6m - qqq_ret) > 0
            if rs_spy_positive is not None and rs_qqq_positive is not None:
                if rs_spy_positive and rs_qqq_positive:
                    rs_combined = 1.0
                elif rs_spy_positive or rs_qqq_positive:
                    rs_combined = 0.5
                else:
                    rs_combined = 0.0

        # trend: ma_alignment 기반으로 업데이트 (하위 호환 유지)
        if ma_alignment == 1:
            trend = "up"
        elif ma_alignment == -1:
            trend = "down"
        elif ma_alignment == 0:
            trend = "mixed"
        else:
            # ma200 계산 불가(데이터 부족) 시 ma50 기준 폴백
            trend = "up" if (ma50 and ma20 > ma50) else "down" if ma50 else None

        info = {}
        try:
            info = t.info or {}
        except Exception:
            info = {}

        high52 = info.get("fiftyTwoWeekHigh")
        low52  = info.get("fiftyTwoWeekLow")
        pos52  = None
        if high52 and low52 and high52 != low52:
            pos52 = round((price - low52) / (high52 - low52) * 100, 1)  # 0=저점, 100=고점

        # profitMargins: yfinance가 소수형(0.039)과 퍼센트형(3.9)을 혼용 → 정규화
        raw_pm = info.get("profitMargins")
        profit_margins = None
        if raw_pm is not None:
            try:
                pm_v = float(raw_pm)
                if abs(pm_v) > 2.0:
                    pm_v /= 100
                profit_margins = round(pm_v, 4) if -10.0 <= pm_v <= 1.0 else None
            except (TypeError, ValueError):
                pass

        # debtToEquity: yfinance가 비율형(0.61)과 퍼센트형(18.74)을 혼용 → 비율형으로 정규화
        raw_dte = info.get("debtToEquity")
        debt_to_equity = None
        if raw_dte is not None:
            try:
                dte_v = float(raw_dte)
                if abs(dte_v) > 5:
                    dte_v /= 100
                debt_to_equity = round(dte_v, 2)
            except (TypeError, ValueError):
                pass

        # grossMargins, operatingMargins (yfinance 소수형, e.g. 0.62 = 62%)
        gross_margins     = info.get("grossMargins")
        operating_margins = info.get("operatingMargins")

        mc   = info.get("marketCap")
        mc_b = mc / 1e9 if mc else None
        is_micro = mc_b is not None and mc_b < 0.3

        # Cash Runway (FCF 기반, 분기 단위)
        cash_runway_q = None
        total_cash = info.get("totalCash")
        fcf = info.get("freeCashflow")  # TTM
        if total_cash and fcf is not None:
            if fcf >= 0:
                cash_runway_q = 99  # FCF 흑자 → 런웨이 문제 없음
            else:
                quarterly_burn = abs(fcf) / 4
                if quarterly_burn > 0:
                    cash_runway_q = round(total_cash / quarterly_burn, 1)

        return {
            "ticker": ticker,
            "price": price,
            "rsi14": rsi14(closes),
            "ma20": ma20,
            "ma50": ma50,
            "ma200": ma200,
            "ma_alignment": ma_alignment,
            "ret_6m": round(ret_6m * 100, 1) if ret_6m is not None else None,
            "rs_combined": rs_combined,
            "rs_spy_positive": rs_spy_positive,
            "rs_qqq_positive": rs_qqq_positive,
            "pos52": pos52,
            "fiftyTwoWeekHigh": round(high52, 2) if high52 else None,
            "fiftyTwoWeekLow":  round(low52, 2)  if low52  else None,
            "marketCap": mc,
            "is_micro": is_micro,
            "priceToSales": info.get("priceToSalesTrailing12Months"),
            "revenueGrowth": info.get("revenueGrowth"),
            "grossMargins": gross_margins,
            "operatingMargins": operating_margins,
            "profitMargins": profit_margins,
            "forwardPE": info.get("forwardPE"),
            "trailingPE": info.get("trailingPE"),
            "beta": info.get("beta"),
            "debtToEquity": debt_to_equity,
            "totalCash": total_cash,
            "freeCashflow": fcf,
            "cash_runway_q": cash_runway_q,
            "name": info.get("shortName") or info.get("longName"),
            "trend": trend,
        }
    except Exception:
        return None


def score_value(m):
    """저평가/반등: 52주 저점 근접 + 과매도 RSI + 낮은 P/S 일수록 고득점."""
    s, reasons = 0.0, []
    if m.get("pos52") is not None:
        if m["pos52"] <= 30:
            s += 3; reasons.append(f'52주 저점권({m["pos52"]}%)')
        elif m["pos52"] <= 50:
            s += 1.5
    if m.get("rsi14") is not None:
        if m["rsi14"] <= 35:
            s += 3; reasons.append(f'과매도 RSI {m["rsi14"]}')
        elif m["rsi14"] <= 45:
            s += 1.5
    ps = m.get("priceToSales")
    if ps is not None:
        if ps <= 5:
            s += 2; reasons.append(f'낮은 P/S {round(ps,1)}')
        elif ps <= 15:
            s += 1
    return round(s, 1), reasons


def score_momentum(m):
    """v5 성장모멘텀: §0 검증 팩터(MA정배열·RS 종합·52주 위치) + 매출성장.

    §0 백테스트 결과 반영 (2026-06-07):
      MA 정배열(20>50>200) — PASS (IC 12W=0.021, t=3.9)
      RS 종합(SPY·QQQ 6M) — WEAK_PENDING (IC 12W=0.019, t=3.7)
      52주 위치            — PASS (IC 12W=0.031, t=4.4)
      RSI 14               — FAIL (IC 12W 미유의) → 극단 과매수 감점만
    """
    s, reasons = 0.0, []

    # 1. MA 정배열 (§0 PASS)
    ma_align = m.get("ma_alignment")
    if ma_align == 1:
        s += 3; reasons.append("MA 정배열(20>50>200)")
    elif ma_align == -1:
        s -= 2; reasons.append("MA 역배열(20<50<200)")
    elif ma_align == 0:
        pass  # 혼합 — 가감 없음
    elif m.get("trend") == "up":
        # ma200 계산 불가(데이터 부족) 시 폴백
        s += 1.5; reasons.append("MA 상승추세(20>50, ma200 데이터 부족)")

    # 2. RS 종합 — SPY·QQQ 6M 아웃퍼폼 (§0 WEAK_PENDING)
    rs_c = m.get("rs_combined")
    if rs_c is not None:
        if rs_c == 1.0:
            s += 2; reasons.append("RS 종합 양호(SPY·QQQ 모두 아웃퍼폼)")
        elif rs_c == 0.5:
            s += 1; reasons.append("RS 부분 양호(SPY 또는 QQQ 아웃퍼폼)")
        else:
            s -= 0.5; reasons.append("RS 열위(SPY·QQQ 모두 언더퍼폼)")

    # 3. 52주 위치 모멘텀 (§0 PASS — 높을수록 모멘텀 확인됨)
    pos = m.get("pos52")
    if pos is not None:
        if pos >= 65:
            s += 2; reasons.append(f'52주 상단({pos}%) — 상승 모멘텀')
        elif pos >= 40:
            s += 1; reasons.append(f'52주 중단({pos}%)')
        elif pos <= 25:
            s -= 1; reasons.append(f'52주 하단({pos}%) — 모멘텀 약함')

    # 4. 매출성장 (경험적 필터 — IC 미검증이나 성장주 스크리닝 핵심)
    rg = m.get("revenueGrowth")
    if rg is not None:
        if rg >= 0.30:
            s += 3; reasons.append(f'매출성장 {round(rg*100,1)}%')
        elif rg >= 0.10:
            s += 1.5; reasons.append(f'매출성장 {round(rg*100,1)}%')
        else:
            s -= 0.5; reasons.append(f'저성장 매출 {round(rg*100,1)}%')

    # 5. RSI — §0 FAIL → 극단적 과매수(>80)만 감점
    rsi = m.get("rsi14")
    if rsi is not None and rsi > 80:
        s -= 1.5; reasons.append(f'극과매수 RSI {rsi}')

    return round(s, 1), reasons


def score_tenbagger(m):
    """v5 텐배거 후보: 극소형~중형주($30M~$50B) + 고성장 + Rule of 40(영업이익률) + RS + MA정배열.

    §0 백테스트 결과 반영 (2026-06-07):
      RS 종합, MA 정배열, Cash Runway 신규 추가.
      Rule of 40: 영업이익률(operatingMargins) 기준으로 수정.
      시총 상한: $15B → $50B 확장.
      RSI: §0 FAIL 확인 → 극단 과매수 감점만 유지.
    """
    s, reasons = 0.0, []

    # 1. 시총 ($50B까지 확장)
    mc = m.get("marketCap")
    if mc is not None:
        mc_b = mc / 1e9
        if 0.3 <= mc_b <= 5.0:
            s += 3; reasons.append(f'텐배거 시총대 ${round(mc_b,1)}B')
        elif 5.0 < mc_b <= 20.0:
            s += 2; reasons.append(f'중형주 ${round(mc_b,1)}B')
        elif 20.0 < mc_b <= 50.0:
            s += 1; reasons.append(f'대형 성장주 ${round(mc_b,1)}B')
        elif 0.03 <= mc_b < 0.3:
            s += 2; reasons.append(f'극소형주 ${round(mc_b*1000,0):.0f}M — 고성장 시 고배율 가능, 유동성·데이터 신뢰도 낮음')
        elif mc_b < 0.03:
            s -= 2; reasons.append(f'초미니캡 ${round(mc_b*1000,1):.1f}M — 유동성 위험')

    # 2. 매출성장
    rg = m.get("revenueGrowth")
    if rg is not None:
        if rg >= 0.40:
            s += 4; reasons.append(f'초고성장 매출 {round(rg*100,1)}%')
        elif rg >= 0.25:
            s += 3; reasons.append(f'고성장 매출 {round(rg*100,1)}%')
        elif rg >= 0.10:
            s += 1; reasons.append(f'성장 매출 {round(rg*100,1)}%')
        else:
            s -= 1; reasons.append(f'저성장 매출 {round(rg*100,1)}%')

    # 3. Gross Margin (v5 신규)
    gm = m.get("grossMargins")
    if gm is not None:
        if gm >= 0.60:
            s += 2; reasons.append(f'고마진 GM {round(gm*100,1)}%')
        elif gm >= 0.40:
            s += 1; reasons.append(f'양호 GM {round(gm*100,1)}%')
        elif gm < 0.20:
            s -= 1; reasons.append(f'저마진 GM {round(gm*100,1)}%')

    # 4. Rule of 40 (v5: 영업이익률 기준으로 수정)
    om = m.get("operatingMargins")
    if rg is not None and om is not None:
        rule40 = rg * 100 + om * 100
        if rule40 >= 40:
            s += 3; reasons.append(f'Rule of 40 통과({round(rule40,1)}, 영업이익 기준)')
        elif rule40 >= 20:
            s += 1.5; reasons.append(f'Rule of 40 부분({round(rule40,1)}, 영업이익 기준)')
        else:
            reasons.append(f'Rule of 40 미달({round(rule40,1)}, 영업이익 기준)')
    elif rg is not None and m.get("profitMargins") is not None:
        # operatingMargins 없을 때 profitMargins 폴백
        pm = m.get("profitMargins")
        rule40 = rg * 100 + pm * 100
        if rule40 >= 40:
            s += 3; reasons.append(f'Rule of 40 통과({round(rule40,1)}, 순이익 기준-폴백)')
        elif rule40 >= 20:
            s += 1.5; reasons.append(f'Rule of 40 부분({round(rule40,1)}, 순이익 기준-폴백)')

    # 5. 부채비율
    dte = m.get("debtToEquity")
    if dte is not None:
        if dte <= 0.3:
            s += 2; reasons.append(f'무부채수준 D/E {dte}')
        elif dte <= 0.8:
            s += 1; reasons.append(f'적정 부채 D/E {dte}')
        elif dte > 2.0:
            s -= 1; reasons.append(f'고부채 위험 D/E {dte}')

    # 6. Cash Runway (v5 신규)
    cr = m.get("cash_runway_q")
    if cr is not None:
        if cr >= 99:
            s += 2; reasons.append('FCF 흑자 — Cash Runway 문제 없음')
        elif cr >= 8:
            s += 2; reasons.append(f'Cash Runway {cr:.1f}분기 (2년+)')
        elif cr >= 4:
            s += 1; reasons.append(f'Cash Runway {cr:.1f}분기 (1~2년)')
        else:
            s -= 2; reasons.append(f'Cash Runway 부족 {cr:.1f}분기 — 희석 위험')

    # 7. 52주 위치
    pos = m.get("pos52")
    if pos is not None:
        if pos <= 40:
            s += 2; reasons.append(f'52주 저점권({pos}%) — 아직 덜 오름')
        elif pos <= 65:
            s += 1; reasons.append(f'52주 중간권({pos}%)')
        elif pos >= 85:
            s -= 1; reasons.append(f'52주 고점권({pos}%) — 이미 급등')

    # 8. RSI (§0 FAIL 확인 → 극단적 과매수 감점만 유지)
    rsi = m.get("rsi14")
    if rsi is not None:
        if 40 <= rsi <= 65:
            s += 0.5; reasons.append(f'RSI 적정 {rsi}')
        elif rsi > 80:
            s -= 1.5; reasons.append(f'RSI 극과매수 {rsi}')

    # 9. RS 종합 (v5 신규 — §0 WEAK_PENDING)
    rs_c = m.get("rs_combined")
    if rs_c is not None:
        if rs_c == 1.0:
            s += 1; reasons.append("RS 종합 양호(SPY·QQQ 모두 아웃퍼폼)")
        elif rs_c == 0.5:
            s += 0.5; reasons.append("RS 부분 양호(SPY 또는 QQQ 아웃퍼폼)")

    # 10. MA 정배열 (v5 신규 — §0 PASS)
    ma_align = m.get("ma_alignment")
    if ma_align is not None:
        if ma_align == 1:
            s += 1.5; reasons.append("MA 정배열(20>50>200)")
        elif ma_align == -1:
            s -= 1; reasons.append("MA 역배열(20<50<200)")

    # 선택적 보너스 (이하 기존 유지)

    # 11. Macrotrends 성장 지속성
    mt = m.get("mt_revenue")
    if mt:
        consec = mt.get("consecutive_growth_years", 0) or 0
        cagr5 = mt.get("cagr_5yr")
        pos_yrs = mt.get("positive_growth_years", 0) or 0
        total_yrs = mt.get("total_years", 1) or 1
        if consec >= 5:
            s += 2; reasons.append(f'Macrotrends 연속성장 {consec}년')
        elif consec >= 3:
            s += 1; reasons.append(f'Macrotrends 연속성장 {consec}년')
        if cagr5 is not None:
            if cagr5 >= 0.30:
                s += 2; reasons.append(f'Macrotrends 5yr CAGR {round(cagr5*100,1)}%')
            elif cagr5 >= 0.15:
                s += 1; reasons.append(f'Macrotrends 5yr CAGR {round(cagr5*100,1)}%')
            elif cagr5 < 0:
                s -= 1; reasons.append(f'Macrotrends 5yr 매출 역성장 {round(cagr5*100,1)}%')
        if total_yrs >= 5 and pos_yrs / total_yrs < 0.5:
            s -= 1; reasons.append(f'Macrotrends 성장 일관성 낮음 ({pos_yrs}/{total_yrs}년)')

    # 12. Dataroma 슈퍼인베스터
    dt = m.get("dt_signal")
    if dt:
        if dt == "strong_conviction":
            s += 3; reasons.append('슈퍼인베스터 5명+ 보유 (strong_conviction)')
        elif dt == "multi_holder":
            s += 2; reasons.append('슈퍼인베스터 3~4명 보유 (multi_holder)')
        elif dt == "single_holder":
            s += 1; reasons.append('슈퍼인베스터 1~2명 보유 (single_holder)')

    # 13. 뉴스 감성
    ns = m.get("news_signal")
    if ns:
        if ns == "bullish":
            s += 1; reasons.append('뉴스 감성 긍정(bullish)')
        elif ns == "bearish":
            s -= 1; reasons.append('뉴스 감성 부정(bearish)')

    return round(s, 1), reasons


# 테마별 내장 유니버스 (suggest 모드용)
UNIVERSES = {
    "quantum":     ["IONQ", "RGTI", "QBTS", "QUBT", "IBM", "GOOGL", "MSFT"],
    "ai":          ["NVDA", "AMD", "INTC", "MSFT", "GOOGL", "META", "AMZN", "TSM", "AVGO", "QCOM"],
    "ev":          ["TSLA", "RIVN", "LCID", "NIO", "XPEV", "LI", "GM", "F", "CHPT", "BLNK"],
    "biotech":     ["MRNA", "BNTX", "REGN", "BIIB", "VRTX", "ILMN", "CRSP", "EDIT", "NTLA", "BEAM"],
    "defense":     ["LMT", "RTX", "NOC", "GD", "BA", "HII", "LDOS", "CACI", "SAIC", "KTOS"],
    "semiconductor": ["NVDA", "AMD", "INTC", "TSM", "AVGO", "QCOM", "AMAT", "LRCX", "KLAC", "MRVL"],
    "cloud":       ["AMZN", "MSFT", "GOOGL", "CRM", "SNOW", "DDOG", "NET", "ZS", "MDB", "TEAM"],
    "fintech":     ["V", "MA", "PYPL", "SQ", "SOFI", "AFRM", "UPST", "COIN", "HOOD", "NU"],
    "energy":      ["XOM", "CVX", "COP", "SLB", "EOG", "PXD", "OXY", "MPC", "VLO", "PSX"],
    "clean":       ["ENPH", "FSLR", "RUN", "SEDG", "NEE", "BEP", "PLUG", "BLDP", "CWEN", "AES"],
    "healthcare":  ["UNH", "JNJ", "ABT", "TMO", "DHR", "MDT", "SYK", "BSX", "EW", "ISRG"],
    "consumer":    ["AMZN", "COST", "WMT", "TGT", "HD", "LOW", "NKE", "SBUX", "MCD", "YUM"],
    "crypto":      ["COIN", "MSTR", "MARA", "RIOT", "HUT", "CLSK", "BTBT", "WGMI", "HOOD", "SQ"],
    "space":       ["RKLB", "ASTS", "LUNR", "MNTS", "SPCE", "SATL", "KTOS", "AJRD", "LMT", "NOC"],
    "robotics":    ["ISRG", "ABB", "FANUC", "BRKS", "NXPI", "TER", "ONTO", "CGNX", "IRBT", "NVDA"],
    "tenbagger":   ["IONQ", "RGTI", "RKLB", "ASTS", "SOFI", "AFRM", "UPST",
                    "HIMS", "CELH", "DUOL", "SOUN", "RXRX", "TMDX", "NUVL",
                    "GTLB", "BILL", "AXON", "KTOS", "APP", "SMCI"],
    "microcap":    ["QBTS", "QUBT", "SOUN", "BBAI", "GFAI", "IREN", "AEYE",
                    "WULF", "CIFR", "MIGI", "NKGN", "CTXR", "IDAI", "DRUG",
                    "AIXI", "PONO", "BFRI", "INPX", "PRTK", "SOPA"],
}


def main():
    args = sys.argv[1:]
    strat = "value"
    tickers = []
    suggest_mode = False
    suggest_theme = None

    # suggest 모드 감지
    if args and args[0].lower() == "suggest":
        suggest_mode = True
        args = args[1:]
        remaining = []
        for a in args:
            if a.lower() in ("value", "momentum", "tenbagger"):
                strat = a.lower()
            elif a.lower() in UNIVERSES:
                suggest_theme = a.lower()
            else:
                remaining.append(a)

        if strat == "tenbagger" and suggest_theme is None:
            suggest_theme = "tenbagger"

        if suggest_theme is None:
            print(json.dumps({
                "available_themes": list(UNIVERSES.keys()),
                "usage": "py screen.py suggest [theme] [value|momentum|tenbagger]",
                "example": "py screen.py suggest tenbagger",
            }, ensure_ascii=False))
            return

        tickers = UNIVERSES[suggest_theme]
    else:
        if args and args[0].lower() in ("value", "momentum", "tenbagger"):
            strat = args[0].lower()
            args = args[1:]
        if args:
            tickers = [a.upper() for a in args]
        else:
            path = "watchlist.txt"
            if not os.path.exists(path):
                print(json.dumps({
                    "error": "watchlist.txt 가 없습니다. 워크스페이스에 후보 티커를 한 줄씩 넣어주세요.",
                    "template": "IONQ\nRGTI\nQBTS",
                }, ensure_ascii=False))
                return
            try:
                tickers = load_watchlist(path)
            except Exception as e:
                print(json.dumps({"error": f"watchlist 읽기 실패: {e}"}, ensure_ascii=False))
                return

    if not tickers:
        print(json.dumps({"error": "스크리닝할 티커가 없습니다."}, ensure_ascii=False))
        return

    try:
        import yfinance as yf
    except ImportError:
        print(json.dumps({"error": "yfinance 미설치. 'py -m pip install yfinance' 실행."}, ensure_ascii=False))
        return

    # RS 계산용 벤치마크 수익률 사전 수집 (momentum·tenbagger 전략)
    benchmarks = {}
    if strat in ("momentum", "tenbagger"):
        try:
            benchmarks = fetch_benchmark_returns(yf)
        except Exception:
            pass

    if strat == "momentum":
        scorer = score_momentum
    elif strat == "tenbagger":
        scorer = score_tenbagger
    else:
        scorer = score_value

    results = []
    failed = []
    for tk in tickers:
        m = fetch_metrics(yf, tk, benchmarks=benchmarks)
        if m is None:
            failed.append(tk)
            continue
        score, reasons = scorer(m)
        m["score"] = score
        m["reasons"] = reasons
        results.append(m)

    results.sort(key=lambda x: x["score"], reverse=True)

    out = {
        "strategy": strat,
        "scoring_version": SCORING_VERSION,
        "ranked": results,
        "failed": failed,
        "note": ("score 높을수록 해당 전략에 부합. reasons=가점 근거. "
                 "이것은 1차 스크리닝(객관 지표 랭킹)이며, 상위 후보는 반드시 기술/펀더멘털 심층분석으로 검증할 것. 추천이 아니라 후보 정렬. "
                 "is_micro=true인 종목(극소형주, 시총 $300M 미만)은 yfinance 데이터 신뢰도가 낮고 "
                 "상장폐지·유동성 리스크가 있음 — 반드시 IR·재무제표 직접 확인 후 진입 결정할 것."),
        "fields_only": ("이 JSON에 있는 필드(price·rsi14·ma20·ma50·ma200·ma_alignment·ret_6m·"
                        "rs_combined·rs_spy_positive·rs_qqq_positive·pos52·52주고저·marketCap·"
                        "priceToSales·revenueGrowth·grossMargins·operatingMargins·profitMargins·"
                        "forwardPE·trailingPE·beta·debtToEquity·totalCash·freeCashflow·"
                        "cash_runway_q·trend·is_micro)만 인용하라. "
                        "없는 값은 'N/A' 또는 '데이터 미제공'으로 표기. 지어내지 말 것."),
    }
    if suggest_mode and suggest_theme:
        out["theme"] = suggest_theme
        out["universe_size"] = len(tickers)

    if suggest_mode:
        try:
            from watchlist import add_auto
            for r in results[:5]:
                add_auto(r["ticker"], r.get("score"))
        except Exception:
            pass

    print(json.dumps(_sanitize_floats(out), ensure_ascii=False))


if __name__ == "__main__":
    main()
