"""
Connect AI v5 §0 백테스트 검증 시스템 — HTML 보고서 생성
=========================================================
factor_validator 및 backtest_engine 결과를 받아 HTML 보고서로 출력한다.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from config import (
    REPORTS_DIR,
    BACKTEST_START,
    BACKTEST_END,
    PRICE_FACTORS,
    FUNDAMENTAL_FACTORS,
    IC_THRESHOLD,
    FORWARD_PERIOD_LABELS,
)

logger = logging.getLogger(__name__)

# IC 합격 기준 (IC_THRESHOLD 미설정 시 업계 통상값 사용)
_IC_PASS = IC_THRESHOLD if IC_THRESHOLD is not None else 0.03


# ──────────────────────────────────────────────────────────
# 유틸
# ──────────────────────────────────────────────────────────

def _pct(v: float | None, decimals: int = 1) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    return f"{v * 100:.{decimals}f}%"


def _fmt(v: float | None, decimals: int = 3) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    return f"{v:.{decimals}f}"


def _pass_badge(status: str) -> str:
    colors = {
        "PASS":           ("#28a745", "✔ PASS"),
        "STRONG_PENDING": ("#fd7e14", "★ STRONG_PENDING"),
        "WEAK_PENDING":   ("#ffc107", "△ WEAK_PENDING"),
        "FAIL":           ("#dc3545", "✘ FAIL"),
        "NO_DATA":        ("#6c757d", "— NO_DATA"),
    }
    color, label = colors.get(status, ("#6c757d", status))
    return f'<span style="background:{color};color:#fff;padding:2px 8px;border-radius:4px;font-size:0.85em">{label}</span>'


def _ic_cell(ic: float | None, tstat: float | None) -> str:
    if ic is None or (isinstance(ic, float) and np.isnan(ic)):
        return "—"
    color = "#28a745" if abs(ic) >= _IC_PASS else "#dc3545"
    tpart = f" (t={tstat:.2f})" if tstat and not np.isnan(tstat) else ""
    return f'<span style="color:{color};font-weight:bold">{ic:.3f}{tpart}</span>'


# ──────────────────────────────────────────────────────────
# 섹션별 HTML 빌더
# ──────────────────────────────────────────────────────────

def _header(title: str, generated_at: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
  body {{ font-family: 'Segoe UI', sans-serif; margin: 0; padding: 20px; background: #f8f9fa; color: #212529; }}
  h1 {{ color: #343a40; border-bottom: 3px solid #007bff; padding-bottom: 8px; }}
  h2 {{ color: #495057; border-left: 4px solid #007bff; padding-left: 12px; margin-top: 40px; }}
  h3 {{ color: #495057; }}
  table {{ border-collapse: collapse; width: 100%; margin-bottom: 24px; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,.12); }}
  th {{ background: #343a40; color: #fff; padding: 10px 12px; text-align: left; font-size: 0.9em; }}
  td {{ padding: 8px 12px; border-bottom: 1px solid #dee2e6; font-size: 0.88em; }}
  tr:hover td {{ background: #f1f3f5; }}
  .meta {{ color: #6c757d; font-size: 0.85em; margin-bottom: 24px; }}
  .summary-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 32px; }}
  .card {{ background: #fff; border-radius: 8px; padding: 16px; box-shadow: 0 1px 3px rgba(0,0,0,.12); }}
  .card-label {{ font-size: 0.8em; color: #6c757d; text-transform: uppercase; }}
  .card-value {{ font-size: 1.6em; font-weight: bold; color: #343a40; }}
  .positive {{ color: #28a745; }} .negative {{ color: #dc3545; }}
  .note {{ background: #fff3cd; border-left: 4px solid #ffc107; padding: 12px 16px; margin: 16px 0; font-size: 0.9em; }}
  .section {{ background: #fff; border-radius: 8px; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,.12); margin-bottom: 24px; }}
</style>
</head>
<body>
<h1>{title}</h1>
<p class="meta">생성일시: {generated_at} | 백테스트 기간: {BACKTEST_START} ~ {BACKTEST_END}</p>
"""


def _footer() -> str:
    return """
<p class="meta" style="margin-top:48px">Connect AI v5 §0 — 팩터 검증 보고서 (MVP)</p>
</body></html>"""


