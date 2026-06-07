"""
Connect AI v5 §0 — 데이터 수집 모듈
====================================
Yahoo Finance(가격) + FMP(재무) 데이터를 수집하고 Parquet으로 저장한다.
Point-in-Time(PIT) 원칙을 준수한다.
"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import yfinance as yf
from tqdm import tqdm

import config

logger = logging.getLogger(__name__)
logging.basicConfig(level=config.LOG_LEVEL, format=config.LOG_FORMAT)


# ══════════════════════════════════════════════
# 수집 진행 상황 추적
# ══════════════════════════════════════════════

def _load_progress() -> dict:
    """수집 진행 상황 파일 로드."""
    if config.COLLECTION_TRACKING_FILE.exists():
        with open(config.COLLECTION_TRACKING_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"prices_done": [], "fundamentals_done": [], "last_update": None}


def _save_progress(progress: dict):
    """수집 진행 상황 저장."""
    progress["last_update"] = datetime.now().isoformat()
    with open(config.COLLECTION_TRACKING_FILE, "w", encoding="utf-8") as f:
        json.dump(progress, f, indent=2, ensure_ascii=False)


# ══════════════════════════════════════════════
# 종목 리스트 획득
# ══════════════════════════════════════════════

def get_nasdaq_nyse_tickers() -> pd.DataFrame:
    """
    NASDAQ/NYSE 전체 종목 리스트를 수집한다.

    우선순위:
      1. nasdaq.com 스크리너 API (무료, ~6,000종목 — 기본)
      2. FMP stock-list (유료 전용, 402면 건너뜀)
      3. 내장 성장주 유니버스 (최후 폴백, 135종목)

    Returns:
        DataFrame[ticker, name, exchange, sector, market_cap]
        시총 $300M 이상 미국 보통주만 포함
    """
    # 1순위: nasdaq.com (무료, 전체 시장)
    df = _get_tickers_from_nasdaq()
    if not df.empty:
        return df

    # 2순위: FMP (유료 플랜 보유 시)
    if config.FMP_API_KEY:
        df = _get_tickers_from_fmp()
        if not df.empty:
            return df

    # 최후 폴백: 내장 유니버스
    logger.warning("모든 종목 리스트 수집 실패 → 내장 성장주 유니버스(135종목) 사용")
    return _get_builtin_growth_universe()


def _get_tickers_from_nasdaq() -> pd.DataFrame:
    """
    nasdaq.com 스크리너 API로 NASDAQ/NYSE 전체 종목을 수집한다.
    무료, 인증 불필요. 시총 $300M 이상 미국 보통주 필터 적용.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
    }

    all_rows = []
    for exchange in ["NASDAQ", "NYSE"]:
        url = (
            "https://api.nasdaq.com/api/screener/stocks"
            f"?tableonly=true&exchange={exchange}&download=true"
        )
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            rows = data.get("data", {}).get("rows", [])
            if rows:
                all_rows.extend(rows)
                logger.info("%s: %d종목 수집", exchange, len(rows))
        except Exception as e:
            logger.warning("nasdaq.com %s 수집 실패: %s", exchange, e)

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)

    # 컬럼 정규화
    df = df.rename(columns={
        "symbol":    "ticker",
        "name":      "name",
        "sector":    "sector",
        "marketCap": "market_cap_str",
    })

    # 시총 숫자 변환
    def _parse_market_cap(val) -> float:
        try:
            return float(str(val).replace(",", "").replace("$", ""))
        except Exception:
            return 0.0

    df["market_cap"] = df["market_cap_str"].apply(_parse_market_cap)

    # 필터: 시총 $300M 이상, 미국 주식, 티커에 특수문자 없는 보통주
    df = df[
        (df["market_cap"] >= config.MIN_MARKET_CAP) &
        (df["ticker"].str.match(r"^[A-Z]{1,5}$", na=False))
    ].copy()

    # 필요 컬럼 정리
    keep = ["ticker", "name", "sector", "market_cap"]
    for col in keep:
        if col not in df.columns:
            df[col] = ""
    df = df[keep].drop_duplicates("ticker").reset_index(drop=True)

    logger.info(
        "nasdaq.com 유니버스 완성: %d종목 (시총 $300M+ 보통주)", len(df)
    )
    return df


