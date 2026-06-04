# Connect AI — 미국 주식 투자 AI 진행 기록

> 이 파일은 세션 간 컨텍스트 보존용. 새 세션 시작 시 이 파일을 먼저 읽을 것.
> 마지막 업데이트: 2026-06-04

---

## 시스템의 목적 (사용자 핵심 용도) ⭐

1. **종목 발굴 → 추천**: 새 기회 찾기. (screen.py 로 watchlist 랭킹 → 심층분석 검증)
2. **보유 종목 관리 → 매매전략 수행**: 가진 종목 운용. (portfolio.py 로 손익·손절·
   목표·액션 추적 → 리스크규칙으로 매매 실행)
모든 설계·우선순위는 이 두 용도를 우선한다.

---

## 프로젝트 개요

VS Code 확장(connect-ai-lab.vsix)을 미국 주식 투자 분석 AI로 개조.
- LM Studio + Qwen3.5-9B (Q4_K_M) 로컬 실행
- 포트: 127.0.0.1:12345
- 설치 위치: C:\project_list\connect-ai (소스), C:\project_list\ai_agent_antigravity (brain 폴더)
- IDE: Antigravity (VS Code fork)
- 개발 브랜치: claude/charming-hopper-M7yZf

---

## 로드맵

| 단계 | 작업 | 상태 |
|------|------|------|
| 1주차 | agents.ts + prompts 교체 → 투자 프로토타입 | ✅ 완료 |
| 2~3주차 | 시세/재무 데이터 도구 (yfinance, 기술지표 자동계산) | ✅ 완료 |
| 4~5주차 | 증권사 API (잔고/주문), 백테스팅 도구 | ⬜ 미시작 |
| 6주차 | 브레인 템플릿 (종목분석지·투자일지), 면책고지 강제화 | ⬜ 미시작 |
| 상시 | 환각 방지 가드레일, 법적 검토 | 🔄 진행중 |

---

## 완료된 작업

### 1주차 — 에이전트 전환
- `src/agents.ts`: 9개 에이전트를 투자 전문가로 교체 (내부 id 유지)
  - ceo→CIO, youtube→기술분석가, business→펀더멘털분석가, designer→리스크매니저
  - developer→퀀트엔지니어, secretary→포트폴리오매니저, instagram→매크로분석가
  - editor→센티먼트분석가, writer→리포트작가, researcher→리서처
- `assets/prompts/system.md`: 투자팀 정체성, 데이터 원칙, 투자 규칙 주입
- `assets/prompts/ceo-classifier.md`: 투자 도메인 라우팅 규칙
- `assets/prompts/ceo-chat.md`: CIO 소개 메시지

### 2~3주차 — 데이터 도구 (v2.91.0 기준 완료)
- `stock.py` (yfinance 기반):
  - `py stock.py TICKER` → price, marketCap, trailingPE, forwardPE, priceToSales, eps, high52, low52, sector
  - `py stock.py TICKER hist` → 60일 일봉 + **기술지표 자동계산**: RSI(14), MA(20/50), MACD(12/26/9), Signal, Histogram + summary 필드
  - summary: trend(bullish_aligned/bearish_aligned), rsi_state(overbought/oversold/neutral)
- `update.bat`: git pull + stock.py 동기화 자동화 (더블클릭 한 번)
- run_command 자동 분석: 명령 실행 후 결과를 AI가 자동 분석

### 에이전트 페르소나 강화 (v2.90.6~v2.91.0)
- **펀더멘털분석가**: EPS 해석 규칙 주입 — trailing EPS 양수라도 흑자 단정 금지, forward PER 음수 = "향후 적자 예상"
- **기술분석가**: RSI/MA/MACD 해석 규칙 + hist 명령 사용 의무화
- **리스크매니저**: 포지션 사이징 공식, R:R 1:2, 손절 기준 주입

### 상시 — 환각 방지
- system.md: 차트 분석 시 hist 필수, 추측 금지, null = "확인 실패" 원칙
- brain 폴더 지식 파일 3개 (C:\project_list\ai_agent_antigravity\10_Wiki\투자지식\):
  - `펀더멘털_지표해석.md`, `기술지표_해석법.md`, `리스크관리_규칙.md`

---

## 현재 버전: 2.94.0

### 로컬 도구 6종 (전부 워크스페이스에 복사됨 via update.bat)
- stock.py  — 시세·밸류·재무·목표가·실적일 + hist(지표) + risk(포지션사이징)
- macro.py  — VIX·금리·달러·환율·지수·유가·금 + regime
- backtest.py — MA크로스/RSI 전략 백테스트
- sec.py    — SEC EDGAR 공식 공시·재무
- portfolio.py — 보유종목 손익·손절·목표·액션 (portfolio.csv)
- screen.py — 종목발굴 랭킹 value/momentum (watchlist.txt)

