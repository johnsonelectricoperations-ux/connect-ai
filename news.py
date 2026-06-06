#!/usr/bin/env python3
# Connect AI · 종목 뉴스 헬퍼
#
# 사용법:
#   py news.py AAPL          → AAPL 최신 뉴스 10건
#   py news.py IONQ 5        → 최신 5건
#   py news.py TSLA --sentiment → 뉴스 감성 집계(positive/negative/neutral 비율)
#
# 데이터 소스:
#   1순위: Yahoo Finance RSS (무료, 인증 불필요)
#   2순위: Google News RSS (야후 실패 시 폴백)
#
# 외부 라이브러리 없이 stdlib만 사용.
# 실패 시 {"error": ...}. AI는 error/null이면 날조 금지.

import sys, json, re, urllib.request, urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/rss+xml,text/xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

# 감성 키워드 (제목 기반 간이 분류)
_POSITIVE_KW = [
    "surge", "soar", "rally", "beat", "record", "growth", "gain", "up",
    "strong", "bullish", "upgrade", "buy", "outperform", "profit", "rise",
    "higher", "jump", "boom", "positive", "exceed", "top", "win", "boost",
]
_NEGATIVE_KW = [
    "fall", "drop", "decline", "miss", "loss", "down", "weak", "bearish",
    "downgrade", "sell", "underperform", "risk", "cut", "lower", "crash",
    "plunge", "slump", "warn", "concern", "disappoint", "negative", "threat",
    "fine", "lawsuit", "probe", "recall", "layoff", "bankrupt",
]


def _http_get(url, timeout=12):
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        try:
            import gzip
            if r.info().get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
        except Exception:
            pass
        return raw.decode("utf-8", errors="replace")


def _parse_rss(xml_text):
    """RSS XML → [{title, url, published, source, description}] 목록."""
    items = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        # XML 파싱 실패 시 정규식 폴백
        return _parse_rss_regex(xml_text)

    ns = {
        "media": "http://search.yahoo.com/mrss/",
        "content": "http://purl.org/rss/1.0/modules/content/",
    }

    for item in root.iter("item"):
        title = _text(item.find("title"))
        url = _text(item.find("link")) or _text(item.find("guid"))
        pub = _text(item.find("pubDate"))
        source = _text(item.find("source"))
        desc = _text(item.find("description"))

        if not title:
            continue

        # pubDate → ISO 형식 정규화
        pub_iso = _parse_date(pub)

        # description에서 HTML 태그 제거
        if desc:
            desc = re.sub(r'<[^>]+>', '', desc).strip()
            desc = re.sub(r'\s+', ' ', desc)
            if len(desc) > 300:
                desc = desc[:297] + "..."

        items.append({
            "title": title.strip(),
            "url": url.strip() if url else None,
            "published": pub_iso,
            "source": source.strip() if source else None,
            "description": desc if desc else None,
        })

    return items


def _parse_rss_regex(xml_text):
    """ET 실패 시 정규식 기반 RSS 파싱."""
    items = []
    for block in re.findall(r'<item>(.*?)</item>', xml_text, re.DOTALL):
        title = _re_tag(block, "title")
        url = _re_tag(block, "link") or _re_tag(block, "guid")
        pub = _re_tag(block, "pubDate")
        source = _re_tag(block, "source")
        desc = _re_tag(block, "description")

        if not title:
            continue
        if desc:
            desc = re.sub(r'<[^>]+>', '', desc).strip()[:300]

        items.append({
            "title": title.strip(),
            "url": url.strip() if url else None,
            "published": _parse_date(pub),
            "source": source.strip() if source else None,
            "description": desc if desc else None,
        })
    return items


def _text(elem):
    if elem is None:
        return None
    return (elem.text or "").strip() or None


def _re_tag(s, tag):
    m = re.search(rf'<{tag}[^>]*>(.*?)</{tag}>', s, re.DOTALL | re.IGNORECASE)
    if not m:
        return None
    val = m.group(1).strip()
    # CDATA 제거
    val = re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', val, flags=re.DOTALL)
    return val.strip() or None


def _parse_date(s):
    """RFC 2822 또는 ISO 날짜 문자열 → 'YYYY-MM-DD HH:MM UTC' 형식."""
    if not s:
        return None
    # RFC 2822: Mon, 03 Jun 2024 12:34:56 +0000
    m = re.search(
        r'(\d{1,2})\s+(\w{3})\s+(\d{4})\s+(\d{2}):(\d{2})',
        s
    )
    if m:
        month_map = {
            "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
            "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
        }
        d, mo_s, y, H, M = m.groups()
        mo = month_map.get(mo_s, 0)
        if mo:
            return f"{y}-{mo:02d}-{int(d):02d} {H}:{M} UTC"
    # ISO 8601
    m2 = re.search(r'(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})', s)
    if m2:
        return f"{m2.group(1)} {m2.group(2)} UTC"
    return s[:30].strip()


