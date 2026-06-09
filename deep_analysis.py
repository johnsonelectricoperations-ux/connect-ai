#!/usr/bin/env python3
# Connect AI · Deep Analysis + Conviction Band (v5 §2)
#
# 사용법:
#   py deep_analysis.py IONQ               → Deep Analysis 실행 + watchlist.json 저장
#   py deep_analysis.py IONQ --no-save     → 저장 없이 결과만 출력
#   py deep_analysis.py IONQ --force       → watchlist.json 이미 있어도 덮어쓰기
#
# 흐름:
#   1. yfinance로 재무·밸류에이션·애널리스트 데이터 수집
#   2. news.py로 최신 뉴스 헤드라인 수집 (선택)
#   3. macrotrends.py로 10년 성장 지속성 수집 (선택)
#   4. dataroma.py로 슈퍼인베스터 현황 수집 (선택)
#   5. 로컬 LLM(Ollama)에 분석 요청
#   6. Conviction Band 산출 (상/중/하) — BAND_HIGH=38, BAND_MID=28
#   7. watchlist.json 저장
#
# LLM 설정: system_schema.json → ollama_url, default_model
# 기본값: http://127.0.0.1:11434, gemma4:e2b
#
# 확증편향 차단(v5 §2): 프롬프트에서 bear_case·key_risks 먼저 작성 강제.

import sys, json, os, math, subprocess
from datetime import datetime, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_DIR         = Path(__file__).resolve().parent
_SCHEMA_PATH = _DIR / "system_schema.json"
_WL_PATH     = _DIR / "watchlist.json"

# 사용자 확정 파라미터 (2026-06-09)
BAND_HIGH = 38   # Conviction '상' 하한 (raw 0~50)
BAND_MID  = 28   # Conviction '중' 하한 (이 미만 = '하' → 매수 차단)


def _sanitize(obj):
    if isinstance(obj, float):
        return None if (math.isinf(obj) or math.isnan(obj)) else obj
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return obj


# ─────────────────────────────────────────────────────────────
# LM Studio 설정 로드
# ─────────────────────────────────────────────────────────────
# LM Studio: http://127.0.0.1:12345 (OpenAI 호환 API)
# 모델명은 system_schema.json → default_model 에서 읽음.
# 집에서 모델 변경 시 system_schema.json 의 default_model 만 수정하면 됨.

def _load_llm_config():
    """system_schema.json 에서 lm_studio_url, default_model 읽기.
    키 우선순위: lm_studio_url > ollama_url (하위 호환) → 기본값 포트 12345."""
    defaults = {"url": "http://127.0.0.1:12345", "model": "TODO"}
    if not _SCHEMA_PATH.exists():
        return defaults
    try:
        with open(_SCHEMA_PATH, encoding="utf-8") as f:
            schema = json.load(f)
        eng = schema.get("configuration", {}).get("engine_options", {})
        url = (eng.get("lm_studio_url")
               or eng.get("ollama_url")
               or defaults["url"])
        model = eng.get("default_model") or defaults["model"]
        return {"url": url.rstrip("/"), "model": model}
    except Exception:
        return defaults


# ─────────────────────────────────────────────────────────────
# 데이터 수집
# ─────────────────────────────────────────────────────────────

def _run_tool(script_name, *args):
    """py {script_name}.py {args} 실행 → JSON dict 반환. 실패 시 None."""
    cmd = [sys.executable, str(_DIR / f"{script_name}.py")] + list(args)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=60, cwd=str(_DIR), encoding="utf-8")
        raw = (r.stdout or "").strip()
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return None