def _get_tickers_from_fmp() -> pd.DataFrame:
    """FMP stock-list API로 NASDAQ/NYSE 종목을 수집한다.
    402(유료 전용) 응답 시 빈 DataFrame 반환.
    """
    url = f"{config.FMP_BASE_URL}/stock-list"
    params = {"apikey": config.FMP_API_KEY}

    logger.info("FMP에서 종목 리스트 수집 시도...")
    try:
        resp = requests.get(url, params=params, timeout=30)
        if resp.status_code == 402:
            logger.info("FMP stock-list 유료 전용(402) — 건너뜀")
            return pd.DataFrame()
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        logger.warning("FMP 종목 리스트 실패(%s)", e)
        return pd.DataFrame()

    data = resp.json()
    if not data:
        return pd.DataFrame()

    df = pd.DataFrame(data)
    # NASDAQ/NYSE 필터 + 보통주만
    mask = (
        df["exchangeShortName"].isin(["NASDAQ", "NYSE"]) &
        df["type"].eq("stock")
    )
    df = df.loc[mask, ["symbol", "name", "exchangeShortName"]].copy()
    df.columns = ["ticker", "name", "exchange"]

    logger.info(f"FMP 종목 리스트: {len(df)}종목 (NASDAQ/NYSE)")
    return df


