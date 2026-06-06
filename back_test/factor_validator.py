"""
Connect AI v5 §0 — 팩터 검증 모듈
====================================
각 팩터의 예측력(IC)을 측정하고 통계적으로 유의한 팩터만 통과시킨다.
v5 §0의 핵심 모듈.

검증 방법:
  1. 각 팩터 점수와 forward 수익률의 Spearman IC 측정
  2. IC t-test로 통계적 유의성 검정
  3. 분위별(quintile) 수익률 분석
  4. RS SPY-QQQ 상관 확인 (v5 팩터 중복 통합)
  5. 성장/퀄리티 클러스터 상관 확인
"""

import logging
from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats
from tqdm import tqdm

import config

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════
# IC (Information Coefficient) 계산
# ══════════════════════════════════════════════

def compute_spearman_ic(
    factor_values: pd.Series,
    forward_returns: pd.Series,
) -> tuple[float, float]:
    """
    Spearman 순위 상관(IC)을 계산한다.

    Args:
        factor_values: 팩터 점수
        forward_returns: forward 수익률

    Returns:
        (ic_value, p_value) 튜플
    """
    # NaN 제거 후 정렬
    valid = pd.DataFrame({
        "factor": factor_values,
        "return": forward_returns,
    }).dropna()

    if len(valid) < 10:
        return np.nan, np.nan

    ic, p = stats.spearmanr(valid["factor"], valid["return"])
    return ic, p


def compute_ic_timeseries(
    features_df: pd.DataFrame,
    fwd_returns_df: pd.DataFrame,
    factor_name: str,
    fwd_period: str = "fwd_ret_60d",
    rebalance_freq: str = config.REBALANCE_FREQ,
) -> pd.DataFrame:
    """
    시간별 IC 추이를 계산한다. 각 리밸런싱 시점에서의 cross-sectional IC.

    Args:
        features_df: 피처 데이터 (date, ticker, factor_name, ...)
        fwd_returns_df: forward 수익률 (date, ticker, fwd_ret_*d)
        factor_name: 팩터 컬럼 이름
        fwd_period: forward 수익률 컬럼 이름
        rebalance_freq: 리밸런싱 주기

    Returns:
        DataFrame[date, ic, p_value, n_stocks]
    """
    # 병합
    merged = features_df[["date", "ticker", factor_name]].merge(
        fwd_returns_df[["date", "ticker", fwd_period]],
        on=["date", "ticker"],
        how="inner",
    )

    # 리밸런싱 날짜 필터
    merged["date"] = pd.to_datetime(merged["date"])
    rebal_dates = pd.date_range(
        start=merged["date"].min(),
        end=merged["date"].max(),
        freq=rebalance_freq,
    )
    # 가장 가까운 거래일에 매핑
    all_dates = merged["date"].sort_values().unique()

    ic_records = []
    for rd in rebal_dates:
        # 리밸런싱 날짜 이하의 가장 가까운 거래일
        valid_dates = all_dates[all_dates <= rd]
        if len(valid_dates) == 0:
            continue
        closest_date = valid_dates[-1]

        cross_section = merged[merged["date"] == closest_date]

        if len(cross_section) < 10:
            continue

        ic, p = compute_spearman_ic(
            cross_section[factor_name],
            cross_section[fwd_period],
        )

        ic_records.append({
            "date": closest_date,
            "ic": ic,
            "p_value": p,
            "n_stocks": len(cross_section),
        })

    return pd.DataFrame(ic_records)


# ══════════════════════════════════════════════
# 분위별(Quintile) 수익률 분석
# ══════════════════════════════════════════════

