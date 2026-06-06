#!/usr/bin/env python3
# Connect AI · 한국투자증권(KIS) 해외주식 시세 헬퍼 — 증권사급 교차검증 소스
#
# 사용법:
#   py kis.py AAPL              → 현재가 + 밸류에이션(PER/PBR/EPS/시총/52주) JSON
#   py kis.py AAPL NAS          → 거래소 직접 지정(자동 탐색 생략, 빠름)
#
# 목적: yfinance 데이터를 한투 API(실제 체결 소스)와 교차검증한다. yfinance가
#       종종 시총·PER을 10배 틀리게 주므로(IONQ 사례), 증권사급 값으로 대조한다.
#
# 자격증명(둘 중 하나):
#   ① 환경변수 KIS_APP_KEY / KIS_APP_SECRET  (KIS_ENV=prod|vps, 기본 prod=실전)
#   ② 같은 폴더의 kis_config.json: {"appkey":"...","appsecret":"...","env":"prod"}
#   ※ 둘 다 .gitignore 처리됨. 절대 커밋 금지.
#
# 데이터 출처: 한국투자증권 Open API (KIS Developers). OAuth 토큰 인증.
# 외부 라이브러리 없이 stdlib(urllib)만 사용. 출력은 JSON 한 줄.
# 실패 시 {"error": ...}. AI는 error/null이면 날조 금지.

import sys, os, json, time, urllib.request, urllib.error
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_DIR = Path(__file__).resolve().parent
_TOKEN_CACHE = _DIR / ".kis_token.json"     # 발급 토큰 캐시(gitignore)
_CONFIG_FILE = _DIR / "kis_config.json"     # 자격증명 파일(gitignore)

_DOMAINS = {
    "prod": "https://openapi.koreainvestment.com:9443",   # 실전
    "vps": "https://openapivts.koreainvestment.com:29443",  # 모의
}
# 미국 거래소 코드 — 티커가 어느 거래소인지 모를 때 순서대로 시도.
_US_EXCHANGES = ["NAS", "NYS", "AMS"]


def _load_creds():
    """환경변수 우선, 없으면 kis_config.json. (appkey, appsecret, env) 반환."""
    appkey = os.environ.get("KIS_APP_KEY")
    appsecret = os.environ.get("KIS_APP_SECRET")
    env = os.environ.get("KIS_ENV", "prod")
    if appkey and appsecret:
        return appkey, appsecret, env
    if _CONFIG_FILE.exists():
        try:
            cfg = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
            return cfg.get("appkey"), cfg.get("appsecret"), cfg.get("env", "prod")
        except Exception:
            pass
    return None, None, env


def _http_json(url, headers, data=None, method="GET", timeout=15):
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _get_token(appkey, appsecret, domain):
    """유효한 액세스 토큰 반환. 캐시 우선(KIS가 토큰 발급을 rate-limit하므로 필수)."""
    # 캐시된 토큰이 아직 유효하면 재사용 (만료 5분 전까지)
    if _TOKEN_CACHE.exists():
        try:
            c = json.loads(_TOKEN_CACHE.read_text(encoding="utf-8"))
            if (c.get("appkey") == appkey and c.get("domain") == domain
                    and c.get("expires_at", 0) - 300 > time.time()):
                return c["access_token"]
        except Exception:
            pass
    # 신규 발급
    url = f"{domain}/oauth2/tokenP"
    headers = {"content-type": "application/json"}
    payload = {"grant_type": "client_credentials",
               "appkey": appkey, "appsecret": appsecret}
    res = _http_json(url, headers, data=payload, method="POST")
    token = res.get("access_token")
    if not token:
        raise RuntimeError(f"토큰 발급 실패: {res}")
    # expires_in(초) 기준으로 만료시각 저장. 없으면 24h 가정.
    expires_in = int(res.get("expires_in", 86400))
    try:
        _TOKEN_CACHE.write_text(json.dumps({
            "access_token": token, "appkey": appkey, "domain": domain,
            "expires_at": time.time() + expires_in,
        }), encoding="utf-8")
    except Exception:
        pass  # 캐시 실패해도 이번 호출은 진행
    return token


def _price_detail(domain, token, appkey, appsecret, excd, symb):
    """해외주식 현재가상세 1건 조회. rt_cd!='0'이거나 빈값이면 None 반환."""
    url = (f"{domain}/uapi/overseas-price/v1/quotations/price-detail"
           f"?AUTH=&EXCD={excd}&SYMB={symb}")
    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": appkey,
        "appsecret": appsecret,
        "tr_id": "HHDFS76200200",
        "custtype": "P",
    }
    res = _http_json(url, headers, method="GET")
    if res.get("rt_cd") != "0":
        return None
    out = res.get("output") or {}
    # last(현재가)가 비어있으면 해당 거래소에 없는 티커.
    last = out.get("last")
    if last in (None, "", "0", "0.0000"):
        return None
    return out