def _get_builtin_growth_universe() -> pd.DataFrame:
    """
    내장 성장주 유니버스. Connect AI v5 전략에 해당하는
    기술·헬스케어·우주·양자·AI 등 성장 섹터 종목을 포함한다.
    + 주요 대형주를 포함해 충분한 유니버스를 구성한다.
    """
    tickers_data = [
        # === AI / Cloud / Software ===
        ("PLTR", "Palantir Technologies", "NYSE", "Technology"),
        ("AI", "C3.ai", "NYSE", "Technology"),
        ("SNOW", "Snowflake", "NYSE", "Technology"),
        ("DDOG", "Datadog", "NASDAQ", "Technology"),
        ("NET", "Cloudflare", "NYSE", "Technology"),
        ("CRWD", "CrowdStrike", "NASDAQ", "Technology"),
        ("ZS", "Zscaler", "NASDAQ", "Technology"),
        ("MDB", "MongoDB", "NASDAQ", "Technology"),
        ("CFLT", "Confluent", "NASDAQ", "Technology"),
        ("S", "SentinelOne", "NYSE", "Technology"),
        ("BILL", "BILL Holdings", "NYSE", "Technology"),
        ("MNDY", "monday.com", "NASDAQ", "Technology"),
        ("GTLB", "GitLab", "NASDAQ", "Technology"),
        ("PATH", "UiPath", "NYSE", "Technology"),
        ("DOCN", "DigitalOcean", "NYSE", "Technology"),
        ("ESTC", "Elastic", "NYSE", "Technology"),
        ("HUBS", "HubSpot", "NYSE", "Technology"),
        ("SHOP", "Shopify", "NYSE", "Technology"),
        ("TTD", "The Trade Desk", "NASDAQ", "Technology"),
        ("ADSK", "Autodesk", "NASDAQ", "Technology"),
        ("PANW", "Palo Alto Networks", "NASDAQ", "Technology"),
        ("FTNT", "Fortinet", "NASDAQ", "Technology"),
        ("TEAM", "Atlassian", "NASDAQ", "Technology"),
        ("NOW", "ServiceNow", "NYSE", "Technology"),
        ("WDAY", "Workday", "NASDAQ", "Technology"),
        ("TWLO", "Twilio", "NYSE", "Technology"),
        ("OKTA", "Okta", "NASDAQ", "Technology"),
        ("U", "Unity Software", "NYSE", "Technology"),
        ("APP", "AppLovin", "NASDAQ", "Technology"),
        ("RDDT", "Reddit", "NYSE", "Technology"),
        ("DUOL", "Duolingo", "NASDAQ", "Technology"),
        ("SAMSARA", "Samsara", "NYSE", "Technology"),

        # === Semiconductor / Hardware ===
        ("NVDA", "NVIDIA", "NASDAQ", "Semiconductors"),
        ("AMD", "AMD", "NASDAQ", "Semiconductors"),
        ("AVGO", "Broadcom", "NASDAQ", "Semiconductors"),
        ("ARM", "Arm Holdings", "NASDAQ", "Semiconductors"),
        ("SMCI", "Super Micro Computer", "NASDAQ", "Semiconductors"),
        ("MRVL", "Marvell Technology", "NASDAQ", "Semiconductors"),
        ("ANET", "Arista Networks", "NYSE", "Semiconductors"),
        ("IONQ", "IonQ", "NYSE", "Quantum"),
        ("RGTI", "Rigetti Computing", "NASDAQ", "Quantum"),
        ("QBTS", "D-Wave Quantum", "NYSE", "Quantum"),
        ("TSM", "TSMC", "NYSE", "Semiconductors"),
        ("ASML", "ASML", "NASDAQ", "Semiconductors"),
        ("KLAC", "KLA Corporation", "NASDAQ", "Semiconductors"),
        ("LRCX", "Lam Research", "NASDAQ", "Semiconductors"),
        ("ON", "ON Semiconductor", "NASDAQ", "Semiconductors"),

        # === Space / Defense ===
        ("RKLB", "Rocket Lab", "NASDAQ", "Space"),
        ("ASTS", "AST SpaceMobile", "NASDAQ", "Space"),
        ("LUNR", "Intuitive Machines", "NASDAQ", "Space"),
        ("RDW", "Redwire", "NYSE", "Space"),
        ("BKSY", "BlackSky Technology", "NYSE", "Space"),
        ("PL", "Planet Labs", "NYSE", "Space"),
        ("MNTS", "Momentus", "NASDAQ", "Space"),
        ("LMT", "Lockheed Martin", "NYSE", "Defense"),
        ("NOC", "Northrop Grumman", "NYSE", "Defense"),
        ("BA", "Boeing", "NYSE", "Defense"),

        # === EV / Energy / Clean Tech ===
        ("TSLA", "Tesla", "NASDAQ", "EV"),
        ("RIVN", "Rivian", "NASDAQ", "EV"),
        ("LCID", "Lucid Group", "NASDAQ", "EV"),
        ("ENPH", "Enphase Energy", "NASDAQ", "Energy"),
        ("SEDG", "SolarEdge", "NASDAQ", "Energy"),
        ("FSLR", "First Solar", "NASDAQ", "Energy"),
        ("RUN", "Sunrun", "NASDAQ", "Energy"),
        ("PLUG", "Plug Power", "NASDAQ", "Energy"),
        ("BE", "Bloom Energy", "NYSE", "Energy"),
        ("CHPT", "ChargePoint", "NYSE", "Energy"),
        ("NEE", "NextEra Energy", "NYSE", "Energy"),

        # === Biotech / Healthcare ===
        ("MRNA", "Moderna", "NASDAQ", "Healthcare"),
        ("CRSP", "CRISPR Therapeutics", "NASDAQ", "Healthcare"),
        ("BEAM", "Beam Therapeutics", "NASDAQ", "Healthcare"),
        ("NTLA", "Intellia Therapeutics", "NASDAQ", "Healthcare"),
        ("DXCM", "DexCom", "NASDAQ", "Healthcare"),
        ("ISRG", "Intuitive Surgical", "NASDAQ", "Healthcare"),
        ("VEEV", "Veeva Systems", "NYSE", "Healthcare"),
        ("EXAS", "Exact Sciences", "NASDAQ", "Healthcare"),
        ("HIMS", "Hims & Hers Health", "NYSE", "Healthcare"),
        ("DOCS", "Doximity", "NYSE", "Healthcare"),

        # === Fintech / Payments ===
        ("SQ", "Block (Square)", "NYSE", "Fintech"),
        ("AFRM", "Affirm", "NASDAQ", "Fintech"),
        ("SOFI", "SoFi Technologies", "NASDAQ", "Fintech"),
        ("COIN", "Coinbase", "NASDAQ", "Fintech"),
        ("HOOD", "Robinhood", "NASDAQ", "Fintech"),
        ("NU", "Nu Holdings", "NYSE", "Fintech"),
        ("PYPL", "PayPal", "NASDAQ", "Fintech"),
        ("FI", "Fiserv", "NYSE", "Fintech"),
        ("TOST", "Toast", "NYSE", "Fintech"),

        # === E-Commerce / Consumer ===
        ("MELI", "MercadoLibre", "NASDAQ", "E-Commerce"),
        ("SE", "Sea Limited", "NYSE", "E-Commerce"),
        ("ETSY", "Etsy", "NASDAQ", "E-Commerce"),
        ("PINS", "Pinterest", "NYSE", "E-Commerce"),
        ("SNAP", "Snap", "NYSE", "E-Commerce"),
        ("RBLX", "Roblox", "NYSE", "E-Commerce"),
        ("ABNB", "Airbnb", "NASDAQ", "E-Commerce"),
        ("UBER", "Uber", "NYSE", "E-Commerce"),
        ("LYFT", "Lyft", "NASDAQ", "E-Commerce"),
        ("DASH", "DoorDash", "NASDAQ", "E-Commerce"),
        ("CPNG", "Coupang", "NYSE", "E-Commerce"),

        # === Mega Cap Tech (벤치마크 + 유니버스 구성) ===
        ("AAPL", "Apple", "NASDAQ", "Technology"),
        ("MSFT", "Microsoft", "NASDAQ", "Technology"),
        ("GOOGL", "Alphabet", "NASDAQ", "Technology"),
        ("AMZN", "Amazon", "NASDAQ", "Technology"),
        ("META", "Meta Platforms", "NASDAQ", "Technology"),
        ("NFLX", "Netflix", "NASDAQ", "Technology"),

        # === Robotics / Industrial Tech ===
        ("AXON", "Axon Enterprise", "NASDAQ", "Technology"),
        ("TER", "Teradyne", "NASDAQ", "Technology"),
        ("UPST", "Upstart", "NASDAQ", "Fintech"),

        # === Data / Analytics ===
        ("DOMO", "Domo", "NASDAQ", "Technology"),
        ("DT", "Dynatrace", "NYSE", "Technology"),
        ("BRZE", "Braze", "NASDAQ", "Technology"),
        ("IOT", "Samsara Inc", "NYSE", "Technology"),
        ("CELH", "Celsius Holdings", "NASDAQ", "Consumer"),
        ("GRAB", "Grab Holdings", "NASDAQ", "Technology"),
        ("FOUR", "Shift4 Payments", "NYSE", "Fintech"),
        ("GCT", "GigaCloud Technology", "NASDAQ", "E-Commerce"),
        ("CAVA", "Cava Group", "NYSE", "Consumer"),
        ("TMDX", "TransMedics Group", "NASDAQ", "Healthcare"),
        ("CELH", "Celsius Holdings", "NASDAQ", "Consumer"),

        # === Additional Growth / Mid-cap ===
        ("ROKU", "Roku", "NASDAQ", "Technology"),
        ("ZI", "ZoomInfo", "NASDAQ", "Technology"),
        ("DKNG", "DraftKings", "NASDAQ", "Technology"),
        ("MGNI", "Magnite", "NASDAQ", "Technology"),
        ("PUBM", "PubMatic", "NASDAQ", "Technology"),
        ("SKLZ", "Skillz", "NYSE", "Technology"),
        ("OPEN", "Opendoor", "NASDAQ", "Technology"),
        ("VRTX", "Vertex Pharmaceuticals", "NASDAQ", "Healthcare"),
        ("REGN", "Regeneron", "NASDAQ", "Healthcare"),
        ("LLY", "Eli Lilly", "NYSE", "Healthcare"),
        ("AMGN", "Amgen", "NASDAQ", "Healthcare"),
        ("GILD", "Gilead Sciences", "NASDAQ", "Healthcare"),
        ("BIIB", "Biogen", "NASDAQ", "Healthcare"),
        ("ELF", "e.l.f. Beauty", "NYSE", "Consumer"),
        ("LULU", "Lululemon", "NASDAQ", "Consumer"),
        ("DECK", "Deckers Outdoor", "NYSE", "Consumer"),
        ("ONON", "On Holding", "NYSE", "Consumer"),
        ("BIRK", "Birkenstock", "NYSE", "Consumer"),
    ]

    # 중복 제거
    seen = set()
    unique = []
    for row in tickers_data:
        if row[0] not in seen:
            seen.add(row[0])
            unique.append(row)

    df = pd.DataFrame(unique, columns=["ticker", "name", "exchange", "sector"])
    logger.info(f"내장 유니버스: {len(df)}종목")
    return df


