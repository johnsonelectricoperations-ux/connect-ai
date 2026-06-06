내 베스트는 이거다.

### 1. 가격 데이터

* Yahoo Finance (`yfinance`)
* 무료
* 20년 이상
* 백테스트 충분

```bash
pip install yfinance
```

---

### 2. 재무 데이터

* FMP (Financial Modeling Prep)
* 무료 플랜으로 시작
* 매출, FCF, Gross Margin, Debt, Cash

```bash
pip install fmpsdk
```

---

### 3. 기관 데이터

* SEC 13F 직접 수집
* Dataroma는 참고용만

백테스트는 반드시

```text
Holding Date ❌
Filing Date ⭕
```

---

### 4. 백테스트 엔진

무조건

```bash
vectorbt
```

추천

이유

* Pandas 기반
* 수천 종목 동시 테스트
* Backtrader보다 훨씬 빠름
* 팩터 연구에 최적

```bash
pip install vectorbt
```

---

### 5. 네 v5 기준 우선순위

먼저 검증

```text
RS
MA200 Regime
52주 위치
RSI
```

↓

그 다음

```text
Revenue Growth
Gross Margin
FCF
```

↓

그 다음

```text
13F
Dataroma
```

---

### 내가 실제로 한다면

```text
데이터
=
Yahoo Finance
+
FMP
+
SEC 13F

엔진
=
vectorbt

DB
=
DuckDB
```

이 조합으로 시작한다.

Macrotrends, TradingView, Dataroma는 **분석용**이고,

**백테스트 원천 데이터는 Yahoo + FMP + SEC 13F**가 가장 낫다.
