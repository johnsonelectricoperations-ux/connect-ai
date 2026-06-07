"""
Connect AI v5 §0 — 백테스트 엔진
====================================
통과한 팩터로 포트폴리오를 구성하고 성과를 측정한다.
vectorbt를 사용한 주간 리밸런싱 등가중 포트폴리오 시뮬레이션.

3가지 시뮬레이션:
  1. 단일 팩터 포트폴리오 (IC 검증 통과 팩터별)
  2. 조합 점수 포트폴리오 (Screen Score + Fundamental Score 합산)
  3. 레짐 필터 적용 포트폴리오 (SPY/QQQ MA200 게이트)

결과 비교:
  - CAGR, MDD, Sharpe, Sortino, Alpha(vs QQQ)
  - 레짐 필터 유무 비교
"""

import logging
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

import config

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════
# 레짐 판별
# ══════════════════════════════════════════════

def compute_regime(
    benchmark_prices: pd.DataFrame,
    ma_period: int = config.MA_LONG,
) -> pd.Series:
    """
    SPY·QQQ MA200 기준 레짐을 계산한다.

    Returns:
        Series[date → "RISK_ON" | "CAUTION" | "RISK_OFF"]
    """
    spy = benchmark_prices.get("SPY")
    qqq = benchmark_prices.get("QQQ")

    if spy is None or qqq is None:
        logger.warning("SPY 또는 QQQ 데이터 없음 — 레짐 RISK_ON으로 고정")
        return pd.Series("RISK_ON", index=benchmark_prices.index)

    spy_ma = spy.rolling(ma_period).mean()
    qqq_ma = qqq.rolling(ma_period).mean()

    spy_above = spy > spy_ma
    qqq_above = qqq > qqq_ma

    regime = pd.Series(index=spy.index, dtype=str)
    regime[spy_above & qqq_above] = "RISK_ON"
    regime[spy_above ^ qqq_above] = "CAUTION"  # 하나만 위
    regime[~spy_above & ~qqq_above] = "RISK_OFF"
    regime = regime.fillna("RISK_ON")

    counts = regime.value_counts()
    logger.info(f"레짐 분포: {counts.to_dict()}")
    return regime


# ══════════════════════════════════════════════
# 성과 통계 계산 (vectorbt 없이 pandas로 구현)
# ══════════════════════════════════════════════

def compute_stats(
    portfolio_returns: pd.Series,
    benchmark_returns: Optional[pd.Series] = None,
    periods_per_year: int = 252,
) -> dict:
    """
    포트폴리오 성과 통계를 계산한다.

    Args:
        portfolio_returns: 일별 수익률 Series
        benchmark_returns: 벤치마크 일별 수익률 (Alpha 계산용)
        periods_per_year: 연환산 기준 (기본 252 거래일)

    Returns:
        dict with CAGR, MDD, Sharpe, Sortino, Alpha, Hit Rate
    """
    r = portfolio_returns.dropna()
    if len(r) == 0:
        return {k: np.nan for k in ["cagr", "mdd", "sharpe", "sortino", "alpha", "hit_rate", "n_days"]}

    # 누적 수익률
    cum = (1 + r).cumprod()
    total_return = cum.iloc[-1] - 1
    n_years = len(r) / periods_per_year

    # CAGR
    cagr = (1 + total_return) ** (1 / n_years) - 1 if n_years > 0 else np.nan

    # MDD
    roll_max = cum.cummax()
    drawdown = (cum - roll_max) / roll_max
    mdd = drawdown.min()

    # Sharpe (무위험이자율 0 가정)
    sharpe = (r.mean() / r.std() * np.sqrt(periods_per_year)) if r.std() > 0 else np.nan

    # Sortino (하방 표준편차)
    downside = r[r < 0]
    sortino_denom = downside.std() * np.sqrt(periods_per_year) if len(downside) > 0 else np.nan
    sortino = (r.mean() * periods_per_year / sortino_denom) if sortino_denom and sortino_denom > 0 else np.nan

    # Alpha vs 벤치마크
    alpha = np.nan
    if benchmark_returns is not None:
        b = benchmark_returns.reindex(r.index).dropna()
        common = r.index.intersection(b.index)
        if len(common) > 20:
            p_ann = r.loc[common].mean() * periods_per_year
            b_ann = b.loc[common].mean() * periods_per_year
            alpha = p_ann - b_ann

    # Hit Rate (양수 수익일 비율)
    hit_rate = (r > 0).mean()

    return {
        "cagr": round(cagr, 4),
        "total_return": round(total_return, 4),
        "mdd": round(mdd, 4),
        "sharpe": round(sharpe, 4) if not np.isnan(sharpe) else np.nan,
        "sortino": round(sortino, 4) if not np.isnan(sortino) else np.nan,
        "alpha": round(alpha, 4) if not np.isnan(alpha) else np.nan,
        "hit_rate": round(hit_rate, 4),
        "n_days": len(r),
    }


