# Connect AI v5 §0 백테스트 검증 시스템 구현

## Phase 1: 기반 설정
- [x] `requirements.txt` 생성
- [x] `config.py` 생성

## Phase 2: 데이터 수집
- [x] `data_collector.py` — Yahoo Finance 가격 수집
- [x] `data_collector.py` — FMP 재무 수집 (API 키 필요)
- [x] `data_collector.py` — 유니버스 스냅샷 생성

## Phase 3: 데이터 관리
- [x] `db_manager.py` — DuckDB 테이블 관리

## Phase 4: 피처 생성
- [x] `feature_engine.py` — 가격 팩터 (RS, MA, RSI, 52주 위치)
- [x] `feature_engine.py` — 재무 팩터 (Revenue Growth, GM, Rule of 40 등)

## Phase 5: 팩터 검증
- [x] `factor_validator.py` — IC 계산, 분위 수익률, 통계 검정

## Phase 6: 백테스트 엔진
- [x] `backtest_engine.py` — vectorbt 포트폴리오 시뮬레이션

## Phase 7: 보고서 & CLI
- [x] `report_generator.py` — HTML 보고서 생성
- [x] `main.py` — CLI 진입점

## Phase 8: 검증
- [x] 전체 파이프라인 테스트 실행
