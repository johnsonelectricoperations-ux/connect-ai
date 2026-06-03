# Connect AI — 미국 주식 투자 AI 진행 기록

> 이 파일은 세션 간 컨텍스트 보존용. 새 세션 시작 시 이 파일을 먼저 읽을 것.
> 마지막 업데이트: 2026-06-03

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
| 2~3주차 | 시세/재무 데이터 도구 (yfinance, 기술지표 자동계산) | 🔄 진행중 |
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

### 2~3주차 — 데이터 도구
- `stock.py` 생성 (yfinance 기반):
  - `py stock.py TICKER` → JSON: price, marketCap, trailingPE, forwardPE, priceToSales, eps, high52, low52, sector
  - `py stock.py TICKER hist` → JSON: 최근 60거래일 일봉 (date/close/volume)
- run_command 자동 분석 (v2.90.4): 명령 실행 후 결과를 AI가 자동 분석

### 상시 — 환각 방지
- system.md: "수치는 stock.py 결과만 인용, null이면 확인 실패 표기" 원칙
- 펀더멘털분석가 페르소나에 EPS 해석 규칙 직접 주입 (v2.90.6):
  - trailing EPS 양수라도 흑자 단정 금지
  - forward PER 음수 = "향후 적자 예상이라 PER 무의미" (배수로 읽지 말 것)
- brain 폴더에 지식 파일 3개:
  - `10_Wiki/투자지식/펀더멘털_지표해석.md`
  - `10_Wiki/투자지식/기술지표_해석법.md`
  - `10_Wiki/투자지식/리스크관리_규칙.md`

---

## 현재 버전: 2.90.6

### 알려진 문제 / 미해결
- [ ] `stock.py hist` 데이터에서 RSI/MACD/MA 자동 계산 없음 → AI가 raw 데이터만 받음
- [ ] 기술분석가 페르소나에 RSI/MACD 해석 규칙 미주입
- [ ] 리스크매니저 페르소나에 포지션 사이징 공식 미주입
- [ ] OpenDART / SEC Edgar 연동 없음
- [ ] 다중 에이전트 연계 (CIO가 여러 전문가 동시 호출) 미구현
- [ ] 투자일지·종목분석 brain 템플릿 없음

---

## 다음 작업 (2~3주차 완성)

### Step 1 — stock.py에 기술지표 계산 추가 ← 현재 여기
`py stock.py TICKER hist` 결과에 RSI(14), MA(20/50), MACD(12/26/9) 자동 계산 추가.
- 파일: `stock.py`
- 목표: AI가 raw 가격 대신 계산된 지표를 바로 받아 분석

### Step 2 — 기술분석가·리스크매니저 페르소나 업데이트
핵심 해석 규칙을 페르소나에 직접 주입.

### Step 3 — ceo-classifier.md 다중 에이전트 연계
복합 질문("IONQ 종합 분석") 시 기술분석가 + 펀더멘털분석가 + 리스크매니저 순서로 연계.

### Step 4 — 투자일지 brain 템플릿
종목 분석지 (brain에 저장), 투자일지 자동 기록.

---

## 사용자 환경

- OS: Windows 11, i5-13400F, AMD RX 7600 8GB, RAM 32GB
- LM Studio: 포트 12345, Qwen3.5-9B Q4_K_M, Context 16384, GPU Offload 32
- Python: py 3.14.2 (py 명령어 사용)
- 워크스페이스: C:\project_list\NA-stock-ai (stock.py 여기에도 복사 필요)
- Brain 폴더: C:\project_list\ai_agent_antigravity

---

## 핵심 원칙 (변경 금지)

1. 에이전트 내부 id 변경 금지 (이미지·tool-seeds와 연결됨)
2. 수치는 stock.py 결과만 인용, 절대 지어내지 않음
3. 9B 모델 한계 고려 — 복잡한 런타임 워크플로우보다 페르소나에 규칙 직접 주입
4. 면책고지 필수 (투자 책임은 사용자 본인)
