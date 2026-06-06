좋습니다. 당신이 정리한 Yahoo + FMP + SEC 13F + vectorbt + DuckDB 조합은 현재 Connect AI v5의 목표(팩터 검증 → 라이브 운용)에 가장 현실적이고 유지보수 가능한 선택입니다. 여기에 누락된 분석/검증 도구와 운영 인프라를 보완하면 바로 구현 가능한 수준이 됩니다.

원천 데이터 레이어 (백테스트용 권장 조합)

| 영역     | 권장 소스                         | 역할                                                       |
| ------ | ----------------------------- | -------------------------------------------------------- |
| 가격 데이터 | Yahoo Finance (`yfinance`)    | OHLCV, RSI, MA, 52주 위치, RS 계산                            |
| 재무 데이터 | FMP (Financial Modeling Prep) | Revenue, Gross Margin, Operating Margin, FCF, Cash, Debt |
| 기관 수급  | SEC EDGAR 13F 직접 수집           | 기관보유율 변화, filing-date 기준 백테스트                            |
| 보조 참고  | Dataroma                      | 슈퍼인베스터 참고(라이브 표시용), 백테스트 핵심 소스 아님                        |

중요: point-in-time 원칙

| 데이터       | 백테스트 기준 날짜                                     |
| --------- | ---------------------------------------------- |
| 13F       | Filing Date (공시 공개일)                           |
| 재무제표      | Filing/Acceptance Date 기준 권장 (최소한 발표일 이후부터 사용) |
| 애널리스트 추정치 | 그 시점 스냅샷 저장(현재값으로 과거를 덮어쓰면 look-ahead bias)    |

빠진 핵심 분석 도구: DuckDB + Parquet + PyArrow

백테스트는 결국 많은 종목 × 긴 기간 × 반복 계산입니다. CSV만 쓰면 느리고 관리가 힘듭니다.

권장 저장 구조:

DuckDB 장점:

1. 수천 개 Parquet를 SQL로 즉시 조회

2. Pandas보다 메모리 효율 좋음

3. vectorbt와 연동 쉬움

팩터 검증용 추가 라이브러리

vectorbt만으로도 충분하지만, 팩터 연구(IC, 분위별 수익률, Alphalens 스타일 분석)을 쉽게 하려면 아래를 추천합니다.

| 도구                 | 용도                       |
| ------------------ | ------------------------ |
| alphalens-reloaded | 분위별 수익률, IC, turnover 분석 |
| scipy              | Spearman IC, 통계 검정       |
| statsmodels        | 회귀/팩터 노출 분석              |

v5 기준으로 꼭 저장해야 하는 시계열 피처 테이블

백테스트가 반복될수록 가장 귀찮은 부분은 매번 재계산하는 것입니다. 아래는 features_daily.parquet 같은 단일 피처 테이블로 저장하세요.

| 컬럼                         | 설명                  |
| -------------------------- | ------------------- |
| date, ticker               | 키                   |
| ret_1m, ret_3m, ret_6m     | RS 계산용              |
| spy_ret_1m … qqq_ret_6m    | 상대강도 기준             |
| rs_spy_1m … rs_qqq_6m      | RS 팩터               |
| ma20, ma50, ma200          | 정배열·레짐              |
| rsi14                      | RSI 팩터              |
| week52_pos                 | 52주 위치              |
| market_cap                 | 동적 가중치·유니버스 필터      |
| revenue_growth_yoy         | Fundamental         |
| gross_margin               | Fundamental         |
| operating_margin           | Rule of 40          |
| fcf_margin 또는 fcf_positive | Fundamental         |
| cash_runway_quarters       | Fundamental         |
| inst_own_change_pctpt      | 13F 기반 변화율          |
| forward_ps                 | Market Score        |
| eps_revision_3m            | Market Score(가능할 때) |

이렇게 저장하면 vectorbt는 단순히 시그널 생성과 포트폴리오 시뮬레이션만 하면 됩니다.

backtest_validate.py 권장 검증 절차 (구체화)

1단계: 가격 팩터만 먼저 (데이터 품질·PIT 재구성 쉬움)

방법:

1. 매주 금요일 리밸런싱

2. 유니버스: 해당 시점 시총 300M+, 거래량 50만+

3. 각 팩터 점수 계산

4. 상위 20% / 하위 20% 분위 생성

5. 향후 4주·12주·24주 수익률 측정

6. Spearman IC와 분위 스프레드 기록

2단계: 재무 팩터 추가

주의: 발표일 이후부터만 사용.

3단계: 13F 추가

반드시 filing_date 기준으로 유효화.

4단계: 조합 점수 검증

상위 N개 포트폴리오의 CAGR, MDD, Sharpe, Alpha를 QQQ 대비 비교.

v5에서 특히 놓치기 쉬운 함정 5개

| 함정                             | 예방                                     |
| ------------------------------ | -------------------------------------- |
| Look-ahead bias (현재 재무로 과거 계산) | 발표/공시일 기준 PIT 스냅샷 저장                   |
| 13F holding-date 사용            | Filing Date만 사용                        |
| 생존 편향 (현재 상장 종목만 테스트)          | 당시 유니버스 스냅샷 사용, 최소 delisted 일부 포함 고려   |
| 실행 비용 무시                       | signal_price vs fill_price, 슬리피지 기록 유지 |
| QQQ 대비 단순 수익률만 비교              | Alpha, MDD, turnover, hit rate 함께 평가   |

최종 권장 구현 순서 (현실적 최소 MVP)

MVP 순서

