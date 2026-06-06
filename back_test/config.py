"""
Connect AI v5 §0 백테스트 검증 시스템 — 중앙 설정
=================================================
모든 경로, API 키, 백테스트 파라미터를 이 파일에서 관리한다.
🔧 마커가 붙은 값은 백테스트 결과 확인 후 사용자가 확정한다.
"""

import os
from pathlib import Path

# ──────────────────────────────────────────────
# 프로젝트 경로
# ──────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PRICES_DIR = RAW_DIR / "prices"
FUNDAMENTALS_DIR = RAW_DIR / "fundamentals"
FEATURES_DIR = DATA_DIR / "features"
UNIVERSE_DIR = DATA_DIR / "universe"
RESULTS_DIR = PROJECT_ROOT / "results"
IC_RESULTS_DIR = RESULTS_DIR / "ic_results"
QUINTILE_DIR = RESULTS_DIR / "quintile_returns"
REPORTS_DIR = RESULTS_DIR / "reports"
DB_PATH = PROJECT_ROOT / "connect_ai.duckdb"

# 디렉토리 자동 생성
for d in [
    PRICES_DIR, FUNDAMENTALS_DIR, FEATURES_DIR, UNIVERSE_DIR,
    IC_RESULTS_DIR, QUINTILE_DIR, REPORTS_DIR,
]:
    d.mkdir(parents=True, exist_ok=True)

# ──────────────────────────────────────────────
# 백테스트 기간 및 유니버스 필터
# ──────────────────────────────────────────────
BACKTEST_START = "2018-01-01"
BACKTEST_END = "2025-12-31"
MIN_MARKET_CAP = 300_000_000        # $300M
MIN_AVG_VOLUME = 500_000            # 일 평균 거래량 50만주
MAX_MARKET_CAP_SCREEN = 50_000_000_000  # Screen 시총 상한 $50B

# ──────────────────────────────────────────────
# 리밸런싱 및 수익률 측정
# ──────────────────────────────────────────────
REBALANCE_FREQ = "W-FRI"            # 매주 금요일 리밸런싱
FORWARD_PERIODS = [20, 60, 120]     # 4주(20일), 12주(60일), 24주(120일)
FORWARD_PERIOD_LABELS = ["4W", "12W", "24W"]
N_QUANTILES = 5                     # 분위 수 (quintile)
TOP_N_STOCKS = 20                   # 상위 선정 종목 수

# ──────────────────────────────────────────────
# FMP (Financial Modeling Prep) API
# ──────────────────────────────────────────────
FMP_API_KEY = os.environ.get("FMP_API_KEY", None)  # 🔧 사용자 입력 필요: 환경변수 또는 직접 입력
FMP_BASE_URL = "https://financialmodelingprep.com/stable"
FMP_DAILY_LIMIT = 250
FMP_RATE_LIMIT_DELAY = 0.3  # 초 (4 parallel queries/sec 제한 대응)

# ──────────────────────────────────────────────
# 기술 팩터 계산 파라미터
# ──────────────────────────────────────────────
RSI_PERIOD = 14
MA_SHORT = 20
MA_MID = 50
MA_LONG = 200
RS_PERIODS_DAYS = {
    "1m": 21,    # 약 1개월
    "3m": 63,    # 약 3개월
    "6m": 126,   # 약 6개월
}

# ──────────────────────────────────────────────
# 벤치마크
# ──────────────────────────────────────────────
BENCHMARKS = ["SPY", "QQQ"]

