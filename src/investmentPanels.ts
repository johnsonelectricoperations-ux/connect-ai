/**
 * Connect AI · 투자 UI 패널
 *  - PortfolioPanel  : 보유종목 매매 입력 (portfolio.csv CRUD)
 *  - WatchlistPanel  : 관심종목 관리 (watchlist.json, 자동/수동 구분)
 */
import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import { spawnSync, spawn } from 'child_process';

// ─────────────────────────────────────────────
// 공통 유틸
// ─────────────────────────────────────────────

function _py(): string {
    try {
        const cfg = vscode.workspace.getConfiguration('connectAiLab');
        const ov = (cfg.get<string>('pythonPath') || '').trim();
        if (ov) {
            const r = spawnSync(ov, ['--version'], { encoding: 'utf-8', timeout: 3000 });
            if (r.status === 0) return ov;
        }
    } catch { /* ignore */ }
    const candidates = process.platform === 'win32'
        ? ['py', 'python3', 'python']
        : ['python3', 'python', '/usr/bin/python3'];
    for (const cmd of candidates) {
        try {
            const r = spawnSync(cmd, ['--version'], { encoding: 'utf-8', timeout: 3000, shell: process.platform === 'win32' });
            if (r.status === 0) return cmd;
        } catch { /* ignore */ }
    }
    return 'python3';
}

function _wsDir(): string {
    return vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || '';
}

function _runPy(script: string, args: string[] = []): Promise<string> {
    return new Promise((resolve) => {
        const cwd = _wsDir();
        const scriptPath = path.join(cwd, script);
        if (!fs.existsSync(scriptPath)) {
            resolve(JSON.stringify({ error: `${script} 파일이 없습니다. 워크스페이스에 복사하세요.` }));
            return;
        }
        const py = _py();
        // Windows: 'py -3' might be 'py' with arg '-3'
        let cmd = py;
        let cmdArgs = [scriptPath, ...args];
        if (py.includes(' ')) {
            const parts = py.split(' ');
            cmd = parts[0];
            cmdArgs = [...parts.slice(1), scriptPath, ...args];
        }
        let out = '';
        const proc = spawn(cmd, cmdArgs, { cwd, env: { ...process.env } });
        proc.stdout?.on('data', (d: Buffer) => { out += d.toString(); });
        proc.stderr?.on('data', () => { /* ignore */ });
        const timer = setTimeout(() => { try { proc.kill(); } catch {} resolve(JSON.stringify({ error: '타임아웃 (20초)' })); }, 20000);
        proc.on('close', () => { clearTimeout(timer); resolve(out.trim() || JSON.stringify({ error: '출력 없음' })); });
    });
}

// ─────────────────────────────────────────────
// CSV 유틸 (portfolio.csv 직접 읽기/쓰기)
// ─────────────────────────────────────────────

interface PortfolioRow {
    ticker: string;
    shares: string;
    avg_cost: string;
    stop: string;
    target: string;
}

function _readCsv(filePath: string): PortfolioRow[] {
    if (!fs.existsSync(filePath)) return [];
    const lines = fs.readFileSync(filePath, 'utf-8').split('\n').map(l => l.trim()).filter(Boolean);
    if (lines.length < 2) return [];
    const rows: PortfolioRow[] = [];
    for (let i = 1; i < lines.length; i++) {
        const parts = lines[i].split(',');
        if (parts.length < 1 || !parts[0].trim()) continue;
        rows.push({
            ticker:   (parts[0] || '').trim().toUpperCase(),
            shares:   (parts[1] || '').trim(),
            avg_cost: (parts[2] || '').trim(),
            stop:     (parts[3] || '').trim(),
            target:   (parts[4] || '').trim(),
        });
    }
    return rows;
}

function _writeCsv(filePath: string, rows: PortfolioRow[]): void {
    const header = 'ticker,shares,avg_cost,stop,target';
    const body = rows.map(r =>
        `${r.ticker},${r.shares},${r.avg_cost},${r.stop},${r.target}`
    ).join('\n');
    fs.writeFileSync(filePath, header + '\n' + body + '\n', 'utf-8');
}

// ─────────────────────────────────────────────
// watchlist.json 유틸
// ─────────────────────────────────────────────

interface WatchlistEntry {
    added: string;
    note: string;
    earningsDate: string | null;
    lastScore: number | null;
    addedBy: 'auto' | 'manual';
}

interface WatchlistDb { [ticker: string]: WatchlistEntry; }

function _readWatchlist(filePath: string): WatchlistDb {
    if (!fs.existsSync(filePath)) return {};
    try { return JSON.parse(fs.readFileSync(filePath, 'utf-8')); } catch { return {}; }
}

