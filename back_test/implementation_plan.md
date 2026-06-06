# Connect AI v5 §0 백테스트 검증 시스템 구현 계획

## 배경

v5 설계 문서의 §0 "과거 백테스트(검증)"를 구현한다. 점수 가중치가 *느낌*이 아니라 *예측력*에 근거하도록 만드는 것이 목적이다. 이 단계를 통과하기 전까지 시스템은 "가설"이며, 라이브 운용을 시작하지 않는다.

### 1차 MVP 범위

| 포함 | 제외 (2단계) |
|------|-------------|
| Yahoo Finance (가격/기술 팩터) | SEC 13F (기관보유율) |
| FMP 무료 플랜 (재무 팩터) | Dataroma (슈퍼인베스터) |
| DuckDB + Parquet (저장) | Deep Analysis (LLM) |
| vectorbt (포트폴리오 시뮬레이션) | 텔레그램 알림 |
| alphalens-reloaded (팩터 IC 분석) | |
| scipy (통계 검정) | |

> [!IMPORTANT]
> FMP 무료 플랜 제약: API 콜 250회/일, 재무제표 ~4년. 유니버스 전체를 한 번에 수집하기 어려우므로, **수집 → 캐싱 → 증분 업데이트** 전략을 사용한다. 초기 수집은 여러 날에 걸쳐 진행될 수 있다.

---

## 🔧 사용자 정의 필요 파라미터 (구현 전 확인)

v5 설계 문서에 `🔧 사용자 정의 필요`로 표시된 값들은 **백테스트 결과가 나온 뒤 확정**하는 것이 원칙이다. 코드에는 `None` + `# 🔧 사용자 정의 필요` 주석으로 둔다.

| 파라미터 | 설명 | 코드 위치 |
|----------|------|-----------|
| `IC_THRESHOLD` | 팩터 IC 합격 임계값 | `factor_validator.py` |
| `BAND_HIGH` / `BAND_MID` | Conviction 상/중/하 밴드 경계 | 2단계 (이번 MVP 범위 밖) |
| `CAUTION_MULT` / `CAUTION_SCORE_REQ` | 레짐 CAUTION 배율/점수 | 2단계 |
| `HARD_STOP_PCT` / `MA50_VOL_MULT` / `TRAILING_STOP_PCT` | 가격 손절 파라미터 | 2단계 |
| `THEME_CAP` / `SECTOR_CAP` | 테마/섹터 비중 상한 | 2단계 |

> 이번 MVP에서 직접 사용하는 `IC_THRESHOLD`는 백테스트 결과를 본 뒤 사용자에게 질문할 예정이다.

---

## Proposed Changes

### 프로젝트 구조

```
back_test/
├── config.py                 # 설정, API 키, 경로, 상수
├── data_collector.py         # Yahoo/FMP 데이터 수집 → Parquet
├── db_manager.py             # DuckDB 테이블 생성/관리
├── feature_engine.py         # 팩터 피처 생성 (가격 + 재무)
├── factor_validator.py       # IC 계산, 분위 수익률, 통계 검정
├── backtest_engine.py        # vectorbt 포트폴리오 시뮬레이션
├── report_generator.py       # 검증 결과 HTML 보고서
├── main.py                   # CLI 진입점
├── requirements.txt          # 의존성
├── data/                     # 데이터 저장소
│   ├── raw/                  # 원천 데이터
│   │   ├── prices/           # Yahoo OHLCV Parquet (종목별)
│   │   └── fundamentals/     # FMP 재무 Parquet (종목별)
│   ├── features/             # 가공된 피처 테이블
│   │   └── features_daily.parquet
│   └── universe/             # 시점별 유니버스 스냅샷
│       └── universe_snapshots.parquet
├── results/                  # 검증 결과
│   ├── ic_results/           # 팩터별 IC 시계열
│   ├── quintile_returns/     # 분위별 수익률
│   └── reports/              # HTML 보고서
└── connect_ai.duckdb         # DuckDB 영구 저장소
```

---

