# Connect AI — 미국 주식 투자 AI 진행 기록

> 이 파일은 세션 간 컨텍스트 보존용. 새 세션 시작 시 이 파일을 먼저 읽을 것.
> 마지막 업데이트: 2026-06-04 (v3.0.3 — 4개 라우팅 경로 검증 완료)

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
| 4~5주차 | 백테스팅 도구 + 결정적 라우팅 시스템 (forcedArgs) | ✅ 완료 |
| 6주차 | 브레인 템플릿 (종목분석지·투자일지), 면책고지 강제화 | ✅ 템플릿 완료·배포배선 추가 |
| Solo | 종합 분석 (종목 1개 → 펀더멘털+기술+리스크+거시 통합) | ✅ v3.0.5 (멀티 프리페치) |
| 상시 | 환각 방지 가드레일, 면책고지 강제화 | ✅ v3.0.8 (면책 자동주입) |

---

## 완료된 작업

### 1주차 — 에이전트 전환
- `src/agents.ts`: 9개 에이전트를 투자 전문가로 교체 (내부 id 유지)
  - ceo→CIO, youtube→기술분석가, business→펀더멘털분석가, designer→리스크매니저
  - developer→퀀트엔지니어, secretary→포트폴리오매니저, instagram→매크로분석가
  - editor→센티먼트분석가, writer→리포트작가, researcher→리서처
- `assets/prompts/system.md`: 투자팀 정체성, 데이터 원칙, 투자 규칙 주입
- `assets/prompts/ceo-classifier.md`: 투자 도메인 라우팅 규칙

### 2~3주차 — 데이터 도구
- `stock.py` (yfinance 기반):
  - `py stock.py TICKER` → price, marketCap, trailingPE, forwardPE, priceToSales, eps, high52, low52, sector, recommendation_trend, recent_rating_changes
  - `py stock.py TICKER hist` → 60일 일봉 + RSI(14), MA(20/50), MACD(12/26/9), Signal, Histogram + summary
  - `py stock.py TICKER risk` → beta·atr14 기반 손절가·매수수량·비중·최대손실·R:R 사전계산
  - `py stock.py TICKER analyst` → 전용 애널리스트 등급변경·의견추세·목표가
- `macro.py` → VIX·S&P500·나스닥·다우·달러·10년물금리·환율·유가·금·BTC + state/regime
- `backtest.py` → MA크로스/RSI 전략, 룩어헤드 없음, 수수료 0.1%, 표본 2년
- `sec.py` → SEC EDGAR 공식 공시 목록·원문 링크·XBRL 재무
- `portfolio.py` → 보유종목 손익·손절거리·목표거리·action·alerts (portfolio.csv)
- `screen.py` → 종목발굴 value/momentum + suggest 테마 모드 (watchlist.txt)

### 에이전트 페르소나 강화
- 기술분석가: hist 실행 의무, RSI/MA/MACD 해석 규칙 주입
- 펀더멘털분석가: EPS 해석 (forward PER 음수="향후 적자 예상"), 섹터별 잣대
- 리스크매니저: 포지션 사이징 공식, R:R 1:2, ATR 손절 기준, USD 일관성
- 매크로분석가: change_pct 방향 오기재 차단 (금 +1.25%→"약세" 날조 사례)
- 퀀트엔지니어: backtest.py 강제 실행, 수치 날조 차단

---

## 현재 버전: 3.1.3

### v3.x 변경사항 — 결정적 투자 도구 라우팅 (forcedArgs 시스템)

**배경 문제**: 9B 모델이 자발적으로 도구를 잘 호출하지 않아 데이터 없이 날조하거나,
호출해도 타이밍이 늦고 followUp 루프가 불안정했음.

**v3.0.0 — 사전 실행(prefetch) 시스템**
- `_detectInvestmentCommand(prompt)`: 사용자 프롬프트에서 투자 도구 키워드 감지
  - "거시 환경" → `macro.py`
  - "백테스트/골든크로스" → `backtest.py TICKER`
  - "포트폴리오 점검" → `portfolio.py`
  - "종목 발굴/양자컴퓨터" → `screen.py suggest quantum value` 등