function _writeWatchlist(filePath: string, db: WatchlistDb): void {
    fs.writeFileSync(filePath, JSON.stringify(db, null, 2), 'utf-8');
    // watchlist.txt 동기화 (screen.py 호환)
    const txtPath = path.join(path.dirname(filePath), 'watchlist.txt');
    const tickers = Object.keys(db).join('\n') + '\n';
    fs.writeFileSync(txtPath, tickers, 'utf-8');
}

function _today(): string {
    return new Date().toISOString().slice(0, 10);
}

// ─────────────────────────────────────────────
// PortfolioPanel
// ─────────────────────────────────────────────

export class PortfolioPanel {
    public static current: PortfolioPanel | null = null;
    private static readonly _viewType = 'connectAiLab.portfolio';
    private readonly _panel: vscode.WebviewPanel;
    private readonly _csvPath: string;
    private _disposables: vscode.Disposable[] = [];

    public static createOrShow(extensionUri: vscode.Uri): void {
        const column = vscode.ViewColumn.Active;
        if (PortfolioPanel.current) {
            PortfolioPanel.current._panel.reveal(column);
            PortfolioPanel.current._refresh();
            return;
        }
        const panel = vscode.window.createWebviewPanel(
            PortfolioPanel._viewType,
            '📊 내 포트폴리오',
            column,
            { enableScripts: true, retainContextWhenHidden: true }
        );
        PortfolioPanel.current = new PortfolioPanel(panel, extensionUri);
    }

    private constructor(panel: vscode.WebviewPanel, _extUri: vscode.Uri) {
        this._panel = panel;
        this._csvPath = path.join(_wsDir(), 'portfolio.csv');
        this._panel.webview.html = this._html();
        this._panel.onDidDispose(() => {
            PortfolioPanel.current = null;
            this._disposables.forEach(d => d.dispose());
        }, null, this._disposables);
        this._panel.webview.onDidReceiveMessage(async (msg) => {
            switch (msg?.type) {
                case 'ready':     await this._refresh(); break;
                case 'save':      this._save(msg.rows); await this._refresh(); break;
                case 'runPy':     await this._refreshWithPrices(); break;
            }
        }, null, this._disposables);
    }

    private _save(rows: PortfolioRow[]): void {
        _writeCsv(this._csvPath, rows.filter(r => r.ticker));
    }

    private async _refresh(): Promise<void> {
        const rows = _readCsv(this._csvPath);
        this._panel.webview.postMessage({ type: 'csvData', rows });
    }

    private async _refreshWithPrices(): Promise<void> {
        this._panel.webview.postMessage({ type: 'loading', on: true });
        const raw = await _runPy('portfolio.py');
        this._panel.webview.postMessage({ type: 'loading', on: false });
        try {
            const data = JSON.parse(raw);
            this._panel.webview.postMessage({ type: 'pyData', data });
        } catch {
            this._panel.webview.postMessage({ type: 'pyData', data: { error: raw } });
        }
    }

