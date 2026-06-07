"""
Connect AI v5 §0 백테스트 검증 시스템 — HTML 보고서 생성
=========================================================
factor_validator 및 backtest_engine 결과를 받아 HTML 보고서로 출력한다.

포함 섹션:
  1. 팩터 IC 요약 테이블
  2. IC 시계열 차트 (plotly)
  3. 분위별 누적 수익률 차트 (plotly)
  4. RS SPY-QQQ 상관 행렬
  5. 성장/퀄리티 클러스터 상관 행렬
  6. Forward P/S IC 부호 경고
  7. 포트폴리오 백테스트 성과
  8. 레짐 게이트 효과
  9. 팩터 상관관계 행렬
  10. 종합 권고사항
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
    IC_RESULTS_DIR,
    BACKTEST_START,
    BACKTEST_END,
    PRICE_FACTORS,
    FUNDAMENTAL_FACTORS,
    IC_THRESHOLD,
    FORWARD_PERIOD_LABELS,
    N_QUANTILES,
)

logger = logging.getLogger(__name__)

_IC_PASS = IC_THRESHOLD if IC_THRESHOLD is not None else 0.03

# plotly JSON을 인라인 HTML로 삽입하기 위해 지연 임포트
try:
    import plotly.graph_objects as go
    import plotly.express as px
    from plotly.subplots import make_subplots
    import plotly.io as pio
    _PLOTLY_OK = True
except ImportError:
    _PLOTLY_OK = False
    logger.warning("plotly 미설치 — 차트 섹션이 생략됩니다. pip install plotly")


# ──────────────────────────────────────────────────────────
# 유틸
# ──────────────────────────────────────────────────────────

def _pct(v, decimals: int = 1) -> str:
    if v is None or (isinstance(v, float) and (v != v or abs(v) == float("inf"))):
        return "—"
    return f"{v * 100:.{decimals}f}%"


def _fmt(v, decimals: int = 3) -> str:
    if v is None or (isinstance(v, float) and (v != v or abs(v) == float("inf"))):
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
    return (
        f'<span style="background:{color};color:#fff;'
        f'padding:2px 8px;border-radius:4px;font-size:0.85em">{label}</span>'
    )


def _ic_cell(ic, tstat) -> str:
    if ic is None or (isinstance(ic, float) and ic != ic):
        return "—"
    color = "#28a745" if abs(ic) >= _IC_PASS else "#dc3545"
    tpart = f" (t={tstat:.2f})" if tstat and not (isinstance(tstat, float) and tstat != tstat) else ""
    return f'<span style="color:{color};font-weight:bold">{ic:.3f}{tpart}</span>'


def _fig_to_html(fig) -> str:
    """plotly figure → 인라인 HTML div"""
    if not _PLOTLY_OK or fig is None:
        return "<p style='color:#6c757d'>plotly 미설치로 차트를 생성하지 못했습니다.</p>"
    return pio.to_html(fig, full_html=False, include_plotlyjs=False)


# ──────────────────────────────────────────────────────────
# HTML 뼈대
# ──────────────────────────────────────────────────────────

def _header(title: str, generated_at: str) -> str:
    plotly_cdn = (
        '<script src="https://cdn.plot.ly/plotly-latest.min.js"></script>'
        if _PLOTLY_OK else ""
    )
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
{plotly_cdn}
<style>
  body {{ font-family: 'Segoe UI', sans-serif; margin: 0; padding: 20px;
          background: #f8f9fa; color: #212529; }}
  h1 {{ color: #343a40; border-bottom: 3px solid #007bff; padding-bottom: 8px; }}
  h2 {{ color: #495057; border-left: 4px solid #007bff; padding-left: 12px;
        margin-top: 40px; }}
  h3 {{ color: #495057; }}
  table {{ border-collapse: collapse; width: 100%; margin-bottom: 24px;
           background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,.12); }}
  th {{ background: #343a40; color: #fff; padding: 10px 12px;
        text-align: left; font-size: 0.9em; }}
  td {{ padding: 8px 12px; border-bottom: 1px solid #dee2e6; font-size: 0.88em; }}
  tr:hover td {{ background: #f1f3f5; }}
  .meta {{ color: #6c757d; font-size: 0.85em; margin-bottom: 24px; }}
  .summary-grid {{ display: grid;
                   grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                   gap: 16px; margin-bottom: 32px; }}
  .card {{ background: #fff; border-radius: 8px; padding: 16px;
           box-shadow: 0 1px 3px rgba(0,0,0,.12); }}
  .card-label {{ font-size: 0.8em; color: #6c757d; text-transform: uppercase; }}
  .card-value {{ font-size: 1.6em; font-weight: bold; color: #343a40; }}
  .positive {{ color: #28a745; }} .negative {{ color: #dc3545; }}
  .note {{ background: #fff3cd; border-left: 4px solid #ffc107;
           padding: 12px 16px; margin: 16px 0; font-size: 0.9em; }}
  .warn {{ background: #f8d7da; border-left: 4px solid #dc3545;
           padding: 12px 16px; margin: 16px 0; font-size: 0.9em; }}
  .section {{ background: #fff; border-radius: 8px; padding: 20px;
              box-shadow: 0 1px 3px rgba(0,0,0,.12); margin-bottom: 24px; }}
  .chart-grid {{ display: grid;
                 grid-template-columns: repeat(auto-fit, minmax(480px, 1fr));
                 gap: 20px; }}
</style>
</head>
<body>
<h1>{title}</h1>
<p class="meta">생성일시: {generated_at} | 백테스트 기간: {BACKTEST_START} ~ {BACKTEST_END}</p>
"""