- LLM 호출 **전에** 시스템이 명령을 실행 → 결과를 `forcedToolContext`로 system prompt에 주입
- 모델은 이미 받은 데이터로 분석만 하면 됨 → 날조 원천 차단
- 사용자에게 `> 🖥️ [자동 실행] py -3 명령` 즉시 표시

**v3.0.1 — 이중 실행 버그 수정**
- **문제**: 9B가 forcedToolContext 지시를 무시하고 `<run_command>` 태그를 출력
  → cmdReads가 감지해 followUp이 같은 명령을 재실행 (두 번 실행)
  → 또는 cmdReads=[] 로 막으면 followUp 자체가 안 돼서 "▶ py 명령" 후 멈춤
- **수정**: `cmdReadsRaw` 감지는 하되 `cmdReads=[]` 유지. `needsForcedFollowUp=true`일 때
  `forcedToolOutput`(사전 실행 결과)을 `fetchedContent`에 주입 → followUp 발동·분석 출력
- `_executeActions`에 `skipRunCommand:true` → ACTION 6 경로 이중 실행 차단
- `_stripForcedToolNotice` 헬퍼: 히스토리 저장 시 "[자동 실행]" notice 제거
  → 다음 턴에 9B가 이 패턴 흉내내 중복 출력하던 문제 차단

**v3.0.2 — screen 환각 차단 + screen.py 데이터 보강**
- **문제**: screen.py 출력에 없는 데이터(매출 금액·파트너십·기술방식·시총·52주 최고/저)를
  9B가 전부 날조. IBM/IONQ에 동일 "Microsoft·Oracle·BMW 파트너십" 복붙.
- **수정**:
  - `screen.py`에 누락 필드 추가: `fiftyTwoWeekHigh`, `fiftyTwoWeekLow`, `marketCap`, `trailingPE`
  - `screen.py` 출력에 `fields_only` 지시 주입 → 모델에게 "이 필드 목록만 사용 가능" 명시
  - `forcedToolContext`에 강화된 환각 차단 지침 ("여러 종목에 동일 정성 설명 복붙=날조")
  - `_stripStrayCommandEcho`: 모델이 본문에 흉내낸 "▶ py ..." echo 줄 제거
  - display/history 저장 분리: 히스토리엔 notice 전부 제거(흉내 방지), 표시엔 정당한 [자동 실행] 유지

**v3.0.3 — 미검증 4개 라우팅 경로 키워드 보강 + 검증 완료**
- **문제**: `_detectInvestmentCommand`의 4개 키워드 감지 정규식이 너무 좁아
  흔한 투자 질문이 라우팅을 못 타고 `return null`로 떨어짐(9B 폴백 → 날조 위험).
- **수정**: 4개 정규식 확장 (extension.ts 679~689줄)
  - hasRisk: 손절·포지션사이징·비중·매수수량·ATR·R:R 등 추가
  - hasChart: RSI·볼린저·지지/저항·캔들·추세 등 기술분석 전반 포함 (단, "rsi" 단독은 backtest 우선)
  - hasSec: 공시·10-K/Q·사업보고서·EDGAR·IR자료 등 추가
  - hasFundamental: 재무·PER/EPS/ROE·매출/이익·순이익·영업이익 단독 쿼리 포함
- 27개 인라인 단위테스트 전부 통과 + 집 PC 라이브 테스트 통과:
  - "IONQ 차트 분석해줘" → stock.py IONQ hist (기술분석가) ✅
  - "IONQ 손절 어디야" → stock.py IONQ risk (리스크매니저) ✅
  - "AAPL 공시 뭐 있어" → sec.py AAPL (리서처) ✅
  - "IONQ 재무 어때" → stock.py IONQ (펀더멘털분석가) ✅