# ══════════════════════════════════════════════
# Yahoo Finance — 가격 데이터 수집
# ══════════════════════════════════════════════

def collect_price_data(
    tickers: list[str],
    start: str = config.BACKTEST_START,
    end: str = config.BACKTEST_END,
    force: bool = False,
) -> dict[str, pd.DataFrame]:
    """
    yfinance로 OHLCV 데이터를 수집하고 종목별 Parquet으로 저장한다.

    Args:
        tickers: 종목 리스트
        start: 시작일 (YYYY-MM-DD)
        end: 종료일 (YYYY-MM-DD)
        force: True이면 이미 수집된 종목도 재수집

    Returns:
        {ticker: DataFrame} 딕셔너리
    """
    progress = _load_progress()
    results = {}

    # 이미 수집된 종목 건너뛰기
    if not force:
        remaining = [t for t in tickers if t not in progress["prices_done"]]
        skipped = len(tickers) - len(remaining)
        if skipped > 0:
            logger.info(f"이미 수집된 {skipped}종목 건너뜀")
        tickers = remaining

    if not tickers:
        logger.info("수집할 종목 없음 — 모두 완료")
        return results

    # 배치 단위 다운로드
    total_batches = (len(tickers) + config.YFINANCE_BATCH_SIZE - 1) // config.YFINANCE_BATCH_SIZE
    logger.info(f"가격 데이터 수집 시작: {len(tickers)}종목, {total_batches}배치")

    for i in range(0, len(tickers), config.YFINANCE_BATCH_SIZE):
        batch = tickers[i : i + config.YFINANCE_BATCH_SIZE]
        batch_num = i // config.YFINANCE_BATCH_SIZE + 1
        logger.info(f"배치 {batch_num}/{total_batches}: {len(batch)}종목 다운로드 중...")

        try:
            data = yf.download(
                tickers=batch,
                start=start,
                end=end,
                interval="1d",
                auto_adjust=True,
                group_by="ticker",
                threads=True,
                progress=False,
            )

            if data.empty:
                logger.warning(f"배치 {batch_num}: 데이터 없음")
                continue

            # 종목별 분리 및 저장
            for ticker in batch:
                try:
                    if len(batch) == 1:
                        df = data.copy()
                    else:
                        if ticker not in data.columns.get_level_values(0):
                            logger.warning(f"{ticker}: 데이터 없음, 건너뜀")
                            continue
                        df = data[ticker].copy()

                    df = df.dropna(subset=["Close"])
                    if df.empty or len(df) < 60:  # 최소 3개월 데이터
                        logger.warning(f"{ticker}: 데이터 부족 ({len(df)}행), 건너뜀")
                        continue

                    # 컬럼 정리
                    df.columns = [c.lower() for c in df.columns]
                    df.index.name = "date"
                    df = df.reset_index()
                    df["ticker"] = ticker

                    # Parquet 저장
                    path = config.PRICES_DIR / f"{ticker}.parquet"
                    df.to_parquet(path, index=False, engine="pyarrow")
                    results[ticker] = df

                    # 진행 상황 기록
                    if ticker not in progress["prices_done"]:
                        progress["prices_done"].append(ticker)

                except Exception as e:
                    logger.warning(f"{ticker}: 처리 오류 — {e}")

            _save_progress(progress)

        except Exception as e:
            logger.error(f"배치 {batch_num} 다운로드 오류: {e}")

    logger.info(f"가격 수집 완료: {len(results)}종목 성공")
    return results


