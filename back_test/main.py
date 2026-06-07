"""
Connect AI v5 §0 백테스트 검증 시스템 — CLI 진입점
====================================================
Usage examples:
  python main.py --run-all
  python main.py --collect-prices
  python main.py --build-features
  python main.py --validate-price-factors
  python main.py --validate-fundamental-factors
  python main.py --run-backtest
  python main.py --generate-report
  python main.py --validate-price-factors --validate-fundamental-factors --generate-report
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import (
    DATA_DIR,
    FEATURES_DIR,
    PRICES_DIR,
    IC_RESULTS_DIR,
    FMP_API_KEY,
    LOG_LEVEL,
    LOG_FORMAT,
    BACKTEST_START,
    BACKTEST_END,
    BENCHMARKS,
    PRICE_FACTORS,
    FUNDAMENTAL_FACTORS,
    FORWARD_PERIOD_LABELS,
)

logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO), format=LOG_FORMAT)
logger = logging.getLogger("main")

_FWD_RETURNS_PATH = FEATURES_DIR / "fwd_returns.parquet"
_FEATURES_PATH    = FEATURES_DIR / "features_daily.parquet"


# ──────────────────────────────────────────────────────────
# 공통 로더
# ──────────────────────────────────────────────────────────

def _load_features():
    import pandas as pd
    if not _FEATURES_PATH.exists():
        logger.error("features_daily.parquet 없음. --build-features 먼저 실행하세요.")
        return None
    df = pd.read_parquet(_FEATURES_PATH)
    logger.info("피처 로드: %d rows, %d cols", len(df), df.shape[1])
    return df


def _load_fwd_returns():
    import pandas as pd
    if not _FWD_RETURNS_PATH.exists():
        logger.error("fwd_returns.parquet 없음. --build-features 먼저 실행하세요.")
        return None
    df = pd.read_parquet(_FWD_RETURNS_PATH)
    logger.info("Forward 수익률 로드: %d rows", len(df))
    return df


def _load_prices_wide():
    import pandas as pd
    price_files = list(PRICES_DIR.glob("*.parquet"))
    if not price_files:
        logger.error("가격 parquet 없음. --collect-prices 먼저 실행하세요.")
        return None
    frames = []
    for f in price_files:
        try:
            df = pd.read_parquet(f)
            if {"close", "ticker", "date"}.issubset(df.columns):
                frames.append(df[["date", "ticker", "close"]])
        except Exception:
            pass
    if not frames:
        return None
    combined = pd.concat(frames, ignore_index=True)
    combined["date"] = pd.to_datetime(combined["date"])
    wide = combined.pivot_table(index="date", columns="ticker", values="close", aggfunc="last")
    logger.info("가격 wide 행렬: %d rows × %d tickers", *wide.shape)
    return wide.sort_index()


def _load_benchmark_prices():
    import pandas as pd
    frames = {}
    for ticker in BENCHMARKS:
        f = PRICES_DIR / f"{ticker}.parquet"
        if f.exists():
            df = pd.read_parquet(f)
            if {"close", "date"}.issubset(df.columns):
                df["date"] = pd.to_datetime(df["date"])
                frames[ticker] = df.set_index("date")["close"]
    if not frames:
        logger.warning("벤치마크(SPY/QQQ) 가격 없음 — 레짐 게이트 비활성화.")
        return None
    return pd.DataFrame(frames)


def _df_to_records(df) -> list[dict]:
    """DataFrame → list[dict], NaN 안전 변환"""
    import numpy as np
    records = []
    for row in df.to_dict("records"):
        cleaned = {}
        for k, v in row.items():
            if isinstance(v, float) and (v != v or v == float("inf") or v == float("-inf")):
                cleaned[k] = None
            else:
                cleaned[k] = v
        records.append(cleaned)
    return records


# ──────────────────────────────────────────────────────────
# 단계별 실행 함수
# ──────────────────────────────────────────────────────────

def step_collect_prices(args) -> bool:
    logger.info("=== [1/7] 가격 데이터 수집 시작 ===")
    try:
        from data_collector import (
            get_nasdaq_nyse_tickers,
            collect_price_data,
            collect_spy_qqq_data,
            build_universe_snapshots,
        )
        tickers_df = get_nasdaq_nyse_tickers()
        tickers = tickers_df["symbol"].dropna().tolist()
        logger.info("유니버스: %d 종목", len(tickers))

        collect_price_data(tickers)
        collect_spy_qqq_data()
        build_universe_snapshots()
        logger.info("가격 데이터 수집 완료.")
        return True
    except Exception as e:
        logger.error("가격 수집 실패: %s", e, exc_info=True)
        return False


def step_collect_fundamentals(args) -> bool:
    logger.info("=== [2/7] 재무 데이터 수집 시작 ===")
    if not FMP_API_KEY:
        logger.warning(
            "FMP_API_KEY 환경변수 미설정 — 재무 수집 건너뜀.\n"
            "재무 팩터 검증은 API 키 설정 후 재실행하세요."
        )
        return False
    try:
        from data_collector import get_nasdaq_nyse_tickers, collect_fundamentals
        tickers_df = get_nasdaq_nyse_tickers()
        tickers = tickers_df["symbol"].dropna().tolist()
        collect_fundamentals(tickers)
        logger.info("재무 데이터 수집 완료.")
        return True
    except Exception as e:
        logger.error("재무 수집 실패: %s", e, exc_info=True)
        return False


def step_build_features(args) -> bool:
    logger.info("=== [3/7] 피처 생성 시작 ===")
    try:
        from data_collector import load_all_prices, load_all_fundamentals
        from feature_engine import build_all_features, compute_forward_returns

        prices_df = load_all_prices()
        if prices_df.empty:
            logger.error("가격 데이터 없음. --collect-prices 먼저 실행하세요.")
            return False

        fundamentals_df = load_all_fundamentals()
        features_df = build_all_features(
            prices_df,
            fundamentals_df if not fundamentals_df.empty else None,
        )

        if features_df.empty:
            logger.error("피처 생성 결과가 비어있습니다.")
            return False

        # forward 수익률 계산 및 저장 (검증 단계에서 사용)
        fwd_returns_df = compute_forward_returns(prices_df)
        fwd_returns_df.to_parquet(_FWD_RETURNS_PATH, index=False)
        logger.info(
            "피처 완료: %d rows | fwd_returns: %d rows",
            len(features_df), len(fwd_returns_df),
        )
        return True
    except Exception as e:
        logger.error("피처 생성 실패: %s", e, exc_info=True)
        return False


def step_validate_price_factors(args) -> list[dict] | None:
    logger.info("=== [4a/7] 가격 팩터 검증 시작 ===")
    features_df   = _load_features()
    fwd_returns_df = _load_fwd_returns()
    if features_df is None or fwd_returns_df is None:
        return None
    try:
        from factor_validator import validate_price_factors
        summary_df = validate_price_factors(features_df, fwd_returns_df)
        results = _df_to_records(summary_df)
        _print_validation_summary(results, "가격 팩터")
        return results
    except Exception as e:
        logger.error("가격 팩터 검증 실패: %s", e, exc_info=True)
        return None


def step_validate_fundamental_factors(args) -> list[dict] | None:
    logger.info("=== [4b/7] 재무 팩터 검증 시작 ===")
    features_df    = _load_features()
    fwd_returns_df = _load_fwd_returns()
    if features_df is None or fwd_returns_df is None:
        return None
    try:
        from factor_validator import validate_fundamental_factors
        summary_df = validate_fundamental_factors(features_df, fwd_returns_df)
        results = _df_to_records(summary_df)
        _print_validation_summary(results, "재무 팩터")
        return results
    except Exception as e:
        logger.error("재무 팩터 검증 실패: %s", e, exc_info=True)
        return None


def _print_validation_summary(results: list[dict], label: str):
    pass_count = sum(1 for r in results if r.get("pass") == "PASS")
    logger.info("%s 검증 완료: %d / %d PASS", label, pass_count, len(results))
    for r in results:
        factor = r.get("factor", "")
        status = r.get("pass", "NO_DATA")
        ic4  = r.get("ic_mean_4W")  or 0.0
        ic12 = r.get("ic_mean_12W") or 0.0
        ic24 = r.get("ic_mean_24W") or 0.0
        logger.info(
            "  %-30s  %-18s  IC(4W/12W/24W): %+.3f / %+.3f / %+.3f",
            factor, status, ic4, ic12, ic24,
        )


def step_run_factor_correlation(args) -> dict:
    logger.info("=== [4c/7] 팩터 상관 분석 ===")
    features_df = _load_features()
    if features_df is None:
        return {}
    try:
        from factor_validator import analyze_factor_correlations
        return analyze_factor_correlations(features_df)
    except Exception as e:
        logger.error("팩터 상관 분석 실패: %s", e, exc_info=True)
        return {}


def step_check_forward_ps(args) -> dict:
    logger.info("=== [4d/7] Forward P/S IC 부호 확인 ===")
    features_df    = _load_features()
    fwd_returns_df = _load_fwd_returns()
    if features_df is None or fwd_returns_df is None:
        return {}
    try:
        from factor_validator import check_forward_ps_sign_warning
        return check_forward_ps_sign_warning(features_df, fwd_returns_df)
    except Exception as e:
        logger.error("Forward P/S 확인 실패: %s", e, exc_info=True)
        return {}


def step_run_backtest(args, validation_results: list[dict] | None = None) -> dict:
    logger.info("=== [5/7] 백테스트 실행 시작 ===")
    features_df = _load_features()
    if features_df is None:
        return {}
    prices_wide      = _load_prices_wide()
    benchmark_prices = _load_benchmark_prices()
    if prices_wide is None:
        return {}
    try:
        from backtest_engine import run_full_backtest
        results = run_full_backtest(
            features_df=features_df,
            prices_wide=prices_wide,
            benchmark_prices=benchmark_prices,
            validation_results=validation_results or [],
        )
        _print_backtest_summary(results)
        return results
    except Exception as e:
        logger.error("백테스트 실패: %s", e, exc_info=True)
        return {}


def _print_backtest_summary(results: dict):
    for key, val in results.items():
        if not isinstance(val, dict):
            continue
        stats = val.get("stats", {})
        if not stats:
            continue
        cagr   = stats.get("cagr")   or 0.0
        mdd    = stats.get("max_drawdown") or 0.0
        sharpe = stats.get("sharpe") or 0.0
        logger.info(
            "  %-30s  CAGR: %+.1f%%  MDD: %.1f%%  Sharpe: %.2f",
            key, cagr * 100, mdd * 100, sharpe,
        )


def step_generate_report(
    args,
    validation_results: list[dict] | None = None,
    backtest_results:   dict | None        = None,
    correlation_data:   dict | None        = None,
    forward_ps_result:  dict | None        = None,
) -> Path | None:
    logger.info("=== [6/7] 보고서 생성 시작 ===")
    try:
        from report_generator import generate_report, save_validation_json
        report_path = generate_report(
            validation_results=validation_results or [],
            backtest_results=backtest_results or {},
            correlation_data=correlation_data or {},
            forward_ps_result=forward_ps_result or {},
        )
        logger.info("HTML 보고서: %s", report_path)
        if validation_results:
            json_path = save_validation_json(validation_results)
            logger.info("검증 결과 JSON: %s", json_path)
        return report_path
    except Exception as e:
        logger.error("보고서 생성 실패: %s", e, exc_info=True)
        return None


# ──────────────────────────────────────────────────────────
# CLI 인수 파서
# ──────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python main.py",
        description="Connect AI v5 §0 팩터 백테스트 검증 파이프라인",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
단계별 실행 예시:
  python main.py --collect-prices              # Yahoo Finance 가격 수집
  python main.py --collect-fundamentals        # FMP 재무 수집 (API 키 필요)
  python main.py --build-features              # 팩터 계산 + forward 수익률
  python main.py --validate-price-factors      # 가격 팩터 IC 검증
  python main.py --validate-fundamental-factors # 재무 팩터 IC 검증
  python main.py --run-backtest                # 포트폴리오 시뮬레이션
  python main.py --generate-report             # HTML 보고서 생성
  python main.py --run-all                     # 전체 파이프라인 실행
        """,
    )
    parser.add_argument("--collect-prices",               action="store_true")
    parser.add_argument("--collect-fundamentals",         action="store_true")
    parser.add_argument("--build-features",               action="store_true")
    parser.add_argument("--validate-price-factors",       action="store_true")
    parser.add_argument("--validate-fundamental-factors", action="store_true")
    parser.add_argument("--run-backtest",                 action="store_true")
    parser.add_argument("--generate-report",              action="store_true")
    parser.add_argument("--run-all",                      action="store_true")
    parser.add_argument("--skip-collect",      action="store_true",
                        help="--run-all 시 데이터 수집 건너뜀")
    parser.add_argument("--skip-fundamentals", action="store_true",
                        help="--run-all 시 재무 수집 건너뜀 (FMP 키 없을 때)")
    return parser


