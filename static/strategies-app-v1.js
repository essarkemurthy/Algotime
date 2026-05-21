/* Strategies v1 — tile-row layout with slide-out config pane.
   Reuses strategies-data.js for the strategy list. */
(function () {
  'use strict';

  // ── DOM refs ────────────────────────────────────────────────────
  const rowIntra  = document.getElementById('tiles-intra');
  const rowOpt    = document.getElementById('tiles-opt');
  const rowCust   = document.getElementById('tiles-cust');
  const cntIntra  = document.getElementById('cnt-intra');
  const cntOpt    = document.getElementById('cnt-opt');
  const cntCust   = document.getElementById('cnt-cust');
  const clockEl   = document.getElementById('clock');
  const pane      = document.getElementById('pane');
  const backdrop  = document.getElementById('pane-backdrop');

  // ── State ───────────────────────────────────────────────────────
  const strategies = (window.STRATEGIES || []).slice();
  let activeId = null;
  const edits = Object.create(null);

  // ── Helpers ─────────────────────────────────────────────────────
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => (
      { '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c]
    ));
  }
  function findStrategy(id) { return strategies.find(s => s.id === id); }
  function valueFor(strat, field) {
    const m = edits[strat.id];
    if (m && Object.prototype.hasOwnProperty.call(m, field.key)) return m[field.key];
    return field.value;
  }
  function setValue(stratId, key, value) {
    if (!edits[stratId]) edits[stratId] = {};
    edits[stratId][key] = value;
  }

  // ── Deterministic back-test results ─────────────────────────────
  function strategyHash(id) {
    let h = 0;
    for (let i = 0; i < id.length; i++) h = ((h << 5) - h + id.charCodeAt(i)) | 0;
    return Math.abs(h) + 1;
  }
  function seededRand(seed) {
    let x = seed;
    return () => { x = (x * 9301 + 49297) % 233280; return x / 233280; };
  }
  function backtestResults(s) {
    const rnd = seededRand(strategyHash(s.id + (s.btSeed || '')));
    const tone = (s.stats && s.stats.m2m && s.stats.m2m.tone) || 'flat';
    const bias = tone === 'pos' ? 1 : (tone === 'neg' ? -0.45 : 0.4);
    const totalReturn = (8 + rnd() * 28) * bias;
    const cagrNum   = totalReturn * 1.6;
    const winRate   = 48 + rnd() * 22;
    const maxDD     = -(2 + rnd() * 9);
    const sharpe    = 0.6 + rnd() * 1.4;
    const trades    = 60 + Math.round(rnd() * 280);
    const avgR      = 0.5 + rnd() * 1.4;
    const pts = [];
    let y = 48;
    const target = 48 - totalReturn * 1.2;
    for (let x = 0; x <= 240; x += 8) {
      const noise = (rnd() - 0.5) * 7;
      const drift = (target - y) * 0.045;
      y = Math.max(6, Math.min(54, y + drift + noise));
      pts.push(x + ',' + y.toFixed(1));
    }
    return {
      ret:     (totalReturn >= 0 ? '+ ' : '− ') + Math.abs(totalReturn).toFixed(2) + '%',
      retTone: totalReturn >= 0 ? 'pos' : 'neg',
      cagr:    (cagrNum >= 0 ? '+ ' : '− ') + Math.abs(cagrNum).toFixed(1) + '%',
      cagrTone:cagrNum >= 0 ? 'pos' : 'neg',
      winRate: winRate.toFixed(1) + '%',
      maxDD:   '− ' + Math.abs(maxDD).toFixed(1) + '%',
      sharpe:  sharpe.toFixed(2),
      trades:  String(trades),
      avgR:    avgR.toFixed(2) + 'R',
      curve:   pts.join(' '),
      tone:    totalReturn >= 0 ? 'pos' : 'neg',
    };
  }

  // ── Clock ───────────────────────────────────────────────────────
  function pad(n) { return String(n).padStart(2, '0'); }
  function tickClock() {
    if (!clockEl) return;
    const d = new Date();
    clockEl.textContent = pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
  }
  tickClock();
  setInterval(tickClock, 1000);

  // ── Render: tile rows ───────────────────────────────────────────
  function tileHtml(s, idx) {
    const stateCls = (s.running ? ' running' : (s.armed ? ' armed' : '')) + (s.deployed ? ' deployed' : '');
    const m2m = s.stats && s.stats.m2m ? s.stats.m2m : { value: '—', tone: 'flat' };
    const ix = String(idx).padStart(2, '0');
    return (
      '<button class="strat-tile' + stateCls + '" data-id="' + esc(s.id) + '" type="button">' +
        '<div class="tile-head">' +
          '<span class="num">' + ix + '</span>' +
          '<span class="status-dot" aria-hidden="true"></span>' +
        '</div>' +
        '<div class="nm">' + esc(s.name) + '</div>' +
        '<div class="foot">' +
          '<span class="lbl">M2M</span>' +
          '<span class="val ' + esc(m2m.tone) + '">' + esc(m2m.value) + '</span>' +
        '</div>' +
      '</button>'
    );
  }

  function renderTiles() {
    const intra = strategies.filter(s => s.kind === 'intra');
    const opt   = strategies.filter(s => s.kind === 'opt');
    const cust  = strategies.filter(s => s.kind === 'custom');

    cntIntra.textContent = String(intra.length);
    cntOpt.textContent   = String(opt.length);
    cntCust.textContent  = String(cust.length);

    const kCust = document.getElementById('kpi-custom');
    const kDep  = document.getElementById('kpi-deployed');
    if (kCust) kCust.textContent = String(cust.length);
    if (kDep)  kDep.textContent  = String(strategies.filter(s => s.deployed).length);

    rowIntra.innerHTML = intra.map((s, i) => tileHtml(s, i + 1)).join('');
    rowOpt.innerHTML   = opt.map((s, i) => tileHtml(s, i + 1)).join('');

    const addTile =
      '<button class="strat-tile add" data-id="__new__" type="button">' +
        '<div class="plus-icon">' +
          '<svg viewBox="0 0 24 24"><path d="M5 12h14M12 5v14"/></svg>' +
        '</div>' +
        '<div class="nm">Add new strategy</div>' +
      '</button>';
    rowCust.innerHTML = cust.map((s, i) => tileHtml(s, i + 1)).join('') + addTile;
  }

  // ── Field renderer ──────────────────────────────────────────────
  function renderField(strat, field) {
    const val = valueFor(strat, field);
    const id = 'f-' + strat.id + '-' + field.key;
    const hint = field.hint ? '<div class="hint">' + field.hint + '</div>' : '';
    let control;
    if (field.type === 'select') {
      control = '<select id="' + id + '" data-key="' + esc(field.key) + '">' +
        field.options.map(o => '<option' + (o === val ? ' selected' : '') + '>' + esc(o) + '</option>').join('') +
        '</select>';
    } else if (field.type === 'number') {
      control = '<input id="' + id + '" class="mono" type="number" data-key="' + esc(field.key) +
        '" value="' + esc(val) + '" step="' + esc(field.step || '1') + '" />';
    } else if (field.type === 'multi') {
      const arr = Array.isArray(val) ? val : [];
      control = '<div class="sym-multi" data-key="' + esc(field.key) + '">' +
        arr.map((s, i) =>
          '<span class="chip-sel" data-idx="' + i + '">' + esc(s) + ' <span class="x" data-idx="' + i + '">×</span></span>'
        ).join('') +
        '<input type="text" placeholder="+ add" data-multi-input="1"/>' +
      '</div>';
    } else if (field.type === 'textarea') {
      control = '<textarea id="' + id + '" data-key="' + esc(field.key) + '" rows="3">' + esc(val) + '</textarea>';
    } else {
      const mc = field.mono ? ' mono' : '';
      control = '<input id="' + id + '" class="' + mc.trim() + '" type="text" data-key="' + esc(field.key) + '" value="' + esc(val) + '" />';
    }
    return (
      '<div class="cfg-field' + (field.span2 ? ' span2' : '') + '">' +
        '<label for="' + id + '">' + esc(field.label) + '</label>' +
        control + hint +
      '</div>'
    );
  }

  // ── Pane: open / close ──────────────────────────────────────────
  function openPane(id) {
    activeId = id;
    if (id === '__new__') {
      const n = strategies.filter(s => s.kind === 'custom').length + 1;
      const newId = 'custom-' + Date.now();
      strategies.push({
        id: newId, kind: 'custom',
        name: 'Custom strategy ' + n,
        sub: 'Your own strategy',
        desc: 'Describe what this strategy does and when it should fire.',
        running: false, armed: false, mode: 'paper',
        stats: { signals: 0, acted: 0, hit: '—', m2m: { value: '— flat', tone: 'flat' } },
        lastSignal: { time: '—', text: 'No signals yet — strategy is brand-new.' },
        symbols: ['NIFTY'],
        tf: '5 minute',
        side: 'Long only',
        sizing: '0.5% of capital',
        rules: [
          { indicator: 'RSI(14)', op: '<', val: '30' },
          { indicator: 'Close', op: 'crosses above', val: 'VWAP' },
        ],
        stop: 'ATR(14) · 1.0',
        target: '1.5R',
        timeExit: '15:10 IST',
        reentry: 'Once per day',
      });
      activeId = newId;
    }
    renderTiles();
    renderPane();
    pane.classList.add('show');
    backdrop.classList.add('show');
    document.body.style.overflow = 'hidden';
  }
  function closePane() {
    pane.classList.remove('show');
    backdrop.classList.remove('show');
    document.body.style.overflow = '';
    activeId = null;
  }

  // ── Pane content ────────────────────────────────────────────────
  function renderPane() {
    const s = findStrategy(activeId);
    if (!s) return;

    const kindLabel = s.kind === 'opt' ? 'Option strategy'
                    : s.kind === 'custom' ? 'Custom strategy'
                    : 'Intraday strategy';
    const kindCls = s.kind === 'opt' ? 'opt' : (s.kind === 'custom' ? 'custom' : '');
    const numCls  = s.running ? ' running' : (s.kind === 'custom' ? ' add' : '');
    const statusCls  = s.running ? 'running' : (s.armed ? 'armed' : '');
    const statusText = s.running ? 'Running'  : (s.armed ? 'Armed'   : 'Paused');
    const m2m = (s.stats && s.stats.m2m) || { value: '— flat', tone: 'flat' };

    const headHtml =
      '<div class="pane-head">' +
        '<div class="num-box' + numCls + '">' + esc((s.kind === 'custom' ? 'C' : '')) + '</div>'.replace('></div>','>') +
        '<div class="body">' +
          '<span class="kind-tag ' + kindCls + '">' + esc(kindLabel) + '</span>' +
          '<h2 id="pane-title" contenteditable="true" data-name="1">' + esc(s.name) + '</h2>' +
          '<p class="desc"><span contenteditable="true" data-desc="1">' + esc(s.desc || 'Describe what this strategy does.') + '</span></p>' +
        '</div>' +
        '<span class="status-pill ' + statusCls + '">' + esc(statusText) + '</span>' +
        '<button class="pane-close" type="button" aria-label="Close" data-action="close">' +
          '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg>' +
        '</button>' +
      '</div>';

    const statsHtml =
      '<div class="pane-stats">' +
        '<div class="cell"><div class="l">Signals today</div><div class="v">' + esc((s.stats||{}).signals || 0) + '</div></div>' +
        '<div class="cell"><div class="l">Acted</div><div class="v">' + esc((s.stats||{}).acted || 0) + '</div></div>' +
        '<div class="cell"><div class="l">Hit rate</div><div class="v">' + esc((s.stats||{}).hit || '—') + '</div></div>' +
        '<div class="cell"><div class="l">M2M</div><div class="v ' + esc(m2m.tone) + '">' + esc(m2m.value) + '</div></div>' +
      '</div>';

    let bodyHtml;
    if (s.kind === 'custom') {
      const rules = s.rules || [];
      const ruleRows = rules.map((r, i) => (
        '<div class="rule-row" data-ridx="' + i + '">' +
          '<div class="cfg-field"><label>Indicator / signal</label>' +
            '<input class="mono" type="text" data-rule-key="indicator" value="' + esc(r.indicator || '') + '" placeholder="e.g. RSI(14)" /></div>' +
          '<div class="cfg-field"><label>Operator</label>' +
            '<select data-rule-key="op">' +
              ['>','<','>=','<=','crosses above','crosses below','=='].map(o =>
                '<option' + (o === r.op ? ' selected' : '') + '>' + esc(o) + '</option>'
              ).join('') +
            '</select></div>' +
          '<div class="cfg-field"><label>Value</label>' +
            '<input class="mono" type="text" data-rule-key="val" value="' + esc(r.val || '') + '" placeholder="e.g. 30 / VWAP / 20-bar high" /></div>' +
          '<button class="rule-del" data-rule-del="' + i + '" type="button" aria-label="Delete rule">' +
            '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg></button>' +
        '</div>'
      )).join('');

      bodyHtml =
        statsHtml +
        '<div class="cfg-section">' +
          '<div class="section-title">Basics</div>' +
          '<div class="cfg-form">' +
            renderField(s, { key: 'symbols', label: 'Symbols', type: 'multi', value: s.symbols || [] }) +
            renderField(s, { key: 'tf', label: 'Timeframe', type: 'select', options: ['1 minute','5 minute','15 minute','60 minute','Daily'], value: s.tf || '5 minute' }) +
            renderField(s, { key: 'side', label: 'Side', type: 'select', options: ['Long only','Short only','Both'], value: s.side || 'Long only' }) +
            renderField(s, { key: 'sizing', label: 'Position sizing', type: 'text', value: s.sizing || '0.5% of capital', mono: true }) +
          '</div>' +
        '</div>' +
        '<div class="cfg-section">' +
          '<div class="section-title">' +
            '<span>Entry rules — all must be true</span>' +
            '<button class="add-mini" data-add-rule="entry" type="button">+ Add rule</button>' +
          '</div>' +
          '<div data-rule-section="entry">' + ruleRows + '</div>' +
        '</div>' +
        '<div class="cfg-section">' +
          '<div class="section-title">Exit rules</div>' +
          '<div class="cfg-form">' +
            renderField(s, { key: 'stop', label: 'Stop loss', type: 'text', value: s.stop || 'ATR(14) · 1.0', mono: true }) +
            renderField(s, { key: 'target', label: 'Target', type: 'text', value: s.target || '1.5R', mono: true }) +
            renderField(s, { key: 'timeExit', label: 'Time-based exit', type: 'text', value: s.timeExit || '15:10 IST', mono: true }) +
            renderField(s, { key: 'reentry', label: 'Re-entry', type: 'select', options: ['Allowed','Once per day','Not allowed'], value: s.reentry || 'Once per day' }) +
          '</div>' +
        '</div>';
    } else {
      const fieldsHtml = (s.config || []).map(f => renderField(s, f)).join('');
      bodyHtml =
        statsHtml +
        '<div class="cfg-section">' +
          '<div class="section-title">Configuration</div>' +
          '<div class="cfg-form">' + fieldsHtml + '</div>' +
        '</div>';
    }

    // Back-test section
    const bt = backtestResults(s);
    const btHtml =
      '<div class="cfg-section">' +
        '<div class="section-title">' +
          '<span>Back-test</span>' +
          '<button class="add-mini" data-action="run-bt" type="button">↻ Re-run</button>' +
        '</div>' +
        '<div class="cfg-form">' +
          renderField(s, { key: 'btPeriod',     label: 'Period',          type: 'select', options: ['Last 1 month','Last 3 months','Last 6 months','Last 1 year','Last 3 years'], value: s.btPeriod || 'Last 6 months' }) +
          renderField(s, { key: 'btCapital',    label: 'Initial capital', type: 'text', value: s.btCapital    || '₹10,00,000', mono: true }) +
          renderField(s, { key: 'btSlippage',   label: 'Slippage',        type: 'text', value: s.btSlippage   || '0.05%',       mono: true }) +
          renderField(s, { key: 'btCommission', label: 'Commission',      type: 'text', value: s.btCommission || '₹20 / order', mono: true }) +
        '</div>' +
        '<div class="bt-results">' +
          '<div class="bt-curve">' +
            '<span class="bt-label">Equity curve</span>' +
            '<svg viewBox="0 0 240 60" preserveAspectRatio="none">' +
              '<line x1="0" y1="48" x2="240" y2="48" stroke="var(--border-1)" stroke-width="1" stroke-dasharray="2 2"/>' +
              '<polyline points="' + bt.curve + '" fill="none" stroke="var(--tu-' + (bt.tone === 'pos' ? 'success' : 'danger') + ')" stroke-width="1.6" stroke-linejoin="round"/>' +
            '</svg>' +
          '</div>' +
          '<div class="bt-metrics">' +
            '<div class="mcell"><div class="l">Total return</div><div class="v ' + bt.retTone + '">' + esc(bt.ret) + '</div></div>' +
            '<div class="mcell"><div class="l">CAGR</div><div class="v ' + bt.cagrTone + '">' + esc(bt.cagr) + '</div></div>' +
            '<div class="mcell"><div class="l">Win rate</div><div class="v">' + esc(bt.winRate) + '</div></div>' +
            '<div class="mcell"><div class="l">Max drawdown</div><div class="v neg">' + esc(bt.maxDD) + '</div></div>' +
            '<div class="mcell"><div class="l">Sharpe</div><div class="v">' + esc(bt.sharpe) + '</div></div>' +
            '<div class="mcell"><div class="l">Trades</div><div class="v">' + esc(bt.trades) + '</div></div>' +
            '<div class="mcell"><div class="l">Avg R / trade</div><div class="v">' + esc(bt.avgR) + '</div></div>' +
            '<div class="mcell"><div class="l">Ran</div><div class="v" style="font-size:11px;color:var(--fg-3);">just now</div></div>' +
          '</div>' +
        '</div>' +
      '</div>';

    const last = s.lastSignal || { time: '—', text: 'No signals yet.' };
    const deployBtn = s.deployed
      ? '<button class="btn btn-ghost btn-sm" data-action="undeploy" title="Remove from paper-trading desk">' +
          '<svg class="ic" viewBox="0 0 24 24"><path d="M5 12l4 4L19 6"/></svg> Deployed</button>'
      : '<button class="btn btn-primary btn-sm" data-action="deploy">' +
          '<svg class="ic" viewBox="0 0 24 24"><path d="M5 12h14M13 5l7 7-7 7"/></svg> Deploy to Paper Trading</button>';
    const footHtml =
      '<div class="pane-foot">' +
        '<div class="left-side">' +
          '<span class="when">' + esc(last.time) + '</span>' +
          '<span>Last · ' + esc(last.text) + '</span>' +
        '</div>' +
        '<div class="actions">' +
          '<div class="mode-seg">' +
            '<button class="' + (s.mode === 'paper' ? 'on paper' : '') + '" data-mode="paper">Paper</button>' +
            '<button class="' + (s.mode === 'live'  ? 'on live'  : '') + '" data-mode="live">Live</button>' +
          '</div>' +
          '<button class="btn btn-ghost btn-sm" data-action="save">' +
            '<svg class="ic" viewBox="0 0 24 24"><path d="M5 12l4 4L19 6"/></svg> Save' +
          '</button>' +
          deployBtn +
        '</div>' +
      '</div>';

    pane.innerHTML = headHtml + '<div class="pane-body">' + bodyHtml + btHtml + '</div>' + footHtml;
    bindPaneEvents(s);
  }

  // ── Pane events ─────────────────────────────────────────────────
  function bindPaneEvents(s) {
    pane.querySelectorAll('input[data-key], select[data-key], textarea[data-key]').forEach(el => {
      el.addEventListener('input', () => setValue(s.id, el.dataset.key, el.value));
      el.addEventListener('change', () => setValue(s.id, el.dataset.key, el.value));
    });

    // Symbol-multi
    pane.querySelectorAll('.sym-multi').forEach(multi => {
      const key = multi.dataset.key;
      multi.addEventListener('click', ev => {
        const x = ev.target.closest('.x');
        if (!x) return;
        const idx = parseInt(x.dataset.idx, 10);
        const current = valueFor(s, { key, value: [] }) || [];
        const arr = Array.isArray(current) ? current.slice() : [];
        arr.splice(idx, 1);
        setValue(s.id, key, arr);
        renderPane();
      });
      multi.addEventListener('keydown', ev => {
        const input = ev.target.closest('input[data-multi-input]');
        if (!input) return;
        if (ev.key === 'Enter' && input.value.trim()) {
          ev.preventDefault();
          const current = valueFor(s, { key, value: [] }) || [];
          const arr = Array.isArray(current) ? current.slice() : [];
          arr.push(input.value.trim().toUpperCase());
          setValue(s.id, key, arr);
          renderPane();
        }
      });
    });

    // Mode toggle
    pane.querySelectorAll('[data-mode]').forEach(b => {
      b.addEventListener('click', () => { s.mode = b.dataset.mode; renderPane(); });
    });

    // Actions
    pane.querySelectorAll('[data-action]').forEach(b => {
      b.addEventListener('click', () => {
        const a = b.dataset.action;
        if (a === 'close') return closePane();
        if (a === 'start') { s.running = true; s.armed = true; }
        if (a === 'stop')  { s.running = false; s.armed = false; }
        if (a === 'deploy') {
          s.deployed = true; s.running = true; s.armed = true;
          flashButton(b, 'Deployed');
          renderTiles();
          // Persist to backend
          fetch('/api/strategies/' + encodeURIComponent(s.id) + '/deploy', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mode: s.mode || 'paper' }),
          }).catch(() => {});
          setTimeout(() => { if (activeId === s.id) renderPane(); }, 1100);
          return;
        }
        if (a === 'undeploy') {
          s.deployed = false; s.running = false;
          flashButton(b, 'Removed');
          renderTiles();
          fetch('/api/strategies/' + encodeURIComponent(s.id) + '/undeploy', {
            method: 'POST',
          }).catch(() => {});
          setTimeout(() => { if (activeId === s.id) renderPane(); }, 1100);
          return;
        }
        if (a === 'run-bt') {
          s.btSeed = String(Date.now());
          flashButton(b, 'Running…', 600);
          const period   = (edits[s.id] && edits[s.id].btPeriod)   || s.btPeriod   || 'Last 6 months';
          const capital  = (edits[s.id] && edits[s.id].btCapital)  || s.btCapital  || '₹10,00,000';
          // Try backend backtest, fall back to local deterministic mock
          fetch('/api/strategies/' + encodeURIComponent(s.id) + '/backtest', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ period, capital }),
          }).catch(() => null).finally(() => {
            if (activeId === s.id) renderPane();
          });
          return;
        }
        if (a === 'save') {
          // Collect pending edits and persist
          const payload = Object.assign({}, edits[s.id] || {});
          fetch('/api/strategies/' + encodeURIComponent(s.id), {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
          }).catch(() => {});
          flashButton(b, 'Saved');
          return;
        }
        renderTiles();
        renderPane();
      });
    });

    // Name / description inline edits
    const nameEl = pane.querySelector('[data-name]');
    if (nameEl) nameEl.addEventListener('blur', () => {
      const v = nameEl.textContent.trim();
      if (v && v !== s.name) { s.name = v; renderTiles(); }
    });
    const descEl = pane.querySelector('[data-desc]');
    if (descEl) descEl.addEventListener('blur', () => {
      const v = descEl.textContent.trim();
      if (v) s.desc = v;
    });

    // Custom strategy rule controls
    if (s.kind === 'custom') {
      if (!s.rules) s.rules = [];
      pane.querySelectorAll('[data-add-rule]').forEach(b => {
        b.addEventListener('click', () => {
          s.rules.push({ indicator: '', op: '>', val: '' });
          renderPane();
        });
      });
      pane.querySelectorAll('[data-rule-del]').forEach(b => {
        b.addEventListener('click', () => {
          const i = parseInt(b.dataset.ruleDel, 10);
          s.rules.splice(i, 1);
          renderPane();
        });
      });
      pane.querySelectorAll('[data-ridx]').forEach(row => {
        const i = parseInt(row.dataset.ridx, 10);
        row.querySelectorAll('[data-rule-key]').forEach(input => {
          const k = input.dataset.ruleKey;
          const onChange = () => { if (s.rules[i]) s.rules[i][k] = input.value; };
          input.addEventListener('input', onChange);
          input.addEventListener('change', onChange);
        });
      });
    }
  }

  // ── Wiring: tile clicks, backdrop, Esc ──────────────────────────
  document.body.addEventListener('click', ev => {
    const tile = ev.target.closest('.strat-tile');
    if (tile) {
      ev.preventDefault();
      openPane(tile.dataset.id);
    }
  });
  backdrop.addEventListener('click', closePane);
  document.addEventListener('keydown', ev => {
    if (ev.key === 'Escape' && pane.classList.contains('show')) closePane();
  });

  // ── Start-all ───────────────────────────────────────────────────
  const startAll = document.getElementById('start-all');
  if (startAll) {
    startAll.addEventListener('click', () => {
      strategies.forEach(s => { s.deployed = true; s.running = true; s.armed = true; });
      renderTiles();
      if (activeId) renderPane();
    });
  }

  function flashButton(b, text, dur) {
    if (!b) return;
    const orig = b.innerHTML;
    b.innerHTML = '<svg class="ic" viewBox="0 0 24 24"><path d="M5 12l4 4L19 6"/></svg> ' + text;
    setTimeout(() => { b.innerHTML = orig; }, dur || 1100);
  }

  // ── First paint ─────────────────────────────────────────────────
  renderTiles();

  // ── Merge deployment status from backend ─────────────────────────
  fetch('/api/strategies')
    .then(r => r.ok ? r.json() : null)
    .then(data => {
      if (!Array.isArray(data)) return;
      data.forEach(remote => {
        const local = findStrategy(remote.id);
        if (!local) return;
        // Backend sends boolean running/armed; fall back to status string
        if (remote.running !== undefined)  local.running  = !!remote.running;
        else if (remote.status !== undefined) local.running = remote.status === 'running';
        if (remote.armed !== undefined)    local.armed    = !!remote.armed;
        else if (remote.status !== undefined) local.armed  = remote.status === 'running';
        if (remote.deployed !== undefined) local.deployed = !!remote.deployed;
        if (remote.mode    !== undefined)  local.mode     = remote.mode;
      });
      renderTiles();
    })
    .catch(() => {});
})();