def compute_quintile_returns(
    features_df: pd.DataFrame,
    fwd_returns_df: pd.DataFrame,
    factor_name: str,
    fwd_period: str = "fwd_ret_60d",
    n_quantiles: int = config.N_QUANTILES,
) -> pd.DataFrame:
    """
    팩터 점수 기준 분위별 평균 forward 수익률을 계산한다.

    Returns:
        DataFrame[quantile, mean_return, median_return, count, std]
    """
    merged = features_df[["date", "ticker", factor_name]].merge(
        fwd_returns_df[["date", "ticker", fwd_period]],
        on=["date", "ticker"],
        how="inner",
    ).dropna(subset=[factor_name, fwd_period])

    if merged.empty:
        return pd.DataFrame()

    # 날짜별 분위 할당 (cross-sectional quantile)
    merged["quantile"] = merged.groupby("date")[factor_name].transform(
        lambda x: pd.qcut(x, n_quantiles, labels=False, duplicates="drop") + 1
    )

    result = merged.groupby("quantile")[fwd_period].agg(
        mean_return="mean",
        median_return="median",
        count="count",
        std="std",
    ).reset_index()

    result.columns = ["quantile", "mean_return", "median_return", "count", "std"]
    return result


def compute_quintile_cumulative_returns(
    features_df: pd.DataFrame,
    fwd_returns_df: pd.DataFrame,
    factor_name: str,
    fwd_period: str = "fwd_ret_60d",
    n_quantiles: int = config.N_QUANTILES,
) -> pd.DataFrame:
    """
    분위별 시간 경과에 따른 누적 수익률을 계산한다.

    Returns:
        DataFrame[date, Q1, Q2, ..., QN]
    """
    merged = features_df[["date", "ticker", factor_name]].merge(
        fwd_returns_df[["date", "ticker", fwd_period]],
        on=["date", "ticker"],
        how="inner",
    ).dropna(subset=[factor_name, fwd_period])

    if merged.empty:
        return pd.DataFrame()

    # 날짜별 분위 할당
    merged["quantile"] = merged.groupby("date")[factor_name].transform(
        lambda x: pd.qcut(x, n_quantiles, labels=False, duplicates="drop") + 1
    )

    # 분위별 평균 수익률의 시계열
    pivot = merged.groupby(["date", "quantile"])[fwd_period].mean().unstack("quantile")
    pivot.columns = [f"Q{int(c)}" for c in pivot.columns]

    # 누적 수익률
    cumulative = (1 + pivot).cumprod()
    return cumulative.reset_index()


# ══════════════════════════════════════════════
# 통계적 유의성 검정
# ══════════════════════════════════════════════

def test_ic_significance(ic_series: pd.Series) -> dict:
    """
    IC 시계열이 통계적으로 0과 다른지 t-test로 검정한다.

    Returns:
        dict with keys: mean_ic, std_ic, t_stat, p_value, n_periods,
                        is_significant (p < 0.05)
    """
    clean = ic_series.dropna()
    if len(clean) < 5:
        return {
            "mean_ic": np.nan, "std_ic": np.nan,
            "t_stat": np.nan, "p_value": np.nan,
            "n_periods": len(clean), "is_significant": False,
        }

    t_stat, p_value = stats.ttest_1samp(clean, 0)

    return {
        "mean_ic": clean.mean(),
        "std_ic": clean.std(),
        "t_stat": t_stat,
        "p_value": p_value,
        "n_periods": len(clean),
        "is_significant": p_value < 0.05,
    }


# ══════════════════════════════════════════════
# 종합 팩터 검증
# ══════════════════════════════════════════════