def _sentiment(title):
    """제목 기반 간이 감성: positive / negative / neutral."""
    t = title.lower()
    pos = sum(1 for kw in _POSITIVE_KW if kw in t)
    neg = sum(1 for kw in _NEGATIVE_KW if kw in t)
    if pos > neg:
        return "positive"
    if neg > pos:
        return "negative"
    return "neutral"


# ─────────────────────────────────────────────────────────────
# RSS 소스 시도 순서
# ─────────────────────────────────────────────────────────────

def _yahoo_rss(ticker):
    url = (f"https://feeds.finance.yahoo.com/rss/2.0/headline"
           f"?s={ticker}&region=US&lang=en-US")
    try:
        xml = _http_get(url)
        items = _parse_rss(xml)
        return items if items else None
    except Exception:
        return None


def _google_news_rss(ticker):
    query = urllib.request.quote(f"{ticker} stock")
    url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
    try:
        xml = _http_get(url)
        items = _parse_rss(xml)
        return items if items else None
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────
# 공개 API
# ─────────────────────────────────────────────────────────────

def fetch_news(ticker, limit=10):
    """종목 최신 뉴스 조회.

    반환: {
        ticker, source_used,
        news: [{title, url, published, source, description, sentiment}],
        count, sentiment_summary: {positive, negative, neutral, signal}
    }
    실패 시 None (graceful).
    """
    ticker = ticker.upper().strip()
    items = None
    source_used = None

    # 1순위: Yahoo Finance RSS
    items = _yahoo_rss(ticker)
    if items:
        source_used = "Yahoo Finance RSS"

    # 2순위: Google News RSS
    if not items:
        items = _google_news_rss(ticker)
        if items:
            source_used = "Google News RSS"

    if not items:
        return None

    # limit 적용 + 감성 추가
    items = items[:limit]
    for it in items:
        it["sentiment"] = _sentiment(it["title"])

    # 감성 집계
    counts = {"positive": 0, "negative": 0, "neutral": 0}
    for it in items:
        counts[it["sentiment"]] += 1
    n = len(items)
    pct_pos = round(counts["positive"] / n * 100) if n else 0
    pct_neg = round(counts["negative"] / n * 100) if n else 0

    if pct_pos >= 60:
        sig = "bullish"
    elif pct_neg >= 60:
        sig = "bearish"
    elif pct_neg >= 40:
        sig = "cautious"
    else:
        sig = "mixed"

    return {
        "ticker": ticker,
        "source_used": source_used,
        "news": items,
        "count": n,
        "sentiment_summary": {
            "positive": counts["positive"],
            "negative": counts["negative"],
            "neutral": counts["neutral"],
            "positive_pct": pct_pos,
            "negative_pct": pct_neg,
            "signal": sig,
        },
    }


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(json.dumps(
            {"error": "사용법: py news.py TICKER [N] [--sentiment]"},
            ensure_ascii=False))
        return

    ticker = sys.argv[1].upper().strip()
    limit = 10
    sentiment_only = False

    for arg in sys.argv[2:]:
        if arg == "--sentiment":
            sentiment_only = True
        elif arg.isdigit():
            limit = max(1, min(int(arg), 30))

    result = fetch_news(ticker, limit)
    if not result:
        print(json.dumps(
            {"error": f"{ticker} 뉴스 조회 실패 — 네트워크 점검 또는 티커 확인"},
            ensure_ascii=False))
        return

    if sentiment_only:
        out = {
            "ticker": result["ticker"],
            "source_used": result["source_used"],
            "count": result["count"],
            "sentiment_summary": result["sentiment_summary"],
        }
    else:
        out = result

    out["note"] = (
        "뉴스 데이터: RSS 기반(Yahoo Finance 또는 Google News). "
        "sentiment=제목 키워드 기반 간이 분류(positive/negative/neutral). "
        "sentiment_summary.signal: bullish=긍정 60%+, bearish=부정 60%+, "
        "cautious=부정 40%+, mixed=혼조. "
        "URL은 원문 링크. null이면 데이터 미제공 — 지어내지 말 것. "
        "뉴스 내용을 요약할 때는 title·published·description 필드만 사용 — 없는 내용 추가 금지. "
        "published=뉴스 날짜(YYYY-MM-DD HH:MM UTC). 각 뉴스 항목에 날짜를 반드시 표시할 것."
    )
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