def _factor_summary_section(validation_results: list[dict]) -> str:
    if not validation_results:
        return "<p>팩터 검증 결과 없음.</p>"

    rows = []
    for r in validation_results:
        factor = r.get("factor", "")
        meta = {**PRICE_FACTORS, **FUNDAMENTAL_FACTORS}.get(factor, (None, factor, ""))
        expected_sign = meta[0] if meta[0] is not None else ""
        description = meta[1] if len(meta) > 1 else factor
        v5_section = meta[2] if len(meta) > 2 else ""

        sign_str = "+" if expected_sign == 1 else ("-" if expected_sign == -1 else "?")

        ic_4w  = r.get("ic_mean_4W");  ts_4w  = r.get("ic_tstat_4W")
        ic_12w = r.get("ic_mean_12W"); ts_12w = r.get("ic_tstat_12W")
        ic_24w = r.get("ic_mean_24W"); ts_24w = r.get("ic_tstat_24W")
        status = r.get("pass", "NO_DATA")
        obs    = r.get("obs", "—")

        rows.append(f"""<tr>
  <td><b>{factor}</b><br><small style="color:#6c757d">{description}</small></td>
  <td>{v5_section}</td>
  <td style="text-align:center">{sign_str}</td>
  <td>{_ic_cell(ic_4w,  ts_4w)}</td>
  <td>{_ic_cell(ic_12w, ts_12w)}</td>
  <td>{_ic_cell(ic_24w, ts_24w)}</td>
  <td>{obs}</td>
  <td>{_pass_badge(status)}</td>
</tr>""")

    rows_html = "\n".join(rows)
    threshold_note = f"IC 합격 기준: |IC| ≥ {_IC_PASS:.3f}" + (" (🔧 사용자 미설정 → 업계 통상값 적용)" if IC_THRESHOLD is None else "")

    pass_count   = sum(1 for r in validation_results if r.get("pass") == "PASS")
    strong_count = sum(1 for r in validation_results if r.get("pass") == "STRONG_PENDING")
    fail_count   = sum(1 for r in validation_results if r.get("pass") in ("FAIL", "NO_DATA"))
    total = len(validation_results)

    return f"""
<h2>1. 팩터 IC 검증 요약</h2>
<div class="note">{threshold_note}</div>
<div class="summary-grid">
  <div class="card"><div class="card-label">전체 팩터</div><div class="card-value">{total}</div></div>
  <div class="card"><div class="card-label">PASS</div><div class="card-value positive">{pass_count}</div></div>
  <div class="card"><div class="card-label">STRONG_PENDING</div><div class="card-value" style="color:#fd7e14">{strong_count}</div></div>
  <div class="card"><div class="card-label">FAIL / NO_DATA</div><div class="card-value negative">{fail_count}</div></div>
</div>
<div class="section">
<table>
<thead><tr>
  <th>팩터</th><th>v5 영역</th><th>예상 부호</th>
  <th>IC 4W</th><th>IC 12W</th><th>IC 24W</th>
  <th>관측수</th><th>판정</th>
</tr></thead>
<tbody>{rows_html}</tbody>
</table>
</div>
"""


def _quintile_section(validation_results: list[dict]) -> str:
    sections = []
    for r in validation_results:
        factor = r.get("factor", "")
        qret = r.get("quintile_returns", {})
        if not qret:
            continue

        period_blocks = []
        for period_label in FORWARD_PERIOD_LABELS:
            period_data = qret.get(period_label, {})
            if not period_data:
                continue
            q_rows = []
            for q in sorted(period_data.keys()):
                val = period_data[q]
                color_class = "positive" if val and val > 0 else ("negative" if val and val < 0 else "")
                q_rows.append(f"<tr><td>Q{q}</td><td class='{color_class}'>{_pct(val)}</td></tr>")
            q_html = "\n".join(q_rows)
            period_blocks.append(f"""
<div style="min-width:140px">
<b>{period_label}</b>
<table style="margin-top:6px">
<thead><tr><th>분위</th><th>평균수익률</th></tr></thead>
<tbody>{q_html}</tbody>
</table>
</div>""")

        if period_blocks:
            blocks_html = "\n".join(period_blocks)
            sections.append(f"""
<div class="section">
<h3>{factor}</h3>
<div style="display:flex;gap:24px;flex-wrap:wrap">{blocks_html}</div>
</div>""")

    if not sections:
        return "<p>분위 수익률 데이터 없음.</p>"

    return "<h2>2. 팩터별 분위(Quintile) 수익률</h2>\n" + "\n".join(sections)


