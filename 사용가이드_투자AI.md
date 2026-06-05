# 투자 AI 사용 가이드

> Connect AI를 미국 주식 투자 분석용으로 개조한 시스템. 이 문서는 전체 사용법 요약.

## 1. 구성

- **본체**: VS Code 확장(connect-ai-lab.vsix v3.0.2) — Antigravity에 설치
- **두뇌(LLM)**: LM Studio + Qwen3.5-9B (포트 127.0.0.1:12345)
- **데이터 도구**: stock.py / macro.py / backtest.py / sec.py / portfolio.py / screen.py (워크스페이스에 위치)
- **지식**: brain 폴더의 .md 파일들 (자동 인식)
- **자동 라우팅**: "거시 환경·백테스트·포트폴리오·발굴" 질문 → 시스템이 명령 먼저 실행 후 분석

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
| "월가 의견", "애널리스트 등급", "목표가 누가 올렸어" | 센티먼트분석가 | stock.py analyst |
| "이 전략 백테스트" | 퀀트엔지니어 | backtest.py |
| "다음 실적 언제", "일정 정리" | 포트폴리오매니저 | stock.py |
| "리포트로 정리해줘" | 리포트작가 | (종합) |
| "최신 뉴스", "공시 찾아줘" | 리서처 | sec.py + 웹 검색 |
| "내 포트폴리오 점검", "뭐 팔까" | 포트폴리오매니저 | portfolio.py |
| "저평가 종목 발굴", "살 만한 거" | 리서처 | screen.py |
| "IONQ 종합 분석해줘", "살까 말까 종합 판단" | CIO 종합 분석 | 펀더멘털+기술+리스크+거시 자동 통합 |

## 두 가지 핵심 용도

### ① 종목 발굴 → 추천
1. `watchlist.txt`에 관심 후보 티커를 모은다 (한 줄에 하나).
2. "저평가 종목 발굴해줘" / "성장주 찾아줘" → screen.py가 객관 지표로 랭킹.
3. 상위 후보를 기술+펀더멘털+리스크로 심층 검증 → 진입가·손절·목표·비중.

### ② 보유 종목 관리 → 매매
1. `portfolio.csv`에 보유 종목 기록 (ticker,shares,avg_cost,stop,target).
2. "내 포트폴리오 점검해줘" → portfolio.py가 손익·손절거리·목표거리·액션.
3. action 종목(손절임박·목표도달) 우선 → 매매전략_실행법대로 실행.

## 4. 데이터 도구 직접 사용 (터미널)

```
py stock.py IONQ            # 현재가·밸류에이션·재무·목표가·실적일
py stock.py IONQ hist       # 차트지표 (RSI·MA·MACD·ATR)
py stock.py IONQ risk       # 손절·포지션 사이징 (기본 $10,000)
py stock.py IONQ risk 50000 1   # 총자산 $50,000, 위험 1%
py stock.py IONQ analyst    # 애널리스트 등급변경·의견추세·목표가
py macro.py                 # 거시 스냅샷 (VIX·금리·달러·지수…)
py macro.py ^VIX            # 특정 지표 하나
py backtest.py AAPL         # MA크로스 백테스트
py backtest.py AAPL rsi     # RSI 전략 백테스트
py sec.py AAPL              # SEC 공시 목록 + 원문 링크
py sec.py AAPL financials   # SEC 공식 재무 (매출·순이익·자산·EPS)
py portfolio.py            # 보유종목 손익·손절·목표·매매액션
py screen.py value                    # 관심종목 저평가 랭킹 (watchlist.txt)
py screen.py momentum                 # 관심종목 성장모멘텀 랭킹
py screen.py suggest quantum          # 양자컴퓨터 테마 자동 발굴
py screen.py suggest ai momentum      # AI 테마 성장모멘텀 발굴
py screen.py suggest                  # 지원 테마 목록 출력
```

지원 테마: `quantum, ai, semiconductor, ev, biotech, defense, cloud, fintech, energy, clean, healthcare, consumer, crypto, space, robotics`

설정 파일 (워크스페이스):
- `portfolio.csv` — 보유 종목 (ticker,shares,avg_cost,stop,target)
- `watchlist.txt` — 발굴 후보 (한 줄에 티커 하나)
- 둘 다 update.bat이 처음에만 예시로 시드 → 이후 직접 편집(덮어쓰지 않음)

## 5. 지식(Second Brain) 운용

- brain 폴더(`ai_agent_antigravity\10_Wiki\투자지식\`)에 `.md` 넣으면 자동 인식.
- 현재 지식(21종): 펀더멘털/기술/리스크/거시경제/시장심리/섹터별 + 밸류에이션 기준표·실적시즌·매매오류패턴·금리환경·포지션관리·양자/AI반도체 심화·세금환율·ETF·경기사이클 + 템플릿 2종.
- 직접 추가 추천: 종목별 분석노트, 투자일지, 나만의 투자원칙, 손실복기.
- AI가 지식을 쓰면 응답 끝에 `📚 출처: 파일명.md` 표기.

## 6. 핵심 안전장치

- **자동 라우팅(v3.x)**: 투자 키워드 감지 → AI가 답하기 **전에** 시스템이 도구를 실행 → 실데이터를 컨텍스트에 주입 → 날조 원천 차단.
- 모든 수치는 도구(yfinance·SEC) 실데이터만 인용 — 지어내지 않음.
- 계산(지표·포지션·백테스트)은 Python에서 끝내고 AI는 읽기만 → 산수 오류 차단.
- screen.py 결과 해석 시 JSON에 있는 필드만 인용 — 파트너십·매출액·기술방식은 JSON에 없으면 안 씀.
- 명령 실패 시 "확인 실패"라 말하고 재실행 — 날조 금지.
- ⚠️ 투자자문 아님. 정보·교육 목적. 최종 판단·책임은 본인.

## 7. 모델 교체

- 같은 LM Studio 내 모델 변경: 설정에서 모델 이름만 바꾸면 끝(5분).
- 나중에 35B-A3B(MoE)로 올리면 분석 품질↑ (8GB+RAM32GB로 가능, 속도 5~12tok/s).
- 시스템 본체·도구·지식은 모델과 분리 → 갈아끼워도 그대로 작동.
