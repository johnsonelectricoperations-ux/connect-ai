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

# ── 프로젝트 루트를 sys.path에 추가 ──────────────────────
sys.path.insert(0, str(Path(__file__).parent))

from config import (
    DATA_DIR,
    FEATURES_DIR,
    PRICES_DIR,
    DB_PATH,
    FMP_API_KEY,
    LOG_LEVEL,
    LOG_FORMAT,
    BACKTEST_START,
    BACKTEST_END,
    BENCHMARKS,
)

# ── 로깅 설정 ─────────────────────────────────────────────
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO), format=LOG_FORMAT)
logger = logging.getLogger("main")


# ──────────────────────────────────────────────────────────
# 단계별 실행 함수
# ──────────────────────────────────────────────────────────

def step_collect_prices(args) -> bool:
    """Yahoo Finance 가격 데이터 수집"""
    logger.info("=== [1/7] 가격 데이터 수집 시작 ===")
    try:
        from data_collector import DataCollector
        collector = DataCollector()
        collector.collect_universe()
        collector.collect_prices()
        logger.info("가격 데이터 수집 완료.")
        return True
    except Exception as e:
        logger.error("가격 수집 실패: %s", e)
        return False


def step_collect_fundamentals(args) -> bool:
    """FMP 재무 데이터 수집"""
    logger.info("=== [2/7] 재무 데이터 수집 시작 ===")
    if not FMP_API_KEY:
        logger.warning("FMP_API_KEY 환경변수 미설정 — 재무 데이터 수집 건너뜀.")
        logger.warning("재무 팩터(Revenue Growth, Gross Margin 등) 검증은 API 키 설정 후 재실행하세요.")
        return False
    try:
        from data_collector import DataCollector
        collector = DataCollector()
        collector.collect_fundamentals()
        logger.info("재무 데이터 수집 완료.")
        return True
    except Exception as e:
        logger.error("재무 수집 실패: %s", e)
        return False


def step_build_features(args) -> bool:
    """피처 엔진 실행 (가격 + 재무 팩터 계산)"""
    logger.info("=== [3/7] 피처 생성 시작 ===")
    try:
        from db_manager import DBManager
        from feature_engine import FeatureEngine

        db = DBManager()
        engine = FeatureEngine(db)
        features_df = engine.build_all_features()

        if features_df.empty:
            logger.error("피처 생성 결과가 비어있습니다. 데이터 수집을 먼저 실행하세요.")
            return False

        out_path = FEATURES_DIR / "features.parquet"
        features_df.to_parquet(out_path, index=False)
        logger.info("피처 저장 완료: %s (%d rows)", out_path, len(features_df))
        return True
    except Exception as e:
        logger.error("피처 생성 실패: %s", e)
        return False


def _load_features() -> "pd.DataFrame | None":
    import pandas as pd
    feat_path = FEATURES_DIR / "features.parquet"
    if not feat_path.exists():
        logger.error("features.parquet 없음. --build-features 먼저 실행하세요.")
        return None
    df = pd.read_parquet(feat_path)
    logger.info("피처 로드: %d rows, %d cols", len(df), df.shape[1])
    return df


def step_validate_price_factors(args) -> "list[dict] | None":
    """가격 팩터 IC 검증"""
    logger.info("=== [4a/7] 가격 팩터 검증 시작 ===")
    features_df = _load_features()
    if features_df is None:
        return None
    try:
        from factor_validator import FactorValidator
        from config import PRICE_FACTORS
        validator = FactorValidator(features_df)
        results = validator.run_validation(list(PRICE_FACTORS.keys()))
        _print_validation_summary(results, "가격 팩터")
        return results
    except Exception as e:
        logger.error("가격 팩터 검증 실패: %s", e)
        return None