def _backtest_perf_section(backtest_results: dict) -> str:
    if not backtest_results:
        return "<p>백테스트 결과 없음.</p>"

    cards = []
    tables = []

    for key, result in backtest_results.items():
        if not isinstance(result, dict):
            continue
        stats = result.get("stats", {})
        if not stats:
            continue

        cagr   = stats.get("cagr")
        mdd    = stats.get("max_drawdown")
        sharpe = stats.get("sharpe")
        bench_cagr = stats.get("benchmark_cagr")
        alpha  = stats.get("alpha")
        hit    = stats.get("hit_rate")
        n      = stats.get("n_periods", "—")

        cagr_class  = "positive" if cagr and cagr > 0 else "negative"
        alpha_class = "positive" if alpha and alpha > 0 else "negative"

        cards.append(f"""<div class="card">
<div class="card-label">{key}</div>
<div class="card-value {cagr_class}">{_pct(cagr)}</div>
<small>CAGR | MDD: {_pct(mdd)} | Sharpe: {_fmt(sharpe, 2)}</small><br>
<small>Alpha: <span class="{alpha_class}">{_pct(alpha)}</span> | Hit: {_pct(hit)} | N={n}</small>
</div>""")

        row = f"""<tr>
<td><b>{key}</b></td>
<td class="{cagr_class}">{_pct(cagr)}</td>
<td>{_pct(bench_cagr)}</td>
<td class="{alpha_class}">{_pct(alpha)}</td>
<td>{_pct(mdd)}</td>
<td>{_fmt(sharpe, 2)}</td>
<td>{_pct(hit)}</td>
<td>{n}</td>
</tr>"""
        tables.append(row)

    if not cards:
        return "<p>포트폴리오 성과 데이터 없음.</p>"

    cards_html  = "\n".join(cards)
    table_rows  = "\n".join(tables)

    return f"""
<h2>3. 포트폴리오 백테스트 성과</h2>
<div class="summary-grid">{cards_html}</div>
<div class="section">
<table>
<thead><tr>
  <th>포트폴리오</th><th>CAGR</th><th>벤치마크 CAGR</th><th>Alpha</th>
  <th>MDD</th><th>Sharpe</th><th>Hit Rate</th><th>리밸런싱 횟수</th>
</tr></thead>
<tbody>{table_rows}</tbody>
</table>
</div>
"""


def _regime_section(backtest_results: dict) -> str:
    regime_on  = backtest_results.get("regime_on",  {}).get("stats", {})
    regime_off = backtest_results.get("regime_off", {}).get("stats", {})

    if not regime_on and not regime_off:
        return ""

    def _row(label, stats):
        cagr  = stats.get("cagr")
        mdd   = stats.get("max_drawdown")
        sharpe= stats.get("sharpe")
        n     = stats.get("n_periods", "—")
        color = "positive" if cagr and cagr > 0 else "negative"
        return f"<tr><td>{label}</td><td class='{color}'>{_pct(cagr)}</td><td>{_pct(mdd)}</td><td>{_fmt(sharpe,2)}</td><td>{n}</td></tr>"

    rows = ""
    if regime_on:
        rows += _row("Regime RISK_ON", regime_on)
    if regime_off:
        rows += _row("Regime OFF (전체 포함)", regime_off)

    return f"""
<h2>4. 레짐 게이트 효과</h2>
<div class="note">SPY/QQQ MA200 기반 레짐 게이트 ON/OFF 비교. CAUTION 구간 축소 운용 효과 확인.</div>
<div class="section">
<table>
<thead><tr><th>구분</th><th>CAGR</th><th>MDD</th><th>Sharpe</th><th>리밸런싱 횟수</th></tr></thead>
<tbody>{rows}</tbody>
</table>
</div>
"""


def _factor_corr_section(validation_results: list[dict]) -> str:
    corr_data = None
    for r in validation_results:
        if "factor_correlation" in r:
            corr_data = r["factor_correlation"]
            break
    if corr_data is None:
        return ""

    try:
        corr_df = pd.DataFrame(corr_data)
    except Exception:
        return ""

    cols = corr_df.columns.tolist()
    header = "<tr><th></th>" + "".join(f"<th>{c}</th>" for c in cols) + "</tr>"
    body_rows = []
    for idx, row in corr_df.iterrows():
        cells = ""
        for c in cols:
            v = row[c]
            if isinstance(v, float) and not np.isnan(v):
                if abs(v) > 0.7 and str(idx) != c:
                    cells += f'<td style="background:#f8d7da;font-weight:bold">{v:.2f}</td>'
                else:
                    cells += f"<td>{v:.2f}</td>"
            else:
                cells += "<td>—</td>"
        body_rows.append(f"<tr><th>{idx}</th>{cells}</tr>")

    body = "\n".join(body_rows)
    return f"""
<h2>5. 팩터 상관관계 행렬</h2>
<div class="note">|상관계수| &gt; 0.7 셀은 빨간색으로 표시 — 중복 팩터 의심 구간</div>
<div class="section" style="overflow-x:auto">
<table><thead>{header}</thead><tbody>{body}</tbody></table>
</div>
"""


