# Connect AI 투자 시스템 설계 v4.0

> 작성일: 2026-06-06  
> 상태: 설계 확정 (구현 대기)  
> 버전 이력: v1(초안) → v2(Buy/Exit 분리) → v3(Conviction Gate) → v4(Backtest 로그 + Deep Analysis 요약 저장)

---

## 전체 파이프라인

```
Universe Scan (주 1회)
  NASDAQ/NYSE CSV → 시총 $300M+ · 거래량 50만+ → ~800종목
         ↓
Screen Score (주 2회)
  Gross Margin · Rule of 40(영업이익률) · RS(SPY+QQQ)
  기관보유율 변화 · 시총 $50B까지
  상위 20개 → 관심종목 자동 등록
         ↓
Deep Analysis (등록 시 1회 + 분기 재실행)
  입력: business_summary · recent_news · 재무지표
       major_customers · competitors · CEO · insider_buying
       analyst_estimates
  출력: Conviction Score (0~100)
       + bull_case · bear_case · key_risks · summary 저장
  → Conviction < 50 이면 이후 단계 중단
         ↓
Fundamental Score (주 1회, 100점)
         +
Market Score (매일, 100점)
         ↓
Buy Score = F × 동적가중치 + M × 동적가중치
         ↓
매수 판정 매트릭스 (Buy Score × Conviction Gate)
         ↓
Position Sizing → Backtest 로그 기록
         ↓
         매수
         ↓
Position Score (매일 모니터링)
         ↓
Exit Score (주 1회)
  펀더멘털 악화 · 밸류에이션 과열 · 경영진 이탈
  누적 -5 → Exit Review / -10 → 강력 매도
  → 매도 시 Backtest 로그 수익률 기록
```

---

## 1. Screen Score (`screen.py` 개선)

**목적:** "좋은 회사"를 찾는 1차 필터. 800종목 → 20종목.

| 항목 | 현재 | 변경 |
|------|------|------|
| Rule of 40 | 순이익률 사용 | **영업이익률(operatingMargins)으로 수정** |
| Gross Margin | 없음 | **신규 추가** |
| 시총 상한 | $15B | **$50B로 확장** |
| 기관보유율 | 없음 | **변화율(전분기 대비) 기준으로 추가** |
| RS | 없음 | **SPY · QQQ 각각 추가** |

### Tenbagger 전략 점수표 (개선 후)

| 항목 | 배점 | 기준 |
|------|------|------|
| 시총 (피터 린치) | 최대 +3 | $300M~$5B: +3 / $5B~$20B: +2 / $20B~$50B: +1 |
| 매출 성장률 | 최대 +4 | ≥40%: +4 / ≥25%: +3 / ≥10%: +1 / <10%: -1 |
| Gross Margin | 최대 +2 | ≥60%: +2 / ≥40%: +1 / <20%: -1 |
| Rule of 40 (영업이익률) | 최대 +3 | ≥40: +3 / ≥20: +1.5 / <20: 0 |
| 부채비율 D/E | 최대 +2 | ≤0.3: +2 / ≤0.8: +1 / >2.0: -1 |
| Cash Runway | 최대 +2 | 8분기+: +2 / 4~8분기: +1 / <4분기: -2 |
| 52주 위치 | 최대 +2 | ≤40%: +2 / ≤65%: +1 / ≥85%: -1 |
| RSI | 최대 +1 | 40~65: +1 / >75: -1 |
| RS vs SPY (6개월) | 최대 +1 | 양수: +1 |
| RS vs QQQ (6개월) | 최대 +1 | 양수: +1 |
| 기관보유율 변화 | 최대 +2 | +10%p+: +2 / +5%p+: +1 / 감소: -1 |
| Macrotrends 연속성장 | 보너스 | 5년+: +2 / 3년+: +1 |
| Macrotrends 5yr CAGR | 보너스 | ≥30%: +2 / ≥15%: +1 |
| Dataroma (Screen 단계) | 보너스 | strong_conviction: +3 / multi: +2 / single: +1 |

**관심종목 자동 등록:** 상위 5개 (`addedBy: "auto"`, `addReason`, `name`, `sector` 포함)

---

## 2. Deep Analysis + Conviction Score

**목적:** "지금 살 회사인가?"의 정성 검증. LLM이 담당. 20종목 대상으로만 실행.

### 입력 데이터 (LLM에 전달)

```json
{
  "ticker": "RKLB",
  "business_summary": "소형 발사체 전문 우주기업...",
  "recent_news": ["NASA 계약 수주 $50M", "Neutron 개발 진척"],
  "revenue_growth": 34,
  "gross_margin": 31,
  "fcf": -120,
  "cash": 480,
  "cash_runway_quarters": 6,
  "major_customers": ["NASA", "DoD"],
  "competitors": ["SpaceX", "ULA"],
  "ceo": "Peter Beck",
  "insider_buying": "CEO +$2M (2026-03)",
  "analyst_estimates": {
    "next_q_revenue_growth": 38,
    "eps_revision_3m": "+25%"
  },
  "sector": "Space",
  "market_cap_b": 4.2
}
```