# ──────────────────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────────────────

def main():
    parser = build_parser()
    args = parser.parse_args()

    flags = [
        args.collect_prices, args.collect_fundamentals, args.build_features,
        args.validate_price_factors, args.validate_fundamental_factors,
        args.run_backtest, args.generate_report, args.run_all,
    ]
    if not any(flags):
        parser.print_help()
        sys.exit(0)

    t_start = time.time()
    validation_results: list[dict] = []
    backtest_results:   dict       = {}
    correlation_data:   dict       = {}
    forward_ps_result:  dict       = {}

    if args.run_all:
        logger.info("======= 전체 파이프라인 시작 =======")

        if not args.skip_collect:
            step_collect_prices(args)
            if not args.skip_fundamentals:
                step_collect_fundamentals(args)

        if not step_build_features(args):
            logger.error("피처 생성 실패 — 파이프라인 중단.")
            sys.exit(1)

        price_results = step_validate_price_factors(args)    or []
        fund_results  = step_validate_fundamental_factors(args) or []
        validation_results = price_results + fund_results

        correlation_data  = step_run_factor_correlation(args)
        forward_ps_result = step_check_forward_ps(args)
        backtest_results  = step_run_backtest(args, validation_results)
        step_generate_report(
            args, validation_results, backtest_results,
            correlation_data, forward_ps_result,
        )

        elapsed = time.time() - t_start
        logger.info("======= 전체 파이프라인 완료 (%.1fs) =======", elapsed)
        return

    # 개별 단계
    if args.collect_prices:
        step_collect_prices(args)

    if args.collect_fundamentals:
        step_collect_fundamentals(args)

    if args.build_features:
        step_build_features(args)

    if args.validate_price_factors:
        res = step_validate_price_factors(args)
        if res:
            validation_results.extend(res)

    if args.validate_fundamental_factors:
        res = step_validate_fundamental_factors(args)
        if res:
            validation_results.extend(res)

    if args.run_backtest:
        backtest_results = step_run_backtest(args, validation_results or None)

    if args.generate_report:
        if not validation_results and not backtest_results:
            logger.warning("검증/백테스트 결과 없음 — 먼저 --validate-* 또는 --run-backtest 실행 권장.")
        # 상관분석/Forward P/S는 검증 결과가 있을 때만 실행
        if validation_results:
            correlation_data  = step_run_factor_correlation(args)
            forward_ps_result = step_check_forward_ps(args)
        step_generate_report(
            args, validation_results, backtest_results,
            correlation_data, forward_ps_result,
        )

    elapsed = time.time() - t_start
    logger.info("완료 (%.1fs)", elapsed)


if __name__ == "__main__":
    main()
