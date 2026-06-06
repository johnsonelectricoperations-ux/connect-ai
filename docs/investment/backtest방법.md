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