def collect_spy_qqq_data(
    start: str = config.BACKTEST_START,
    end: str = config.BACKTEST_END,
) -> dict[str, pd.DataFrame]:
    """SPY/QQQ 벤치마크 가격을 수집한다."""
    logger.info("벤치마크(SPY, QQQ) 수집 중...")
    results = {}

    for ticker in config.BENCHMARKS:
        data = yf.download(
            ticker, start=start, end=end,
            auto_adjust=True, progress=False,
        )
        if data.empty:
            logger.error(f"{ticker} 벤치마크 수집 실패")
            continue

        data.columns = [c.lower() if isinstance(c, str) else c[0].lower() for c in data.columns]
        data.index.name = "date"
        data = data.reset_index()
        data["ticker"] = ticker

        path = config.PRICES_DIR / f"{ticker}.parquet"
        data.to_parquet(path, index=False, engine="pyarrow")
        results[ticker] = data
        logger.info(f"{ticker}: {len(data)}행 수집 완료")

    return results


# ══════════════════════════════════════════════
# FMP — 재무 데이터 수집
# ══════════════════════════════════════════════

class FMPDailyLimitExceeded(Exception):
    """FMP 일일 API 한도 초과 시 발생."""
    pass


def _fmp_request(endpoint: str, params: dict = None) -> list | dict | None:
    """FMP API 요청 헬퍼. 레이트 리밋 및 일일 한도 초과 감지."""
    if not config.FMP_API_KEY:
        logger.error("FMP API 키가 설정되지 않음.")
        return None

    url = f"{config.FMP_BASE_URL}/{endpoint}"
    p = {"apikey": config.FMP_API_KEY}
    if params:
        p.update(params)

    time.sleep(config.FMP_RATE_LIMIT_DELAY)

    try:
        resp = requests.get(url, params=p, timeout=30)

        # 일일 한도 초과 — 즉시 중단
        if resp.status_code == 429:
            raise FMPDailyLimitExceeded(
                "FMP 일일 API 한도 초과 (429). "
                "오늘 수집은 여기서 중단합니다. "
                "내일 다시 실행하면 이어서 수집됩니다."
            )

        # 결제 필요 (유료 엔드포인트)
        if resp.status_code == 402:
            logger.warning("FMP 402: 유료 플랜 전용 엔드포인트 — %s", endpoint)
            return None

        resp.raise_for_status()
        return resp.json()

    except FMPDailyLimitExceeded:
        raise  # 상위로 전파
    except requests.RequestException as e:
        logger.warning("FMP 요청 실패: %s — %s", endpoint, e)
        return None