### LLM 출력 (전체 저장)

```json
{
  "business_quality":       8,
  "competitive_advantage":  9,
  "execution_risk":         4,
  "dilution_risk":          3,
  "tam_score":              9,

  "summary": "소형 발사체 시장에서 독점적 위치. NASA·DoD 장기 계약 기반 수익 가시성 높음. FCF 적자이나 현금 6분기 확보. 우주 민영화 핵심 수혜주.",

  "bull_case": [
    "Neutron 중형 로켓 개발 성공 시 시장 확장성 급증",
    "미 정부 우주 예산 증가로 장기 수주 파이프라인 견고",
    "발사 횟수 증가 → Gross Margin 구조적 개선 중"
  ],

  "bear_case": [
    "SpaceX Falcon 9 대비 가격 경쟁력 열위",
    "Neutron 개발 지연 시 희석 리스크 증가",
    "FCF 적자 지속 → 추가 자금조달 가능성"
  ],

  "key_risks": [
    "Neutron 개발 일정 지연",
    "정부 예산 삭감",
    "핵심 엔지니어 이탈"
  ]
}
```

### Conviction Score 계산

```python
Conviction = (
    business_quality +
    competitive_advantage +
    (10 - execution_risk) +
    (10 - dilution_risk) +
    tam_score
) / 50 × 100

# Conviction < 50 → 하드 게이트 (이후 모든 단계 중단)
```

### 저장 위치 (`watchlist.json`)

```json
"RKLB": {
  "conviction_score": 86,
  "conviction_updated": "2026-06-06",
  "analysis": {
    "summary": "...",
    "bull_case": ["...", "...", "..."],
    "bear_case": ["...", "...", "..."],
    "key_risks": ["...", "...", "..."]
  }
}
```

---

## 3. Fundamental Score (주 1회, 100점)

**목적:** 재무 건전성과 성장 지속성 정량 평가.

| 항목 | 배점 | 기준 |
|------|------|------|
| 매출 성장률 | 25 | ≥40%: +25 / ≥25%: +18 / ≥10%: +10 / <10%: 0 |
| Gross Margin | 20 | ≥60%: +20 / ≥40%: +13 / <20%: -5 |
| FCF | 15 | 흑자: +15 / 전환중: +8 / 적자: 0 |
| Cash Runway | 15 | 8분기+: +15 / 4~8분기: +8 / <4분기: **-15** |
| 기관보유율 변화 | 13 | +10%p+: +13 / +5%p+: +8 / 감소: **-5** |
| Dataroma | 12 | strong_conviction: +12 / multi: +8 / single: +4 |

---

## 4. Market Score (매일, 100점)

**목적:** 지금 이 가격에 사도 되는가? 기술적 타이밍 평가.

| 항목 | 배점 | 기준 |
|------|------|------|
| RS 1M/3M/6M × SPY/QQQ (6개) | 36 | 양수 1개당 +6 |
| MA20/50 정배열 | 20 | 정배열: +20 / 역배열: -10 |
| Forward P/S | 20 | 현재 P/S 대비 낮을수록 가점 |
| 52주 위치 | 14 | ≤40%: +14 / ≤65%: +9 / ≥85%: -5 |
| 실적 D-Day + EPS 예상 상향 | 10 | 30일 이내 + 상향: +10 / D-Day만: +4 |

---

## 5. Buy Score 계산

### 동적 가중치 (시총 기준)

```python
if market_cap < 5B:      # 소형 성장주 (IONQ·ASTS·RKLB)
    F_weight, M_weight = 0.8, 0.2
else:                    # 중대형 성장주 (APP·PLTR)
    F_weight, M_weight = 0.6, 0.4

Buy Score = F_score × F_weight + M_score × M_weight
```

### 매수 판정 매트릭스

| Buy Score | Conviction 70+ | Conviction 50~69 | Conviction 50미만 |
|-----------|---------------|-----------------|-----------------|
| **85+** | 적극 매수 | 분할 매수 | **매수 차단** |
| **75~84** | 분할 매수 | 소량 진입 | **매수 차단** |
| **65~74** | 소량 진입 | 관찰 | **매수 차단** |
| **65미만** | 관찰 | 보류 | **매수 차단** |

---

## 6. Position Sizing

**목적:** 과도 집중 방지. 단일 종목 최대 10% 상한.

```python
if buy_score >= 85 and conviction >= 85:
    max_position = 0.10    # 최대 10%
elif buy_score >= 80 and conviction >= 75:
    max_position = 0.07    # 최대 7%
elif buy_score >= 75 and conviction >= 65:
    max_position = 0.05    # 최대 5%
else:
    max_position = 0.02    # 최대 2%
```

