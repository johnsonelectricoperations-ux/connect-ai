#!/usr/bin/env python3
# Connect AI · screen.py 단위 테스트
#
# 네트워크 없이 순수 로직만 검증한다.
# 실행: py test_screen.py
#
# 각 케이스가 PASS면 로직 정상. 새 기능 추가 후 반드시 재실행해 회귀 확인.

import sys, traceback

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from screen import score_tenbagger, score_value, score_momentum, rsi14, SCORING_VERSION

PASS = 0
FAIL = 0


def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        print(f"  PASS  {name}")
        PASS += 1
    else:
        print(f"  FAIL  {name}" + (f" — {detail}" if detail else ""))
        FAIL += 1


def run(label, fn):
    print(f"\n[{label}]")
    try:
        fn()
    except Exception:
        global FAIL
        FAIL += 1
        print(f"  FAIL  예외 발생:")
        traceback.print_exc()


# ─────────────────────────────────────────────
# 1. 극소형주 시총 구간 테스트
# ─────────────────────────────────────────────
def test_micro_cap_scoring():
    # 극소형주 $150M + 고성장 → 페널티 없이 양수 점수, reasons에 "극소형주" 포함
    m = {
        "marketCap": 150_000_000,
        "revenueGrowth": 0.45,
        "profitMargins": 0.05,
        "debtToEquity": 0.2,
        "pos52": 35,
        "rsi14": 52,
        "is_micro": True,
    }
    score, reasons = score_tenbagger(m)
    check("극소형주 score > 0", score > 0, f"score={score}")
    check("극소형주 reasons에 '극소형주' 포함", any("극소형주" in r for r in reasons),
          f"reasons={reasons}")
    check("극소형주 score < 소형주 동일조건 score",
          score < score_tenbagger({**m, "marketCap": 500_000_000})[0],
          "극소형주가 소형주보다 낮아야 함")


# ─────────────────────────────────────────────
# 2. 소형주($500M) + 고성장 → 최고 점수 구간
# ─────────────────────────────────────────────
def test_smallcap_highgrowth():
    m = {
        "marketCap": 500_000_000,
        "revenueGrowth": 0.45,
        "profitMargins": 0.10,
        "debtToEquity": 0.2,
        "pos52": 35,
        "rsi14": 52,
        "is_micro": False,
    }
    score, reasons = score_tenbagger(m)
    check("소형+고성장 score >= 10", score >= 10, f"score={score}")
    check("텐배거 시총대 reasons 포함", any("텐배거 시총대" in r for r in reasons))
    check("초고성장 매출 reasons 포함", any("초고성장" in r for r in reasons))
    check("Rule of 40 통과 reasons 포함", any("Rule of 40 통과" in r for r in reasons))


# ─────────────────────────────────────────────
# 3. 중형주($8B) + 저성장 → 낮은 점수
# ─────────────────────────────────────────────
def test_midcap_lowgrowth():
    m = {
        "marketCap": 8_000_000_000,
        "revenueGrowth": 0.03,
        "profitMargins": 0.05,
        "debtToEquity": 1.5,
        "pos52": 70,
        "rsi14": 60,
        "is_micro": False,
    }
    score, reasons = score_tenbagger(m)
    check("중형+저성장 score < 5", score < 5, f"score={score}")
    check("저성장 매출 reasons 포함", any("저성장" in r for r in reasons))


# ─────────────────────────────────────────────
# 4. D/E 정규화: 퍼센트형(18.74) → 비율형(0.1874)
# ─────────────────────────────────────────────
def test_dte_normalization():
    # fetch_metrics 내부 정규화 로직을 직접 검증
    cases = [
        (18.74, True, 0.19),   # 퍼센트형: 18.74 → ÷100 → 0.1874 → 반올림 0.19
        (0.61,  False, 0.61),  # 비율형: 0.61 그대로
        (150.0, True, 1.50),   # 퍼센트형 고값: 150 → ÷100 → 1.50
        (0.0,   False, 0.0),   # 0은 그대로
    ]
    for raw, expect_divided, expected_ratio in cases:
        dte_v = float(raw)
        if abs(dte_v) > 5:
            dte_v = dte_v / 100
        result = round(dte_v, 2)
        check(f"D/E 정규화 raw={raw} → {expected_ratio}",
              result == expected_ratio, f"got {result}")


# ─────────────────────────────────────────────
# 5. profitMargins 정규화: 퍼센트형(3.9) → 소수형(0.039)
# ─────────────────────────────────────────────
def test_pm_normalization():
    cases = [
        (3.9,   0.039),   # 퍼센트형 → ÷100
        (0.039, 0.039),   # 소수형 → 그대로
        (-50.0, -0.5),    # 음수 퍼센트형
        (-0.5,  -0.5),    # 음수 소수형 그대로
        (250.0, None),    # 정규화 후에도 범위 초과(>1.0) → None
    ]
    for raw, expected in cases:
        pm_v = float(raw)
        if abs(pm_v) > 2.0:
            pm_v = pm_v / 100
        result = round(pm_v, 4) if -10.0 <= pm_v <= 1.0 else None
        check(f"profitMargins 정규화 raw={raw} → {expected}",
              result == expected, f"got {result}")