# ══════════════════════════════════════════════
# 포트폴리오 수익률 시뮬레이션 (pandas 기반)
# ══════════════════════════════════════════════

def _simulate_portfolio(
    scores_df: pd.DataFrame,
    prices_wide: pd.DataFrame,
    top_n: int = config.TOP_N_STOCKS,
    rebalance_freq: str = config.REBALANCE_FREQ,
    slippage_pct: float = config.SLIPPAGE_PCT,
    regime: Optional[pd.Series] = None,
) -> pd.Series:
    """
    매주 금요일 리밸런싱, 상위 top_n 종목 등가중 포트폴리오 일별 수익률을 계산한다.

    Args:
        scores_df: 피처 DataFrame (date, ticker, score 컬럼 필요)
        prices_wide: 종목별 종가 (index=date, columns=ticker)
        top_n: 상위 종목 수
        rebalance_freq: 리밸런싱 주기
        slippage_pct: 슬리피지 비율
        regime: 레짐 Series (date → RISK_ON/CAUTION/RISK_OFF)

    Returns:
        일별 포트폴리오 수익률 Series
    """
    # 리밸런싱 날짜 생성
    all_dates = pd.DatetimeIndex(sorted(scores_df["date"].unique()))
    rebal_dates = pd.date_range(
        all_dates.min(), all_dates.max(), freq=rebalance_freq
    )

    # 가격 일별 수익률
    price_rets = prices_wide.pct_change()

    portfolio_rets = {}
    current_holdings: list[str] = []

    for i, rebal_dt in enumerate(rebal_dates):
        # 해당 날짜 데이터
        dt_str = rebal_dt.strftime("%Y-%m-%d")
        snap = scores_df[scores_df["date"] == rebal_dt].copy()

        if snap.empty:
            # 가장 가까운 이전 날짜
            prev = scores_df[scores_df["date"] <= rebal_dt]
            if prev.empty:
                continue
            snap = prev[prev["date"] == prev["date"].max()].copy()

        # 레짐 게이트
        if regime is not None:
            reg_val = regime.get(rebal_dt, "RISK_ON")
            if reg_val == "RISK_OFF":
                current_holdings = []
                logger.debug(f"{dt_str}: RISK_OFF → 현금 보유")
            elif reg_val == "CAUTION":
                # CAUTION: top_n 절반만 (🔧 사용자 정의 필요 → 일단 50% 적용)
                top_n_eff = max(1, top_n // 2)
                current_holdings = (
                    snap.nlargest(top_n_eff, "score")["ticker"].tolist()
                )
                logger.debug(f"{dt_str}: CAUTION → {top_n_eff}종목")
            else:
                current_holdings = snap.nlargest(top_n, "score")["ticker"].tolist()
        else:
            current_holdings = snap.nlargest(top_n, "score")["ticker"].tolist()

        # 다음 리밸런싱까지 보유 기간
        if i + 1 < len(rebal_dates):
            next_dt = rebal_dates[i + 1]
        else:
            next_dt = all_dates.max()

        hold_period = price_rets.loc[
            (price_rets.index > rebal_dt) & (price_rets.index <= next_dt)
        ]

        if hold_period.empty or not current_holdings:
            # 현금 보유
            for dt in hold_period.index:
                portfolio_rets[dt] = 0.0
            continue

        # 보유 종목 중 가격 있는 것만
        valid_tickers = [t for t in current_holdings if t in hold_period.columns]
        if not valid_tickers:
            for dt in hold_period.index:
                portfolio_rets[dt] = 0.0
            continue

        # 등가중 포트폴리오 수익률 (슬리피지 첫날 차감)
        daily_rets = hold_period[valid_tickers].mean(axis=1)
        for j, (dt, ret) in enumerate(daily_rets.items()):
            if j == 0:
                portfolio_rets[dt] = ret - slippage_pct
            else:
                portfolio_rets[dt] = ret

    return pd.Series(portfolio_rets).sort_index()


# ══════════════════════════════════════════════
# 단일 팩터 포트폴리오
# ══════════════════════════════════════════════

def run_factor_portfolio(
    features_df: pd.DataFrame,
    prices_wide: pd.DataFrame,
    factor_name: str,
    top_n: int = config.TOP_N_STOCKS,
    benchmark_returns: Optional[pd.Series] = None,
) -> dict:
    """
    단일 팩터 상위 N개 등가중 포트폴리오 성과를 계산한다.

    Returns:
        {stats: dict, returns: Series, factor_name: str}
    """
    logger.info(f"단일 팩터 포트폴리오: {factor_name}")

    if factor_name not in features_df.columns:
        logger.warning(f"{factor_name} 컬럼 없음")
        return {"factor_name": factor_name, "stats": {}, "returns": pd.Series()}

    scores = features_df[["date", "ticker", factor_name]].rename(
        columns={factor_name: "score"}
    ).copy()

    port_rets = _simulate_portfolio(scores, prices_wide, top_n=top_n)
    stats = compute_stats(port_rets, benchmark_returns)

    logger.info(
        f"  CAGR={stats.get('cagr', 'N/A'):.1%}  "
        f"MDD={stats.get('mdd', 'N/A'):.1%}  "
        f"Sharpe={stats.get('sharpe', 'N/A'):.2f}  "
        f"Alpha={stats.get('alpha', 'N/A'):.1%}"
    )

    return {"factor_name": factor_name, "stats": stats, "returns": port_rets}


# ══════════════════════════════════════════════
# 조합 점수 포트폴리오
# ══════════════════════════════════════════════

def run_combined_portfolio(
    features_df: pd.DataFrame,
    prices_wide: pd.DataFrame,
    factor_weights: dict[str, float],
    market_cap_col: Optional[str] = "market_cap",
    top_n: int = config.TOP_N_STOCKS,
    benchmark_returns: Optional[pd.Series] = None,
    label: str = "combined",
) -> dict:
    """
    여러 팩터를 가중합해 조합 점수 포트폴리오를 구성한다.

    Args:
        factor_weights: {factor_name: weight} — 정규화 불필요, 내부에서 처리
        market_cap_col: 시총 컬럼 (동적 가중치용 — None이면 고정 가중치)

    Returns:
        {label, stats, returns, factor_weights}
    """
    logger.info(f"조합 포트폴리오: {label} ({len(factor_weights)}개 팩터)")

    df = features_df.copy()

    # 각 팩터를 cross-sectional z-score 정규화 후 가중합
    score_cols = []
    for factor, weight in factor_weights.items():
        if factor not in df.columns:
            logger.warning(f"  {factor} 없음 — 건너뜀")
            continue
        col = f"_zscore_{factor}"
        df[col] = df.groupby("date")[factor].transform(
            lambda x: (x - x.mean()) / x.std() if x.std() > 0 else 0
        )
        df[col] = df[col] * weight
        score_cols.append(col)

    if not score_cols:
        logger.error("유효한 팩터 없음")
        return {"label": label, "stats": {}, "returns": pd.Series()}

    df["score"] = df[score_cols].sum(axis=1)

    # 동적 가중치: 시총 $5B 기준 (v5 설계)
    if market_cap_col and market_cap_col in df.columns:
        mc_thresh = 5_000_000_000
        f_w = df[market_cap_col].apply(lambda x: 0.8 if (x and x < mc_thresh) else 0.6)
        m_w = 1 - f_w
        # 재무 팩터와 가격 팩터를 분리해 재가중
        fund_factors = [f for f in factor_weights if f in config.FUNDAMENTAL_FACTORS]
        price_factors = [f for f in factor_weights if f in config.PRICE_FACTORS]
        if fund_factors and price_factors:
            fund_cols = [f"_zscore_{f}" for f in fund_factors if f"_zscore_{f}" in df.columns]
            price_cols = [f"_zscore_{f}" for f in price_factors if f"_zscore_{f}" in df.columns]
            if fund_cols and price_cols:
                df["score"] = (
                    df[fund_cols].sum(axis=1) * f_w +
                    df[price_cols].sum(axis=1) * m_w
                )

    scores = df[["date", "ticker", "score"]]
    port_rets = _simulate_portfolio(scores, prices_wide, top_n=top_n)
    stats = compute_stats(port_rets, benchmark_returns)

    logger.info(
        f"  CAGR={stats.get('cagr', 0):.1%}  "
        f"MDD={stats.get('mdd', 0):.1%}  "
        f"Sharpe={stats.get('sharpe', 0):.2f}  "
        f"Alpha={stats.get('alpha', 0):.1%}"
    )

    return {
        "label": label,
        "stats": stats,
        "returns": port_rets,
        "factor_weights": factor_weights,
    }


# ══════════════════════════════════════════════
# 레짐 필터 포트폴리오
# ══════════════════════════════════════════════

def run_regime_filtered(
    features_df: pd.DataFrame,
    prices_wide: pd.DataFrame,
    benchmark_prices: pd.DataFrame,
    factor_weights: dict[str, float],
    top_n: int = config.TOP_N_STOCKS,
    benchmark_returns: Optional[pd.Series] = None,
) -> dict:
    """
    레짐 게이트를 적용한 포트폴리오와 미적용 포트폴리오를 비교한다.

    Returns:
        {
          "no_regime": {stats, returns},
          "with_regime": {stats, returns},
          "regime_series": Series,
        }
    """
    logger.info("레짐 필터 비교 시뮬레이션...")

    # 레짐 계산
    regime = compute_regime(benchmark_prices)

    # 조합 점수 준비
    df = features_df.copy()
    score_cols = []
    for factor, weight in factor_weights.items():
        if factor not in df.columns:
            continue
        col = f"_z_{factor}"
        df[col] = df.groupby("date")[factor].transform(
            lambda x: (x - x.mean()) / x.std() if x.std() > 0 else 0
        )
        df[col] = df[col] * weight
        score_cols.append(col)

    df["score"] = df[score_cols].sum(axis=1) if score_cols else 0
    scores = df[["date", "ticker", "score"]]

    # 레짐 미적용
    rets_no = _simulate_portfolio(scores, prices_wide, top_n=top_n)
    stats_no = compute_stats(rets_no, benchmark_returns)

    # 레짐 적용
    rets_with = _simulate_portfolio(scores, prices_wide, top_n=top_n, regime=regime)
    stats_with = compute_stats(rets_with, benchmark_returns)

    logger.info("  레짐 미적용  →  "
                f"CAGR={stats_no.get('cagr', 0):.1%}  MDD={stats_no.get('mdd', 0):.1%}")
    logger.info("  레짐 적용    →  "
                f"CAGR={stats_with.get('cagr', 0):.1%}  MDD={stats_with.get('mdd', 0):.1%}")

    return {
        "no_regime": {"stats": stats_no, "returns": rets_no},
        "with_regime": {"stats": stats_with, "returns": rets_with},
        "regime_series": regime,
    }


# ══════════════════════════════════════════════
# 벤치마크 비교
# ══════════════════════════════════════════════

def compare_with_benchmark(
    portfolio_returns: pd.Series,
    benchmark_returns: pd.Series,
    label: str = "Portfolio",
) -> pd.DataFrame:
    """
    포트폴리오와 벤치마크의 누적 수익률을 비교하는 DataFrame을 반환한다.
    """
    port_cum = (1 + portfolio_returns).cumprod()
    bench_cum = (1 + benchmark_returns.reindex(portfolio_returns.index).fillna(0)).cumprod()

    return pd.DataFrame({
        label: port_cum,
        "Benchmark": bench_cum,
    })


# ══════════════════════════════════════════════
# 전체 백테스트 실행
# ══════════════════════════════════════════════

def run_full_backtest(
    features_df: pd.DataFrame,
    prices_wide: pd.DataFrame,
    benchmark_prices: pd.DataFrame,
    validation_results: list[dict],
) -> dict:
    """
    검증 통과 팩터로 전체 백테스트를 실행한다.

    Args:
        validation_results: factor_validator.validate_*_factors() 결과 리스트

    Returns:
        {
          "single_factor": {factor_name: result},
          "combined_price": result,
          "combined_full": result,
          "regime_comparison": result,
        }
    """
    logger.info("=" * 60)
    logger.info("전체 백테스트 실행")
    logger.info("=" * 60)

    # QQQ 벤치마크 수익률
    qqq_rets = None
    if "QQQ" in benchmark_prices.columns:
        qqq_rets = benchmark_prices["QQQ"].pct_change().dropna()

    results = {}

    # 1. 단일 팩터 포트폴리오
    logger.info("\n--- 단일 팩터 포트폴리오 ---")
    single_results = {}
    passed_factors = [
        r for r in validation_results
        if r.get("pass") in ("PASS", "STRONG_PENDING", "WEAK_PENDING")
    ]

    for val_result in passed_factors[:5]:  # 상위 5개만
        fname = val_result["factor"]
        res = run_factor_portfolio(features_df, prices_wide, fname,
                                   benchmark_returns=qqq_rets)
        single_results[fname] = res

        # 저장
        if not res["returns"].empty:
            res["returns"].to_frame("returns").to_parquet(
                config.RESULTS_DIR / f"backtest_single_{fname}.parquet"
            )

    results["single_factor"] = single_results

    # 2. 가격 팩터만 조합
    logger.info("\n--- 가격 팩터 조합 포트폴리오 ---")
    price_passed = {
        r["factor"]: 1.0 for r in passed_factors
        if r["factor"] in config.PRICE_FACTORS
    }
    if price_passed:
        res_price = run_combined_portfolio(
            features_df, prices_wide, price_passed,
            benchmark_returns=qqq_rets, label="price_only",
        )
        results["combined_price"] = res_price
        if not res_price["returns"].empty:
            res_price["returns"].to_frame("returns").to_parquet(
                config.RESULTS_DIR / "backtest_combined_price.parquet"
            )

    # 3. 전체 팩터 조합 (가격 + 재무)
    logger.info("\n--- 전체 팩터 조합 포트폴리오 ---")
    all_passed = {r["factor"]: 1.0 for r in passed_factors}
    if all_passed:
        res_full = run_combined_portfolio(
            features_df, prices_wide, all_passed,
            benchmark_returns=qqq_rets, label="full_combined",
        )
        results["combined_full"] = res_full
        if not res_full["returns"].empty:
            res_full["returns"].to_frame("returns").to_parquet(
                config.RESULTS_DIR / "backtest_combined_full.parquet"
            )

    # 4. 레짐 필터 비교
    logger.info("\n--- 레짐 필터 비교 ---")
    if all_passed and not benchmark_prices.empty:
        res_regime = run_regime_filtered(
            features_df, prices_wide, benchmark_prices, all_passed,
            benchmark_returns=qqq_rets,
        )
        results["regime_comparison"] = res_regime

    logger.info("\n백테스트 완료")
    return results