def collect_data(yf, ticker):
    """yfinance + 보조 도구로 Deep Analysis 입력 데이터 구성."""
    data = {"ticker": ticker}

    # yfinance 기본 정보
    try:
        t    = yf.Ticker(ticker)
        info = t.info or {}

        data["name"]             = info.get("shortName") or info.get("longName") or ticker
        data["sector"]           = info.get("sector")
        data["industry"]         = info.get("industry")
        data["business_summary"] = (info.get("longBusinessSummary") or "")[:600]
        data["market_cap_b"]     = round(info["marketCap"] / 1e9, 2) if info.get("marketCap") else None
        data["revenue_growth_pct"] = round(info["revenueGrowth"] * 100, 1) if info.get("revenueGrowth") is not None else None
        data["gross_margin_pct"]   = round(info["grossMargins"] * 100, 1) if info.get("grossMargins") is not None else None
        data["operating_margin_pct"] = round(info["operatingMargins"] * 100, 1) if info.get("operatingMargins") is not None else None
        data["profit_margin_pct"]  = round(info["profitMargins"] * 100, 1) if info.get("profitMargins") is not None else None

        # FCF·Cash
        fcf  = info.get("freeCashflow")
        cash = info.get("totalCash")
        data["fcf_positive"]      = (fcf > 0) if fcf is not None else None
        data["fcf_m"]             = round(fcf / 1e6, 1) if fcf is not None else None
        data["cash_m"]            = round(cash / 1e6, 1) if cash is not None else None
        if cash and fcf is not None and fcf < 0:
            q_burn = abs(fcf) / 4
            data["cash_runway_q"] = round(cash / q_burn, 1) if q_burn > 0 else None
        else:
            data["cash_runway_q"] = 99 if (fcf is not None and fcf >= 0) else None

        # D/E
        raw_dte = info.get("debtToEquity")
        if raw_dte is not None:
            try:
                dte = float(raw_dte)
                data["debt_to_equity"] = round(dte / 100 if abs(dte) > 5 else dte, 2)
            except Exception:
                pass

        # 밸류에이션
        data["forward_pe"]     = info.get("forwardPE")
        data["price_to_sales"] = info.get("priceToSalesTrailing12Months")

        # 애널리스트
        data["num_analysts"]   = info.get("numberOfAnalystOpinions") or info.get("numAnalysts")
        data["recommendation"] = info.get("recommendationKey")
        data["target_mean"]    = info.get("targetMeanPrice")

        # CEO
        officers = info.get("companyOfficers") or []
        ceo = next((o.get("name") for o in officers
                    if "ceo" in (o.get("title") or "").lower()), None)
        data["ceo"] = ceo

        # 주요 고객·경쟁사 (yfinance 미제공, 사용자가 아는 경우 향후 확장)
        data["major_customers"] = None
        data["competitors"]     = None

    except Exception as e:
        data["fetch_error"] = str(e)

    # news.py — 최신 뉴스 헤드라인 5건
    news_result = _run_tool("news", ticker, "5")
    if news_result and isinstance(news_result, dict):
        items = news_result.get("news") or news_result.get("items") or []
        data["recent_news"] = [n.get("title") for n in items[:5] if n.get("title")]
    else:
        data["recent_news"] = []

    # macrotrends.py — 10년 성장 지속성
    mt_result = _run_tool("macrotrends", ticker, "revenue")
    if mt_result and isinstance(mt_result, dict) and not mt_result.get("error"):
        stats = mt_result.get("stats") or mt_result.get("revenue", {})
        if isinstance(stats, dict):
            data["mt_consecutive_growth_years"] = stats.get("consecutive_growth_years")
            data["mt_cagr_5yr_pct"] = round(stats.get("cagr_5yr", 0) * 100, 1) if stats.get("cagr_5yr") is not None else None

    # dataroma.py — 슈퍼인베스터 현황
    dt_result = _run_tool("dataroma", ticker)
    if dt_result and isinstance(dt_result, dict) and not dt_result.get("error"):
        summary = dt_result.get("summary", {})
        data["superinvestor_signal"]  = summary.get("signal")
        data["superinvestor_holders"] = summary.get("holder_count")
        data["superinvestor_recent_action"] = summary.get("recent_action")

    return data


# ─────────────────────────────────────────────────────────────
# 프롬프트 구성
# ─────────────────────────────────────────────────────────────

