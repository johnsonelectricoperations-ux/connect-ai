"""
Connect AI v5 §0 — 팩터 피처 생성 엔진
========================================
원천 데이터(가격·재무)로부터 v5 Screen Score + Market Score에
대응하는 팩터 피처를 계산한다.
Point-in-Time(PIT) 원칙을 엄격히 준수한다.
"""

import logging

import numpy as np
import pandas as pd
from tqdm import tqdm

import config

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════
# 기술 지표 계산 함수
# ══════════════════════════════════════════════

def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """RSI (Relative Strength Index) 계산."""
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)

    avg_gain = gain.ewm(span=period, adjust=False).mean()
    avg_loss = loss.ewm(span=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def compute_returns(series: pd.Series, period: int) -> pd.Series:
    """기간 수익률 계산."""
    return series / series.shift(period) - 1


def compute_52week_position(close: pd.Series) -> pd.Series:
    """52주 위치 계산: (현재가 - 52주저) / (52주고 - 52주저)."""
    high_52w = close.rolling(252, min_periods=126).max()
    low_52w = close.rolling(252, min_periods=126).min()
    span = high_52w - low_52w
    return np.where(span > 0, (close - low_52w) / span, 0.5)


# ══════════════════════════════════════════════
# 가격 기반 피처 생성
# ══════════════════════════════════════════════

def build_price_features(prices_df: pd.DataFrame) -> pd.DataFrame:
    """
    가격 데이터로부터 가격 기반 팩터 피처를 계산한다.

    Args:
        prices_df: 전체 가격 데이터 (date, ticker, open, high, low, close, volume)

    Returns:
        DataFrame with price factor features per (date, ticker)
    """
    logger.info("가격 기반 피처 생성 시작...")

    prices_df = prices_df.copy()
    prices_df["date"] = pd.to_datetime(prices_df["date"])
    prices_df = prices_df.sort_values(["ticker", "date"])

    # 벤치마크 데이터 분리
    benchmarks = {}
    for bm in config.BENCHMARKS:
        bm_df = prices_df[prices_df["ticker"] == bm][["date", "close"]].copy()
        bm_df = bm_df.set_index("date").sort_index()
        bm_df.columns = [f"{bm.lower()}_close"]
        benchmarks[bm] = bm_df

    # 벤치마크 제외한 종목만
    stock_df = prices_df[~prices_df["ticker"].isin(config.BENCHMARKS)].copy()

    all_features = []
    tickers = stock_df["ticker"].unique()
    logger.info(f"피처 계산 대상: {len(tickers)}종목")

    for ticker in tqdm(tickers, desc="가격 피처 계산"):
        try:
            df = stock_df[stock_df["ticker"] == ticker].copy()
            df = df.set_index("date").sort_index()

            if len(df) < 60:  # 최소 데이터 요구
                continue

            feat = pd.DataFrame(index=df.index)
            feat["ticker"] = ticker
            feat["close"] = df["close"]
            feat["volume"] = df["volume"]

            # 20일 평균 거래량
            feat["avg_volume_20d"] = df["volume"].rolling(20, min_periods=10).mean()

            # ── 이동평균 ──
            feat["ma20"] = df["close"].rolling(config.MA_SHORT).mean()
            feat["ma50"] = df["close"].rolling(config.MA_MID).mean()
            feat["ma200"] = df["close"].rolling(config.MA_LONG).mean()

            # MA 정배열: ma20 > ma50 > ma200 → +1, 역배열 → -1, 기타 → 0
            feat["ma_alignment"] = np.where(
                (feat["ma20"] > feat["ma50"]) & (feat["ma50"] > feat["ma200"]),
                1,
                np.where(
                    (feat["ma20"] < feat["ma50"]) & (feat["ma50"] < feat["ma200"]),
                    -1,
                    0,
                ),
            )

            # ── RSI ──
            feat["rsi14"] = compute_rsi(df["close"], config.RSI_PERIOD)

            # ── 52주 위치 ──
            feat["week52_pos"] = compute_52week_position(df["close"])

            # ── 상대강도 (RS) ──
            for period_label, period_days in config.RS_PERIODS_DAYS.items():
                stock_ret = compute_returns(df["close"], period_days)

                for bm_name, bm_df in benchmarks.items():
                    bm_close = bm_df.iloc[:, 0].reindex(df.index, method="ffill")
                    bm_ret = compute_returns(bm_close, period_days)
                    col_name = f"rs_{bm_name.lower()}_{period_label}"
                    feat[col_name] = stock_ret - bm_ret

            # ── RS 종합 (v5: SPY·QQQ 통합, 최대 +1) ──
            # 6M RS 기준: 둘 다 양수 → +1, 하나만 → +0.5, 없으면 0
            spy_positive = feat["rs_spy_6m"] > 0
            qqq_positive = feat["rs_qqq_6m"] > 0
            feat["rs_combined"] = np.where(
                spy_positive & qqq_positive, 1.0,
                np.where(spy_positive | qqq_positive, 0.5, 0.0),
            )

            all_features.append(feat.reset_index())

        except Exception as e:
            logger.warning(f"{ticker}: 피처 계산 오류 — {e}")

    if not all_features:
        logger.error("피처 계산 결과 없음")
        return pd.DataFrame()

    result = pd.concat(all_features, ignore_index=True)
    result["date"] = pd.to_datetime(result["date"])

    logger.info(f"가격 피처 생성 완료: {len(result):,}행, {len(tickers)}종목")
    return result


# ══════════════════════════════════════════════
# 재무 기반 피처 병합
# ══════════════════════════════════════════════

def merge_fundamental_features(
    price_features: pd.DataFrame,
    fundamentals: pd.DataFrame,
) -> pd.DataFrame:
    """
    재무 팩터를 가격 피처에 Point-in-Time 기준으로 병합한다.
    filing_date 기준: 해당 재무 데이터는 filing_date 이후부터만 유효하다.

    Args:
        price_features: 가격 기반 피처 (date, ticker, ...)
        fundamentals: 재무 데이터 (ticker, period_end, filing_date, ...)

    Returns:
        병합된 피처 DataFrame
    """
    if fundamentals.empty:
        logger.warning("재무 데이터 없음 — 재무 팩터 컬럼을 NaN으로 채움")
        for col in [
            "revenue_growth_yoy", "gross_margin", "operating_margin",
            "rule_of_40", "fcf_positive", "cash_runway_q", "de_ratio",
            "market_cap",
        ]:
            if col not in price_features.columns:
                price_features[col] = np.nan
        return price_features

    logger.info("재무 팩터 PIT 병합 시작...")

    fundamentals = fundamentals.copy()
    fundamentals["filing_date"] = pd.to_datetime(fundamentals["filing_date"])
    fundamentals = fundamentals.sort_values(["ticker", "filing_date"])

    result = price_features.copy()

    # 재무 컬럼 초기화
    fund_cols = [
        "revenue_growth_yoy", "gross_margin", "operating_margin",
        "rule_of_40", "fcf_positive", "cash_runway_q", "de_ratio",
        "market_cap",
    ]
    for col in fund_cols:
        result[col] = np.nan

    tickers_with_fund = fundamentals["ticker"].unique()
    logger.info(f"재무 데이터 보유 종목: {len(tickers_with_fund)}")

    for ticker in tqdm(tickers_with_fund, desc="재무 병합"):
        fund_ticker = fundamentals[fundamentals["ticker"] == ticker].copy()
        price_mask = result["ticker"] == ticker

        if not price_mask.any():
            continue

        price_dates = result.loc[price_mask, "date"].values

        for _, row in fund_ticker.iterrows():
            filing_dt = row["filing_date"]
            if pd.isna(filing_dt):
                continue

            # filing_date 이후의 가격 행에 재무 데이터 적용
            # (다음 filing이 나올 때까지만 유효)
            valid_mask = price_mask & (result["date"] >= filing_dt)

            # 이후 filing이 있으면 그 전까지만
            later_filings = fund_ticker[
                fund_ticker["filing_date"] > filing_dt
            ]["filing_date"]
            if not later_filings.empty:
                next_filing = later_filings.iloc[0]
                valid_mask = valid_mask & (result["date"] < next_filing)

            if not valid_mask.any():
                continue

            result.loc[valid_mask, "revenue_growth_yoy"] = row.get("revenue_growth_yoy")
            result.loc[valid_mask, "gross_margin"] = row.get("gross_margin")
            result.loc[valid_mask, "operating_margin"] = row.get("operating_margin")
            result.loc[valid_mask, "rule_of_40"] = row.get("rule_of_40")
            result.loc[valid_mask, "fcf_positive"] = row.get("fcf_positive")
            result.loc[valid_mask, "de_ratio"] = row.get("de_ratio")

            cr = row.get("cash_runway_quarters")
            result.loc[valid_mask, "cash_runway_q"] = cr if cr != 99 else np.nan

    logger.info("재무 팩터 PIT 병합 완료")
    return result


# ══════════════════════════════════════════════
# 전체 피처 빌드 파이프라인
# ══════════════════════════════════════════════

def build_all_features(
    prices_df: pd.DataFrame,
    fundamentals_df: pd.DataFrame = None,
) -> pd.DataFrame:
    """
    전체 피처 빌드 파이프라인. 가격 + 재무 팩터를 결합한다.

    Args:
        prices_df: 전체 가격 데이터
        fundamentals_df: 전체 재무 데이터 (없으면 None)

    Returns:
        features_daily DataFrame, Parquet으로도 저장
    """
    # 1. 가격 피처
    features = build_price_features(prices_df)

    if features.empty:
        return features

    # 2. 섹터 정보 병합 (팩터 검증 필터용)
    if config.SECTOR_MAP_PATH.exists():
        try:
            sector_df = pd.read_parquet(config.SECTOR_MAP_PATH)[["ticker", "sector"]]
            features = features.merge(sector_df, on="ticker", how="left")
            coverage = features["sector"].notna().mean() * 100
            logger.info("섹터 정보 병합: %.1f%% 커버리지", coverage)
        except Exception as e:
            logger.warning("섹터 정보 병합 실패(무시): %s", e)

    # 3. 재무 피처 병합
    if fundamentals_df is not None and not fundamentals_df.empty:
        features = merge_fundamental_features(features, fundamentals_df)
    else:
        logger.info("재무 데이터 없음 — 가격 팩터만으로 진행")
        for col in [
            "revenue_growth_yoy", "gross_margin", "operating_margin",
            "rule_of_40", "fcf_positive", "cash_runway_q", "de_ratio",
            "market_cap",
        ]:
            if col not in features.columns:
                features[col] = np.nan

    # 4. 컬럼 순서 정리
    ordered_cols = [
        "date", "ticker", "sector", "close", "volume", "avg_volume_20d",
        # 가격 팩터
        "rs_spy_1m", "rs_spy_3m", "rs_spy_6m",
        "rs_qqq_1m", "rs_qqq_3m", "rs_qqq_6m",
        "rs_combined",
        "ma20", "ma50", "ma200", "ma_alignment",
        "rsi14", "week52_pos",
        # 재무 팩터
        "revenue_growth_yoy", "gross_margin", "operating_margin",
        "rule_of_40", "fcf_positive", "cash_runway_q", "de_ratio",
        # 메타
        "market_cap",
    ]

    # 존재하는 컬럼만 선택
    available = [c for c in ordered_cols if c in features.columns]
    features = features[available]

    # 4. Parquet 저장
    output_path = config.FEATURES_DIR / "features_daily.parquet"
    features.to_parquet(output_path, index=False, engine="pyarrow")
    logger.info(f"피처 저장 완료: {output_path} ({len(features):,}행)")

    return features


# ══════════════════════════════════════════════
# Forward Return 계산 (팩터 검증용)
# ══════════════════════════════════════════════

def compute_forward_returns(
    prices_df: pd.DataFrame,
    periods: list[int] = None,
) -> pd.DataFrame:
    """
    각 종목·날짜에 대한 forward 수익률을 계산한다.
    팩터 IC 검증에 사용.

    Args:
        prices_df: 가격 데이터 (date, ticker, close)
        periods: forward 기간 리스트 (영업일). 기본: [20, 60, 120]

    Returns:
        DataFrame[date, ticker, fwd_ret_20d, fwd_ret_60d, fwd_ret_120d]
    """
    if periods is None:
        periods = config.FORWARD_PERIODS

    logger.info(f"Forward 수익률 계산: 기간 {periods}")

    prices_df = prices_df.copy()
    prices_df["date"] = pd.to_datetime(prices_df["date"])

    # 종목별 close 피벗
    pivot = prices_df.pivot_table(
        index="date", columns="ticker", values="close"
    ).sort_index()

    fwd_returns = {}
    for period in periods:
        label = f"fwd_ret_{period}d"
        # forward return = (close_t+period / close_t) - 1
        fwd = pivot.shift(-period) / pivot - 1
        fwd_returns[label] = fwd

    # 멜트하여 long format으로
    result_parts = []
    for label, fwd_df in fwd_returns.items():
        melted = fwd_df.reset_index().melt(
            id_vars="date", var_name="ticker", value_name=label,
        )
        result_parts.append(melted.set_index(["date", "ticker"]))

    result = pd.concat(result_parts, axis=1).reset_index()
    result = result.dropna(subset=[f"fwd_ret_{periods[0]}d"])

    logger.info(f"Forward 수익률 계산 완료: {len(result):,}행")
    return result