### 1. config.py [NEW]

설정 파일. 모든 경로, API 키, 백테스트 파라미터를 중앙 관리한다.

```python
# 핵심 설정
BACKTEST_START = "2018-01-01"
BACKTEST_END = "2025-12-31"
MIN_MARKET_CAP = 300_000_000      # $300M
MIN_AVG_VOLUME = 500_000          # 50만주
REBALANCE_FREQ = "W-FRI"          # 매주 금요일 리밸런싱
FORWARD_PERIODS = [20, 60, 120]   # 4주, 12주, 24주 (영업일)
N_QUANTILES = 5                   # 분위 수

# FMP API
FMP_API_KEY = None  # 🔧 사용자 입력 필요
FMP_DAILY_LIMIT = 250
FMP_BASE_URL = "https://financialmodelingprep.com/stable"

# 경로
DATA_DIR = "./data"
RESULTS_DIR = "./results"
DB_PATH = "./connect_ai.duckdb"

# 팩터 IC 합격 임계값
IC_THRESHOLD = None  # 🔧 사용자 정의 필요: 백테스트 결과 확인 후 확정
```

---

### 2. data_collector.py [NEW]

Yahoo Finance와 FMP에서 데이터를 수집하고 Parquet으로 저장한다.

#### 핵심 기능

| 함수 | 역할 |
|------|------|
| `collect_price_data(tickers, start, end)` | yfinance로 OHLCV 수집 → `data/raw/prices/` Parquet 저장 |
| `collect_spy_qqq_data(start, end)` | SPY/QQQ 벤치마크 가격 수집 (RS, 레짐 계산용) |
| `collect_fundamentals(tickers)` | FMP income-statement, balance-sheet, cash-flow 수집 |
| `build_universe_snapshots()` | 시점별 유니버스(시총 $300M+, 거래량 50만+) 스냅샷 생성 |
| `get_nasdaq_nyse_tickers()` | 현재 NASDAQ/NYSE 종목 리스트 수집 (FMP stock-screener 또는 CSV) |

#### FMP 무료 플랜 대응 전략

```
1. 하루 250콜 제한 → 종목을 배치로 나눠 며칠에 걸쳐 수집
2. 수집 진행 상황을 tracking 파일로 기록
3. 이미 수집된 종목은 건너뛰기 (증분 수집)
4. 재무제표 4년 제한 → 가능한 범위만 사용, 나머지는 가격팩터로 보완
```

#### Point-in-Time (PIT) 원칙

```
- 재무제표: FMP의 fillingDate(또는 acceptedDate) 기준으로 유효화
  → 해당 날짜 이전에는 그 데이터를 사용하지 않음
- 가격 데이터: 자연스럽게 PIT (당일 종가 = 당일 정보)
- 유니버스: 각 리밸런싱 시점에서의 시총/거래량으로 필터
```

---

### 3. db_manager.py [NEW]

DuckDB 데이터베이스 관리. Parquet 파일을 SQL로 조회할 수 있게 한다.

#### 핵심 기능

| 함수 | 역할 |
|------|------|
| `init_db()` | DuckDB 연결 + 테이블 스키마 생성 |
| `load_prices_to_db()` | `data/raw/prices/*.parquet` → `prices` 테이블 |
| `load_fundamentals_to_db()` | `data/raw/fundamentals/*.parquet` → `fundamentals` 테이블 |
| `load_features_to_db()` | `data/features/features_daily.parquet` → `features` 테이블 |
| `query(sql)` | SQL 쿼리 실행 → DataFrame 반환 |

#### 테이블 스키마