    private _html(): string {
        return `<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>포트폴리오</title>
<style>
  :root {
    --bg:       var(--vscode-editor-background, #1e1e1e);
    --bg2:      var(--vscode-sideBar-background, #252526);
    --bg3:      var(--vscode-input-background, #3c3c3c);
    --border:   var(--vscode-panel-border, #444);
    --fg:       var(--vscode-editor-foreground, #ccc);
    --fg2:      var(--vscode-descriptionForeground, #999);
    --accent:   var(--vscode-button-background, #0e639c);
    --accent-fg:var(--vscode-button-foreground, #fff);
    --green:    #4ec994;
    --red:      #f14c4c;
    --yellow:   #d7ba7d;
    --radius:   6px;
    font-size: 13px;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--fg); font-family: var(--vscode-font-family, sans-serif); padding: 16px; }

  h2 { font-size: 16px; font-weight: 600; margin-bottom: 4px; }
  .subtitle { color: var(--fg2); font-size: 11px; margin-bottom: 16px; }

  /* summary bar */
  .summary-bar { display: flex; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }
  .stat-card { background: var(--bg2); border: 1px solid var(--border); border-radius: var(--radius); padding: 10px 16px; min-width: 140px; }
  .stat-card .label { font-size: 11px; color: var(--fg2); margin-bottom: 4px; }
  .stat-card .value { font-size: 15px; font-weight: 600; }
  .stat-card .value.up   { color: var(--green); }
  .stat-card .value.down { color: var(--red); }

  /* toolbar */
  .toolbar { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
  .toolbar h3 { flex: 1; font-size: 13px; font-weight: 600; }
  button { background: var(--accent); color: var(--accent-fg); border: none; border-radius: var(--radius); padding: 5px 12px; cursor: pointer; font-size: 12px; }
  button:hover { opacity: 0.85; }
  button.secondary { background: var(--bg3); color: var(--fg); }
  button.danger    { background: #5a1d1d; color: #f14c4c; }
  button.sm { padding: 3px 8px; font-size: 11px; }

  /* table */
  .table-wrap { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  th { background: var(--bg2); padding: 8px 10px; text-align: left; font-weight: 600; color: var(--fg2); border-bottom: 1px solid var(--border); white-space: nowrap; }
  td { padding: 7px 10px; border-bottom: 1px solid var(--border); vertical-align: middle; }
  tr:hover td { background: var(--bg2); }
  .ticker-cell { font-weight: 700; font-size: 13px; letter-spacing: 0.5px; }
  .num  { text-align: right; font-variant-numeric: tabular-nums; }
  .up   { color: var(--green); }
  .down { color: var(--red); }
  .badge { display: inline-block; padding: 2px 7px; border-radius: 10px; font-size: 10px; font-weight: 700; }
  .badge.hold   { background: #1f3a2f; color: var(--green); }
  .badge.stop   { background: #3a1f1f; color: var(--red); }
  .badge.target { background: #1f2e3a; color: #79b8ff; }
  .badge.add    { background: #2e2a1f; color: var(--yellow); }
  .empty-msg { text-align: center; color: var(--fg2); padding: 32px 0; font-size: 13px; }

  /* modal overlay */
  .overlay { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.55); z-index: 100; align-items: center; justify-content: center; }
  .overlay.show { display: flex; }
  .modal { background: var(--bg2); border: 1px solid var(--border); border-radius: 8px; padding: 20px; width: 360px; max-width: 95vw; }
  .modal h3 { margin-bottom: 14px; font-size: 14px; }
  .form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  .form-grid .full { grid-column: 1 / -1; }
  .field label { display: block; font-size: 11px; color: var(--fg2); margin-bottom: 4px; }
  .field input { width: 100%; background: var(--bg3); color: var(--fg); border: 1px solid var(--border); border-radius: 4px; padding: 6px 8px; font-size: 12px; }
  .field input:focus { outline: 1px solid var(--accent); border-color: var(--accent); }
  .modal-btns { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }

  /* loading */
  .loading-bar { display: none; text-align: center; color: var(--fg2); font-size: 12px; padding: 8px 0; }
  .loading-bar.on { display: block; }

  /* note */
  .note-hint { color: var(--fg2); font-size: 11px; margin-top: 4px; }
</style>
</head>
<body>
<h2>📊 내 포트폴리오</h2>
<p class="subtitle">portfolio.csv 직접 관리 — 매매는 내가 직접 입력</p>

<div class="summary-bar" id="summaryBar">
  <div class="stat-card"><div class="label">총 보유 종목</div><div class="value" id="statCount">—</div></div>
  <div class="stat-card"><div class="label">총 평가액</div><div class="value" id="statValue">—</div></div>
  <div class="stat-card"><div class="label">총 손익</div><div class="value" id="statPnl">—</div></div>
  <div class="stat-card"><div class="label">총 투자금</div><div class="value" id="statCost">—</div></div>
</div>

<div class="toolbar">
  <h3>보유 종목</h3>
  <button class="secondary sm" id="btnRefreshPy" title="Python으로 현재가·손익 계산">⟳ 현재가 갱신</button>
  <button id="btnAdd">+ 매수 추가</button>
</div>
<div class="loading-bar" id="loadingBar">현재가 조회 중… (yfinance)</div>

<div class="table-wrap">
  <table id="holdingsTable">
    <thead>
      <tr>
        <th>티커</th>
        <th class="num">수량</th>
        <th class="num">매수가</th>
        <th class="num">현재가</th>
        <th class="num">평가액</th>
        <th class="num">손익</th>
        <th class="num">손절가</th>
        <th class="num">목표가</th>
        <th>액션</th>
        <th>편집</th>
      </tr>
    </thead>
    <tbody id="holdingsBody">
      <tr><td colspan="10" class="empty-msg">포트폴리오를 불러오는 중…</td></tr>
    </tbody>
  </table>
</div>

<!-- 추가/수정 모달 -->
<div class="overlay" id="overlay">
  <div class="modal">
    <h3 id="modalTitle">매수 추가</h3>
    <div class="form-grid">
      <div class="field full">
        <label>티커 (예: IONQ)</label>
        <input id="fTicker" placeholder="IONQ" style="text-transform:uppercase">
      </div>
      <div class="field">
        <label>수량</label>
        <input id="fShares" type="number" placeholder="10" min="0.0001" step="any">
      </div>
      <div class="field">
        <label>평균 매수가 ($)</label>
        <input id="fCost" type="number" placeholder="45.00" min="0" step="any">
      </div>
      <div class="field">
        <label>손절가 ($) <span style="color:var(--fg2)">선택</span></label>
        <input id="fStop" type="number" placeholder="40.00" min="0" step="any">
      </div>
      <div class="field">
        <label>목표가 ($) <span style="color:var(--fg2)">선택</span></label>
        <input id="fTarget" type="number" placeholder="90.00" min="0" step="any">
      </div>
    </div>
    <p class="note-hint">현재가는 저장 후 "현재가 갱신" 버튼으로 조회합니다.</p>
    <div class="modal-btns">
      <button class="secondary" id="btnCancel">취소</button>
      <button id="btnSave">저장</button>
    </div>
  </div>
</div>

<script>
const vscode = acquireVsCodeApi();
let csvRows = [];      // [{ticker, shares, avg_cost, stop, target}]
let pyData = null;     // portfolio.py 결과
let editIdx = -1;      // -1=추가, >=0=수정

// ─── 초기화 ───
window.addEventListener('message', e => {
  const msg = e.data;
  if (msg.type === 'csvData') {
    csvRows = msg.rows || [];
    renderTable();
  } else if (msg.type === 'pyData') {
    pyData = msg.data;
    renderTable();
  } else if (msg.type === 'loading') {
    document.getElementById('loadingBar').classList.toggle('on', !!msg.on);
  }
});
vscode.postMessage({ type: 'ready' });

// ─── 렌더 ───
function fmt(v, dec=2) {
  if (v == null || v === '' || isNaN(+v)) return '—';
  return (+v).toLocaleString('en-US', { minimumFractionDigits: dec, maximumFractionDigits: dec });
}
function fmtUSD(v) { return v == null ? '—' : '$' + fmt(v); }
function pnlClass(v) { return v > 0 ? 'up' : v < 0 ? 'down' : ''; }

function renderTable() {
  // 요약 바
  let totalVal = 0, totalCost = 0, validRows = 0;
  const byTicker = {};
  if (pyData && pyData.holdings) {
    pyData.holdings.forEach(h => { byTicker[h.ticker] = h; });
  }

  const tbody = document.getElementById('holdingsBody');
  if (csvRows.length === 0) {
    tbody.innerHTML = '<tr><td colspan="10" class="empty-msg">보유 종목이 없습니다. "매수 추가" 버튼으로 추가하세요.</td></tr>';
    updateSummary(0, null, null, null);
    return;
  }

  tbody.innerHTML = csvRows.map((r, i) => {
    const py = byTicker[r.ticker];
    const curPrice = py?.currentPrice ?? null;
    const shares   = +r.shares || 0;
    const avgCost  = +r.avg_cost || 0;
    const stopP    = r.stop ? +r.stop : null;
    const targetP  = r.target ? +r.target : null;
    const evalVal  = curPrice ? curPrice * shares : null;
    const costVal  = avgCost * shares;
    const pnlVal   = evalVal != null ? evalVal - costVal : null;
    const pnlPct   = pnlVal != null && costVal ? pnlVal / costVal * 100 : null;

    if (evalVal) totalVal += evalVal;
    if (costVal) { totalCost += costVal; validRows++; }

    const action = py?.action || '—';
    const badgeCls = action === 'STOP_BREACHED' ? 'stop' : action === 'TARGET_HIT' ? 'target' : action === 'ADD' ? 'add' : 'hold';

    return \`<tr>
      <td class="ticker-cell">\${r.ticker}</td>
      <td class="num">\${fmt(r.shares, r.shares % 1 === 0 ? 0 : 4)}</td>
      <td class="num">\${fmtUSD(r.avg_cost)}</td>
      <td class="num">\${curPrice ? fmtUSD(curPrice) : '—'}</td>
      <td class="num">\${evalVal ? fmtUSD(evalVal) : '—'}</td>
      <td class="num \${pnlClass(pnlVal)}">\${pnlPct != null ? (pnlPct >= 0 ? '+' : '') + fmt(pnlPct, 1) + '%' : '—'}</td>
      <td class="num \${stopP && curPrice && curPrice <= stopP ? 'down' : ''}">\${fmtUSD(stopP)}</td>
      <td class="num \${targetP && curPrice && curPrice >= targetP ? 'up' : ''}">\${fmtUSD(targetP)}</td>
      <td><span class="badge \${badgeCls}">\${action}</span></td>
      <td style="white-space:nowrap">
        <button class="secondary sm" onclick="openEdit(\${i})">수정</button>
        <button class="danger sm" onclick="deleteRow(\${i})" style="margin-left:4px">삭제</button>
      </td>
    </tr>\`;
  }).join('');

  const totalPnl = totalVal && totalCost ? totalVal - totalCost : null;
  updateSummary(csvRows.length, totalVal || null, totalPnl, totalCost || null);
}

function updateSummary(count, val, pnl, cost) {
  document.getElementById('statCount').textContent = count;
  document.getElementById('statValue').textContent = val ? '$' + fmt(val) : '—';
  const pnlEl = document.getElementById('statPnl');
  if (pnl != null) {
    const pct = cost ? pnl / cost * 100 : 0;
    pnlEl.textContent = (pnl >= 0 ? '+$' : '-$') + fmt(Math.abs(pnl)) + ' (' + (pnl >= 0 ? '+' : '') + fmt(pct, 1) + '%)';
    pnlEl.className = 'value ' + (pnl >= 0 ? 'up' : 'down');
  } else {
    pnlEl.textContent = '—';
    pnlEl.className = 'value';
  }
  document.getElementById('statCost').textContent = cost ? '$' + fmt(cost) : '—';
}

// ─── 모달 ───
function openAdd() {
  editIdx = -1;
  document.getElementById('modalTitle').textContent = '매수 추가';
  ['fTicker','fShares','fCost','fStop','fTarget'].forEach(id => document.getElementById(id).value = '');
  document.getElementById('overlay').classList.add('show');
  document.getElementById('fTicker').focus();
}
function openEdit(i) {
  editIdx = i;
  const r = csvRows[i];
  document.getElementById('modalTitle').textContent = r.ticker + ' 수정';
  document.getElementById('fTicker').value = r.ticker;
  document.getElementById('fShares').value = r.shares;
  document.getElementById('fCost').value = r.avg_cost;
  document.getElementById('fStop').value = r.stop;
  document.getElementById('fTarget').value = r.target;
  document.getElementById('overlay').classList.add('show');
  document.getElementById('fShares').focus();
}
function closeModal() {
  document.getElementById('overlay').classList.remove('show');
}
function saveModal() {
  const ticker = document.getElementById('fTicker').value.trim().toUpperCase();
  const shares = document.getElementById('fShares').value.trim();
  const cost   = document.getElementById('fCost').value.trim();
  const stop   = document.getElementById('fStop').value.trim();
  const target = document.getElementById('fTarget').value.trim();
  if (!ticker || !shares || !cost) {
    alert('티커, 수량, 매수가는 필수입니다.');
    return;
  }
  const row = { ticker, shares, avg_cost: cost, stop, target };
  if (editIdx < 0) csvRows.push(row);
  else csvRows[editIdx] = row;
  closeModal();
  vscode.postMessage({ type: 'save', rows: csvRows });
}
function deleteRow(i) {
  const r = csvRows[i];
  if (!confirm(r.ticker + ' 을 삭제할까요?')) return;
  csvRows.splice(i, 1);
  vscode.postMessage({ type: 'save', rows: csvRows });
  renderTable();
}

document.getElementById('btnAdd').addEventListener('click', openAdd);
document.getElementById('btnCancel').addEventListener('click', closeModal);
document.getElementById('btnSave').addEventListener('click', saveModal);
document.getElementById('btnRefreshPy').addEventListener('click', () => vscode.postMessage({ type: 'runPy' }));
document.getElementById('overlay').addEventListener('click', e => { if (e.target === e.currentTarget) closeModal(); });
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });
</script>
</body>
</html>`;
    }
}