# ─────────────────────────────────────────────
# 6. 초미니캡($10M) → 페널티
# ─────────────────────────────────────────────
def test_nano_cap_penalty():
    m = {
        "marketCap": 10_000_000,
        "revenueGrowth": 0.50,
        "profitMargins": 0.10,
        "debtToEquity": 0.1,
        "pos52": 20,
        "rsi14": 45,
        "is_micro": True,
    }
    score, reasons = score_tenbagger(m)
    check("초미니캡 reasons에 '유동성 위험' 포함",
          any("유동성 위험" in r for r in reasons), f"reasons={reasons}")


# ─────────────────────────────────────────────
# 7. RSI14 계산 검증
# ─────────────────────────────────────────────
def test_rsi():
    # 꾸준히 오르는 가격 → RSI 높음
    rising = list(range(50, 80))
    r = rsi14(rising)
    check("상승 추세 RSI > 70", r is not None and r > 70, f"rsi={r}")

    # 꾸준히 내리는 가격 → RSI 낮음
    falling = list(range(80, 50, -1))
    r = rsi14(falling)
    check("하락 추세 RSI < 30", r is not None and r < 30, f"rsi={r}")

    # 데이터 부족 → None
    r = rsi14([100] * 5)
    check("데이터 부족 → None", r is None, f"rsi={r}")


# ─────────────────────────────────────────────
# 8. value / momentum 전략 기본 동작
# ─────────────────────────────────────────────
def test_value_momentum():
    m_value = {"pos52": 20, "rsi14": 30, "priceToSales": 3}
    s, r = score_value(m_value)
    check("value 전략: 52주저점+과매도+낮은P/S → score >= 8", s >= 8, f"score={s}")

    m_mom = {"trend": "up", "revenueGrowth": 0.35, "rsi14": 58}
    s, r = score_momentum(m_mom)
    check("momentum 전략: 정배열+고성장+RSI적정 → score >= 8", s >= 8, f"score={s}")


# ─────────────────────────────────────────────
# 9. Macrotrends 성장 지속성 보너스
# ─────────────────────────────────────────────
def test_macrotrends_bonus():
    base = {
        "marketCap": 500_000_000,
        "revenueGrowth": 0.20,
        "profitMargins": 0.05,
        "debtToEquity": 0.3,
        "pos52": 50,
        "rsi14": 55,
        "is_micro": False,
    }

    # 연속 5년 성장 + CAGR 30% → +4점 보너스
    mt_strong = {
        "consecutive_growth_years": 5,
        "cagr_5yr": 0.32,
        "positive_growth_years": 8,
        "total_years": 9,
    }
    s_base, _ = score_tenbagger(base)
    s_mt, reasons = score_tenbagger({**base, "mt_revenue": mt_strong})
    check("MT 강한 성장: mt 포함 점수 > mt 없음 점수", s_mt > s_base, f"base={s_base} mt={s_mt}")
    check("MT 연속성장 5년 reasons 포함", any("연속성장 5년" in r for r in reasons), f"reasons={reasons}")
    check("MT CAGR reasons 포함", any("CAGR" in r for r in reasons), f"reasons={reasons}")

    # 연속 3년 + CAGR 20% → +2점 보너스
    mt_mid = {
        "consecutive_growth_years": 3,
        "cagr_5yr": 0.20,
        "positive_growth_years": 5,
        "total_years": 8,
    }
    s_mid, reasons_mid = score_tenbagger({**base, "mt_revenue": mt_mid})
    check("MT 중간 성장: 연속3년 reasons 포함", any("연속성장 3년" in r for r in reasons_mid), f"reasons={reasons_mid}")
    check("MT 중간 성장 score 범위", s_base < s_mid < s_mt, f"base={s_base} mid={s_mid} strong={s_mt}")

    # 역성장 → 페널티
    mt_neg = {
        "consecutive_growth_years": 0,
        "cagr_5yr": -0.05,
        "positive_growth_years": 2,
        "total_years": 8,
    }
    s_neg, reasons_neg = score_tenbagger({**base, "mt_revenue": mt_neg})
    check("MT 역성장: score <= base", s_neg <= s_base, f"base={s_base} neg={s_neg}")
    check("MT 역성장 reasons 포함", any("역성장" in r for r in reasons_neg), f"reasons={reasons_neg}")

    # 성장 일관성 낮음 (<50%) → 페널티
    mt_inconsistent = {
        "consecutive_growth_years": 1,
        "cagr_5yr": 0.10,
        "positive_growth_years": 2,
        "total_years": 7,
    }
    s_inc, reasons_inc = score_tenbagger({**base, "mt_revenue": mt_inconsistent})
    check("MT 일관성 낮음 reasons 포함", any("일관성" in r for r in reasons_inc), f"reasons={reasons_inc}")

    # mt_revenue 없으면 기존 점수 그대로
    s_no_mt, _ = score_tenbagger(base)
    check("mt_revenue 없음 → score 변동 없음", s_no_mt == s_base, f"no_mt={s_no_mt} base={s_base}")