def _footer() -> str:
    return """
<p class="meta" style="margin-top:48px">
Connect AI v5 §0 — 팩터 검증 보고서 (MVP)
</p>
</body></html>"""


# ──────────────────────────────────────────────────────────
# 섹션 1: 팩터 IC 요약 테이블
# ──────────────────────────────────────────────────────────

def _factor_summary_section(validation_results: list[dict]) -> str:
    if not validation_results:
        return "<p>팩터 검증 결과 없음.</p>"

    rows = []
    all_factors = {**PRICE_FACTORS, **FUNDAMENTAL_FACTORS}
    for r in validation_results:
        factor = r.get("factor", "")
        meta = all_factors.get(factor, (+1, factor, ""))
        sign_str  = "+" if meta[0] == 1 else ("−" if meta[0] == -1 else "?")
        desc      = meta[1]
        v5_sect   = meta[2] if len(meta) > 2 else ""
        status    = r.get("pass", "NO_DATA")
        obs       = r.get("ic_n_periods_12W", "—")
        ic4   = r.get("ic_mean_4W");  ts4  = r.get("ic_tstat_4W")
        ic12  = r.get("ic_mean_12W"); ts12 = r.get("ic_tstat_12W")
        ic24  = r.get("ic_mean_24W"); ts24 = r.get("ic_tstat_24W")
        rows.append(f"""<tr>
  <td><b>{factor}</b><br><small style="color:#6c757d">{desc}</small></td>
  <td>{v5_sect}</td>
  <td style="text-align:center">{sign_str}</td>
  <td>{_ic_cell(ic4,  ts4)}</td>
  <td>{_ic_cell(ic12, ts12)}</td>
  <td>{_ic_cell(ic24, ts24)}</td>
  <td>{obs}</td>
  <td>{_pass_badge(status)}</td>
</tr>""")

    rows_html = "\n".join(rows)
    threshold_note = (
        f"IC 합격 기준: |IC| ≥ {_IC_PASS:.3f}"
        + (" (🔧 IC_THRESHOLD 미설정 → 업계 통상값 적용)" if IC_THRESHOLD is None else "")
    )

    pass_count   = sum(1 for r in validation_results if r.get("pass") == "PASS")
    strong_count = sum(1 for r in validation_results if r.get("pass") == "STRONG_PENDING")
    fail_count   = sum(1 for r in validation_results if r.get("pass") in ("FAIL", "NO_DATA"))
    total = len(validation_results)

    return f"""
<h2>1. 팩터 IC 검증 요약</h2>
<div class="note">{threshold_note}</div>
<div class="summary-grid">
  <div class="card">
    <div class="card-label">전체 팩터</div>
    <div class="card-value">{total}</div>
  </div>
  <div class="card">
    <div class="card-label">PASS</div>
    <div class="card-value positive">{pass_count}</div>
  </div>
  <div class="card">
    <div class="card-label">STRONG_PENDING</div>
    <div class="card-value" style="color:#fd7e14">{strong_count}</div>
  </div>
  <div class="card">
    <div class="card-label">FAIL / NO_DATA</div>
    <div class="card-value negative">{fail_count}</div>
  </div>
</div>
<div class="section">
<table>
<thead><tr>
  <th>팩터</th><th>v5 영역</th><th>예상 부호</th>
  <th>IC 4W</th><th>IC 12W</th><th>IC 24W</th>
  <th>관측수(12W)</th><th>판정</th>
</tr></thead>
<tbody>{rows_html}</tbody>
</table>
</div>
"""