# ──────────────────────────────────────────────
# 팩터 정의 (이름, 의도 부호, v5 대응 영역)
# IC 부호가 의도와 불일치하면 해당 팩터는 불합격이다.
# ──────────────────────────────────────────────
PRICE_FACTORS = {
    # factor_name: (expected_sign, description, v5_section)
    "rs_spy_1m":    (+1, "RS vs SPY 1개월",    "Market Score"),
    "rs_spy_3m":    (+1, "RS vs SPY 3개월",    "Market Score"),
    "rs_spy_6m":    (+1, "RS vs SPY 6개월",    "Market Score"),
    "rs_qqq_1m":    (+1, "RS vs QQQ 1개월",    "Market Score"),
    "rs_qqq_3m":    (+1, "RS vs QQQ 3개월",    "Market Score"),
    "rs_qqq_6m":    (+1, "RS vs QQQ 6개월",    "Market Score"),
    "rs_combined":  (+1, "RS 종합 (SPY·QQQ)",  "Screen Score"),
    "ma_alignment": (+1, "MA 정배열 (20>50>200)", "Market Score"),
    "rsi14":        (-1, "RSI 14 (과매수 = 감점)", "Screen Score"),
    "week52_pos":   (-1, "52주 위치 (낮을수록 가점)", "Screen/Market"),
}

FUNDAMENTAL_FACTORS = {
    "revenue_growth_yoy": (+1, "YoY 매출성장률",     "Screen+Fundamental"),
    "gross_margin":       (+1, "매출총이익률",         "Screen+Fundamental"),
    "operating_margin":   (+1, "영업이익률",           "Rule of 40"),
    "rule_of_40":         (+1, "Rule of 40",          "Screen Score"),
    "fcf_positive":       (+1, "FCF 흑자 여부",        "Fundamental"),
    "cash_runway_q":      (+1, "Cash Runway (분기)",   "Screen+Fundamental"),
    "de_ratio":           (-1, "부채비율 (낮을수록 좋음)", "Screen Score"),
}

# ──────────────────────────────────────────────
# v5 🔧 사용자 정의 필요 파라미터 (백테스트 결과 확인 후 확정)
# ──────────────────────────────────────────────
IC_THRESHOLD = None  # 🔧 사용자 정의 필요: IC 합격 임계값 (업계 통상 0.03)

# 아래는 이번 MVP 범위 밖이지만 참고용으로 기록
# BAND_HIGH = None          # 🔧 사용자 정의 필요: Conviction '상' 진입 raw 하한
# BAND_MID = None           # 🔧 사용자 정의 필요: Conviction '중' 진입 raw 하한
# CAUTION_MULT = None       # 🔧 사용자 정의 필요: CAUTION 레짐 사이즈 배율
# CAUTION_SCORE_REQ = None  # 🔧 사용자 정의 필요: CAUTION 시 Buy Score 추가 요구점수
# HARD_STOP_PCT = None      # 🔧 사용자 정의 필요: 하드 스톱 비율
# MA50_VOL_MULT = None      # 🔧 사용자 정의 필요: MA50 이탈 거래량 배수
# TRAILING_STOP_PCT = None  # 🔧 사용자 정의 필요: 트레일링 스톱 비율
# THEME_CAP = None          # 🔧 사용자 정의 필요: 테마 비중 상한
# SECTOR_CAP = None         # 🔧 사용자 정의 필요: 섹터 비중 상한

# ──────────────────────────────────────────────
# 시뮬레이션 파라미터
# ──────────────────────────────────────────────
SLIPPAGE_PCT = 0.001        # 0.1% 슬리피지 (소형주 보수적)
COMMISSION_PCT = 0.0        # 미국주식 무수수료 브로커 가정
INITIAL_CAPITAL = 100_000   # $100,000 초기 자본

# ──────────────────────────────────────────────
# 데이터 수집 배치 설정
# ──────────────────────────────────────────────
YFINANCE_BATCH_SIZE = 50    # yfinance 동시 다운로드 배치 크기
FMP_BATCH_SIZE = 5          # FMP API 배치 크기 (일일 제한 대응)
COLLECTION_TRACKING_FILE = DATA_DIR / "collection_progress.json"

# ──────────────────────────────────────────────
# 로깅
# ──────────────────────────────────────────────
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