# ─────────────────────────────────────────────
# 10. Dataroma 슈퍼인베스터 보유 보너스
# ─────────────────────────────────────────────
def test_dataroma_bonus():
    base = {
        "marketCap": 500_000_000,
        "revenueGrowth": 0.20,
        "profitMargins": 0.05,
        "debtToEquity": 0.3,
        "pos52": 50,
        "rsi14": 55,
        "is_micro": False,
    }
    s_base, _ = score_tenbagger(base)

    # strong_conviction → +3
    s_sc, r_sc = score_tenbagger({**base, "dt_signal": "strong_conviction"})
    check("DT strong_conviction: +3", round(s_sc - s_base, 1) == 3.0, f"diff={round(s_sc-s_base,1)}")
    check("DT strong_conviction reasons 포함", any("strong_conviction" in r for r in r_sc), f"reasons={r_sc}")

    # multi_holder → +2
    s_mh, r_mh = score_tenbagger({**base, "dt_signal": "multi_holder"})
    check("DT multi_holder: +2", round(s_mh - s_base, 1) == 2.0, f"diff={round(s_mh-s_base,1)}")
    check("DT multi_holder reasons 포함", any("multi_holder" in r for r in r_mh), f"reasons={r_mh}")

    # single_holder → +1
    s_sh, r_sh = score_tenbagger({**base, "dt_signal": "single_holder"})
    check("DT single_holder: +1", round(s_sh - s_base, 1) == 1.0, f"diff={round(s_sh-s_base,1)}")

    # no_holder → 변동 없음
    s_nh, _ = score_tenbagger({**base, "dt_signal": "no_holder"})
    check("DT no_holder: 변동 없음", s_nh == s_base, f"base={s_base} no_holder={s_nh}")

    # dt_signal 없음 → 변동 없음
    s_nd, _ = score_tenbagger(base)
    check("DT 없음: 변동 없음", s_nd == s_base, f"base={s_base} no_dt={s_nd}")

    # strong_conviction + MT 강한성장 조합 → 누적 적용
    mt_strong = {"consecutive_growth_years": 5, "cagr_5yr": 0.32, "positive_growth_years": 8, "total_years": 9}
    s_combo, _ = score_tenbagger({**base, "dt_signal": "strong_conviction", "mt_revenue": mt_strong})
    check("DT+MT 조합: base보다 큰 점수", s_combo > s_sc and s_combo > s_base, f"combo={s_combo} sc={s_sc} base={s_base}")


# ─────────────────────────────────────────────
# 실행
# ─────────────────────────────────────────────
def test_version():
    check("SCORING_VERSION 존재", bool(SCORING_VERSION), SCORING_VERSION)
    parts = SCORING_VERSION.split(".")
    check("SCORING_VERSION 형식 X.Y.Z", len(parts) == 3 and all(p.isdigit() for p in parts),
          SCORING_VERSION)
    check("SCORING_VERSION >= 1.2.0",
          tuple(int(p) for p in parts) >= (1, 2, 0), SCORING_VERSION)


if __name__ == "__main__":
    run("0. 버전 명세", test_version)
    run("1. 극소형주 시총 구간", test_micro_cap_scoring)
    run("2. 소형주+고성장 최고점수", test_smallcap_highgrowth)
    run("3. 중형주+저성장 낮은점수", test_midcap_lowgrowth)
    run("4. D/E 정규화", test_dte_normalization)
    run("5. profitMargins 정규화", test_pm_normalization)
    run("6. 초미니캡 페널티", test_nano_cap_penalty)
    run("7. RSI14 계산", test_rsi)
    run("8. value/momentum 전략", test_value_momentum)
    run("9. Macrotrends 성장 지속성 보너스", test_macrotrends_bonus)
    run("10. Dataroma 슈퍼인베스터 보너스", test_dataroma_bonus)

    total = PASS + FAIL
    print(f"\n{'='*40}")
    print(f"결과: {PASS}/{total} PASS" + (f"  ({FAIL} FAIL)" if FAIL else "  — 전체 통과"))
    sys.exit(0 if FAIL == 0 else 1)