def validate_single_factor(
    features_df: pd.DataFrame,
    fwd_returns_df: pd.DataFrame,
    factor_name: str,
    expected_sign: int,
    description: str = "",
) -> dict:
    """
    단일 팩터를 종합 검증한다.

    Args:
        features_df: 피처 DataFrame
        fwd_returns_df: forward 수익률 DataFrame
        factor_name: 팩터 컬럼 이름
        expected_sign: 의도 부호 (+1 또는 -1)
        description: 팩터 설명

    Returns:
        검증 결과 딕셔너리
    """
    result = {
        "factor": factor_name,
        "description": description,
        "expected_sign": expected_sign,
    }

    # 각 forward 기간별 IC 계산
    for period, label in zip(config.FORWARD_PERIODS, config.FORWARD_PERIOD_LABELS):
        fwd_col = f"fwd_ret_{period}d"

        if fwd_col not in fwd_returns_df.columns:
            continue

        # IC 시계열
        ic_ts = compute_ic_timeseries(
            features_df, fwd_returns_df, factor_name, fwd_col,
        )

        if ic_ts.empty:
            result[f"ic_mean_{label}"] = np.nan
            result[f"ic_tstat_{label}"] = np.nan
            result[f"ic_pvalue_{label}"] = np.nan
            result[f"ic_significant_{label}"] = False
            result[f"sign_match_{label}"] = False
            continue

        # IC 통계
        sig = test_ic_significance(ic_ts["ic"])
        result[f"ic_mean_{label}"] = sig["mean_ic"]
        result[f"ic_std_{label}"] = sig["std_ic"]
        result[f"ic_tstat_{label}"] = sig["t_stat"]
        result[f"ic_pvalue_{label}"] = sig["p_value"]
        result[f"ic_significant_{label}"] = sig["is_significant"]
        result[f"ic_n_periods_{label}"] = sig["n_periods"]

        # 부호 일치 확인
        if not np.isnan(sig["mean_ic"]):
            actual_sign = 1 if sig["mean_ic"] > 0 else -1
            result[f"sign_match_{label}"] = (actual_sign == expected_sign)
        else:
            result[f"sign_match_{label}"] = False

        # 분위 수익률
        q_returns = compute_quintile_returns(
            features_df, fwd_returns_df, factor_name, fwd_col,
        )

        if not q_returns.empty:
            top_q = q_returns[q_returns["quantile"] == config.N_QUANTILES]
            bot_q = q_returns[q_returns["quantile"] == 1]

            if not top_q.empty and not bot_q.empty:
                spread = top_q["mean_return"].values[0] - bot_q["mean_return"].values[0]
                # 부호에 따라 spread 방향 조정
                if expected_sign == -1:
                    spread = -spread  # 부호 반전 (낮은 값이 좋은 팩터)
                result[f"spread_{label}"] = spread
                result[f"spread_positive_{label}"] = spread > 0
            else:
                result[f"spread_{label}"] = np.nan
                result[f"spread_positive_{label}"] = False

        # IC 시계열 저장
        ic_ts.to_parquet(
            config.IC_RESULTS_DIR / f"{factor_name}_ic_{label}.parquet",
            index=False,
        )

    # 합격 판정
    result["pass"] = _judge_factor(result)

    return result


def _judge_factor(result: dict) -> str:
    """
    팩터 합격/불합격 판정.

    Returns:
        "PASS", "WEAK", "FAIL", 또는 "PENDING" (IC_THRESHOLD 미확정)
    """
    ic_threshold = config.IC_THRESHOLD

    # 12주(주요 기간) IC 기준으로 판정
    ic_mean = result.get("ic_mean_12W", np.nan)
    is_significant = result.get("ic_significant_12W", False)
    sign_match = result.get("sign_match_12W", False)
    spread_positive = result.get("spread_positive_12W", False)

    if np.isnan(ic_mean):
        return "NO_DATA"

    if not sign_match:
        return "FAIL"  # 부호 불일치 → 무조건 불합격

    if ic_threshold is None:
        # 🔧 사용자 정의 필요: IC_THRESHOLD 미확정
        # 잠정 판정 (절대값 기준)
        if abs(ic_mean) >= 0.05 and is_significant and spread_positive:
            return "STRONG_PENDING"  # 강한 후보 (임계값 확정 대기)
        elif abs(ic_mean) >= 0.02 and spread_positive:
            return "WEAK_PENDING"  # 약한 후보
        else:
            return "FAIL"
    else:
        if abs(ic_mean) >= ic_threshold and is_significant and sign_match and spread_positive:
            return "PASS"
        elif abs(ic_mean) >= ic_threshold * 0.7 and sign_match and spread_positive:
            return "WEAK"
        else:
            return "FAIL"


# ══════════════════════════════════════════════
# 전체 팩터 검증 실행
# ══════════════════════════════════════════════

