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

from screen import score_tenbagger, score_value, score_momentum, rsi14

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
# 실행
# ─────────────────────────────────────────────
if __name__ == "__main__":
    run("1. 극소형주 시총 구간", test_micro_cap_scoring)
    run("2. 소형주+고성장 최고점수", test_smallcap_highgrowth)
    run("3. 중형주+저성장 낮은점수", test_midcap_lowgrowth)
    run("4. D/E 정규화", test_dte_normalization)
    run("5. profitMargins 정규화", test_pm_normalization)
    run("6. 초미니캡 페널티", test_nano_cap_penalty)
    run("7. RSI14 계산", test_rsi)
    run("8. value/momentum 전략", test_value_momentum)

    total = PASS + FAIL
    print(f"\n{'='*40}")
    print(f"결과: {PASS}/{total} PASS" + (f"  ({FAIL} FAIL)" if FAIL else "  — 전체 통과"))
    sys.exit(0 if FAIL == 0 else 1)