def _recommendations_section(validation_results: list[dict]) -> str:
    passed   = [r["factor"] for r in validation_results if r.get("pass") == "PASS"]
    pending  = [r["factor"] for r in validation_results if r.get("pass") in ("STRONG_PENDING", "WEAK_PENDING")]
    failed   = [r["factor"] for r in validation_results if r.get("pass") in ("FAIL", "NO_DATA")]

    passed_li  = "".join(f"<li><code>{f}</code></li>" for f in passed)  or "<li>없음</li>"
    pending_li = "".join(f"<li><code>{f}</code></li>" for f in pending) or "<li>없음</li>"
    failed_li  = "".join(f"<li><code>{f}</code></li>" for f in failed)  or "<li>없음</li>"

    ic_note = ("⚠️ IC_THRESHOLD 🔧 미설정 — 업계 통상값 0.03 임시 적용. 백테스트 결과 확인 후 config.py에서 확정 필요."
               if IC_THRESHOLD is None else f"IC 합격 기준: {IC_THRESHOLD:.3f}")

    return f"""
<h2>6. 종합 권고사항</h2>
<div class="note">{ic_note}</div>
<div class="section">
<h3>✔ 합격 팩터 (v5 시스템 채택 권장)</h3>
<ul>{passed_li}</ul>
<h3>★ 보류 팩터 (추가 데이터 수집 후 재검증)</h3>
<ul>{pending_li}</ul>
<h3>✘ 불합격 / 데이터 부족 팩터</h3>
<ul>{failed_li}</ul>
<h3>다음 단계</h3>
<ul>
  <li>합격 팩터로 <code>run_combined_portfolio()</code> 재실행하여 최종 성과 확인</li>
  <li><code>config.py</code>의 🔧 파라미터를 백테스트 결과 기반으로 확정</li>
  <li>PASS 팩터만으로 universe scan → screen.py 구현 진행</li>
</ul>
</div>
"""


# ──────────────────────────────────────────────────────────
# 공개 API
# ──────────────────────────────────────────────────────────

def generate_report(
    validation_results: list[dict],
    backtest_results: dict | None = None,
    output_path: Path | None = None,
) -> Path:
    """
    Parameters
    ----------
    validation_results : factor_validator.run_validation() 반환값
    backtest_results   : backtest_engine.run_full_backtest() 반환값 (선택)
    output_path        : 지정하지 않으면 REPORTS_DIR/report_<timestamp>.html

    Returns
    -------
    Path : 저장된 HTML 파일 경로
    """
    if backtest_results is None:
        backtest_results = {}

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    title = f"Connect AI v5 §0 팩터 검증 보고서 ({generated_at[:10]})"

    html_parts = [
        _header(title, generated_at),
        _factor_summary_section(validation_results),
        _quintile_section(validation_results),
        _backtest_perf_section(backtest_results),
        _regime_section(backtest_results),
        _factor_corr_section(validation_results),
        _recommendations_section(validation_results),
        _footer(),
    ]
    html = "\n".join(html_parts)

    if output_path is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = REPORTS_DIR / f"report_{ts}.html"

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    logger.info("보고서 저장: %s", output_path)
    return output_path


def save_validation_json(validation_results: list[dict], output_path: Path | None = None) -> Path:
    """검증 결과를 JSON으로 저장 (프로그래밍 활용)"""
    if output_path is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = REPORTS_DIR / f"validation_{ts}.json"
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    serializable = []
    for r in validation_results:
        row = {}
        for k, v in r.items():
            if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
                row[k] = None
            elif isinstance(v, np.integer):
                row[k] = int(v)
            elif isinstance(v, np.floating):
                row[k] = float(v)
            elif isinstance(v, pd.DataFrame):
                row[k] = v.to_dict()
            else:
                row[k] = v
        serializable.append(row)

    output_path.write_text(json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("검증 결과 JSON 저장: %s", output_path)
    return output_path
