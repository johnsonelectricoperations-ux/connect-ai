# 투자 AI 사용 가이드

> Connect AI를 미국 주식 투자 분석용으로 개조한 시스템. 이 문서는 전체 사용법 요약.

## 1. 구성

- **본체**: VS Code 확장(connect-ai-lab.vsix) — Antigravity에 설치
- **두뇌(LLM)**: LM Studio + Qwen3.5-9B (포트 127.0.0.1:12345)
- **데이터 도구**: stock.py / macro.py / backtest.py (워크스페이스에 위치)
- **지식**: brain 폴더의 .md 파일들 (자동 인식)

## 2. 업데이트 방법

`C:\project_list\connect-ai\update.bat` 더블클릭 →
git pull + 도구 복사 + 컴파일 + VSIX 패키징까지 자동.
끝나면 Antigravity에서 .vsix 재설치 → Reload → 새 채팅.

## 3. 투자팀 (CIO + 9 전문가)

| 부르면 좋은 질문 | 담당 | 쓰는 도구 |
|----------------|------|----------|
| "차트 분석", "RSI 어때", "매매 타이밍" | 기술분석가 | stock.py hist |
| "밸류에이션", "PER 적정해?", "재무 어때" | 펀더멘털분석가 | stock.py |
| "손절 어디", "얼마나 사", "리스크" | 리스크매니저 | stock.py risk |
| "시장 거시 환경", "금리·달러 영향" | 매크로분석가 | macro.py |
| "지금 공포야 탐욕이야" | 센티먼트분석가 | macro.py ^VIX |
| "이 전략 백테스트" | 퀀트엔지니어 | backtest.py |
| "다음 실적 언제", "일정 정리" | 포트폴리오매니저 | stock.py |
| "리포트로 정리해줘" | 리포트작가 | (종합) |
| "최신 뉴스", "공시 찾아줘" | 리서처 | 웹 검색 |
| "살까 말까 종합 판단" | CIO (👔 Solo Mode) | 전체 연계 |

## 4. 데이터 도구 직접 사용 (터미널)

```
py stock.py IONQ            # 현재가·밸류에이션·재무·목표가·실적일
py stock.py IONQ hist       # 차트지표 (RSI·MA·MACD·ATR)
py stock.py IONQ risk       # 손절·포지션 사이징 (기본 $10,000)
py stock.py IONQ risk 50000 1   # 총자산 $50,000, 위험 1%
py macro.py                 # 거시 스냅샷 (VIX·금리·달러·지수…)
py macro.py ^VIX            # 특정 지표 하나
py backtest.py AAPL         # MA크로스 백테스트
py backtest.py AAPL rsi     # RSI 전략 백테스트
```

## 5. 지식(Second Brain) 운용

- brain 폴더(`ai_agent_antigravity\10_Wiki\투자지식\`)에 `.md` 넣으면 자동 인식.
- 현재 지식: 펀더멘털/기술/리스크/거시경제/시장심리/섹터별 + 템플릿 2종.
- 직접 추가 추천: 종목별 분석노트, 투자일지, 나만의 투자원칙, 손실복기.
- AI가 지식을 쓰면 응답 끝에 `📚 출처: 파일명.md` 표기.

## 6. 핵심 안전장치

- 모든 수치는 도구(yfinance) 실데이터만 인용 — 지어내지 않음.
- 계산(지표·포지션·백테스트)은 Python에서 끝내고 AI는 읽기만 → 산수 오류 차단.
- 명령 실패 시 "확인 실패"라 말하고 재실행 — 날조 금지.
- ⚠️ 투자자문 아님. 정보·교육 목적. 최종 판단·책임은 본인.

## 7. 모델 교체

- 같은 LM Studio 내 모델 변경: 설정에서 모델 이름만 바꾸면 끝(5분).
- 나중에 35B-A3B(MoE)로 올리면 분석 품질↑ (8GB+RAM32GB로 가능, 속도 5~12tok/s).
- 시스템 본체·도구·지식은 모델과 분리 → 갈아끼워도 그대로 작동.