def collect_fundamentals(
    tickers: list[str],
    force: bool = False,
) -> dict[str, pd.DataFrame]:
    """
    FMP에서 재무제표(Income Statement + Balance Sheet + Cash Flow)를 수집한다.
    Point-in-Time: fillingDate 기준으로 유효화.

    Args:
        tickers: 종목 리스트
        force: True이면 이미 수집된 종목도 재수집

    Returns:
        {ticker: DataFrame} 딕셔너리
    """
    if not config.FMP_API_KEY:
        logger.error("FMP API 키 없음 — 재무 데이터 수집 불가")
        logger.info("https://site.financialmodelingprep.com/register 에서 무료 가입 후 키 발급")
        return {}

    progress = _load_progress()
    results = {}

    if not force:
        remaining = [t for t in tickers if t not in progress["fundamentals_done"]]
        skipped = len(tickers) - len(remaining)
        if skipped > 0:
            logger.info(f"재무 이미 수집된 {skipped}종목 건너뜀")
        tickers = remaining

    if not tickers:
        logger.info("재무 수집할 종목 없음")
        return results

    # API 콜 수 계산 (종목당 3콜: income, balance, cashflow)
    api_calls_needed = len(tickers) * 3
    if api_calls_needed > config.FMP_DAILY_LIMIT:
        max_today = config.FMP_DAILY_LIMIT // 3
        logger.warning(
            f"일일 한도 {config.FMP_DAILY_LIMIT}콜 초과 예상. "
            f"오늘은 {max_today}종목만 수집 (나머지 {len(tickers)-max_today}종목은 내일)"
        )
        tickers = tickers[:max_today]

    logger.info(f"재무 데이터 수집 시작: {len(tickers)}종목 (API 콜 ~{len(tickers)*3})")

    collected = 0
    for ticker in tqdm(tickers, desc="재무 수집"):
        try:
            fund_df = _collect_single_fundamental(ticker)
            if fund_df is not None and not fund_df.empty:
                path = config.FUNDAMENTALS_DIR / f"{ticker}.parquet"
                fund_df.to_parquet(path, index=False, engine="pyarrow")
                results[ticker] = fund_df
                collected += 1

                if ticker not in progress["fundamentals_done"]:
                    progress["fundamentals_done"].append(ticker)
                _save_progress(progress)

        except FMPDailyLimitExceeded as e:
            # 일일 한도 초과 — 진행 상황 저장 후 즉시 중단
            _save_progress(progress)
            remaining_count = len(tickers) - collected
            logger.warning(
                "\n" + "="*60 + "\n"
                "FMP 일일 API 한도(250콜) 초과\n"
                "오늘 수집: %d종목 완료\n"
                "남은 종목: %d종목 (내일 재실행 시 자동으로 이어서 수집)\n"
                "재실행 명령: py main.py --collect-fundamentals\n"
                + "="*60,
                collected, remaining_count,
            )
            break

        except Exception as e:
            logger.warning("%s: 재무 수집 오류 — %s", ticker, e)

    logger.info("재무 수집 완료: %d종목 성공 (누적 완료: %d종목)",
                collected, len(progress["fundamentals_done"]))
    return results