// ─────────────────────────────────────────────
// WatchlistPanel
// ─────────────────────────────────────────────

export class WatchlistPanel {
    public static current: WatchlistPanel | null = null;
    private static readonly _viewType = 'connectAiLab.watchlist';
    private readonly _panel: vscode.WebviewPanel;
    private readonly _jsonPath: string;
    private _disposables: vscode.Disposable[] = [];

    public static createOrShow(extensionUri: vscode.Uri): void {
        const column = vscode.ViewColumn.Active;
        if (WatchlistPanel.current) {
            WatchlistPanel.current._panel.reveal(column);
            WatchlistPanel.current._refresh();
            return;
        }
        const panel = vscode.window.createWebviewPanel(
            WatchlistPanel._viewType,
            '👁 관심종목',
            column,
            { enableScripts: true, retainContextWhenHidden: true }
        );
        WatchlistPanel.current = new WatchlistPanel(panel, extensionUri);
    }

    private constructor(panel: vscode.WebviewPanel, _extUri: vscode.Uri) {
        this._panel = panel;
        this._jsonPath = path.join(_wsDir(), 'watchlist.json');
        this._panel.webview.html = this._html();
        this._panel.onDidDispose(() => {
            WatchlistPanel.current = null;
            this._disposables.forEach(d => d.dispose());
        }, null, this._disposables);
        this._panel.webview.onDidReceiveMessage(async (msg) => {
            switch (msg?.type) {
                case 'ready':
                    await this._refresh();
                    break;
                case 'add': {
                    const db = _readWatchlist(this._jsonPath);
                    const tk = (msg.ticker || '').toUpperCase().trim();
                    if (tk && !db[tk]) {
                        db[tk] = { added: _today(), note: msg.note || '', earningsDate: null, lastScore: null, addedBy: 'manual' };
                        _writeWatchlist(this._jsonPath, db);
                    }
                    await this._refresh();
                    break;
                }
                case 'remove': {
                    const db = _readWatchlist(this._jsonPath);
                    delete db[msg.ticker];
                    _writeWatchlist(this._jsonPath, db);
                    await this._refresh();
                    break;
                }
                case 'note': {
                    const db = _readWatchlist(this._jsonPath);
                    if (db[msg.ticker]) { db[msg.ticker].note = msg.note; }
                    _writeWatchlist(this._jsonPath, db);
                    await this._refresh();
                    break;
                }
                case 'sync': {
                    this._panel.webview.postMessage({ type: 'loading', on: true });
                    await _runPy('watchlist.py', ['sync']);
                    this._panel.webview.postMessage({ type: 'loading', on: false });
                    await this._refresh();
                    break;
                }
                case 'analyze': {
                    vscode.commands.executeCommand('connect-ai-lab.newChat');
                    setTimeout(() => {
                        vscode.commands.executeCommand('workbench.action.focusActiveEditorGroup');
                    }, 300);
                    vscode.env.clipboard.writeText(`${msg.ticker} 종합 분석해줘`);
                    vscode.window.showInformationMessage(`클립보드에 복사됨: "${msg.ticker} 종합 분석해줘" — 채팅창에 붙여넣으세요.`);
                    break;
                }
            }
        }, null, this._disposables);
    }