---

## 7. Backtest 로그 (`backtest_log.json`)

**목적:** 매수/매도 결정을 기록해 6개월 후 실제 수익률과 비교 → 시스템 개선.

### 매수 시 기록

```json
{
  "id": "RKLB-20260606",
  "date": "2026-06-06",
  "ticker": "RKLB",
  "action": "BUY",
  "price": 24.50,
  "buy_score": 84,
  "fundamental_score": 81,
  "market_score": 91,
  "conviction_score": 88,
  "position_size_pct": 7,
  "f_weight": 0.8,
  "m_weight": 0.2,
  "reasons": ["고성장 매출 34%", "Gross Margin 개선 중", "NASA 계약"],
  "exit_score_at_buy": 0
}
```

### 매도 시 업데이트

```json
{
  "id": "RKLB-20260606",
  "exit_date": "2026-12-15",
  "exit_price": 34.80,
  "return_pct": 42.0,
  "hold_days": 192,
  "exit_reason": "exit_score -6 (FCF 악화 + 기관 감소)",
  "exit_score_at_sell": -6
}
```

### 나중에 분석 가능한 항목

```
Buy Score 85+ 종목 평균 수익률
Conviction 80+ 종목 승률
Exit Score -5 시점 매도 vs 보유 비교
소형주(F_weight 0.8) vs 중형주(0.6) 성과 비교
```

---

## 8. Exit Score (주 1회, 누적 감점)

**목적:** "언제 팔까?" 시스템화. 성장 스토리가 깨질 때 신호 제공.

### 펀더멘털 악화

| 조건 | 감점 |
|------|------|
| 매출 성장 전분기 대비 -10%p 이상 둔화 | -3 |
| Gross Margin -5%p 이상 악화 | -2 |
| FCF 흑자→적자 전환 | -2 |
| 기관보유율 -10%p 이상 감소 | -2 |
| Dataroma 슈퍼인베스터 매도 | -2 |
| RS 6개월 SPY·QQQ 모두 마이너스 전환 | -2 |
| CEO 교체 | -5 |
| CFO 교체 | -4 |
| CFO 교체 + 유상증자 동시 발생 | **-8** |

### 밸류에이션 과열

| 조건 | 처리 |
|------|------|
| Forward P/S > 40 | -3 |
| 현재 P/S > 5년 평균 3배 | -2 |
| RS 1개월 +50% 이상 | ⚠️ 경고 플래그만 (감점 없음, 텐배거 과정에서 정상) |

### 판정

```
누적 -5 이하  → ⚠️ Exit Review 알림 + Backtest 로그 갱신
누적 -10 이하 → 🚨 강력 매도 신호
```

---

## 9. 운영 스케줄

| 주기 | 작업 |
|------|------|
| **매일** (장 마감 후) | Market Score 갱신 · 손절/급락 알림 · Position Score |
| **주 2회** (월/목) | Screen Score 실행 · Buy Score 재계산 |
| **주 1회** (월) | NASDAQ/NYSE CSV 갱신 · Exit Score 체크 |
| **분기** (실적 후) | Fundamental Score 강제 갱신 · Deep Analysis 재실행 |

---

## 10. 파일 구조 및 구현 순서

```
1단계  screen.py 개선
       Rule of 40(영업이익률) · Gross Margin · RS(SPY+QQQ)
       기관보유율 변화 · 시총 $50B 확장
       관심종목 자동 등록 시 name·sector·addReason 저장

2단계  buy_score.py 신규
       Fundamental Score + Market Score
       동적 가중치 · 매수 판정 매트릭스 · Position Sizing
       → backtest_log.json 기록 시작

3단계  exit_score.py 신규
       펀더멘털 악화 + 밸류에이션 과열
       CEO -5 / CFO -4 분리 · RS 과열 경고 플래그
       → backtest_log.json 수익률 업데이트

4단계  monitor.py
       스케줄러 + 텔레그램 알림
       매일/주1회/주2회/분기 자동 실행

5단계  Deep Analysis (마지막)
       stock.py → 풍부한 데이터 수집
       → LLM → Conviction Score
       + bull_case · bear_case · key_risks → watchlist.json 저장
       정량 시스템 안정화 후 추가
```

---

## 11. 데이터 저장 구조

```
watchlist.json          관심종목 · Conviction · Deep Analysis 요약
portfolio.csv           보유종목 · 매수가 · 손절가 · 목표가
backtest_log.json       매수/매도 결정 로그 · 실제 수익률
screen_cache/           Universe Scan 결과 캐시 (주 1회 갱신)
```

---

*두 AI 리뷰어 의견 반영 완료. 최종 평가: 개인 성장주 투자 플랫폼으로 9.3/10 수준.*
