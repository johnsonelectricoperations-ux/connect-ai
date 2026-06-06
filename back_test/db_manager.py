"""
Connect AI v5 §0 — DuckDB 데이터베이스 관리 모듈
=================================================
Parquet 파일을 DuckDB로 로드하고 SQL 조회를 지원한다.
"""

import logging
from pathlib import Path

import duckdb
import pandas as pd

import config

logger = logging.getLogger(__name__)


class DBManager:
    """DuckDB 데이터베이스 연결 및 테이블 관리."""

    def __init__(self, db_path: Path = config.DB_PATH):
        self.db_path = db_path
        self.con = None

    def connect(self) -> "DBManager":
        """DuckDB 연결."""
        self.con = duckdb.connect(str(self.db_path))
        logger.info(f"DuckDB 연결: {self.db_path}")
        return self

    def close(self):
        """연결 종료."""
        if self.con:
            self.con.close()
            self.con = None

    def __enter__(self):
        return self.connect()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    # ──────────────────────────────────────────
    # 스키마 초기화
    # ──────────────────────────────────────────

    def init_schema(self):
        """모든 테이블 스키마를 생성한다."""
        self.con.execute("""
            CREATE TABLE IF NOT EXISTS prices (
                date DATE,
                ticker VARCHAR,
                open DOUBLE,
                high DOUBLE,
                low DOUBLE,
                close DOUBLE,
                volume BIGINT,
                PRIMARY KEY (date, ticker)
            )
        """)

        self.con.execute("""
            CREATE TABLE IF NOT EXISTS fundamentals (
                ticker VARCHAR,
                period_end DATE,
                filing_date DATE,
                revenue DOUBLE,
                revenue_growth_yoy DOUBLE,
                gross_profit DOUBLE,
                gross_margin DOUBLE,
                operating_income DOUBLE,
                operating_margin DOUBLE,
                net_income DOUBLE,
                fcf DOUBLE,
                fcf_positive DOUBLE,
                total_cash DOUBLE,
                total_debt DOUBLE,
                total_equity DOUBLE,
                de_ratio DOUBLE,
                cash_runway_quarters DOUBLE,
                rule_of_40 DOUBLE,
                shares_outstanding DOUBLE,
                eps DOUBLE,
                operating_cash_flow DOUBLE,
                capex DOUBLE,
                PRIMARY KEY (ticker, period_end)
            )
        """)

        self.con.execute("""
            CREATE TABLE IF NOT EXISTS features (
                date DATE,
                ticker VARCHAR,
                close DOUBLE,
                volume BIGINT,
                avg_volume_20d DOUBLE,
                -- 가격 팩터
                rs_spy_1m DOUBLE,
                rs_spy_3m DOUBLE,
                rs_spy_6m DOUBLE,
                rs_qqq_1m DOUBLE,
                rs_qqq_3m DOUBLE,
                rs_qqq_6m DOUBLE,
                rs_combined DOUBLE,
                ma20 DOUBLE,
                ma50 DOUBLE,
                ma200 DOUBLE,
                ma_alignment INTEGER,
                rsi14 DOUBLE,
                week52_pos DOUBLE,
                -- 재무 팩터
                revenue_growth_yoy DOUBLE,
                gross_margin DOUBLE,
                operating_margin DOUBLE,
                rule_of_40 DOUBLE,
                fcf_positive DOUBLE,
                cash_runway_q DOUBLE,
                de_ratio DOUBLE,
                -- 메타
                market_cap DOUBLE,
                PRIMARY KEY (date, ticker)
            )
        """)

        self.con.execute("""
            CREATE TABLE IF NOT EXISTS universe_snapshots (
                date DATE,
                ticker VARCHAR,
                PRIMARY KEY (date, ticker)
            )
        """)

        logger.info("DuckDB 스키마 초기화 완료")

    # ──────────────────────────────────────────
    # 데이터 로드
    # ──────────────────────────────────────────

    def load_prices(self):
        """Parquet 가격 파일들을 prices 테이블로 로드한다."""
        price_files = list(config.PRICES_DIR.glob("*.parquet"))
        if not price_files:
            logger.warning("가격 Parquet 파일 없음")
            return

        # 기존 데이터 삭제 후 재로드
        self.con.execute("DELETE FROM prices")

        count = 0
        for pf in price_files:
            try:
                self.con.execute(f"""
                    INSERT OR IGNORE INTO prices
                    SELECT
                        CAST(date AS DATE) as date,
                        ticker,
                        open, high, low, close,
                        CAST(volume AS BIGINT) as volume
                    FROM read_parquet('{pf.as_posix()}')
                """)
                count += 1
            except Exception as e:
                logger.warning(f"{pf.stem}: 로드 오류 — {e}")

        total = self.con.execute("SELECT COUNT(*) FROM prices").fetchone()[0]
        logger.info(f"prices 테이블 로드: {count}파일, {total:,}행")

    def load_fundamentals(self):
        """Parquet 재무 파일들을 fundamentals 테이블로 로드한다."""
        fund_files = list(config.FUNDAMENTALS_DIR.glob("*.parquet"))
        if not fund_files:
            logger.warning("재무 Parquet 파일 없음")
            return

        self.con.execute("DELETE FROM fundamentals")

        count = 0
        for ff in fund_files:
            try:
                self.con.execute(f"""
                    INSERT OR IGNORE INTO fundamentals
                    SELECT
                        ticker,
                        CAST(period_end AS DATE),
                        CAST(filing_date AS DATE),
                        revenue, revenue_growth_yoy,
                        gross_profit, gross_margin,
                        operating_income, operating_margin,
                        net_income, fcf, fcf_positive,
                        total_cash, total_debt, total_equity,
                        de_ratio, cash_runway_quarters, rule_of_40,
                        shares_outstanding, eps,
                        operating_cash_flow, capex
                    FROM read_parquet('{ff.as_posix()}')
                """)
                count += 1
            except Exception as e:
                logger.warning(f"{ff.stem}: 로드 오류 — {e}")

        total = self.con.execute("SELECT COUNT(*) FROM fundamentals").fetchone()[0]
        logger.info(f"fundamentals 테이블 로드: {count}파일, {total:,}행")

    def load_features(self):
        """피처 Parquet을 features 테이블로 로드한다."""
        feat_path = config.FEATURES_DIR / "features_daily.parquet"
        if not feat_path.exists():
            logger.warning("features_daily.parquet 없음")
            return

        self.con.execute("DELETE FROM features")
        self.con.execute(f"""
            INSERT INTO features
            SELECT * FROM read_parquet('{feat_path.as_posix()}')
        """)

        total = self.con.execute("SELECT COUNT(*) FROM features").fetchone()[0]
        logger.info(f"features 테이블 로드: {total:,}행")

    def load_universe_snapshots(self):
        """유니버스 스냅샷을 로드한다."""
        snap_path = config.UNIVERSE_DIR / "universe_snapshots.parquet"
        if not snap_path.exists():
            logger.warning("universe_snapshots.parquet 없음")
            return

        self.con.execute("DELETE FROM universe_snapshots")
        self.con.execute(f"""
            INSERT INTO universe_snapshots
            SELECT CAST(date AS DATE), ticker
            FROM read_parquet('{snap_path.as_posix()}')
        """)

        total = self.con.execute("SELECT COUNT(*) FROM universe_snapshots").fetchone()[0]
        logger.info(f"universe_snapshots 테이블 로드: {total:,}행")

    def load_all(self):
        """모든 Parquet 데이터를 DuckDB로 로드한다."""
        self.init_schema()
        self.load_prices()
        self.load_fundamentals()
        self.load_features()
        self.load_universe_snapshots()

    # ──────────────────────────────────────────
    # 쿼리 유틸리티
    # ──────────────────────────────────────────

    def query(self, sql: str) -> pd.DataFrame:
        """SQL 쿼리를 실행하고 DataFrame으로 반환한다."""
        return self.con.execute(sql).df()

    def query_prices(
        self,
        tickers: list[str] = None,
        start: str = None,
        end: str = None,
    ) -> pd.DataFrame:
        """가격 데이터 조회."""
        sql = "SELECT * FROM prices WHERE 1=1"
        if tickers:
            ticker_list = ", ".join(f"'{t}'" for t in tickers)
            sql += f" AND ticker IN ({ticker_list})"
        if start:
            sql += f" AND date >= '{start}'"
        if end:
            sql += f" AND date <= '{end}'"
        sql += " ORDER BY ticker, date"
        return self.con.execute(sql).df()

    def query_features(
        self,
        tickers: list[str] = None,
        start: str = None,
        end: str = None,
    ) -> pd.DataFrame:
        """피처 데이터 조회."""
        sql = "SELECT * FROM features WHERE 1=1"
        if tickers:
            ticker_list = ", ".join(f"'{t}'" for t in tickers)
            sql += f" AND ticker IN ({ticker_list})"
        if start:
            sql += f" AND date >= '{start}'"
        if end:
            sql += f" AND date <= '{end}'"
        sql += " ORDER BY ticker, date"
        return self.con.execute(sql).df()

    def get_universe_at(self, date: str) -> list[str]:
        """특정 날짜의 유니버스 종목 리스트를 반환한다."""
        result = self.con.execute(f"""
            SELECT ticker
            FROM universe_snapshots
            WHERE date = '{date}'
        """).fetchall()
        return [r[0] for r in result]

    def get_table_stats(self) -> pd.DataFrame:
        """각 테이블의 행 수를 반환한다."""
        tables = ["prices", "fundamentals", "features", "universe_snapshots"]
        stats = []
        for t in tables:
            try:
                count = self.con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                stats.append({"table": t, "rows": count})
            except Exception:
                stats.append({"table": t, "rows": 0})
        return pd.DataFrame(stats)