    private async _refresh(): Promise<void> {
        const db = _readWatchlist(this._jsonPath);
        const today = new Date().toISOString().slice(0, 10);
        const entries = Object.entries(db).map(([ticker, meta]) => {
            const ed = meta.earningsDate;
            let daysUntil: number | null = null;
            let earningsAlert: string | null = null;
            if (ed) {
                daysUntil = Math.round((new Date(ed).getTime() - new Date(today).getTime()) / 86400000);
                if (daysUntil === 0) earningsAlert = '오늘 실적 발표';
                else if (daysUntil > 0 && daysUntil <= 7) earningsAlert = `실적 ${daysUntil}일 후 임박`;
                else if (daysUntil < 0) earningsAlert = `실적 ${Math.abs(daysUntil)}일 전 완료`;
            }
            return { ticker, ...meta, daysUntil, earningsAlert };
        });
        this._panel.webview.postMessage({ type: 'data', entries });
    }

    private _html(): string {
        return `<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>관심종목</title>
<style>
  :root {
    --bg:       var(--vscode-editor-background, #1e1e1e);
    --bg2:      var(--vscode-sideBar-background, #252526);
    --bg3:      var(--vscode-input-background, #3c3c3c);
    --border:   var(--vscode-panel-border, #444);
    --fg:       var(--vscode-editor-foreground, #ccc);
    --fg2:      var(--vscode-descriptionForeground, #999);
    --accent:   var(--vscode-button-background, #0e639c);
    --accent-fg:var(--vscode-button-foreground, #fff);
    --green:    #4ec994;
    --red:      #f14c4c;
    --yellow:   #d7ba7d;
    --blue:     #79b8ff;
    --radius:   6px;
    font-size: 13px;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--fg); font-family: var(--vscode-font-family, sans-serif); padding: 16px; }
  h2 { font-size: 16px; font-weight: 600; margin-bottom: 4px; }
  .subtitle { color: var(--fg2); font-size: 11px; margin-bottom: 16px; }

  /* toolbar */
  .toolbar { display: flex; align-items: center; gap: 8px; margin-bottom: 14px; }
  .toolbar .spacer { flex: 1; }
  button { background: var(--accent); color: var(--accent-fg); border: none; border-radius: var(--radius); padding: 5px 12px; cursor: pointer; font-size: 12px; }
  button:hover { opacity: 0.85; }
  button.secondary { background: var(--bg3); color: var(--fg); }
  button.danger { background: #5a1d1d; color: var(--red); }
  button.sm { padding: 3px 8px; font-size: 11px; }

  /* add form */
  .add-form { display: flex; gap: 8px; margin-bottom: 16px; align-items: flex-end; flex-wrap: wrap; }
  .add-form .field { display: flex; flex-direction: column; gap: 3px; }
  .add-form label { font-size: 11px; color: var(--fg2); }
  .add-form input { background: var(--bg3); color: var(--fg); border: 1px solid var(--border); border-radius: 4px; padding: 6px 10px; font-size: 12px; min-width: 80px; }
  .add-form input:focus { outline: 1px solid var(--accent); border-color: var(--accent); }
  #fAddNote { min-width: 200px; }

  /* two-column layout */
  .columns { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
  @media (max-width: 700px) { .columns { grid-template-columns: 1fr; } }

  .section-box { background: var(--bg2); border: 1px solid var(--border); border-radius: var(--radius); overflow: hidden; }
  .section-header { padding: 10px 14px; border-bottom: 1px solid var(--border); display: flex; align-items: center; gap: 8px; }
  .section-header h3 { font-size: 12px; font-weight: 700; flex: 1; }
  .section-label { font-size: 10px; padding: 2px 7px; border-radius: 10px; font-weight: 700; }
  .section-label.auto   { background: #1f2e3a; color: var(--blue); }
  .section-label.manual { background: #2a1f3a; color: #c586c0; }
  .count-badge { font-size: 11px; color: var(--fg2); }

  /* ticker cards */
  .ticker-list { padding: 8px; display: flex; flex-direction: column; gap: 6px; min-height: 60px; }
  .ticker-card { background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius); padding: 10px 12px; }
  .ticker-card:hover { border-color: var(--accent); }
  .card-top { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
  .card-ticker { font-weight: 700; font-size: 14px; letter-spacing: 0.5px; flex: 1; }
  .card-score { font-size: 11px; color: var(--yellow); font-weight: 600; }
  .card-meta { font-size: 11px; color: var(--fg2); margin-bottom: 6px; display: flex; gap: 10px; flex-wrap: wrap; }
  .card-alert { color: var(--red); font-weight: 600; }
  .card-alert.soon { color: var(--yellow); }
  .card-note-row { display: flex; align-items: center; gap: 6px; }
  .note-input { background: transparent; color: var(--fg); border: none; border-bottom: 1px solid transparent; font-size: 11px; flex: 1; padding: 2px 0; }
  .note-input:focus { outline: none; border-bottom-color: var(--accent); }
  .note-input::placeholder { color: var(--fg2); }
  .card-actions { display: flex; gap: 6px; justify-content: flex-end; margin-top: 6px; }

  .empty-msg { text-align: center; color: var(--fg2); padding: 20px 0; font-size: 12px; }
  .loading-bar { display: none; color: var(--fg2); font-size: 12px; padding: 6px 0; }
  .loading-bar.on { display: block; }
</style>
</head>
<body>
<h2>👁 관심종목</h2>
<p class="subtitle">자동 등록(screen.py 발굴) + 직접 등록으로 관리</p>

<div class="toolbar">
  <button class="secondary sm" id="btnSync" title="yfinance로 실적일 갱신">⟳ 실적일 갱신</button>
  <div class="spacer"></div>
</div>
<div class="loading-bar" id="loadingBar">실적일 갱신 중… (yfinance)</div>

<!-- 빠른 추가 폼 -->
<div class="add-form">
  <div class="field">
    <label>티커</label>
    <input id="fAddTicker" placeholder="IONQ" maxlength="5" style="width:90px;text-transform:uppercase">
  </div>
  <div class="field">
    <label>메모 (선택)</label>
    <input id="fAddNote" placeholder="양자컴퓨터 1위 후보…">
  </div>
  <button id="btnAddTicker">+ 직접 추가</button>
</div>

<div class="columns">
  <!-- 자동 등록 -->
  <div class="section-box">
    <div class="section-header">
      <span class="section-label auto">자동</span>
      <h3>자동 등록</h3>
      <span class="count-badge" id="autoCount">0개</span>
    </div>
    <div class="ticker-list" id="autoList">
      <p class="empty-msg">screen.py 발굴 종목이 없습니다.</p>
    </div>
  </div>

  <!-- 직접 등록 -->
  <div class="section-box">
    <div class="section-header">
      <span class="section-label manual">수동</span>
      <h3>직접 등록</h3>
      <span class="count-badge" id="manualCount">0개</span>
    </div>
    <div class="ticker-list" id="manualList">
      <p class="empty-msg">직접 추가한 종목이 없습니다.</p>
    </div>
  </div>
</div>

<script>
const vscode = acquireVsCodeApi();
let allEntries = [];

window.addEventListener('message', e => {
  const msg = e.data;
  if (msg.type === 'data') { allEntries = msg.entries || []; render(); }
  else if (msg.type === 'loading') { document.getElementById('loadingBar').classList.toggle('on', !!msg.on); }
});
vscode.postMessage({ type: 'ready' });

function render() {
  const auto   = allEntries.filter(e => e.addedBy === 'auto');
  const manual = allEntries.filter(e => e.addedBy !== 'auto');

  document.getElementById('autoCount').textContent   = auto.length + '개';
  document.getElementById('manualCount').textContent = manual.length + '개';

  renderList('autoList',   auto);
  renderList('manualList', manual);
}

function renderList(containerId, entries) {
  const el = document.getElementById(containerId);
  if (!entries.length) {
    el.innerHTML = '<p class="empty-msg">종목이 없습니다.</p>';
    return;
  }
  el.innerHTML = entries.map(e => cardHtml(e)).join('');
  // note input 이벤트 바인딩
  entries.forEach(e => {
    const inp = document.getElementById('note_' + e.ticker);
    if (inp) {
      inp.addEventListener('change', ev => {
        vscode.postMessage({ type: 'note', ticker: e.ticker, note: ev.target.value });
      });
    }
  });
}

function alertClass(daysUntil) {
  if (daysUntil == null) return '';
  if (daysUntil < 0)  return '';
  if (daysUntil === 0) return 'card-alert';
  if (daysUntil <= 3)  return 'card-alert';
  if (daysUntil <= 7)  return 'card-alert soon';
  return '';
}

function cardHtml(e) {
  const scoreStr = e.lastScore != null ? 'Score ' + e.lastScore : '';
  const edStr    = e.earningsDate ? e.earningsDate : '실적일 미확인';
  const alertStr = e.earningsAlert || '';
  const alertCls = alertClass(e.daysUntil);
  const addedStr = e.added ? '추가: ' + e.added : '';
  return \`<div class="ticker-card">
    <div class="card-top">
      <span class="card-ticker">\${e.ticker}</span>
      \${scoreStr ? '<span class="card-score">' + scoreStr + '</span>' : ''}
    </div>
    <div class="card-meta">
      <span>\${edStr}</span>
      \${alertStr ? '<span class="' + alertCls + '">' + alertStr + '</span>' : ''}
      \${addedStr ? '<span>' + addedStr + '</span>' : ''}
    </div>
    <div class="card-note-row">
      <input class="note-input" id="note_\${e.ticker}" value="\${(e.note||'').replace(/"/g,'&quot;')}" placeholder="메모 입력 후 Enter…">
    </div>
    <div class="card-actions">
      <button class="secondary sm" onclick="analyze('\${e.ticker}')">분석</button>
      <button class="danger sm" onclick="removeTicker('\${e.ticker}')">삭제</button>
    </div>
  </div>\`;
}

function removeTicker(ticker) {
  if (!confirm(ticker + ' 을 삭제할까요?')) return;
  vscode.postMessage({ type: 'remove', ticker });
}
function analyze(ticker) {
  vscode.postMessage({ type: 'analyze', ticker });
}

document.getElementById('btnAddTicker').addEventListener('click', () => {
  const ticker = document.getElementById('fAddTicker').value.trim().toUpperCase();
  const note   = document.getElementById('fAddNote').value.trim();
  if (!ticker) { alert('티커를 입력하세요.'); return; }
  if (!/^[A-Z]{1,5}$/.test(ticker)) { alert('올바른 티커 형식이 아닙니다 (예: IONQ)'); return; }
  vscode.postMessage({ type: 'add', ticker, note });
  document.getElementById('fAddTicker').value = '';
  document.getElementById('fAddNote').value = '';
});
document.getElementById('fAddTicker').addEventListener('keydown', e => {
  if (e.key === 'Enter') document.getElementById('fAddNote').focus();
});
document.getElementById('fAddNote').addEventListener('keydown', e => {
  if (e.key === 'Enter') document.getElementById('btnAddTicker').click();
});
document.getElementById('btnSync').addEventListener('click', () => {
  vscode.postMessage({ type: 'sync' });
});
</script>
</body>
</html>`;
    }
}