# ──────────────────────────────────────────────────────────
# 섹션 2: IC 시계열 차트 (plotly)
# ──────────────────────────────────────────────────────────

def _ic_timeseries_section(validation_results: list[dict]) -> str:
    if not _PLOTLY_OK or not validation_results:
        return ""

    charts_html = []
    for r in validation_results:
        factor = r.get("factor", "")
        status = r.get("pass", "")
        if status in ("NO_DATA",):
            continue

        period_figs = []
        for label in FORWARD_PERIOD_LABELS:
            parquet_path = IC_RESULTS_DIR / f"{factor}_ic_{label}.parquet"
            if not parquet_path.exists():
                continue
            try:
                ic_ts = pd.read_parquet(parquet_path)
                if ic_ts.empty or "ic" not in ic_ts.columns:
                    continue
                ic_ts["date"] = pd.to_datetime(ic_ts["date"])

                fig = go.Figure()
                fig.add_trace(go.Bar(
                    x=ic_ts["date"],
                    y=ic_ts["ic"],
                    name="IC",
                    marker_color=[
                        "#28a745" if v >= 0 else "#dc3545"
                        for v in ic_ts["ic"]
                    ],
                ))
                fig.add_hline(y=_IC_PASS,  line_dash="dot", line_color="#28a745",
                              annotation_text=f"+{_IC_PASS}")
                fig.add_hline(y=-_IC_PASS, line_dash="dot", line_color="#28a745")
                fig.add_hline(y=0, line_color="#000", line_width=1)

                ic_mean = ic_ts["ic"].mean()
                fig.update_layout(
                    title=f"{factor} — IC 시계열 ({label})  평균: {ic_mean:+.4f}",
                    height=260,
                    margin=dict(l=40, r=20, t=40, b=30),
                    showlegend=False,
                    template="plotly_white",
                )
                period_figs.append(_fig_to_html(fig))
            except Exception as e:
                logger.debug("IC 차트 생성 실패 %s %s: %s", factor, label, e)

        if period_figs:
            inner = "\n".join(
                f'<div style="flex:1;min-width:400px">{f}</div>' for f in period_figs
            )
            charts_html.append(f"""
<div class="section">
<h3>{factor} &nbsp; {_pass_badge(status)}</h3>
<div style="display:flex;flex-wrap:wrap;gap:12px">{inner}</div>
</div>""")

    if not charts_html:
        return ""

    return "<h2>2. IC 시계열 차트</h2>\n" + "\n".join(charts_html)


# ──────────────────────────────────────────────────────────
# 섹션 3: 분위별 누적 수익률 차트 (plotly)
# ──────────────────────────────────────────────────────────