### ⏳ 집 PC에서 테스트 대기 중 (v2.92.0 ~ 2.94.0 일괄)
코드/지식 완성·푸시됨, update.bat 후 테스트만 남음:
- macro.py / backtest.py / sec.py / portfolio.py / screen.py
- 에이전트 9종 페르소나 + 스킬 9종 (_company/_agents/{id}/skills/)
- 지식 추가분: 거시경제·시장심리·섹터별·SEC공시·매매전략·종목발굴 + 템플릿 2종
→ 테스트 체크리스트는 맨 아래 참고.

### 검증 완료 (집 PC 테스트 통과)
- ✅ `py stock.py IONQ` → 실시간 가격·밸류에이션 정확 (beta·roe·목표가·실적일 포함)
- ✅ `py stock.py IONQ hist` → RSI·MA·MACD·ATR 계산값 정확
- ✅ `py stock.py IONQ risk [총자산] [위험%]` → 손절가·수량·비중·최대손실·R:R 사전계산 (USD)
- ✅ 기술분석가: hist 실행 후 실제 지표값으로 분석 (테스트 통과)
- ✅ 펀더멘털분석가: forward PER 음수 해석 + 재무지표(roe·부채·목표가) 인용
- ✅ 리스크매니저: risk 모드로 beta 3.05 → 비중 2.5% 자동, 5만달러 포지션 정확 (테스트 통과)
- ✅ Brain 지식 인용 작동 (📚 출처 표기)

### 주요 버그 수정 이력 (2~3주차)
- v2.91.2: stock.py 덮어쓰기 금지 + 명령 전 추측 출력 금지
- v2.91.3: ATR 추가 + 리스크매니저 quote 실행 의무화
- v2.91.4: risk 모드 신설 (포지션 사이징 사전계산)
- v2.91.5: risk 모드 통화 USD 일관성 + 실적일 환각 차단
- v2.91.6: ⭐ UTF-8 출력 강제 (Windows cp949 크래시 → AI 날조 근본원인 제거)
           + 명령 실패 시 "직접 계산" 날조 금지

### 9B 모델 대응 핵심 교훈
- 모델은 명령 하나만 실행하고 산수에 약함 → 계산을 Python(stock.py)에서 끝내고
  모델은 "읽어주기"만 시키는 게 가장 안정적 (risk 모드가 그 예).
- stock.py 출력에 이모지·특수문자 금지 (Windows 인코딩 크래시 유발).

---

## 다음 작업 (에이전트 데이터 연결)

### Step 1 — stock.py 확장 ✅ 완료 (v2.91.1~2.91.6)
베타·목표가·재무지표·실적일 추가, risk 모드 신설. 리스크매니저 완성.

### Step 2 — macro.py 신규 ✅ 완료 (v2.92.0, 테스트 대기)
VIX·S&P500·나스닥·다우·달러·10년물금리·환율·유가·금·BTC + state/regime 라벨.
매크로분석가·센티먼트분석가 페르소나 연결. 거시·심리 지식 추가.

### Step 3 — 백테스팅 ✅ 완료 (v2.92.0, 테스트 대기)
backtest.py: MA크로스/RSI 전략, 룩어헤드 없음. 퀀트엔지니어 연결.
(공포탐욕지수 CNN API는 보류 — 현재 VIX로 심리 대용. 필요시 추가.)

### Step 4 — 종합 분석 흐름 (Solo Mode) ← 다음 여기
"IONQ 종합 분석해줘" → CIO가 기술+펀더멘털+리스크+매크로 연계.
👔 버튼(Solo Mode) ON 시 _handleCorporatePrompt 경로. extension.ts 수정 필요 →
집 PC 테스트 동반 필수(위험). 신중히 접근.

### Step 5 — 브레인 템플릿 (6주차)
종목 분석지·투자일지 brain 템플릿. (지식 폴더에 템플릿 .md 추가 — 안전.)

---

## 에이전트별 데이터 연결 현황

| 에이전트 | 필요 데이터 | 상태 | 연결 방법 |
|---------|-----------|------|---------|
| 기술분석가 | RSI, MA, MACD, ATR | ✅ 완료 | stock.py hist |
| 펀더멘털분석가 | PER, EPS, 재무제표, 목표가 | ✅ 완료 | stock.py (확장) |
| 리스크매니저 | 베타(β), ATR, 포지션사이징 | ✅ 완료 | stock.py risk |
| 매크로분석가 | 금리, VIX, DXY, 환율 | ✅ 완료(테스트대기) | macro.py |
| 센티먼트분석가 | VIX, 공포탐욕지수 | ✅ VIX 연결(테스트대기) | macro.py ^VIX |
| 리서처 | 뉴스, SEC 공시 | ✅ 완료(테스트대기) | sec.py + 웹검색 |
| 포트폴리오매니저 | 실적발표일, 배당일 | ✅ 완료(테스트대기) | stock.py |
| 퀀트엔지니어 | 백테스팅 | ✅ 완료(테스트대기) | backtest.py |
| 리포트작가 | 없음 (결과 종합) | ✅ | - |