def _f(v):
    """문자열 숫자 → float. 빈값/오류는 None."""
    try:
        if v in (None, ""):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _market_cap_text(mc):
    if mc is None:
        return None
    neg = "-" if mc < 0 else ""
    a = abs(mc)
    jo = a / 1e12
    if jo >= 1:
        ji = int(jo)
        eok = round((a - ji * 1e12) / 1e8)
        body = f"{ji}조 {eok:,}억 달러" if eok else f"{ji}조 달러"
    elif a >= 1e8:
        body = f"{round(a / 1e8):,}억 달러"
    else:
        body = f"{round(a / 1e4):,}만 달러"
    return neg + body


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "ticker 필요. 예: py kis.py AAPL"}, ensure_ascii=False))
        return
    ticker = sys.argv[1].upper().strip()
    forced_excd = sys.argv[2].upper().strip() if len(sys.argv) > 2 else None

    appkey, appsecret, env = _load_creds()
    if not appkey or not appsecret:
        print(json.dumps({"error": "KIS 자격증명 없음. 환경변수 KIS_APP_KEY/KIS_APP_SECRET "
                          "또는 kis_config.json 설정 필요."}, ensure_ascii=False))
        return
    domain = _DOMAINS.get(env, _DOMAINS["prod"])

    try:
        token = _get_token(appkey, appsecret, domain)
    except urllib.error.HTTPError as e:
        print(json.dumps({"error": f"KIS 토큰 HTTP 오류 {e.code}: {e.reason}"}, ensure_ascii=False))
        return
    except Exception as e:
        print(json.dumps({"error": f"KIS 토큰 발급 실패: {e}"}, ensure_ascii=False))
        return

    # 거래소 탐색: 지정되면 그것만, 아니면 NAS→NYS→AMS 순서로.
    exchanges = [forced_excd] if forced_excd else _US_EXCHANGES
    raw, used_excd = None, None
    try:
        for ex in exchanges:
            raw = _price_detail(domain, token, appkey, appsecret, ex, ticker)
            if raw is not None:
                used_excd = ex
                break
    except urllib.error.HTTPError as e:
        print(json.dumps({"error": f"KIS 시세 HTTP 오류 {e.code}: {e.reason}"}, ensure_ascii=False))
        return
    except urllib.error.URLError as e:
        print(json.dumps({"error": f"KIS 연결 실패: {e}. 네트워크 확인."}, ensure_ascii=False))
        return
    except Exception as e:
        print(json.dumps({"error": f"KIS 시세 조회 실패: {e}"}, ensure_ascii=False))
        return

    if raw is None:
        print(json.dumps({"error": f"{ticker}를 한투 해외시세에서 찾지 못함 "
                          "(미국 상장 티커인지, 거래소 코드 확인)."}, ensure_ascii=False))
        return

    # 정규화 — stock.py와 같은 키로 맞춰 교차검증을 쉽게 한다.
    # 필드 매핑(KIS 현재가상세): last=현재가, perx=PER, pbrx=PBR, epsx=EPS,
    #   bpsx=BPS, h52p/l52p=52주 고/저, tvol=거래량, tomv=시가총액.
    mc = _f(raw.get("tomv"))
    out = {
        "ticker": ticker,
        "source": "KIS",
        "exchange": used_excd,
        "price": _f(raw.get("last")),
        "trailingPE": _f(raw.get("perx")),
        "pbr": _f(raw.get("pbrx")),
        "eps": _f(raw.get("epsx")),
        "bps": _f(raw.get("bpsx")),
        "high52": _f(raw.get("h52p")),
        "low52": _f(raw.get("l52p")),
        "volume": _f(raw.get("tvol")),
        "marketCap": mc,
        "marketCapText": _market_cap_text(mc),
        # 첫 실전 테스트에서 필드명·단위(특히 tomv 시총)를 검증할 수 있도록 원본 동봉.
        "_raw": raw,
        "note": ("한투 실전 API 값(증권사급). yfinance와 교차검증용. "
                 "marketCapText 그대로 사용, 원본 환산 산수 금지. null이면 '데이터 미제공'. "
                 "_raw는 원본 응답(필드명·단위 검증용) — 정규화 값과 다르면 _raw 우선 점검."),
    }
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