```sql
-- 가격 테이블
CREATE TABLE prices (
    date DATE, ticker VARCHAR,
    open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
    volume BIGINT, adj_close DOUBLE
);

-- 재무 테이블 (PIT 기준)
CREATE TABLE fundamentals (
    ticker VARCHAR, period_end DATE, filing_date DATE,
    revenue DOUBLE, revenue_growth DOUBLE,
    gross_profit DOUBLE, gross_margin DOUBLE,
    operating_income DOUBLE, operating_margin DOUBLE,
    net_income DOUBLE, fcf DOUBLE,
    total_cash DOUBLE, total_debt DOUBLE,
    shares_outstanding DOUBLE, market_cap DOUBLE
);

-- 피처 테이블
CREATE TABLE features (
    date DATE, ticker VARCHAR,
    -- 가격 팩터
    rs_spy_1m DOUBLE, rs_spy_3m DOUBLE, rs_spy_6m DOUBLE,
    rs_qqq_1m DOUBLE, rs_qqq_3m DOUBLE, rs_qqq_6m DOUBLE,
    ma20 DOUBLE, ma50 DOUBLE, ma200 DOUBLE,
    ma_alignment INT,  -- 1=정배열, -1=역배열
    rsi14 DOUBLE, week52_pos DOUBLE,
    -- 재무 팩터 (filing_date 기준 유효)
    revenue_growth_yoy DOUBLE, gross_margin DOUBLE,
    operating_margin DOUBLE, rule_of_40 DOUBLE,
    fcf_positive INT, cash_runway_quarters DOUBLE,
    de_ratio DOUBLE,
    -- 메타
    market_cap DOUBLE, avg_volume_20d DOUBLE
);
```

---

### 4. feature_engine.py [NEW]

원천 데이터로부터 팩터 피처를 계산한다. **v5 설계의 Screen Score + Market Score 항목들과 정확히 대응.**

#### 가격 기반 팩터 (1단계 — PIT 재구성 용이)

| 피처 | 계산 방법 | v5 대응 |
|------|-----------|---------|
| `rs_spy_1m` | `(stock_ret_1m - spy_ret_1m)` | Market Score RS |
| `rs_spy_3m`, `rs_spy_6m` | 동일, 기간 변경 | Market Score RS |
| `rs_qqq_1m/3m/6m` | QQQ 기준 동일 | Market Score RS |
| `rs_combined` | SPY·QQQ 모두 양수 → +1, 하나만 → +0.5 | Screen Score RS 종합 |
| `ma20`, `ma50`, `ma200` | 이동평균 | Market Score MA정배열, 레짐 |
| `ma_alignment` | ma20 > ma50 > ma200 → 정배열(+1) | Market Score |
| `rsi14` | 14일 RSI | Screen Score RSI |
| `week52_pos` | `(close - 52wk_low) / (52wk_high - 52wk_low)` | Screen/Market Score |

#### 재무 기반 팩터 (2단계 — PIT 주의 필요)

| 피처 | 계산 방법 | v5 대응 |
|------|-----------|---------|
| `revenue_growth_yoy` | YoY 매출성장률 | Screen + Fundamental |
| `gross_margin` | 매출총이익률 | Screen + Fundamental |
| `operating_margin` | 영업이익률 | Rule of 40 |
| `rule_of_40` | revenue_growth + operating_margin | Screen Score |
| `fcf_positive` | FCF > 0 → 1, 전환중 → 0.5, 적자 → 0 | Fundamental |
| `cash_runway_quarters` | total_cash / abs(quarterly_fcf) | Screen + Fundamental |
| `de_ratio` | total_debt / total_equity | Screen Score |

#### 유니버스 필터

```python
# 각 리밸런싱 시점에서:
# 1. 해당 날짜 기준 시총 >= $300M
# 2. 20일 평균 거래량 >= 50만주
# 3. 가격 데이터 최소 6개월 존재 (RS 6M 계산 가능)
```

---

### 5. factor_validator.py [NEW]

**§0의 핵심.** 각 팩터의 예측력(IC)을 측정하고, 통계적으로 유의한 팩터만 통과시킨다.

#### 검증 절차