def validate_price_factors(
    features_df: pd.DataFrame,
    fwd_returns_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    v5 설계의 모든 가격 팩터를 검증한다.

    Returns:
        검증 결과 요약 테이블
    """
    logger.info("=" * 60)
    logger.info("가격 팩터 IC 검증 시작")
    logger.info("=" * 60)

    results = []

    for factor_name, (expected_sign, desc, section) in config.PRICE_FACTORS.items():
        if factor_name not in features_df.columns:
            logger.warning(f"{factor_name}: 피처에 없음, 건너뜀")
            continue

        logger.info(f"\n── {factor_name} ({desc}) ──")

        result = validate_single_factor(
            features_df, fwd_returns_df,
            factor_name, expected_sign, desc,
        )
        result["section"] = section
        results.append(result)

        # 결과 로그
        for label in config.FORWARD_PERIOD_LABELS:
            ic = result.get(f"ic_mean_{label}", np.nan)
            pval = result.get(f"ic_pvalue_{label}", np.nan)
            if not np.isnan(ic):
                logger.info(
                    f"  {label}: IC={ic:+.4f}, p={pval:.4f}, "
                    f"sign_ok={result.get(f'sign_match_{label}')}, "
                    f"spread_ok={result.get(f'spread_positive_{label}')}"
                )

        logger.info(f"  판정: {result['pass']}")

    summary = pd.DataFrame(results)

    # 저장
    summary.to_parquet(
        config.IC_RESULTS_DIR / "price_factor_validation.parquet",
        index=False,
    )
    logger.info(f"\n가격 팩터 검증 완료: {len(results)}개 팩터")
    _log_summary(summary)

    return summary


def validate_fundamental_factors(
    features_df: pd.DataFrame,
    fwd_returns_df: pd.DataFrame,
) -> pd.DataFrame:
    """v5 설계의 모든 재무 팩터를 검증한다."""
    logger.info("=" * 60)
    logger.info("재무 팩터 IC 검증 시작")
    logger.info("=" * 60)

    results = []

    for factor_name, (expected_sign, desc, section) in config.FUNDAMENTAL_FACTORS.items():
        if factor_name not in features_df.columns:
            logger.warning(f"{factor_name}: 피처에 없음, 건너뜀")
            continue

        # 재무 팩터는 NaN이 많을 수 있음
        non_null = features_df[factor_name].notna().sum()
        total = len(features_df)
        coverage = non_null / total * 100
        logger.info(f"\n── {factor_name} ({desc}) — 커버리지: {coverage:.1f}% ──")

        if coverage < 5:
            logger.warning(f"  커버리지 너무 낮음 ({coverage:.1f}%), 건너뜀")
            continue

        result = validate_single_factor(
            features_df, fwd_returns_df,
            factor_name, expected_sign, desc,
        )
        result["section"] = section
        result["coverage_pct"] = coverage
        results.append(result)

        for label in config.FORWARD_PERIOD_LABELS:
            ic = result.get(f"ic_mean_{label}", np.nan)
            pval = result.get(f"ic_pvalue_{label}", np.nan)
            if not np.isnan(ic):
                logger.info(
                    f"  {label}: IC={ic:+.4f}, p={pval:.4f}, "
                    f"sign_ok={result.get(f'sign_match_{label}')}"
                )

        logger.info(f"  판정: {result['pass']}")

    summary = pd.DataFrame(results)

    if not summary.empty:
        summary.to_parquet(
            config.IC_RESULTS_DIR / "fundamental_factor_validation.parquet",
            index=False,
        )

    logger.info(f"\n재무 팩터 검증 완료: {len(results)}개 팩터")
    _log_summary(summary)

    return summary


def _log_summary(summary: pd.DataFrame):
    """검증 결과 요약 로그."""
    if summary.empty:
        return

    logger.info("\n" + "=" * 60)
    logger.info("검증 결과 요약")
    logger.info("=" * 60)

    for _, row in summary.iterrows():
        ic_12w = row.get("ic_mean_12W", np.nan)
        verdict = row.get("pass", "?")
        ic_str = f"{ic_12w:+.4f}" if not np.isnan(ic_12w) else "N/A"
        status = "✅" if verdict in ("PASS", "STRONG_PENDING") else "⚠️" if verdict == "WEAK_PENDING" else "❌"
        logger.info(f"  {status} {row['factor']:25s} IC(12W)={ic_str:>8s}  → {verdict}")


# ══════════════════════════════════════════════
# v5 특별 검증: 팩터 상관 분석
# ══════════════════════════════════════════════

def analyze_factor_correlations(
    features_df: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    """
    v5에서 요구하는 팩터 상관 분석:
    1. RS SPY vs QQQ 상관 (통합 결정)
    2. 성장/퀄리티 클러스터 상관

    Returns:
        {"rs_correlation": DataFrame, "growth_cluster_correlation": DataFrame}
    """
    logger.info("팩터 상관 분석...")
    results = {}

    # 1. RS SPY vs QQQ 상관
    rs_cols = [
        "rs_spy_1m", "rs_spy_3m", "rs_spy_6m",
        "rs_qqq_1m", "rs_qqq_3m", "rs_qqq_6m",
    ]
    available_rs = [c for c in rs_cols if c in features_df.columns]
    if available_rs:
        rs_corr = features_df[available_rs].corr(method="spearman")
        results["rs_correlation"] = rs_corr

        # SPY-QQQ 같은 기간 상관
        for period in ["1m", "3m", "6m"]:
            spy_col = f"rs_spy_{period}"
            qqq_col = f"rs_qqq_{period}"
            if spy_col in features_df.columns and qqq_col in features_df.columns:
                corr = features_df[[spy_col, qqq_col]].corr(method="spearman").iloc[0, 1]
                logger.info(f"  RS SPY-QQQ {period} 상관: {corr:.3f}")
                if corr > 0.85:
                    logger.warning(
                        f"  ⚠️ RS {period} SPY-QQQ 상관 {corr:.3f} > 0.85 → "
                        f"v5 권장: 통합(RS 종합) 사용"
                    )

    # 2. 성장/퀄리티 클러스터
    growth_cols = ["revenue_growth_yoy", "gross_margin", "operating_margin", "rule_of_40"]
    available_growth = [c for c in growth_cols if c in features_df.columns]
    if len(available_growth) >= 2:
        growth_corr = features_df[available_growth].corr(method="spearman")
        results["growth_cluster_correlation"] = growth_corr

        logger.info("\n  성장/퀄리티 클러스터 상관:")
        for i in range(len(available_growth)):
            for j in range(i + 1, len(available_growth)):
                c1, c2 = available_growth[i], available_growth[j]
                corr = growth_corr.loc[c1, c2]
                logger.info(f"    {c1} × {c2}: {corr:.3f}")

    # 저장
    for name, df in results.items():
        df.to_parquet(
            config.IC_RESULTS_DIR / f"correlation_{name}.parquet",
            index=False if not isinstance(df.index, pd.RangeIndex) else True,
        )

    return results


# ══════════════════════════════════════════════
# Forward P/S IC 부호 경고 (v5 §4)
# ══════════════════════════════════════════════

def check_forward_ps_sign_warning(
    features_df: pd.DataFrame,
    fwd_returns_df: pd.DataFrame,
) -> dict:
    """
    v5 §4 경고: Forward P/S의 IC 부호를 확인한다.
    음(-)이면 "비쌀 때만 감점" 방향 전환을 권장한다.
    """
    if "forward_ps" not in features_df.columns:
        logger.info("forward_ps 컬럼 없음 — Forward P/S 경고 건너뜀")
        return {"available": False}

    result = validate_single_factor(
        features_df, fwd_returns_df,
        "forward_ps", -1,  # 낮을수록 가점이 원래 의도
        "Forward P/S",
    )

    ic_12w = result.get("ic_mean_12W", np.nan)
    if not np.isnan(ic_12w) and ic_12w > 0:
        logger.warning(
            f"⚠️ Forward P/S IC 부호 양(+): {ic_12w:+.4f}\n"
            f"   → v5 경고 해당: 낮은 P/S가 저평가가 아니라 둔화 선반영일 수 있음\n"
            f"   → '지나치게 비쌀 때만 감점' 형태로 방향 전환 권장"
        )

    return result