def _quintile_chart_section(validation_results: list[dict]) -> str:
    if not _PLOTLY_OK or not validation_results:
        return ""

    COLORS = ["#dc3545", "#fd7e14", "#ffc107", "#20c997", "#28a745"]

    charts_html = []
    for r in validation_results:
        factor = r.get("factor", "")
        status = r.get("pass", "")
        if status == "NO_DATA":
            continue

        period_figs = []
        for label in FORWARD_PERIOD_LABELS:
            cumul_path = IC_RESULTS_DIR / f"{factor}_cumulative_{label}.parquet"
            if not cumul_path.exists():
                continue
            try:
                cumul = pd.read_parquet(cumul_path)
                if cumul.empty:
                    continue
                cumul["date"] = pd.to_datetime(cumul["date"])
                q_cols = [c for c in cumul.columns if c.startswith("Q")]
                if not q_cols:
                    continue

                fig = go.Figure()
                for i, qc in enumerate(sorted(q_cols)):
                    fig.add_trace(go.Scatter(
                        x=cumul["date"],
                        y=cumul[qc],
                        name=qc,
                        line=dict(color=COLORS[i % len(COLORS)], width=2),
                    ))
                fig.update_layout(
                    title=f"{factor} — 분위별 누적 수익률 ({label})",
                    height=280,
                    margin=dict(l=40, r=20, t=40, b=30),
                    legend=dict(orientation="h", y=-0.15),
                    template="plotly_white",
                    yaxis_tickformat=".0%",
                )
                period_figs.append(_fig_to_html(fig))
            except Exception as e:
                logger.debug("누적 수익률 차트 실패 %s %s: %s", factor, label, e)

        # 분위 평균 수익률 테이블도 함께
        q_table_rows = []
        for label in FORWARD_PERIOD_LABELS:
            q_path = IC_RESULTS_DIR / f"{factor}_quintile_{label}.parquet"
            if not q_path.exists():
                continue
            try:
                q_df = pd.read_parquet(q_path)
                if q_df.empty:
                    continue
                for _, row in q_df.sort_values("quantile").iterrows():
                    ret = row.get("mean_return", None)
                    color = "positive" if ret and ret > 0 else ("negative" if ret and ret < 0 else "")
                    q_table_rows.append(
                        f"<tr><td>{label}</td><td>Q{int(row['quantile'])}</td>"
                        f"<td class='{color}'>{_pct(ret)}</td>"
                        f"<td>{int(row.get('count', 0))}</td></tr>"
                    )
            except Exception:
                pass

        if period_figs or q_table_rows:
            figs_html = "\n".join(
                f'<div style="flex:1;min-width:420px">{f}</div>'
                for f in period_figs
            )
            table_html = ""
            if q_table_rows:
                table_html = f"""
<table style="max-width:420px;margin-top:12px">
<thead><tr><th>기간</th><th>분위</th><th>평균수익률</th><th>관측수</th></tr></thead>
<tbody>{"".join(q_table_rows)}</tbody>
</table>"""
            charts_html.append(f"""
<div class="section">
<h3>{factor} &nbsp; {_pass_badge(status)}</h3>
<div style="display:flex;flex-wrap:wrap;gap:12px">{figs_html}</div>
{table_html}
</div>""")

    if not charts_html:
        return ""

    return "<h2>3. 분위별 누적 수익률</h2>\n" + "\n".join(charts_html)


# ──────────────────────────────────────────────────────────
# 섹션 4: RS SPY-QQQ 상관 행렬
# ──────────────────────────────────────────────────────────

def _rs_correlation_section(correlation_data: dict) -> str:
    rs_corr = correlation_data.get("rs_correlation")
    if rs_corr is None:
        # parquet 파일에서 로드 시도
        p = IC_RESULTS_DIR / "correlation_rs_correlation.parquet"
        if p.exists():
            try:
                rs_corr = pd.read_parquet(p)
            except Exception:
                pass
    if rs_corr is None:
        return ""

    return _corr_matrix_html(
        rs_corr,
        title="4. RS SPY-QQQ 상관 행렬",
        note="|상관계수| > 0.85인 셀(빨간색): v5 권장 — RS 종합 팩터로 통합",
        threshold=0.85,
    )


# ──────────────────────────────────────────────────────────
# 섹션 5: 성장/퀄리티 클러스터 상관 행렬
# ──────────────────────────────────────────────────────────

def _growth_cluster_section(correlation_data: dict) -> str:
    growth_corr = correlation_data.get("growth_cluster_correlation")
    if growth_corr is None:
        p = IC_RESULTS_DIR / "correlation_growth_cluster_correlation.parquet"
        if p.exists():
            try:
                growth_corr = pd.read_parquet(p)
            except Exception:
                pass
    if growth_corr is None:
        return ""

    return _corr_matrix_html(
        growth_corr,
        title="5. 성장/퀄리티 클러스터 상관 행렬",
        note="높은 상관 팩터(|r| > 0.7)는 배점 축소 권장",
        threshold=0.7,
    )


def _corr_matrix_html(corr_df: pd.DataFrame, title: str, note: str, threshold: float) -> str:
    cols = corr_df.columns.tolist()
    header = "<tr><th></th>" + "".join(f"<th>{c}</th>" for c in cols) + "</tr>"
    body_rows = []
    for idx, row in corr_df.iterrows():
        cells = ""
        for c in cols:
            v = row.get(c)
            if v is None or (isinstance(v, float) and v != v):
                cells += "<td>—</td>"
                continue
            is_self = str(idx) == str(c)
            if not is_self and abs(v) > threshold:
                cells += f'<td style="background:#f8d7da;font-weight:bold">{v:.2f}</td>'
            else:
                cells += f"<td>{v:.2f}</td>"
        body_rows.append(f"<tr><th>{idx}</th>{cells}</tr>")

    return f"""
<h2>{title}</h2>
<div class="note">{note}</div>
<div class="section" style="overflow-x:auto">
<table>
<thead>{header}</thead>
<tbody>{"".join(body_rows)}</tbody>
</table>
</div>
"""