def build_prompt(data):
    """v5 §2 설계: bear_case·key_risks 먼저 작성 강제 → 확증편향 차단."""

    def _fmt(v, suffix=""):
        return f"{v}{suffix}" if v is not None else "N/A"

    lines = [
        f"ticker: {data['ticker']}",
        f"name: {data.get('name', 'N/A')}",
        f"sector: {_fmt(data.get('sector'))}",
        f"industry: {_fmt(data.get('industry'))}",
        f"market_cap_b: ${_fmt(data.get('market_cap_b'))}B",
        f"business_summary: {data.get('business_summary') or 'N/A'}",
        "",
        "--- 재무 ---",
        f"revenue_growth: {_fmt(data.get('revenue_growth_pct'), '%')}",
        f"gross_margin: {_fmt(data.get('gross_margin_pct'), '%')}",
        f"operating_margin: {_fmt(data.get('operating_margin_pct'), '%')}",
        f"fcf_positive: {_fmt(data.get('fcf_positive'))}",
        f"fcf_million_usd: {_fmt(data.get('fcf_m'), 'M')}",
        f"cash_runway_quarters: {_fmt(data.get('cash_runway_q'))}",
        f"debt_to_equity: {_fmt(data.get('debt_to_equity'))}",
        "",
        "--- 밸류에이션·애널리스트 ---",
        f"price_to_sales: {_fmt(data.get('price_to_sales'))}",
        f"forward_pe: {_fmt(data.get('forward_pe'))}",
        f"analyst_recommendation: {_fmt(data.get('recommendation'))}",
        f"analyst_target_mean: {_fmt(data.get('target_mean'))}",
        f"num_analysts: {_fmt(data.get('num_analysts'))}",
        "",
        "--- 경영진·슈퍼인베스터 ---",
        f"ceo: {_fmt(data.get('ceo'))}",
        f"superinvestor_signal: {_fmt(data.get('superinvestor_signal'))}",
        f"superinvestor_holders: {_fmt(data.get('superinvestor_holders'))}",
        "",
        "--- 장기 성장 이력 ---",
        f"macrotrends_consecutive_growth_years: {_fmt(data.get('mt_consecutive_growth_years'))}",
        f"macrotrends_cagr_5yr: {_fmt(data.get('mt_cagr_5yr_pct'), '%')}",
        "",
        "--- 최신 뉴스 헤드라인 ---",
    ]

    news = data.get("recent_news") or []
    if news:
        for i, h in enumerate(news, 1):
            lines.append(f"{i}. {h}")
    else:
        lines.append("(뉴스 없음)")

    data_block = "\n".join(lines)

    prompt = f"""당신은 성장주 투자 분석가입니다. 아래 데이터를 바탕으로 종목을 평가하세요.

중요 지침:
1. 확증편향 차단: bear_case와 key_risks를 bull_case보다 먼저, 더 엄격하게 작성하세요.
2. "이 종목을 사지 말아야 할 이유"를 먼저 찾으세요. 데이터가 합리화를 부르는 함정에 주의하세요.
3. 모든 점수(0~10)는 최악=0, 최선=10 기준입니다.
4. 반드시 아래 JSON 형식만 출력하세요. 다른 텍스트는 절대 포함하지 마세요.

[입력 데이터]
{data_block}

[출력 형식 - 이 JSON만 출력]
{{
  "bear_case": ["매수 반대 이유 1", "매수 반대 이유 2", "매수 반대 이유 3"],
  "key_risks": ["핵심 리스크 1", "핵심 리스크 2", "핵심 리스크 3"],
  "bull_case": ["매수 찬성 이유 1", "매수 찬성 이유 2", "매수 찬성 이유 3"],
  "business_quality": 0,
  "competitive_advantage": 0,
  "execution_risk": 0,
  "dilution_risk": 0,
  "tam_score": 0,
  "summary": "한두 문장 요약"
}}"""

    return prompt


# ─────────────────────────────────────────────────────────────
# Ollama 호출
# ─────────────────────────────────────────────────────────────