def step_validate_fundamental_factors(args) -> "list[dict] | None":
    """재무 팩터 IC 검증"""
    logger.info("=== [4b/7] 재무 팩터 검증 시작 ===")
    features_df = _load_features()
    if features_df is None:
        return None
    try:
        from factor_validator import FactorValidator
        from config import FUNDAMENTAL_FACTORS
        validator = FactorValidator(features_df)
        results = validator.run_validation(list(FUNDAMENTAL_FACTORS.keys()))
        _print_validation_summary(results, "재무 팩터")
        return results
    except Exception as e:
        logger.error("재무 팩터 검증 실패: %s", e)
        return None


def _print_validation_summary(results: list[dict], label: str):
    pass_count = sum(1 for r in results if r.get("pass") == "PASS")
    total = len(results)
    logger.info("%s 검증 완료: %d / %d PASS", label, pass_count, total)
    for r in results:
        factor = r.get("factor", "")
        status = r.get("pass", "NO_DATA")
        ic4  = r.get("ic_mean_4W",  float("nan"))
        ic12 = r.get("ic_mean_12W", float("nan"))
        ic24 = r.get("ic_mean_24W", float("nan"))
        logger.info(
            "  %-30s  %-18s  IC(4W/12W/24W): %.3f / %.3f / %.3f",
            factor, status,
            ic4  if ic4  == ic4  else 0.0,
            ic12 if ic12 == ic12 else 0.0,
            ic24 if ic24 == ic24 else 0.0,
        )


def step_run_backtest(args, validation_results: "list[dict] | None" = None) -> dict:
    """포트폴리오 백테스트 실행"""
    logger.info("=== [5/7] 백테스트 실행 시작 ===")
    import pandas as pd

    features_df = _load_features()
    if features_df is None:
        return {}

    # 가격 wide 행렬 로드
    prices_wide = _load_prices_wide()
    if prices_wide is None:
        return {}

    # 벤치마크 가격 로드
    benchmark_prices = _load_benchmark_prices()

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
        logger.error("백테스트 실패: %s", e)
        return {}


def _load_prices_wide() -> "pd.DataFrame | None":
    import pandas as pd
    price_files = list(PRICES_DIR.glob("*.parquet"))
    if not price_files:
        logger.error("가격 parquet 파일 없음. --collect-prices 먼저 실행하세요.")
        return None

    frames = []
    for f in price_files:
        try:
            df = pd.read_parquet(f)
            if "close" in df.columns and "ticker" in df.columns and "date" in df.columns:
                frames.append(df[["date", "ticker", "close"]])
        except Exception:
            pass

    if not frames:
        logger.error("유효한 가격 파일 없음.")
        return None

    combined = pd.concat(frames, ignore_index=True)
    combined["date"] = pd.to_datetime(combined["date"])
    prices_wide = combined.pivot_table(index="date", columns="ticker", values="close", aggfunc="last")
    prices_wide = prices_wide.sort_index()
    logger.info("가격 wide 행렬: %d rows × %d tickers", *prices_wide.shape)
    return prices_wide


def _load_benchmark_prices() -> "pd.DataFrame | None":
    """SPY/QQQ 가격 로드"""
    import pandas as pd
    frames = {}
    for ticker in BENCHMARKS:
        f = PRICES_DIR / f"{ticker}.parquet"
        if f.exists():
            df = pd.read_parquet(f)
            if "close" in df.columns and "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"])
                frames[ticker] = df.set_index("date")["close"]
    if not frames:
        logger.warning("벤치마크(SPY/QQQ) 가격 파일 없음 — 레짐 게이트 비활성화.")
        return None
    return pd.DataFrame(frames)


def _print_backtest_summary(results: dict):
    for key, val in results.items():
        if not isinstance(val, dict):
            continue
        stats = val.get("stats", {})
        if not stats:
            continue
        cagr  = stats.get("cagr", float("nan"))
        mdd   = stats.get("max_drawdown", float("nan"))
        sharpe= stats.get("sharpe", float("nan"))
        logger.info(
            "  %-30s  CAGR: %+.1f%%  MDD: %.1f%%  Sharpe: %.2f",
            key,
            (cagr * 100)   if cagr   == cagr   else 0.0,
            (mdd  * 100)   if mdd    == mdd    else 0.0,
            sharpe          if sharpe == sharpe else 0.0,
        )