# ──────────────────────────────────────────────────────────
# 섹션 6: Forward P/S IC 부호 경고
# ──────────────────────────────────────────────────────────

def _forward_ps_section(forward_ps_result: dict) -> str:
    if not forward_ps_result or not forward_ps_result.get("available", True):
        return ""

    ic_12w = forward_ps_result.get("ic_mean_12W")
    if ic_12w is None or (isinstance(ic_12w, float) and ic_12w != ic_12w):
        return ""

    if ic_12w > 0:
        level = "warn"
        msg = (
            f"⚠️ <b>Forward P/S IC 부호가 양(+{ic_12w:.4f})</b>으로 측정됨.<br>"
            "v5 §4 경고: 낮은 P/S가 저평가가 아니라 성장 둔화 선반영일 가능성.<br>"
            "<b>권장 조치:</b> '지나치게 비쌀 때만 감점' 형태로 스코어링 방향 전환 검토."
        )
    else:
        level = "note"
        msg = f"Forward P/S IC: {ic_12w:+.4f} — 의도 부호(-) 일치. 정상."

    return f"""
<h2>6. Forward P/S IC 부호 확인</h2>
<div class="{level}">{msg}</div>
"""


# ──────────────────────────────────────────────────────────
# 섹션 7: 포트폴리오 백테스트 성과
# ──────────────────────────────────────────────────────────

def _backtest_perf_section(backtest_results: dict) -> str:
    if not backtest_results:
        return "<p>백테스트 결과 없음.</p>"

    cards, table_rows = [], []
    for key, result in backtest_results.items():
        if not isinstance(result, dict):
            continue
        stats = result.get("stats", {})
        if not stats:
            continue

        cagr   = stats.get("cagr")
        mdd    = stats.get("max_drawdown")
        sharpe = stats.get("sharpe")
        alpha  = stats.get("alpha")
        bench_cagr = stats.get("benchmark_cagr")
        hit    = stats.get("hit_rate")
        n      = stats.get("n_periods", "—")

        cagr_cls  = "positive" if cagr  and cagr  > 0 else "negative"
        alpha_cls = "positive" if alpha and alpha > 0 else "negative"

        cards.append(f"""<div class="card">
<div class="card-label">{key}</div>
<div class="card-value {cagr_cls}">{_pct(cagr)}</div>
<small>CAGR | MDD: {_pct(mdd)} | Sharpe: {_fmt(sharpe, 2)}</small><br>
<small>Alpha: <span class="{alpha_cls}">{_pct(alpha)}</span> | Hit: {_pct(hit)} | N={n}</small>
</div>""")

        table_rows.append(f"""<tr>
<td><b>{key}</b></td>
<td class="{cagr_cls}">{_pct(cagr)}</td>
<td>{_pct(bench_cagr)}</td>
<td class="{alpha_cls}">{_pct(alpha)}</td>
<td>{_pct(mdd)}</td>
<td>{_fmt(sharpe, 2)}</td>
<td>{_pct(hit)}</td>
<td>{n}</td>
</tr>""")

    if not cards:
        return "<p>포트폴리오 성과 데이터 없음.</p>"

    # 성과 시계열 차트 (plotly)
    chart_html = ""
    if _PLOTLY_OK:
        for key, result in backtest_results.items():
            ret = result.get("returns") if isinstance(result, dict) else None
            bench = result.get("benchmark_returns") if isinstance(result, dict) else None
            if ret is None:
                continue
            try:
                ret_s = pd.Series(ret)
                ret_s.index = pd.to_datetime(ret_s.index)
                cumul = (1 + ret_s).cumprod()

                fig = go.Figure()
                fig.add_trace(go.Scatter(x=cumul.index, y=cumul.values,
                                         name=key, line=dict(color="#007bff", width=2)))
                if bench is not None:
                    bench_s = pd.Series(bench)
                    bench_s.index = pd.to_datetime(bench_s.index)
                    bench_cumul = (1 + bench_s).cumprod()
                    fig.add_trace(go.Scatter(x=bench_cumul.index, y=bench_cumul.values,
                                             name="Benchmark",
                                             line=dict(color="#6c757d", width=1, dash="dot")))
                fig.update_layout(
                    title=f"{key} — 누적 수익률",
                    height=300,
                    margin=dict(l=40, r=20, t=40, b=30),
                    template="plotly_white",
                    yaxis_tickformat=".1f",
                )
                chart_html += f'<div style="margin-bottom:20px">{_fig_to_html(fig)}</div>'
            except Exception as e:
                logger.debug("성과 차트 실패 %s: %s", key, e)

    return f"""
<h2>7. 포트폴리오 백테스트 성과</h2>
<div class="summary-grid">{"".join(cards)}</div>
{chart_html}
<div class="section">
<table>
<thead><tr>
  <th>포트폴리오</th><th>CAGR</th><th>벤치마크 CAGR</th><th>Alpha</th>
  <th>MDD</th><th>Sharpe</th><th>Hit Rate</th><th>리밸런싱 횟수</th>
</tr></thead>
<tbody>{"".join(table_rows)}</tbody>
</table>
</div>
"""