1. 가격 데이터 수집 → Parquet 저장

2. RS/MA/52주/RSI 피처 생성

3. `backtest_validate.py`로 가격 팩터 IC 검증

4. FMP 재무 수집 → 발표일 기준 정렬 → Revenue/GM/FCF/Rule40 피처 생성

5. 재무 팩터 IC 검증

6. 13F filing-date 테이블 구축

7. 기관보유율 변화 IC 검증

8. 통과한 팩터만 Screen/Buy Score에 반영

9. 그 후에 `screen.py`, `buy_score.py`, `exit_score.py` 연결

10. `monitor.py`와 텔레그램 알림 추가

11. Deep Analysis(LLM)는 마지막

핵심 요약

백테스트 원천 데이터는 Yahoo + FMP + SEC 13F, 엔진은 vectorbt, 저장은 DuckDB + Parquet가 현재 v5 목표에 가장 적합합니다. Macrotrends와 Dataroma는 연구·설명·교차검증용 참고 자료로 두고, 팩터 검증과 포트폴리오 시뮬레이션의 원천 데이터로는 쓰지 않는 편이 좋습니다.

--- 구체적인 방법
네. 결론부터 말하면 **당신이 선정한 5개 모두 Python에서 직접 다룰 수 있습니다.**

다만 난이도가 다릅니다.

| 구성요소          | Python 지원 | 난이도 | 추천    |
| ------------- | --------- | --- | ----- |
| Yahoo Finance | 매우 좋음     | ★   | 적극 추천 |
| FMP           | 매우 좋음     | ★   | 적극 추천 |
| SEC 13F       | 가능        | ★★★ | 추천    |
| DuckDB        | 매우 좋음     | ★   | 적극 추천 |
| vectorbt      | 매우 좋음     | ★★  | 적극 추천 |

---

# 1. Yahoo Finance

가장 쉽습니다.

```python
import yfinance as yf

aapl = yf.Ticker("AAPL")

hist = aapl.history(period="5y")

print(hist.head())
```

얻을 수 있는 것

```text
OHLCV
52주 고가
52주 저가
시총
RS 계산용 가격
MA20
MA50
RSI
```

Connect AI에서는 거의 필수입니다.

---

# 2. FMP (Financial Modeling Prep)

API 제공

```python
import requests

url = f"https://financialmodelingprep.com/api/v3/income-statement/AAPL?apikey=KEY"

data = requests.get(url).json()
```

얻을 수 있는 것

```text
Revenue
Gross Profit
Gross Margin
Operating Margin
FCF
Cash
Debt
Enterprise Value
```

당신의

```text
Revenue Growth
Gross Margin
Rule of 40
FCF
Cash Runway
```

전부 여기서 나옵니다.

---

# 3. SEC 13F

가능은 한데 가장 어렵습니다.

---

방법1

SEC EDGAR API

```python
import requests
```

직접 파싱

---

방법2

WhaleWisdom

---

방법3

sec-edgar-downloader

```bash
pip install sec-edgar-downloader
```

예시

```python
from sec_edgar_downloader import Downloader

dl = Downloader("data")

dl.get("13F-HR", "0001067983")
```

---

13F는

```text
기관보유율 변화
```

를 계산하기 위해 필요합니다.

---

# 4. DuckDB

이건 DB입니다.

엄청 좋습니다.

---

설치

```bash
pip install duckdb
```

---

예시

```python
import duckdb

con = duckdb.connect("connect_ai.db")

con.execute("""
CREATE TABLE prices (
    date DATE,
    ticker VARCHAR,
    close DOUBLE
)
""")
```

---

장점

```text
SQLite보다 빠름

Parquet 직접 읽음

수백만행 처리 가능
```

---

예시

```python
df = con.execute("""
SELECT *
FROM prices
WHERE ticker='RKLB'
""").df()
```

---

Connect AI에서

```text
가격
재무
13F
팩터
```

전부 저장 가능

---

# 5. vectorbt

백테스트 엔진

---

설치

```bash
pip install vectorbt
```

---

예시

```python
import vectorbt as vbt

portfolio = vbt.Portfolio.from_signals(
    close,
    entries,
    exits
)

print(portfolio.stats())
```

---

얻는 것

```text
CAGR
Sharpe
MDD
승률
거래수
```

---

당신의

```text
RS 상위 20%
매주 리밸런싱
12주 보유
```

같은 테스트를 매우 쉽게 구현할 수 있습니다.

---

# 내가 추천하는 실제 구조

```text
Yahoo Finance
    ↓
가격 데이터

FMP
    ↓
재무 데이터

SEC 13F
    ↓
기관 데이터

모두 DuckDB 저장
    ↓
Feature 생성
(RS, GM, FCF...)

vectorbt
    ↓
팩터 검증

통과 팩터만
Screen Score 반영
```

---

### 구현 난이도 순서

```text
1. Yahoo Finance      ★
2. DuckDB             ★
3. vectorbt           ★★
4. FMP                ★★
5. SEC 13F            ★★★★
```

실제로 Connect AI를 만든다면 **1차 MVP는 Yahoo + FMP + DuckDB + vectorbt만으로 먼저 구축**하는 것을 추천합니다.

그 4개만으로도 이미:

* RS
* MA200 Regime
* RSI
* 52주 위치
* Revenue Growth
* Gross Margin
* Rule of 40
* FCF

까지 백테스트할 수 있습니다.

SEC 13F는 데이터 구조가 복잡하므로 **시스템이 안정화된 후 2단계로 추가하는 것이 개발 효율이 가장 좋습니다.**