def step_generate_report(
    args,
    validation_results: "list[dict] | None" = None,
    backtest_results:   "dict | None"        = None,
) -> Path | None:
    """HTML 보고서 생성"""
    logger.info("=== [6/7] 보고서 생성 시작 ===")
    try:
        from report_generator import generate_report, save_validation_json
        report_path = generate_report(
            validation_results=validation_results or [],
            backtest_results=backtest_results or {},
        )
        logger.info("HTML 보고서: %s", report_path)

        if validation_results:
            json_path = save_validation_json(validation_results)
            logger.info("검증 결과 JSON: %s", json_path)

        return report_path
    except Exception as e:
        logger.error("보고서 생성 실패: %s", e)
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
  python main.py --build-features              # 팩터 계산
  python main.py --validate-price-factors      # 가격 팩터 IC 검증
  python main.py --validate-fundamental-factors # 재무 팩터 IC 검증
  python main.py --run-backtest                # 포트폴리오 시뮬레이션
  python main.py --generate-report             # HTML 보고서 생성
  python main.py --run-all                     # 전체 파이프라인 실행
        """,
    )

    parser.add_argument("--collect-prices",               action="store_true", help="Yahoo Finance 가격 수집")
    parser.add_argument("--collect-fundamentals",         action="store_true", help="FMP 재무 데이터 수집 (FMP_API_KEY 필요)")
    parser.add_argument("--build-features",               action="store_true", help="피처 생성 (가격+재무 팩터 계산)")
    parser.add_argument("--validate-price-factors",       action="store_true", help="가격 팩터 IC 검증")
    parser.add_argument("--validate-fundamental-factors", action="store_true", help="재무 팩터 IC 검증")
    parser.add_argument("--run-backtest",                 action="store_true", help="포트폴리오 백테스트 실행")
    parser.add_argument("--generate-report",              action="store_true", help="HTML 보고서 생성")
    parser.add_argument("--run-all",                      action="store_true", help="전체 파이프라인 (수집→피처→검증→백테스트→보고서)")

    parser.add_argument("--start", default=BACKTEST_START, help=f"백테스트 시작일 (기본: {BACKTEST_START})")
    parser.add_argument("--end",   default=BACKTEST_END,   help=f"백테스트 종료일 (기본: {BACKTEST_END})")
    parser.add_argument("--skip-collect",        action="store_true", help="--run-all 시 데이터 수집 건너뜀 (피처부터)")
    parser.add_argument("--skip-fundamentals",   action="store_true", help="--run-all 시 재무 수집 건너뜀 (FMP 키 없을 때)")

    return parser


# ──────────────────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────────────────

def main():
    parser = build_parser()
    args = parser.parse_args()

    # 아무 플래그도 없으면 도움말 출력
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

    # ── --run-all: 전체 파이프라인 ──────────────────────────
    if args.run_all:
        logger.info("======= 전체 파이프라인 시작 =======")

        if not args.skip_collect:
            step_collect_prices(args)
            if not args.skip_fundamentals:
                step_collect_fundamentals(args)

        ok = step_build_features(args)
        if not ok:
            logger.error("피처 생성 실패 — 파이프라인 중단.")
            sys.exit(1)

        price_results = step_validate_price_factors(args) or []
        fund_results  = step_validate_fundamental_factors(args) or []
        validation_results = price_results + fund_results

        backtest_results = step_run_backtest(args, validation_results)
        report_path = step_generate_report(args, validation_results, backtest_results)

        elapsed = time.time() - t_start
        logger.info("======= 전체 파이프라인 완료 (%.1fs) =======", elapsed)
        if report_path:
            logger.info("최종 보고서: %s", report_path)
        return

    # ── 개별 단계 실행 ──────────────────────────────────────
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
        step_generate_report(args, validation_results, backtest_results)

    elapsed = time.time() - t_start
    logger.info("완료 (%.1fs)", elapsed)


if __name__ == "__main__":
    main()