# ──────────────────────────────────────────────────────────
# 섹션 8: 레짐 게이트 효과
# ──────────────────────────────────────────────────────────

def _regime_section(backtest_results: dict) -> str:
    on_stats  = backtest_results.get("regime_on",  {}).get("stats", {}) if backtest_results else {}
    off_stats = backtest_results.get("regime_off", {}).get("stats", {}) if backtest_results else {}
    if not on_stats and not off_stats:
        return ""

    def _row(label, stats):
        cagr   = stats.get("cagr")
        mdd    = stats.get("max_drawdown")
        sharpe = stats.get("sharpe")
        n      = stats.get("n_periods", "—")
        cls    = "positive" if cagr and cagr > 0 else "negative"
        return (f"<tr><td>{label}</td><td class='{cls}'>{_pct(cagr)}</td>"
                f"<td>{_pct(mdd)}</td><td>{_fmt(sharpe, 2)}</td><td>{n}</td></tr>")

    rows = ""
    if on_stats:  rows += _row("레짐 RISK_ON (게이트 적용)", on_stats)
    if off_stats: rows += _row("레짐 OFF (전체 기간)", off_stats)

    return f"""
<h2>8. 레짐 게이트 효과</h2>
<div class="note">
SPY/QQQ MA200 기반 레짐 게이트 ON/OFF 비교.
CAUTION 구간 축소 운용이 MDD 개선에 기여하는지 확인.
</div>
<div class="section">
<table>
<thead><tr><th>구분</th><th>CAGR</th><th>MDD</th><th>Sharpe</th><th>리밸런싱 횟수</th></tr></thead>
<tbody>{rows}</tbody>
</table>
</div>
"""


# ──────────────────────────────────────────────────────────
# 섹션 9: 전체 팩터 상관 행렬
# ──────────────────────────────────────────────────────────

def _factor_corr_section(validation_results: list[dict]) -> str:
    if not validation_results:
        return ""

    # features_daily에서 상관행렬 직접 계산 (저장된 경우만)
    feat_path = IC_RESULTS_DIR.parent.parent / "data" / "features" / "features_daily.parquet"
    # config 경로 기준으로 다시
    from config import FEATURES_DIR as _FEAT_DIR
    feat_path = _FEAT_DIR / "features_daily.parquet"
    if not feat_path.exists():
        return ""

    try:
        all_factors = list(PRICE_FACTORS.keys()) + list(FUNDAMENTAL_FACTORS.keys())
        df = pd.read_parquet(feat_path)
        available = [f for f in all_factors if f in df.columns]
        if len(available) < 2:
            return ""
        corr = df[available].corr(method="spearman")
    except Exception as e:
        logger.debug("전체 팩터 상관 계산 실패: %s", e)
        return ""

    return _corr_matrix_html(
        corr,
        title="9. 전체 팩터 상관 행렬 (Spearman)",
        note="|상관계수| > 0.7 셀(빨간색) — 중복 팩터 의심, 배점 축소 권장",
        threshold=0.7,
    )


# ──────────────────────────────────────────────────────────
# 섹션 10: 종합 권고사항
# ──────────────────────────────────────────────────────────