**v3.0.5 — 종합 분석(Solo) 멀티 프리페치**
- **목표**: "IONQ 종합 분석해줘" → 한 종목을 펀더멘털+기술+리스크+거시 통합 브리핑.
- **설계 선택**: 무거운 multi-agent(_handleCorporatePrompt) 대신 **검증된 forcedArgs
  주입 메커니즘 재사용**(원칙 #3: 복잡한 워크플로우보다 직접 주입). 일반 채팅 경로에서 동작.
- **구현** (extension.ts):
  - `_detectComprehensiveAnalysis(prompt)`: "종합/전반적/다각도/풀 분석" + 티커 감지.
    포트폴리오·발굴·티커 없는 "종합 시황"은 제외(기존 라우팅에 양보).
  - forcedArgs 블록에 분기 추가: 매칭 시 `stock.py TK`·`stock.py TK hist`·
    `stock.py TK risk`·`macro.py` 4개를 순차 사전 실행 → 하나의 forcedToolContext로 결합.
  - CIO 통합 지침 주입: ①결론 ②펀더멘털 ③기술 ④리스크 ⑤거시영향 ⑥종합의견+면책.
  - 단일 `[자동 실행] 종합 분석 — TK 펀더멘털·기술·리스크 + 거시` notice 1회 표시.
  - downstream(cmdReads 억제·skipRunCommand)은 forcedArgs 진위값만 보므로 sentinel로 호환.
- 15개 인라인 단위테스트 통과 (종합 7건 티커 추출 + 비대상 8건 null).
- **v3.0.6 핫픽스**: 종합 블록이 `isAborted()`(=_handleCorporatePrompt 전용 헬퍼)를
  호출 → _handlePrompt엔 없어 "isAborted is not defined" 런타임 오류.
  `this._abortController?.signal.aborted`로 교체. (교훈: forcedArgs 블록은
  _handlePrompt 컨텍스트라 corporate 헬퍼 사용 불가.)
- **v3.0.6 라이브 검증 통과**: "IONQ 종합 분석해줘" → [자동 실행] 1회 + 6섹션 정상,
  이중 실행·stray 명령줄 없음. 단, 2개 결함 발견 → v3.0.7에서 수정.
- **v3.0.7 결함 2종 수정**:
  1. profitMargin 날조: yfinance가 IONQ(적자)에 1.7488(=174.88%) 오류값 반환 →
     stock.py에 sanity check 추가(>100% 또는 <-1000%면 null + data_warnings).
  2. 중국어 혼입(经营·现金流 등): system.md:80 규칙만으론 부족 → 종합
     forcedToolContext에 한국어 강제 지침(🈲) 추가로 생성 지점에서 재차 차단.
- **v3.0.7 라이브 검증 통과**: Profit Margin 미제공 처리 확인, 중국어 혼입 없음.
  **종합 분석 기능 완전 완성.**

**v3.0.8 — 면책고지 강제화 (가드레일 마무리, Step C)**
- **문제**: 면책은 system.md:110 지침일 뿐, 9B가 단일 답변에서 종종 누락 → 규제/법적 리스크.
- **수정**: _handlePrompt 스트림 종료 직전, forcedArgs(투자 도구 실행) 답변에 면책 문구가
  없으면(`면책|투자 판단|책임은 본인|정보·교육|투자자문` 미감지) 표준 면책을 자동 덧붙임.
  - 이미 면책이 있으면 중복 추가 안 함(7/7 단위테스트로 검증).
  - screen.py fields_only 가드레일은 v3.0.2부터 적용 중(정성정보 날조 차단).

**v3.0.9 — 보유관리 통합 흐름 (Step B)**
- **목표(핵심 용도 #2)**: "내 종목들 어때, 뭐 팔까" → portfolio.py → action 종목 우선 매매전략.
- **구현** (extension.ts forcedArgs 블록): `forcedArgs === 'portfolio.py'` 전용 분기.
  - portfolio.py 실행 → 출력 JSON `summary.alerts`에서 action 종목(hold 외) 추출.
  - action 종목(최대 3개)에 `stock.py TICKER risk` 추가 프리페치 → 손절/포지션 데이터 결합.
  - 모델 지침: STOP_BREACHED=손절검토, TARGET_HIT=익절검토, near_*=관찰. 액션종목 우선
    "어디서·왜 팔지" 구체 제시. 액션 없으면 "매도 시그널 없음 — 보유 유지".
  - 단일 `[자동 실행] 포트폴리오 점검 + 액션종목 ... 손절·포지션` notice.
- alerts 파싱 단위테스트 통과(3개 캡·빈/오류 JSON·중복 제거). **집 PC 라이브 검증 대기.**

**v3.1.0 — 발굴 통합 흐름 (Step A)**
- **목표(핵심 용도 #1)**: "살 만한 거 추천" → screen.py 랭킹 → 상위 후보 검증 → 진입가·손절·목표·비중.
- **구현** (extension.ts forcedArgs 블록): `forcedArgs.startsWith('screen.py')` 전용 분기.
  - screen.py 실행 → 출력 JSON `ranked[]`(score 내림차순)에서 상위 2개 ticker 추출.
  - 상위 후보에 `stock.py TICKER risk` 추가 프리페치 → 진입·손절·목표·비중 결합.
  - 모델 지침: ①랭킹 요약(score·reasons) ②상위 1~2개 심층(진입가·손절가·목표가·비중) ③결론.
    screen은 1차 객관 랭킹이지 추천 아님을 명시 + 정성정보 날조 차단(복붙=날조).
  - 단일 `[자동 실행] 종목 발굴 + 상위후보 ... 검증` notice.
- ranked 파싱 단위테스트 통과(상위 2개·빈/오류 JSON).
- **v3.1.0 라이브 검증 통과**: RGTI·QUBT 진입·손절·목표·비중 실데이터, 파트너십 날조 없음 ✅
- **v3.1.1 핫픽스**: 포트폴리오·발굴 경로에 한국어 강제 지침(🈲) 누락 → 均未 혼입 발생.
  두 경로 forcedToolContext에 동일 규칙 추가. (종합 분석은 v3.0.7에서 이미 적용됨.)

**v3.1.2 — 데이터 sanity check 확대 (저장 기반 다지기)**
- **배경**: 자동 저장(투자일지·지식 적재)을 만들기 전, 저장될 수치가 정확해야 함.
  기존엔 profitMargin 한 필드만 검증 → yfinance의 다른 오류값(적자기업 ROE 폭주,
  배당수익률 소수/퍼센트 단위 혼동, 애널리스트 0명일 때 목표가 왜곡)은 무방비였음.
- **구현** (stock.py): `_reject(field, low, high, reason)` 헬퍼로 범위 검증 일반화.
  - `profitMargin`: [-10.0, 1.0]  (순이익률 +100% 초과·-1000% 미만 = 오류)
  - `roe`: [-10.0, 10.0]  (자본잠식 기업 폭주값 차단)
  - `revenueGrowth`: [-1.0, 50.0]  (-100% 미만 불가능, +5000% 초과 오류)
  - `dividendYield`: [0.0, 1.0]  (yfinance 퍼센트형 혼입 차단)
  - `beta`: [-10.0, 10.0]
  - 애널리스트 정합성: `numAnalysts`가 0/없음 → 목표가·추천 신뢰 불가로 None 처리.
  - 거른 필드는 None + `data_warnings`에 사유 → 모델이 복원·추정 못 함.
- 단위테스트 통과(정상 대형주 무오검출·IONQ형 오류주 차단·배당 단위혼동·경계값 허용).
  **집 PC 라이브 검증 대기(AAPL·IONQ·SPY).**

**v3.1.3 — 투자 지식팩 확장 (11종 → 21종)**
- **배경**: 시스템에 폭넓은 판단 기준 주입. 기존 11종은 기초 분석 위주라 섹터·상황별
  판단 공백이 있었음. AI가 인용할 구체 기준서 10종 신규 작성.
- **신규 지식** (`knowledge-pack/10_Wiki/투자지식/`, +463줄):
  - `밸류에이션_기준표` — 섹터별 정상 PER/PSR 범위·프리미엄 경계
  - `실적시즌_전략` — 어닝 전후 행동 원칙·서프라이즈·갭 대응
  - `매매_오류패턴` — FOMO·물타기·확증편향 등 9종 경고 트리거
  - `금리환경별_전략` — 인상/동결/인하 국면별 자산·섹터
  - `포지션_단계별관리` — 분할 진입·피라미딩·분할 청산·비중 한도
  - `양자컴퓨터_섹터심화` / `AI반도체_섹터심화` — 테마별 구조·리스크
  - `미국주식_세금환율` — 한국 거주자 양도세·배당세·환율
  - `ETF_투자가이드` — 유형별·레버리지 경고·코어새틀라이트
  - `경기사이클_섹터로테이션` — 4국면별 주도 섹터
- 모든 파일이 기존 규격 준수(담당 에이전트 헤더 + stock.py/macro.py 필드 연결 + 날조 금지 원칙).
- update.bat이 brain 폴더로 자동 배포 → 다음 분석부터 컨텍스트 인식.

> 🎯 두 핵심 용도(발굴→추천, 보유관리→매매전략) 통합 흐름 + 종합 분석 + 면책 강제화 완성.
> 데이터 sanity check + 지식팩 21종으로 분석 기반 강화. 남은 것은 집 PC 라이브 검증.

### 로컬 도구 6종 (전부 워크스페이스에 복사됨 via update.bat)
- `stock.py`  — 시세·밸류·재무·목표가·실적일 + hist(지표) + risk(포지션사이징) + analyst
- `macro.py`  — VIX·금리·달러·환율·지수·유가·금 + regime
- `backtest.py` — MA크로스/RSI 전략 백테스트
- `sec.py`    — SEC EDGAR 공식 공시·재무
- `portfolio.py` — 보유종목 손익·손절·목표·액션 (portfolio.csv)
- `screen.py` — 종목발굴 랭킹 value/momentum + suggest 테마 (watchlist.txt)

### v3.0.x 검증 완료 (집 PC 테스트 통과)
- ✅ macro: "[자동 실행]" 1회만, 실시간 VIX·금리·regime 분석 정상
- ✅ backtest: 이전 "▶ py 후 멈춤" 해결, 전략 vs 단순보유 비교 출력
- ✅ portfolio: 보유종목 손익·action·alerts 정상
- ✅ screen: "[자동 실행]" 중복 없음 (v3.0.2: 환각은 추가 검증 대기)
- ✅ 연속 4개 질문: 이중 실행 없음, 각 답변 독립 정상 작동
- ✅ (v3.0.3) 기술분석가(hist)·리스크매니저(risk)·리서처(sec)·펀더멘털분석가(stock)
  4개 라우팅 경로 라이브 통과 → **9개 에이전트 데이터 연결 전부 검증 완료**

---

## 다음 작업

### Step 4 — 종합 분석 흐름 ✅ 완료 (v3.0.5)
"IONQ 종합 분석해줘" → 펀더멘털+기술+리스크+거시 4개 도구 사전 실행 → CIO 통합.
- 원래 Solo Mode(_handleCorporatePrompt) 대신 forcedArgs 멀티 프리페치로 구현(안전·빠름).
- **집 PC 라이브 검증 필요** (아래 체크리스트 참고).

### Step 5 — 브레인 템플릿 (6주차) ✅ 완료
종목 분석지·투자일지 brain 템플릿 — `knowledge-pack/10_Wiki/투자지식/`에 존재
(`_템플릿_종목분석지.md`, `_템플릿_투자일지.md` + 지식 9종).
- (v3.0.4) update.bat에 `[3a]` 배포 단계 추가 → 집 PC pull 시 brain `10_Wiki`로 동기화.
  xcopy /Y라 사용자 분석노트(티커_분석노트.md·YYYY_투자일지.md)는 삭제 안 됨(보존).

### Phase 7 — 24시간 자율 투자 (👔 ON 모드 활용) 📋 계획 확정·미착수
> 배경: 원본은 "콘텐츠 1인 기업 OS"라 자율 작업이 유튜브·글쓰기였음. 우리는 투자로 전환했으므로
> 24시간 자율(👔 ON)도 투자 작업으로 재정의한다. 기존 인프라 재사용:
> - 자율 사이클: `autoCycleEnabled`(기본 ON), 15분마다 CEO가 자동 디스패치 (_handleCorporatePrompt)
> - 데일리 브리핑: 매일 09:00 텔레그램 발송 (현재 원본 잔재 = 캘린더·할일·매출·유튜브 블록)
> - 텔레그램 출력: 자리 비워도 폰으로 알림
> ⚠️ 주의: 투자 forcedArgs는 현재 _handlePrompt(👔 OFF)에만 있음. 자율 작업은 _handleCorporatePrompt
>   또는 데일리 브리핑 경로라 별도로 도구를 직접 호출해 결과를 주입하는 방식으로 구현해야 함.

4가지 작업 (우선순위 순):

**② 보유종목 감시 알림** ⭐ 최우선 — "24시간 ON"의 핵심 가치
- 15분 자율 사이클마다 portfolio.py 실행 → action 플래그(STOP_BREACHED/TARGET_HIT/near_*)
  발생 시에만 텔레그램 알림. ("🔴 AAPL 목표가 도달 — 익절 검토")
- 스팸 방지: 같은 종목·같은 action은 하루 1회만 알림(중복 억제 키 필요).
- 핵심 용도 #2(보유관리)에 직결.

**① 투자 모닝 브리핑** — 원본 데일리 브리핑을 투자판으로 교체
- 매일 09:00(장 열기 전) macro.py + portfolio.py 자동 실행 →
  "오늘 시황(regime·VIX·금리·환율) + 내 보유 손익·액션 + 오늘 주의점" 텔레그램.
- 구현 위치: extension.ts 데일리 브리핑 빌더(_buildDailyBriefing 류, ~3859줄 body 조립부).

**③ 관심종목 발굴 스캔** — 핵심 용도 #1(발굴)에 직결
- 하루 1~2회 screen.py로 watchlist 랭킹 → 새 저평가 진입·점수 급등 종목 알림.
- 전일 랭킹 대비 변화 감지 필요(상태 저장: 마지막 스캔 결과 캐시).

**④ 거시·공시 급변 감지**
- macro.py regime이 risk-on→risk-off 전환 또는 VIX 급등 시 경고.
- 보유·관심 종목 earningsDate 임박 또는 sec.py 새 공시 시 알림.
- ⚠️ 잦은 오탐 가능성 → 임계값·쿨다운 신중히 설계.

구현 시 공통 고려사항:
- 알림 스팸 방지(중복 억제·쿨다운)가 자율 작업의 성패를 가름.
- 자율 작업도 면책·환각 가드레일 동일 적용.
- 텔레그램 토큰 미설정 시 silently skip(브리핑 인프라 기존 패턴 따름).

### 보류
- 증권사 API (잔고/주문 자동화): 별도 단계 (실매매는 규제·보안 리스크 큼)
- 공포탐욕지수 CNN API: 현재 VIX로 대용, 필요시 추가

---

## 에이전트별 데이터 연결 현황

| 에이전트 | 필요 데이터 | 상태 | 연결 방법 |
|---------|-----------|------|---------|
| 기술분석가 | RSI, MA, MACD, ATR | ✅ 완료·검증 | stock.py hist |
| 펀더멘털분석가 | PER, EPS, 재무제표, 목표가 | ✅ 완료·검증 | stock.py |
| 리스크매니저 | 베타(β), ATR, 포지션사이징 | ✅ 완료·검증 | stock.py risk |
| 매크로분석가 | 금리, VIX, DXY, 환율 | ✅ 완료·검증 | macro.py |
| 센티먼트분석가 | VIX, 공포탐욕지수 | ✅ VIX 연결·검증 | macro.py |
| 리서처 | 뉴스, SEC 공시, 종목발굴 | ✅ 완료·검증 | sec.py + screen.py + 웹검색 |
| 포트폴리오매니저 | 실적발표일, 배당일, 보유현황 | ✅ 완료·검증 | stock.py + portfolio.py |
| 퀀트엔지니어 | 백테스팅 | ✅ 완료·검증 | backtest.py |
| 리포트작가 | 없음 (결과 종합) | ✅ | - |

---

## 사용자 환경

- OS: Windows 11, i5-13400F, AMD RX 7600 8GB, RAM 32GB
- LM Studio: 포트 12345, Qwen3.5-9B Q4_K_M, Context 16384, GPU Offload 32
- Python: py 3.14.2 (py 명령어 사용)
- 워크스페이스: C:\project_list\NA-stock-ai (stock.py·도구들 여기에 복사)
- Brain 폴더: C:\project_list\ai_agent_antigravity\10_Wiki\투자지식\
- update.bat: C:\project_list\connect-ai\update.bat (더블클릭으로 pull + 도구 동기화)

---

## 핵심 원칙 (변경 금지)

1. 에이전트 내부 id 변경 금지 (이미지·tool-seeds와 연결됨)
2. 수치는 도구(.py) 결과만 인용 — 절대 지어내지 않음
3. 9B 모델 한계 고려 — 복잡한 런타임 워크플로우보다 페르소나에 규칙 직접 주입
4. 면책고지 필수 (투자 책임은 사용자 본인)
5. 로컬 도구(.py 6종) 출력에 이모지·특수문자 금지, UTF-8 강제
6. 계산은 Python에서 끝내고 모델은 결과를 "읽어주기"만
7. 사용자 데이터(portfolio.csv·watchlist.txt)는 update.bat이 덮어쓰지 않음 (없을 때만 시드)
8. 도구 JSON에 없는 정성 정보(파트너십·기술방식·점유율)는 지어내지 말 것

---

## 9B 모델 대응 핵심 교훈

- 자발적 도구 호출을 믿지 말 것 → 시스템이 먼저 실행(forcedArgs)하고 결과를 주입.
- 모델은 명령 하나만 도는 경향 → 핵심 지표를 한 명령에 몰아서 제공.
- 지시를 무시하고 `<run_command>` 태그를 또 출력함 → skipRunCommand + cmdReadsRaw 분리.
- 히스토리에 UI 알림("🖥️ [자동 실행]")이 남으면 다음 턴에 그대로 흉내냄 → strip 필수.
- JSON에 없는 빈칸은 날조로 채움 → fields_only 지시 + 데이터 직접 제공이 이중 차단.
- stock.py 출력에 이모지·특수문자 금지 (Windows cp949 크래시 → AI 날조 근본원인).

---

## 다음 세션 테스트 체크리스트 (집 PC에서 update.bat 후)

먼저 터미널 직접 확인 (C:\project_list\NA-stock-ai):
```
py macro.py                      → indicators + regime JSON
py backtest.py IONQ              → MA크로스 전략 vs 단순보유
py screen.py suggest quantum     → 양자 테마 랭킹 (fiftyTwoWeekHigh·marketCap 포함 확인)
py portfolio.py                  → 보유종목 손익·action
```

VSIX 재설치 → Reload → 새 채팅 연속 테스트:
- [ ] "지금 시장 거시 환경 어때?" → [자동 실행] 1회, macro 분석
- [ ] "IONQ 골든크로스 백테스트해줘" → [자동 실행] 1회, 전략 vs 보유 비교
- [ ] "내 포트폴리오 점검해줘" → [자동 실행] 1회, 손익·action·alerts
- [ ] "양자컴퓨터 종목 발굴해줘" → [자동 실행] 1회, 실제 필드만 인용 (파트너십 날조 없음)
- [ ] "▶ py ..." 같은 stray 명령줄이 본문에 안 나타나는지 확인
- [x] (v3.0.7) "IONQ 종합 분석해줘" → [자동 실행] 1회, 6섹션 정상, 날조 없음, 중국어 없음 ✅

### 두 핵심 용도 통합 시나리오 (최종 목표)
- 발굴: "관심종목 중 살 만한 거 추천" → screen.py 랭킹 → 상위 1~2개 기술+펀더멘털+리스크 분석 → 진입가·손절·목표·비중
- 보유관리: "내 종목들 어때, 뭐 팔까" → portfolio.py → action 종목 우선 → 매매전략 적용

문제 발견 시 패턴:
- 도구 단독은 정상인데 AI가 못 쓰면 → 페르소나/system.md 지시 강화
- 도구 자체가 틀리면 → .py 수정
- 날조 발생하면 → forcedToolContext 지시 강화 + 해당 필드 도구에 추가