def _collect_single_fundamental(ticker: str) -> pd.DataFrame | None:
    """단일 종목의 재무제표 3종을 합쳐서 반환한다."""

    # 1. Income Statement
    income = _fmp_request(f"income-statement/{ticker}", {"period": "quarterly"})
    if not income:
        return None

    # 2. Balance Sheet
    balance = _fmp_request(f"balance-sheet-statement/{ticker}", {"period": "quarterly"})

    # 3. Cash Flow
    cashflow = _fmp_request(f"cash-flow-statement/{ticker}", {"period": "quarterly"})

    # 데이터 병합
    rows = []
    for item in income:
        row = {
            "ticker": ticker,
            "period_end": item.get("date"),
            "filing_date": item.get("fillingDate") or item.get("acceptedDate"),
            "revenue": item.get("revenue"),
            "gross_profit": item.get("grossProfit"),
            "operating_income": item.get("operatingIncome"),
            "net_income": item.get("netIncome"),
            "eps": item.get("eps"),
            "shares_outstanding": item.get("weightedAverageShsOut"),
        }

        # Margin 계산
        rev = row["revenue"]
        if rev and rev > 0:
            row["gross_margin"] = (row["gross_profit"] or 0) / rev
            row["operating_margin"] = (row["operating_income"] or 0) / rev
        else:
            row["gross_margin"] = None
            row["operating_margin"] = None

        # Balance Sheet 매칭 (같은 기간)
        if balance:
            bs = next(
                (b for b in balance if b.get("date") == item.get("date")),
                {},
            )
            row["total_cash"] = (
                bs.get("cashAndCashEquivalents", 0) or 0
            ) + (bs.get("shortTermInvestments", 0) or 0)
            row["total_debt"] = (
                (bs.get("shortTermDebt", 0) or 0) +
                (bs.get("longTermDebt", 0) or 0)
            )
            total_equity = bs.get("totalStockholdersEquity")
            row["total_equity"] = total_equity
            if total_equity and total_equity > 0:
                row["de_ratio"] = row["total_debt"] / total_equity
            else:
                row["de_ratio"] = None

        # Cash Flow 매칭
        if cashflow:
            cf = next(
                (c for c in cashflow if c.get("date") == item.get("date")),
                {},
            )
            row["operating_cash_flow"] = cf.get("operatingCashFlow")
            row["capex"] = cf.get("capitalExpenditure")
            ocf = cf.get("operatingCashFlow", 0) or 0
            capex = cf.get("capitalExpenditure", 0) or 0
            row["fcf"] = ocf + capex  # capex는 보통 음수

        rows.append(row)

    if not rows:
        return None

    df = pd.DataFrame(rows)
    df["period_end"] = pd.to_datetime(df["period_end"])
    df["filing_date"] = pd.to_datetime(df["filing_date"])
    df = df.sort_values("period_end").reset_index(drop=True)

    # YoY 매출성장률 계산 (4분기 전 대비)
    df["revenue_growth_yoy"] = df["revenue"].pct_change(4)

    # Cash Runway 계산
    df["cash_runway_quarters"] = np.where(
        df["fcf"] < 0,
        df["total_cash"] / df["fcf"].abs(),
        np.inf,  # FCF 흑자면 무한
    )
    df["cash_runway_quarters"] = df["cash_runway_quarters"].replace([np.inf], 99)

    # Rule of 40
    df["rule_of_40"] = (df["revenue_growth_yoy"] * 100) + (df["operating_margin"] * 100)

    # FCF 상태
    df["fcf_positive"] = np.where(
        df["fcf"] > 0, 1.0,
        np.where(df["fcf"].shift(1) < 0, 0.5, 0.0)  # 전환중 = 0.5
    )

    return df


# ══════════════════════════════════════════════
# 유니버스 스냅샷 생성
# ══════════════════════════════════════════════