def _recommendations_section(validation_results: list[dict]) -> str:
    passed   = [r["factor"] for r in validation_results if r.get("pass") == "PASS"]
    pending  = [r["factor"] for r in validation_results if r.get("pass") in ("STRONG_PENDING", "WEAK_PENDING")]
    failed   = [r["factor"] for r in validation_results if r.get("pass") in ("FAIL", "NO_DATA")]

    to_li = lambda lst: "".join(f"<li><code>{f}</code></li>" for f in lst) or "<li>없음</li>"
    ic_note = (
        "⚠️ IC_THRESHOLD 🔧 미설정 — 업계 통상값 0.03 임시 적용."
        " 백테스트 결과 확인 후 config.py 에서 확정 필요."
        if IC_THRESHOLD is None else f"IC 합격 기준: {IC_THRESHOLD:.3f}"
    )

    return f"""
<h2>10. 종합 권고사항</h2>
<div class="note">{ic_note}</div>
<div class="section">
<h3>✔ 합격 팩터 (v5 시스템 채택 권장)</h3>
<ul>{to_li(passed)}</ul>
<h3>★ 보류 팩터 (추가 데이터 수집 후 재검증)</h3>
<ul>{to_li(pending)}</ul>
<h3>✘ 불합격 / 데이터 부족 팩터</h3>
<ul>{to_li(failed)}</ul>
<h3>다음 단계</h3>
<ul>
  <li>합격 팩터로 <code>run_combined_portfolio()</code> 재실행하여 최종 성과 확인</li>
  <li><code>config.py</code>의 🔧 파라미터를 백테스트 결과 기반으로 확정</li>
  <li>PASS 팩터만으로 universe scan → <code>screen.py</code> 구현 진행</li>
</ul>
</div>
"""


# ──────────────────────────────────────────────────────────
# 공개 API
# ──────────────────────────────────────────────────────────

def generate_report(
    validation_results: list[dict],
    backtest_results:   dict | None = None,
    correlation_data:   dict | None = None,
    forward_ps_result:  dict | None = None,
    output_path: Path | None = None,
) -> Path:
    """
    HTML 보고서를 생성한다.

    Parameters
    ----------
    validation_results : main.step_validate_*() 반환 list[dict]
    backtest_results   : backtest_engine.run_full_backtest() 반환 dict (선택)
    correlation_data   : factor_validator.analyze_factor_correlations() 반환 dict (선택)
    forward_ps_result  : factor_validator.check_forward_ps_sign_warning() 반환 dict (선택)
    output_path        : 지정 없으면 REPORTS_DIR/report_<timestamp>.html

    Returns
    -------
    Path : 저장된 HTML 파일 경로
    """
    if backtest_results  is None: backtest_results  = {}
    if correlation_data  is None: correlation_data  = {}
    if forward_ps_result is None: forward_ps_result = {}

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    title = f"Connect AI v5 §0 팩터 검증 보고서 ({generated_at[:10]})"

    sections = [
        _header(title, generated_at),
        _factor_summary_section(validation_results),
        _ic_timeseries_section(validation_results),
        _quintile_chart_section(validation_results),
        _rs_correlation_section(correlation_data),
        _growth_cluster_section(correlation_data),
        _forward_ps_section(forward_ps_result),
        _backtest_perf_section(backtest_results),
        _regime_section(backtest_results),
        _factor_corr_section(validation_results),
        _recommendations_section(validation_results),
        _footer(),
    ]
    html = "\n".join(s for s in sections if s)

    if output_path is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = REPORTS_DIR / f"report_{ts}.html"

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    logger.info("보고서 저장: %s", output_path)
    return output_path


def save_validation_json(validation_results: list[dict], output_path: Path | None = None) -> Path:
    """검증 결과를 JSON으로 저장"""
    if output_path is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = REPORTS_DIR / f"validation_{ts}.json"
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    serializable = []
    for r in validation_results:
        row = {}
        for k, v in r.items():
            if isinstance(v, float) and (v != v or abs(v) == float("inf")):
                row[k] = None
            elif isinstance(v, (np.integer,)):
                row[k] = int(v)
            elif isinstance(v, (np.floating,)):
                row[k] = float(v)
            elif isinstance(v, pd.DataFrame):
                row[k] = v.to_dict()
            else:
                row[k] = v
        serializable.append(row)

    output_path.write_text(
        json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("검증 결과 JSON 저장: %s", output_path)
    return output_path