---

## 사용자 환경

- OS: Windows 11, i5-13400F, AMD RX 7600 8GB, RAM 32GB
- LM Studio: 포트 12345, Qwen3.5-9B Q4_K_M, Context 16384, GPU Offload 32
- Python: py 3.14.2 (py 명령어 사용)
- 워크스페이스: C:\project_list\NA-stock-ai (stock.py 여기에 복사해서 사용)
- Brain 폴더: C:\project_list\ai_agent_antigravity\10_Wiki\투자지식\
- update.bat: C:\project_list\connect-ai\update.bat (더블클릭으로 pull + stock.py 동기화)

---

## 핵심 원칙 (변경 금지)

1. 에이전트 내부 id 변경 금지 (이미지·tool-seeds와 연결됨)
2. 수치는 stock.py 결과만 인용, 절대 지어내지 않음
3. 9B 모델 한계 고려 — 복잡한 런타임 워크플로우보다 페르소나에 규칙 직접 주입
4. 면책고지 필수 (투자 책임은 사용자 본인)
5. 로컬 도구(.py 6종) 출력에 이모지·특수문자 금지, UTF-8 강제
6. 계산은 Python에서 끝내고 모델은 결과를 "읽어주기"만
7. 사용자 데이터(portfolio.csv·watchlist.txt)는 update.bat이 덮어쓰지 않음(없을때만 시드)

---

## 다음 세션 테스트 체크리스트 (집 PC에서 update.bat 후)

먼저 터미널에서 도구 동작 확인 (C:\project_list\NA-stock-ai):
```
py macro.py                  → indicators + regime JSON
py macro.py ^VIX             → VIX 단일
py backtest.py AAPL          → MA크로스 전략 vs 단순보유
py backtest.py AAPL rsi      → RSI 전략
py stock.py IONQ             → earningsDate·dividendYield 포함 확인
py sec.py AAPL               → 최근 공시 목록 + 원문 링크
py sec.py AAPL financials    → XBRL 공식 재무 (매출·순이익·자산·EPS)
py sec.py IONQ 10-Q          → 분기보고서만 필터
py portfolio.py              → 보유종목 손익·액션 (portfolio.csv 시드됨)
py screen.py value           → watchlist 저평가 랭킹
py screen.py momentum        → watchlist 성장모멘텀 랭킹
```
⚠️ sec.py·screen.py는 외부 서버 호출 — 첫 실행/다수 티커 시 느릴 수 있음.

그 다음 VSIX 재설치 → Reload → 새 채팅에서 에이전트별 테스트:
- [ ] 매크로분석가: "지금 시장 거시 환경 어때?" → macro.py 실행, VIX/금리/regime 인용
- [ ] 센티먼트분석가: "지금 시장 심리 공포야 탐욕이야?" → VIX 기반 진단
- [ ] 퀀트엔지니어: "AAPL MA크로스 전략 백테스트해줘" → 전략 vs 보유 수익률
- [ ] 포트폴리오매니저: "IONQ 다음 실적 언제야?" → 2026-08-06 (지어내지 않음)
- [ ] 펀더멘털분석가: "IONQ 섹터 특성 반영해서 밸류 봐줘" → 양자=P/S 잣대
- [ ] 리서처: "AAPL 최근 공시 뭐 있어?" → sec.py 공식 공시 목록+링크
- [ ] 리서처: "IONQ 공식 재무 보여줘" → sec.py financials (매출·순이익 출처:SEC)
- [ ] ⭐보유관리: "내 포트폴리오 점검해줘" → portfolio.py, 손익·action·alerts
- [ ] ⭐발굴: "저평가 종목 발굴해줘" → screen.py value 랭킹 → 상위 후보 심층분석 안내
- [ ] 지식 인용: 각 응답에 📚 출처 표기 확인

### 두 핵심 용도 통합 시나리오 (최종 목표)
- 발굴: "관심종목 중 살 만한 거 추천" → screen.py 랭킹 → 상위 1~2개 기술+펀더멘털+리스크 분석 → 진입가·손절·목표·비중 제시
- 보유관리: "내 종목들 어때, 뭐 팔까" → portfolio.py → action 종목 우선 → 각 종목 매매전략_실행법 적용

문제 발견 시 패턴: 도구 단독은 정상인데 AI가 못 쓰면 → 페르소나/system.md 지시 강화.
도구 자체가 틀리면 → .py 수정. (9B는 명령 하나만 도는 경향 → 핵심은 한 명령에 몰기.)