```
1단계: 가격 팩터만 먼저
  - 매주 금요일 리밸런싱
  - 유니버스: 해당 시점 시총 $300M+, 거래량 50만+
  - 각 팩터 점수 계산
  - 상위 20% / 하위 20% 분위 생성
  - forward 4주(20일)/12주(60일)/24주(120일) 수익률 측정
  - Spearman IC와 분위 스프레드 기록

2단계: 재무 팩터 추가
  - filing_date 기준 PIT 유효화
  - 동일한 IC/분위 분석

3단계: 조합 점수 검증
  - 통과한 팩터로 Screen Score / Buy Score 구성
  - 상위 N개 포트폴리오 CAGR, MDD, Sharpe, Alpha를 QQQ 대비 비교
```

#### 핵심 함수

| 함수 | 역할 |
|------|------|
| `compute_ic(factor_series, forward_returns)` | Spearman IC 계산 |
| `compute_ic_timeseries(factor, returns, rebalance_dates)` | 시간별 IC 추이 |
| `compute_quintile_returns(factor, returns, n_quantiles=5)` | 분위별 수익률 |
| `test_ic_significance(ic_series)` | t-test로 IC ≠ 0 검정 |
| `validate_factor(name, factor, returns)` | 위 전부 통합 + 합격/불합격 판정 |
| `run_alphalens_analysis(factor, pricing)` | alphalens tear sheet 생성 |

#### 합격 기준 (v5 §0에서 정의)

```python
IC_THRESHOLD = None  # 🔧 사용자 정의 필요: 백테스트 결과 확인 후 확정
                     # 업계 통상 0.03 수준이나 사용자가 결정

# 자동 체크 항목 (IC_THRESHOLD 확정 전에도 실행 가능):
# 1. |IC| > IC_THRESHOLD 이고 부호가 의도와 일치
# 2. IC t-stat p-value < 0.05
# 3. 상위 분위 수익률 > 하위 분위 수익률 (스프레드 > 0)
# 4. 상위 분위 MDD < QQQ 단순 보유 MDD (또는 유사 수준)
```

#### v5 특별 검증 항목

```
- RS SPY vs QQQ 상관 확인: 상관 > 0.85이면 통합 (RS 종합)
- 매출성장·GM·Rule of 40 공동 IC: 겹치면 배점 축소
- Forward P/S IC 부호: 음(-)이면 "비쌀 때만 감점" 방향 전환
```

---

### 6. backtest_engine.py [NEW]

vectorbt 기반 포트폴리오 시뮬레이션. 통과한 팩터로 실제 전략 성과를 측정한다.

#### 핵심 기능

| 함수 | 역할 |
|------|------|
| `run_factor_portfolio(factor, prices, top_n=20)` | 단일 팩터 상위 N개 등가중 포트폴리오 |
| `run_combined_portfolio(scores, prices, top_n=20)` | 조합 점수 기반 포트폴리오 |
| `run_regime_filtered(scores, prices, spy, qqq)` | 레짐 게이트 적용 시뮬레이션 |
| `compute_stats(portfolio)` | CAGR, MDD, Sharpe, Sortino, Alpha, Hit Rate |
| `compare_with_benchmark(portfolio, benchmark)` | QQQ 대비 성과 비교 |

#### 시뮬레이션 설정

```python
# vectorbt Portfolio.from_orders 사용
# - 매주 금요일 리밸런싱
# - 등가중 (1/N)
# - 슬리피지: 0.1% (소형주 보수적)
# - 수수료: 0 (미국주식 무수수료 브로커 가정)
# - group_by=True (현금 공유)
```

---

### 7. report_generator.py [NEW]

검증 결과를 HTML 보고서로 출력한다.

#### 보고서 내용

```
1. 팩터별 IC 요약 테이블 (IC 평균, t-stat, p-value, 합격/불합격)
2. IC 시계열 차트 (안정성 확인)
3. 분위별 누적 수익률 차트
4. RS SPY-QQQ 상관 행렬
5. 성장/퀄리티 클러스터 상관 행렬
6. 조합 포트폴리오 성과 (CAGR, MDD, Sharpe) vs QQQ
7. 레짐 필터 유무 비교
8. Forward P/S IC 부호 경고
9. 최종 권장 팩터 목록 + 가중치 조정안
```