def build_universe_snapshots() -> pd.DataFrame:
    """
    각 리밸런싱 시점에서의 유니버스 스냅샷을 생성한다.
    조건: 시총 >= $300M, 20일 평균 거래량 >= 50만주, 가격 데이터 6개월+

    Returns:
        DataFrame[date, ticker] — 해당 날짜에 유니버스에 포함된 종목
    """
    logger.info("유니버스 스냅샷 생성 중...")

    # 모든 가격 파일 로드
    price_files = list(config.PRICES_DIR.glob("*.parquet"))
    if not price_files:
        logger.error("가격 데이터 없음 — 먼저 collect_price_data 실행")
        return pd.DataFrame()

    all_prices = []
    for pf in tqdm(price_files, desc="가격 파일 로드"):
        ticker = pf.stem
        if ticker in config.BENCHMARKS:
            continue
        try:
            df = pd.read_parquet(pf)
            df["date"] = pd.to_datetime(df["date"])
            all_prices.append(df[["date", "ticker", "close", "volume"]].copy())
        except Exception as e:
            logger.warning(f"{ticker}: 로드 오류 — {e}")

    if not all_prices:
        return pd.DataFrame()

    prices = pd.concat(all_prices, ignore_index=True)
    prices = prices.sort_values(["ticker", "date"])

    # 20일 평균 거래량 계산
    prices["avg_vol_20d"] = (
        prices.groupby("ticker")["volume"]
        .transform(lambda x: x.rolling(20, min_periods=10).mean())
    )

    # 리밸런싱 날짜 생성 (매주 금요일)
    date_range = pd.date_range(
        start=config.BACKTEST_START,
        end=config.BACKTEST_END,
        freq=config.REBALANCE_FREQ,
    )

    snapshots = []
    for rebal_date in tqdm(date_range, desc="유니버스 스냅샷"):
        # 해당 날짜까지의 데이터만 사용
        mask = prices["date"] <= rebal_date
        current = prices.loc[mask].groupby("ticker").last()

        if current.empty:
            continue

        # 최소 6개월(126일) 데이터 존재 확인
        data_start = prices.loc[mask].groupby("ticker")["date"].min()
        data_length = (rebal_date - data_start).dt.days
        has_enough_data = data_length >= 126

        # 유니버스 조건 필터 (시총은 yfinance에서 직접 얻기 어려우므로
        # 거래량 기준만 일단 적용, 시총은 FMP 데이터가 있을 때 보강)
        universe_mask = (
            (current["avg_vol_20d"] >= config.MIN_AVG_VOLUME) &
            has_enough_data
        )

        valid_tickers = current.index[universe_mask].tolist()

        for t in valid_tickers:
            snapshots.append({"date": rebal_date, "ticker": t})

    snapshot_df = pd.DataFrame(snapshots)

    if not snapshot_df.empty:
        path = config.UNIVERSE_DIR / "universe_snapshots.parquet"
        snapshot_df.to_parquet(path, index=False, engine="pyarrow")
        logger.info(
            f"유니버스 스냅샷 생성 완료: {len(date_range)}시점, "
            f"평균 {len(snapshot_df) / max(len(date_range), 1):.0f}종목/시점"
        )

    return snapshot_df


# ══════════════════════════════════════════════
# 통합 데이터 로드 유틸
# ══════════════════════════════════════════════

def load_all_prices() -> pd.DataFrame:
    """저장된 모든 가격 Parquet을 하나의 DataFrame으로 로드한다."""
    files = list(config.PRICES_DIR.glob("*.parquet"))
    if not files:
        return pd.DataFrame()

    dfs = []
    for f in files:
        df = pd.read_parquet(f)
        dfs.append(df)

    combined = pd.concat(dfs, ignore_index=True)
    combined["date"] = pd.to_datetime(combined["date"])
    return combined.sort_values(["ticker", "date"]).reset_index(drop=True)


def load_all_fundamentals() -> pd.DataFrame:
    """저장된 모든 재무 Parquet을 하나의 DataFrame으로 로드한다."""
    files = list(config.FUNDAMENTALS_DIR.glob("*.parquet"))
    if not files:
        return pd.DataFrame()

    dfs = []
    for f in files:
        df = pd.read_parquet(f)
        dfs.append(df)

    combined = pd.concat(dfs, ignore_index=True)
    combined["period_end"] = pd.to_datetime(combined["period_end"])
    combined["filing_date"] = pd.to_datetime(combined["filing_date"])
    return combined.sort_values(["ticker", "period_end"]).reset_index(drop=True)