def call_ollama(prompt, config):
    try:
        import urllib.request as _ur, urllib.error as _ue
    except ImportError:
        return None, "urllib 없음"

    # LM Studio OpenAI 호환 API: POST /v1/chat/completions
    payload = json.dumps({
        "model": config["model"],
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,   # 낮은 temperature: 일관된 JSON 출력
        "top_p": 0.9,
        "stream": False,
    }).encode("utf-8")

    try:
        req = _ur.Request(
            f"{config['url']}/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with _ur.urlopen(req, timeout=300) as resp:
            raw    = resp.read().decode("utf-8")
            result = json.loads(raw)
            content = (result.get("choices", [{}])[0]
                       .get("message", {})
                       .get("content", "")
                       .strip())
            return content, None
    except _ue.URLError as e:
        return None, (f"LM Studio 연결 실패: {e} "
                      f"— LM Studio가 실행 중이고 '{config['url']}' 에서 서버가 켜져 있는지 확인")
    except Exception as e:
        return None, f"LM Studio 오류: {e}"


# ─────────────────────────────────────────────────────────────
# LLM 응답 파싱
# ─────────────────────────────────────────────────────────────

def parse_llm_response(raw_text):
    """LLM 응답에서 JSON 추출. 앞뒤 텍스트·코드블록 제거 후 파싱."""
    if not raw_text:
        return None, "빈 응답"

    text = raw_text.strip()

    # ```json ... ``` 코드블록 제거
    import re
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        text = m.group(1).strip()

    # 첫 번째 { 부터 마지막 } 까지 추출
    start = text.find("{")
    end   = text.rfind("}")
    if start == -1 or end == -1:
        return None, f"JSON 구조 없음. LLM 원문: {raw_text[:200]}"

    json_str = text[start:end + 1]
    try:
        parsed = json.loads(json_str)
        return parsed, None
    except json.JSONDecodeError as e:
        # 단순 수정 시도: 후행 쉼표 제거
        try:
            fixed = re.sub(r",\s*([}\]])", r"\1", json_str)
            parsed = json.loads(fixed)
            return parsed, None
        except Exception:
            return None, f"JSON 파싱 실패: {e}. 원문: {json_str[:300]}"


# ─────────────────────────────────────────────────────────────
# Conviction Band 산출
# ─────────────────────────────────────────────────────────────

def compute_conviction_band(llm_output):
    """v5 §2 공식:
    raw = business_quality + competitive_advantage
         + (10 - execution_risk) + (10 - dilution_risk) + tam_score   (0~50)
    BAND_HIGH=38 → 상, BAND_MID=28 → 중, <28 → 하
    """
    def _safe(key, default=5):
        try:
            v = float(llm_output.get(key, default))
            return max(0, min(10, v))
        except (TypeError, ValueError):
            return default

    bq  = _safe("business_quality")
    ca  = _safe("competitive_advantage")
    er  = _safe("execution_risk")
    dr  = _safe("dilution_risk")
    tam = _safe("tam_score")

    raw = bq + ca + (10 - er) + (10 - dr) + tam

    if raw >= BAND_HIGH:
        band = "상"
    elif raw >= BAND_MID:
        band = "중"
    else:
        band = "하"

    return band, round(raw, 1), {
        "business_quality":     bq,
        "competitive_advantage": ca,
        "execution_risk":       er,
        "dilution_risk":        dr,
        "tam_score":            tam,
    }


# ─────────────────────────────────────────────────────────────
# watchlist.json 저장
# ─────────────────────────────────────────────────────────────

def save_to_watchlist(ticker, band, raw, scores, llm_output, data):
    if not _WL_PATH.exists():
        db = {}
    else:
        try:
            with open(_WL_PATH, encoding="utf-8") as f:
                db = json.load(f)
        except Exception:
            db = {}

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if ticker not in db:
        db[ticker] = {}

    db[ticker].update({
        "conviction_band":    band,
        "conviction_raw":     raw,
        "conviction_scores":  scores,
        "conviction_updated": today,
        "analysis": {
            "summary":    llm_output.get("summary", ""),
            "bull_case":  llm_output.get("bull_case", []),
            "bear_case":  llm_output.get("bear_case", []),
            "key_risks":  llm_output.get("key_risks", []),
        },
        "input_snapshot": {
            "market_cap_b":      data.get("market_cap_b"),
            "revenue_growth_pct": data.get("revenue_growth_pct"),
            "gross_margin_pct":   data.get("gross_margin_pct"),
            "fcf_positive":       data.get("fcf_positive"),
            "cash_runway_q":      data.get("cash_runway_q"),
        },
    })

    with open(_WL_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)


# ─────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]

    if not args or args[0].startswith("-"):
        print(json.dumps({
            "usage":    "py deep_analysis.py TICKER [--no-save] [--force]",
            "examples": [
                "py deep_analysis.py IONQ",
                "py deep_analysis.py RKLB --force",
                "py deep_analysis.py ASTS --no-save",
            ],
            "conviction_bands": {
                "상": f"raw >= {BAND_HIGH} (50점 만점 중 {BAND_HIGH}점+)",
                "중": f"raw {BAND_MID}~{BAND_HIGH-1}",
                "하": f"raw < {BAND_MID} → 매수 차단",
            },
        }, ensure_ascii=False))
        return

    ticker   = args[0].upper()
    no_save  = "--no-save" in args
    force    = "--force" in args

    # 이미 분석된 종목 확인 (--force 없을 때)
    if not force and not no_save and _WL_PATH.exists():
        try:
            with open(_WL_PATH, encoding="utf-8") as f:
                db = json.load(f)
            if ticker in db and db[ticker].get("conviction_band"):
                existing = db[ticker]
                print(json.dumps({
                    "info":    f"{ticker} 이미 분석됨. --force 로 덮어쓸 수 있음.",
                    "ticker":  ticker,
                    "conviction_band":    existing.get("conviction_band"),
                    "conviction_raw":     existing.get("conviction_raw"),
                    "conviction_updated": existing.get("conviction_updated"),
                    "analysis": existing.get("analysis", {}),
                }, ensure_ascii=False))
                return
        except Exception:
            pass

    config = _load_llm_config()
    print(json.dumps({
        "step": "1/4",
        "msg":  f"{ticker} 데이터 수집 중...",
        "llm_model": config["model"],
        "ollama_url": config["url"],
    }, ensure_ascii=False), file=sys.stderr)

    # yfinance 임포트
    try:
        import yfinance as yf
    except ImportError:
        print(json.dumps({"error": "yfinance 미설치. 'py -m pip install yfinance' 실행."}, ensure_ascii=False))
        return

    # 1. 데이터 수집
    data = collect_data(yf, ticker)
    if data.get("fetch_error"):
        print(json.dumps({"error": f"데이터 수집 실패: {data['fetch_error']}"}, ensure_ascii=False))
        return

    print(json.dumps({"step": "2/4", "msg": "LLM 프롬프트 구성 중..."}, ensure_ascii=False), file=sys.stderr)

    # 2. 프롬프트 구성
    prompt = build_prompt(data)

    print(json.dumps({"step": "3/4", "msg": f"Ollama({config['model']}) 분석 중... (최대 5분)"}, ensure_ascii=False), file=sys.stderr)

    # 3. Ollama 호출
    raw_response, err = call_ollama(prompt, config)
    if err:
        print(json.dumps({"error": err}, ensure_ascii=False))
        return

    print(json.dumps({"step": "4/4", "msg": "응답 파싱 + Conviction Band 산출 중..."}, ensure_ascii=False), file=sys.stderr)

    # 4. 파싱
    llm_output, parse_err = parse_llm_response(raw_response)
    if parse_err:
        print(json.dumps({
            "error":       "LLM 응답 파싱 실패",
            "detail":      parse_err,
            "raw_response": raw_response[:500],
            "tip":         "모델이 JSON을 못 만들면 --force 로 재시도하거나 system_schema.json 모델을 변경하세요.",
        }, ensure_ascii=False))
        return

    # 5. Conviction Band
    band, raw_score, scores = compute_conviction_band(llm_output)

    result = _sanitize({
        "ticker":          ticker,
        "conviction_band": band,
        "conviction_raw":  raw_score,
        "band_thresholds": {"high": BAND_HIGH, "mid": BAND_MID},
        "scores":          scores,
        "analysis": {
            "summary":   llm_output.get("summary", ""),
            "bear_case": llm_output.get("bear_case", []),
            "key_risks": llm_output.get("key_risks", []),
            "bull_case": llm_output.get("bull_case", []),
        },
        "input_summary": {
            "market_cap_b":       data.get("market_cap_b"),
            "revenue_growth_pct": data.get("revenue_growth_pct"),
            "gross_margin_pct":   data.get("gross_margin_pct"),
            "fcf_positive":       data.get("fcf_positive"),
            "cash_runway_q":      data.get("cash_runway_q"),
            "news_count":         len(data.get("recent_news") or []),
            "superinvestor":      data.get("superinvestor_signal"),
        },
        "llm_model":  config["model"],
        "note": (
            "Conviction Band: 상=적극검토 / 중=조건부 / 하=매수차단. "
            f"raw 점수 {BAND_HIGH}+ → 상, {BAND_MID}~{BAND_HIGH-1} → 중, <{BAND_MID} → 하. "
            "경계선(중↔하) 종목은 반드시 수동 확인 후 통과 결정(v5 §2)."
        ),
    })

    # 6. 저장
    if not no_save:
        save_to_watchlist(ticker, band, raw_score, scores, llm_output, data)
        result["saved"] = str(_WL_PATH)

    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