---

### 8. main.py [NEW]

CLI 진입점. 단계별 실행을 지원한다.

```bash
# 전체 파이프라인
python main.py --run-all

# 단계별 실행
python main.py --collect-prices        # 1. 가격 데이터 수집
python main.py --collect-fundamentals  # 2. 재무 데이터 수집 (FMP)
python main.py --build-features        # 3. 피처 테이블 생성
python main.py --validate-price-factors   # 4. 가격 팩터 IC 검증
python main.py --validate-fundamental-factors  # 5. 재무 팩터 IC 검증
python main.py --run-backtest          # 6. 조합 포트폴리오 백테스트
python main.py --generate-report       # 7. HTML 보고서 생성
```

---

### 9. requirements.txt [NEW]

```
yfinance>=0.2.30
duckdb>=0.10.0
vectorbt>=0.26.0
alphalens-reloaded>=0.4.3
pandas>=2.0.0
numpy>=1.24.0
scipy>=1.10.0
pyarrow>=14.0.0
requests>=2.31.0
plotly>=5.18.0
matplotlib>=3.7.0
tqdm>=4.65.0
```

---

## 구현 순서

| 순서 | 모듈 | 의존성 | 예상 작업량 |
|------|------|--------|------------|
| 1 | `requirements.txt` + `config.py` | 없음 | 소 |
| 2 | `data_collector.py` (가격 파트) | config | 중 |
| 3 | `db_manager.py` | config | 중 |
| 4 | `feature_engine.py` (가격 팩터) | data_collector, db_manager | 대 |
| 5 | `factor_validator.py` | feature_engine | 대 |
| 6 | `backtest_engine.py` | factor_validator | 대 |
| 7 | `data_collector.py` (FMP 재무 파트) | config | 중 |
| 8 | `feature_engine.py` (재무 팩터) | data_collector | 중 |
| 9 | `report_generator.py` | 모든 결과 | 중 |
| 10 | `main.py` | 전체 | 소 |

---

## Verification Plan

### 자동 검증
```bash
# 1. 데이터 수집 확인
python main.py --collect-prices
# → data/raw/prices/ 에 Parquet 파일 생성 확인

# 2. 피처 생성 확인
python main.py --build-features
# → data/features/features_daily.parquet 생성 확인

# 3. 팩터 검증 실행
python main.py --validate-price-factors
# → results/ic_results/ 에 IC 시계열 저장 확인

# 4. 백테스트 실행
python main.py --run-backtest
# → results/reports/ 에 HTML 보고서 생성 확인
```

### 수동 검증
- 생성된 IC 결과 테이블에서 각 팩터의 부호가 의도와 일치하는지 확인
- 분위별 수익률이 단조(상위 > 하위)인지 확인
- QQQ 대비 조합 포트폴리오의 Alpha가 양수인지 확인
- 결과를 사용자에게 제시하고 `IC_THRESHOLD` 확정 요청

---

## Open Questions

> [!IMPORTANT]
> **FMP API 키**: 구현 시작 전에 FMP 무료 계정을 만들고 API 키를 발급받아야 합니다. https://site.financialmodelingprep.com/register 에서 가입 가능합니다.

> [!NOTE]
> **유니버스 범위**: 현재 NASDAQ/NYSE 상장 종목 전체(약 6,000+)에서 시총/거래량 필터를 적용하면 ~800종목이 됩니다. FMP 무료 250콜/일 제한으로 전체 재무 수집에 약 4~5일이 소요됩니다. 가격 데이터(Yahoo)는 제한 없이 한 번에 수집 가능합니다.

> [!NOTE]
> **생존 편향(Survivorship Bias)**: 현재 상장된 종목만으로 백테스트하면 과거 상폐된 종목이 빠져 결과가 상향 왜곡됩니다. 1차 MVP에서는 이 한계를 인지하고 결과 해석 시 감안합니다. 완전한 해결은 상폐 종목 데이터베이스가 필요하며 2단계에서 검토합니다.
