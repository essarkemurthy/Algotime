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

  // ── Math strategy constants ─────────────────────────────────────
  const BASE_OPTS = ['Close','Open','High','Low','Volume','Log(Close)','HL2','HLC3'];
  const TRANSFORM_OPTS = [
    { v:'none',         l:'None (pass-through)' },
    { v:'diff1',        l:'1st difference  Δ¹' },
    { v:'diff2',        l:'2nd difference  Δ²' },
    { v:'log_return',   l:'Log return  ln(x/x₋₁)' },
    { v:'pct_change',   l:'% change' },
    { v:'rolling_mean', l:'Rolling mean  μₙ', param: true, paramLabel:'Window', paramDefault:'20' },
    { v:'rolling_std',  l:'Rolling std  σₙ',  param: true, paramLabel:'Window', paramDefault:'20' },
    { v:'z_score',      l:'Z-score  Zₙ',           param: true, paramLabel:'Window', paramDefault:'20' },
    { v:'normalize',    l:'Min-max normalize',           param: true, paramLabel:'Window', paramDefault:'50' },
    { v:'cumsum',       l:'Cumulative sum  Σ' },
    { v:'abs',          l:'Absolute value  |·|' },
    { v:'sign',         l:'Sign  sgn(·)' },
  ];
  const MCOND_OPS = [
    '>','<','>=','<=','==',
    'crosses_above','crosses_below',
    'sign_flip_pos','sign_flip_neg',
    'n_consecutive_pos','n_consecutive_neg',
    'is_peak','is_trough',
  ];

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

  // ── Deterministic back-test results (per strategy id) ──────────
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
    const cust  = strategies.filter(s => s.kind === 'custom' || s.kind === 'math');

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
        '<div class="plus-icon"><svg viewBox="0 0 24 24"><path d="M5 12h14M12 5v14"/></svg></div>' +
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

  // ── Math strategy helpers ───────────────────────────────────────
  function buildFormulaPreview(base, tf, transforms) {
    const SUP = ['⁰','¹','²','³','⁴','⁵','⁶','⁷','⁸','⁹'];
    const SUB = ['₀','₁','₂','₃','₄','₅','₆','₇','⁸','₉'];
    function sup(n) { return String(n).split('').map(c => SUP[+c] || c).join(''); }
    function sub(n) { return String(n).split('').map(c => SUB[+c] || c).join(''); }
    const tfMap = {'1 minute':'1m','5 minute':'5m','15 minute':'15m','60 minute':'1h','Daily':'1D'};
    let inner = base + '[' + (tfMap[tf] || tf) + ']';
    for (const t of (transforms || [])) {
      const w = t.param || '20';
      switch (t.type) {
        case 'diff1':        inner = 'Δ' + sup(1) + '(' + inner + ')'; break;
        case 'diff2':        inner = 'Δ' + sup(2) + '(' + inner + ')'; break;
        case 'log_return':   inner = 'ln(' + inner + '/lag₁)'; break;
        case 'pct_change':   inner = 'pct(' + inner + ')'; break;
        case 'rolling_mean': inner = 'μ' + sub(w) + '(' + inner + ')'; break;
        case 'rolling_std':  inner = 'σ' + sub(w) + '(' + inner + ')'; break;
        case 'z_score':      inner = 'Z' + sub(w) + '(' + inner + ')'; break;
        case 'normalize':    inner = 'norm' + sub(w) + '(' + inner + ')'; break;
        case 'cumsum':       inner = 'Σ(' + inner + ')'; break;
        case 'abs':          inner = '|' + inner + '|'; break;
        case 'sign':         inner = 'sgn(' + inner + ')'; break;
      }
    }
    return inner;
  }

  function mathTransformRowHtml(t, idx) {
    const tfOpts = TRANSFORM_OPTS.map(o =>
      '<option value="' + o.v + '"' + (t.type === o.v ? ' selected' : '') + '>' + esc(o.l) + '</option>'
    ).join('');
    const chosenOpt = TRANSFORM_OPTS.find(o => o.v === t.type) || {};
    const paramHtml = chosenOpt.param
      ? '<input type="number" data-mt-param="' + idx + '" value="' + esc(t.param || chosenOpt.paramDefault || '20') + '" step="1" min="2" />'
      : '<span style="color:var(--fg-4);font-size:12px;text-align:center">—</span>';
    return (
      '<div class="pipeline-step" data-mt-idx="' + idx + '">' +
        '<span class="step-num">' + (idx + 1) + '</span>' +
        '<select data-mt-type="' + idx + '">' + tfOpts + '</select>' +
        paramHtml +
        '<span style="font-size:11px;color:var(--fg-4);">window</span>' +
        '<button class="step-del" data-mt-del="' + idx + '" type="button" aria-label="Remove">' +
          '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg>' +
        '</button>' +
      '</div>'
    );
  }

  function mathCondRowHtml(c, idx, logic) {
    const logicHtml = idx === 0
      ? '<span style="font-size:10px;font-weight:600;color:var(--fg-3);letter-spacing:0.06em;">IF</span>'
      : ('<div class="logic-seg"><button class="' + (logic==='AND'?'on':'') + '" data-mc-logic-and="' + idx + '">AND</button>' +
         '<button class="' + (logic==='OR'?'on':'') + '" data-mc-logic-or="' + idx + '">OR</button></div>');
    const opsHtml = MCOND_OPS.map(o =>
      '<option' + (c.op === o ? ' selected' : '') + '>' + esc(o) + '</option>'
    ).join('');
    return (
      '<div class="mcond-row" data-mc-idx="' + idx + '">' +
        logicHtml +
        '<input type="number" data-mc-thr="' + idx + '" value="' + esc(c.threshold == null ? '' : c.threshold) + '" placeholder="threshold" step="any" />' +
        '<select data-mc-op="' + idx + '">' + opsHtml + '</select>' +
        '<input type="number" data-mc-n="' + idx + '" value="' + esc(c.n == null ? '' : c.n) + '" placeholder="N bars" step="1" min="1" />' +
        '<button class="rule-del" data-mc-del="' + idx + '" type="button"><svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg></button>' +
      '</div>'
    );
  }

  function renderMathBt(s) {
    const bt = s._realBt;
    let inner;
    if (!bt || bt.status === 'idle') {
      inner =
        renderField(s, { key:'btPeriod', label:'Period', type:'select',
          options:['Last 1 month','Last 3 months','Last 6 months','Last 1 year'],
          value: s.btPeriod || 'Last 6 months' }) +
        renderField(s, { key:'btCapital', label:'Initial capital (₹)', type:'text',
          value: s.btCapital || '10,00,000', mono: true }) +
        '<div class="cfg-field span2"><div style="padding-top:6px">' +
          '<button class="btn btn-primary btn-sm" data-action="run-math-bt">↻ Run on real data</button>' +
          ' <span style="font-size:11px;color:var(--fg-3);margin-left:8px;">Fetches candles from DB · numpy</span>' +
        '</div></div>';
    } else if (bt.status === 'running') {
      inner = '<div class="bt-running"><div class="spinner"></div>Running on real data…</div>';
    } else if (bt.status === 'error') {
      inner = '<div class="bt-error">Error: ' + esc(bt.error) + '</div>';
    } else {
      const r = bt;
      const retTone = r.total_return >= 0 ? 'pos' : 'neg';
      const retStr = (r.total_return >= 0 ? '+ ' : '− ') + Math.abs(r.total_return).toFixed(2) + '%';
      inner =
        '<div class="bt-results">' +
          '<div class="bt-curve">' +
            '<span class="bt-label">Equity curve · real data</span>' +
            '<svg viewBox="0 0 240 60" preserveAspectRatio="none">' +
              '<line x1="0" y1="48" x2="240" y2="48" stroke="var(--border-1)" stroke-width="1" stroke-dasharray="2 2"/>' +
              '<polyline points="' + esc(r.curve || '') + '" fill="none" stroke="var(--tu-' + (retTone==='pos'?'success':'danger') + ')" stroke-width="1.6" stroke-linejoin="round"/>' +
            '</svg>' +
          '</div>' +
          '<div class="bt-metrics">' +
            '<div class="mcell"><div class="l">Total return</div><div class="v ' + retTone + '">' + esc(retStr) + '</div></div>' +
            '<div class="mcell"><div class="l">Win rate</div><div class="v">' + esc((r.win_rate||0).toFixed(1)) + '%</div></div>' +
            '<div class="mcell"><div class="l">Max drawdown</div><div class="v neg">− ' + esc(Math.abs(r.max_dd||0).toFixed(1)) + '%</div></div>' +
            '<div class="mcell"><div class="l">Sharpe</div><div class="v">' + esc((r.sharpe||0).toFixed(2)) + '</div></div>' +
            '<div class="mcell"><div class="l">Trades</div><div class="v">' + esc(r.trades||0) + '</div></div>' +
            '<div class="mcell"><div class="l">Candles</div><div class="v" style="font-size:11px">' + esc(r.candles||0) + '</div></div>' +
          '</div>' +
        '</div>';
    }
    return (
      '<div class="cfg-section">' +
        '<div class="section-title"><span>Back-test · Real data</span>' +
          (bt && bt.status === 'done' ? '<button class="add-mini" data-action="run-math-bt" type="button">↻ Re-run</button>' : '') +
        '</div>' +
        '<div class="cfg-form">' + inner + '</div>' +
      '</div>'
    );
  }

  function renderMathBody(s, statsHtml) {
    const tfOpts = ['1 minute','5 minute','15 minute','60 minute','Daily']
      .map(o => '<option' + (s.tf === o ? ' selected' : '') + '>' + esc(o) + '</option>').join('');
    const baseOpts = BASE_OPTS
      .map(o => '<option' + (s.mathBase === o ? ' selected' : '') + '>' + esc(o) + '</option>').join('');
    const transforms = s.mathTransforms || [];
    const conds      = s.mathConds      || [];
    const logics     = s.mathCondLogics || [];
    const formula    = buildFormulaPreview(s.mathBase || 'Close', s.tf || '5 minute', transforms);
    const pipeHtml   = transforms.map((t, i) => mathTransformRowHtml(t, i)).join('');
    const condHtml   = conds.map((c, i) => mathCondRowHtml(c, i, logics[i] || 'AND')).join('');
    return (
      statsHtml +
      '<div class="cfg-section">' +
        '<div class="section-title">Basics</div>' +
        '<div class="cfg-form">' +
          '<div class="cfg-field"><label>Symbol</label>' +
            '<input type="text" data-key="mathSymbol" value="' + esc(s.mathSymbol || 'NIFTY') + '" /></div>' +
          '<div class="cfg-field"><label>Timeframe</label>' +
            '<select data-key="tf">' + tfOpts + '</select></div>' +
          '<div class="cfg-field"><label>Base series</label>' +
            '<select data-key="mathBase">' + baseOpts + '</select></div>' +
          '<div class="cfg-field"><label>Side</label>' +
            '<select data-key="side">' +
              '<option' + (s.side==='Long only'?' selected':'') + '>Long only</option>' +
              '<option' + (s.side==='Short only'?' selected':'') + '>Short only</option>' +
              '<option' + (s.side==='Both'?' selected':'') + '>Both</option>' +
            '</select></div>' +
        '</div>' +
      '</div>' +
      '<div class="cfg-section">' +
        '<div class="section-title"><span>Series pipeline</span>' +
          '<button class="add-mini" data-add-mt="1" type="button">+ Add transform</button></div>' +
        '<div class="formula-preview"><span class="fp-label">Formula preview</span>' + esc(formula) + '</div>' +
        '<div class="pipeline-wrap" id="math-pipeline">' + pipeHtml + '</div>' +
      '</div>' +
      '<div class="cfg-section">' +
        '<div class="section-title"><span>Entry conditions</span>' +
          '<button class="add-mini" data-add-mc="1" type="button">+ Add condition</button></div>' +
        '<div data-mc-section="1">' + condHtml + '</div>' +
      '</div>' +
      '<div class="cfg-section">' +
        '<div class="section-title">Exit rules</div>' +
        '<div class="cfg-form">' +
          '<div class="cfg-field"><label>Stop loss %</label>' +
            '<input class="mono" type="number" data-key="mathStop" value="' + esc(s.mathStop || '0.5') + '" step="0.1" /></div>' +
          '<div class="cfg-field"><label>Target %</label>' +
            '<input class="mono" type="number" data-key="mathTarget" value="' + esc(s.mathTarget || '1.0') + '" step="0.1" /></div>' +
          '<div class="cfg-field"><label>Time exit (IST)</label>' +
            '<input class="mono" type="text" data-key="timeExit" value="' + esc(s.timeExit || '15:10') + '" /></div>' +
          '<div class="cfg-field"><label>Hold bars (max)</label>' +
            '<input class="mono" type="number" data-key="mathHoldBars" value="' + esc(s.mathHoldBars || '10') + '" step="1" /></div>' +
        '</div>' +
      '</div>'
    );
  }

  function runRealBacktest(s) {
    if (!s._realBt) s._realBt = {};
    s._realBt.status = 'running';
    renderPane();
    const body = {
      symbol:     s.mathSymbol      || 'NIFTY',
      tf:         s.tf              || '5 minute',
      base:       s.mathBase        || 'Close',
      transforms: s.mathTransforms  || [],
      conditions: s.mathConds       || [],
      logics:     s.mathCondLogics  || [],
      period:     s.btPeriod        || 'Last 6 months',
      capital:    parseFloat((s.btCapital || '1000000').replace(/[^0-9.]/g, '')) || 1000000,
      stop_pct:   parseFloat(s.mathStop   || '0.5'),
      target_pct: parseFloat(s.mathTarget || '1.0'),
      hold_bars:  parseInt(s.mathHoldBars  || '10', 10),
      side:       s.side || 'Long only',
    };
    fetch('/api/backtest/math', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
      .then(r => r.json())
      .then(data => {
        s._realBt = data.error
          ? { status: 'error', error: data.error }
          : { status: 'done', ...data };
        if (activeId === s.id) renderPane();
      })
      .catch(err => {
        s._realBt = { status: 'error', error: String(err) };
        if (activeId === s.id) renderPane();
      });
  }

  function bindMathPaneEvents(s) {
    if (!s.mathTransforms) s.mathTransforms = [];
    if (!s.mathConds)      s.mathConds      = [];
    if (!s.mathCondLogics) s.mathCondLogics = [];

    pane.querySelectorAll('input[data-key], select[data-key]').forEach(el => {
      const rerender = el.dataset.key === 'tf' || el.dataset.key === 'mathBase';
      el.addEventListener('change', () => {
        setValue(s.id, el.dataset.key, el.value);
        s[el.dataset.key] = el.value;
        if (rerender) renderPane();
      });
      if (!rerender) el.addEventListener('input', () => { setValue(s.id, el.dataset.key, el.value); s[el.dataset.key] = el.value; });
    });

    pane.querySelectorAll('[data-mt-type]').forEach(sel => {
      const i = parseInt(sel.dataset.mtType, 10);
      sel.addEventListener('change', () => {
        s.mathTransforms[i] = { type: sel.value, param: (s.mathTransforms[i] || {}).param };
        renderPane();
      });
    });
    pane.querySelectorAll('[data-mt-param]').forEach(inp => {
      const i = parseInt(inp.dataset.mtParam, 10);
      inp.addEventListener('input', () => { if (s.mathTransforms[i]) s.mathTransforms[i].param = inp.value; });
    });
    pane.querySelectorAll('[data-mt-del]').forEach(b => {
      const i = parseInt(b.dataset.mtDel, 10);
      b.addEventListener('click', () => { s.mathTransforms.splice(i, 1); renderPane(); });
    });
    const addMt = pane.querySelector('[data-add-mt]');
    if (addMt) addMt.addEventListener('click', () => { s.mathTransforms.push({ type: 'diff1' }); renderPane(); });

    pane.querySelectorAll('[data-mc-op]').forEach(sel => {
      const i = parseInt(sel.dataset.mcOp, 10);
      sel.addEventListener('change', () => { if (s.mathConds[i]) s.mathConds[i].op = sel.value; });
    });
    pane.querySelectorAll('[data-mc-thr]').forEach(inp => {
      const i = parseInt(inp.dataset.mcThr, 10);
      inp.addEventListener('input', () => {
        if (s.mathConds[i]) s.mathConds[i].threshold = inp.value === '' ? null : parseFloat(inp.value);
      });
    });
    pane.querySelectorAll('[data-mc-n]').forEach(inp => {
      const i = parseInt(inp.dataset.mcN, 10);
      inp.addEventListener('input', () => {
        if (s.mathConds[i]) s.mathConds[i].n = inp.value === '' ? null : parseInt(inp.value, 10);
      });
    });
    pane.querySelectorAll('[data-mc-del]').forEach(b => {
      const i = parseInt(b.dataset.mcDel, 10);
      b.addEventListener('click', () => {
        s.mathConds.splice(i, 1);
        s.mathCondLogics.splice(i, 1);
        renderPane();
      });
    });
    pane.querySelectorAll('[data-mc-logic-and]').forEach(b => {
      const i = parseInt(b.dataset.mcLogicAnd, 10);
      b.addEventListener('click', () => { s.mathCondLogics[i] = 'AND'; renderPane(); });
    });
    pane.querySelectorAll('[data-mc-logic-or]').forEach(b => {
      const i = parseInt(b.dataset.mcLogicOr, 10);
      b.addEventListener('click', () => { s.mathCondLogics[i] = 'OR'; renderPane(); });
    });
    const addMc = pane.querySelector('[data-add-mc]');
    if (addMc) addMc.addEventListener('click', () => {
      s.mathConds.push({ op: '>', threshold: 0, n: null });
      s.mathCondLogics.push('AND');
      renderPane();
    });

    pane.querySelectorAll('[data-action="run-math-bt"]').forEach(b => {
      b.addEventListener('click', () => runRealBacktest(s));
    });
  }

  function renderTypeChooserPane() {
    const headHtml =
      '<div class="pane-head">' +
        '<div class="num-box add">+</div>' +
        '<div class="body">' +
          '<span class="kind-tag custom">Custom strategy</span>' +
          '<h2>Add new strategy</h2>' +
          '<p class="desc">Choose how signals will be generated.</p>' +
        '</div>' +
        '<button class="pane-close" type="button" aria-label="Close" data-action="close">' +
          '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg>' +
        '</button>' +
      '</div>';
    const bodyHtml =
      '<p class="type-chooser-head">Every custom strategy needs a signal engine. Pick one:</p>' +
      '<div class="type-cards">' +
        '<button class="type-card rule" data-create-kind="custom" type="button">' +
          '<div class="tc-icon">⚡</div>' +
          '<div class="tc-name">Rule-based</div>' +
          '<div class="tc-desc">Combine technical indicators (RSI, MACD, VWAP…) with comparison operators to fire signals.</div>' +
        '</button>' +
        '<button class="type-card math" data-create-kind="math" type="button">' +
          '<div class="tc-icon">∑</div>' +
          '<div class="tc-name">Math series</div>' +
          '<div class="tc-desc">Build a transformation pipeline — differences, z-scores, rolling stats — and trigger on the resulting series.</div>' +
        '</button>' +
      '</div>';
    pane.innerHTML = headHtml + '<div class="pane-body">' + bodyHtml + '</div>';
    pane.querySelector('[data-action="close"]').addEventListener('click', closePane);
    pane.querySelectorAll('[data-create-kind]').forEach(b => {
      b.addEventListener('click', () => createNewStrategy(b.dataset.createKind));
    });
  }

  function createNewStrategy(kind) {
    const n = strategies.filter(s => s.kind === 'custom' || s.kind === 'math').length + 1;
    const newId = (kind === 'math' ? 'math-' : 'custom-') + Date.now();
    if (kind === 'math') {
      strategies.push({
        id: newId, kind: 'math',
        name: 'Math strategy ' + n,
        sub: 'Series transform',
        desc: 'Entry triggered by a mathematical transformation of price series.',
        running: false, armed: false, mode: 'paper',
        stats: { signals: 0, acted: 0, hit: '—', m2m: { value: '— flat', tone: 'flat' } },
        lastSignal: { time: '—', text: 'No signals yet.' },
        mathSymbol: 'NIFTY', tf: '5 minute', mathBase: 'Close',
        mathTransforms: [{ type: 'diff1' }],
        mathConds: [{ op: '>', threshold: 0, n: null }],
        mathCondLogics: ['AND'],
        mathStop: '0.5', mathTarget: '1.0', mathHoldBars: '10',
        side: 'Long only',
      });
    } else {
      strategies.push({
        id: newId, kind: 'custom',
        name: 'Custom strategy ' + n,
        sub: 'Your own strategy',
        desc: 'Describe what this strategy does and when it should fire.',
        running: false, armed: false, mode: 'paper',
        stats: { signals: 0, acted: 0, hit: '—', m2m: { value: '— flat', tone: 'flat' } },
        lastSignal: { time: '—', text: 'No signals yet.' },
        symbols: ['NIFTY'], tf: '5 minute', side: 'Long only', sizing: '0.5% of capital',
        rules: [{ indicator: 'RSI(14)', op: '<', val: '30' }],
        stop: 'ATR(14) · 1.0', target: '1.5R', timeExit: '15:10 IST', reentry: 'Once per day',
      });
    }
    activeId = newId;
    renderTiles();
    renderPane();
  }

  // ── Pane: open / close ──────────────────────────────────────────
  function openPane(id) {
    activeId = id;
    if (id === '__new__') {
      renderTypeChooserPane();
      pane.classList.add('show');
      backdrop.classList.add('show');
      document.body.style.overflow = 'hidden';
      return;
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

    const isMath    = s.kind === 'math';
    const isCustom  = s.kind === 'custom' || isMath;
    const kindLabel = s.kind === 'opt' ? 'Option strategy' : isMath ? 'Math series strategy' : isCustom ? 'Custom strategy' : 'Intraday strategy';
    const kindCls   = s.kind === 'opt' ? 'opt' : (isCustom ? 'custom' : '');
    const numCls    = s.running ? ' running' : (isCustom ? ' add' : '');
    const statusCls  = s.running ? 'running' : (s.armed ? 'armed' : '');
    const statusText = s.running ? 'Running'  : (s.armed ? 'Armed'   : 'Paused');
    const m2m = (s.stats && s.stats.m2m) || { value: '— flat', tone: 'flat' };

    const headHtml =
      '<div class="pane-head">' +
        '<div class="num-box' + numCls + '"></div>' +
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
    if (isMath) {
      bodyHtml = renderMathBody(s, statsHtml);
    } else if (s.kind === 'custom') {
      const rules = s.rules || [];
      const ruleRows = rules.map((r, i) => (
        '<div class="rule-row" data-ridx="' + i + '">' +
          '<div class="cfg-field"><label>Indicator / signal</label><input class="mono" type="text" data-rule-key="indicator" value="' + esc(r.indicator || '') + '" placeholder="e.g. RSI(14)" /></div>' +
          '<div class="cfg-field"><label>Operator</label><select data-rule-key="op">' +
            ['>','<','>=','<=','crosses above','crosses below','=='].map(o => '<option' + (o === r.op ? ' selected' : '') + '>' + esc(o) + '</option>').join('') +
          '</select></div>' +
          '<div class="cfg-field"><label>Value</label><input class="mono" type="text" data-rule-key="val" value="' + esc(r.val || '') + '" placeholder="e.g. 30 / VWAP / 20-bar high" /></div>' +
          '<button class="rule-del" data-rule-del="' + i + '" type="button" aria-label="Delete rule"><svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg></button>' +
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
          '<div class="section-title"><span>Entry rules — all must be true</span><button class="add-mini" data-add-rule="entry" type="button">+ Add rule</button></div>' +
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

    const btHtml = isMath ? renderMathBt(s) : (function() {
    const bt = backtestResults(s);
    return (
      '<div class="cfg-section">' +
        '<div class="section-title"><span>Back-test</span><button class="add-mini" data-action="run-bt" type="button">↻ Re-run</button></div>' +
        '<div class="cfg-form">' +
          renderField(s, { key: 'btPeriod',     label: 'Period',          type: 'select', options: ['Last 1 month','Last 3 months','Last 6 months','Last 1 year','Last 3 years'], value: s.btPeriod || 'Last 6 months' }) +
          renderField(s, { key: 'btCapital',    label: 'Initial capital', type: 'text',   value: s.btCapital    || '₹10,00,000', mono: true }) +
          renderField(s, { key: 'btSlippage',   label: 'Slippage',        type: 'text',   value: s.btSlippage   || '0.05%',       mono: true }) +
          renderField(s, { key: 'btCommission', label: 'Commission',      type: 'text',   value: s.btCommission || '₹20 / order', mono: true }) +
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
      '</div>'
    );
    })());

    const last = s.lastSignal || { time: '—', text: 'No signals yet.' };
    const deployBtn = s.deployed
      ? '<button class="btn btn-ghost btn-sm" data-action="undeploy" title="Remove from paper-trading desk"><svg class="ic" viewBox="0 0 24 24"><path d="M5 12l4 4L19 6"/></svg> Deployed</button>'
      : '<button class="btn btn-primary btn-sm" data-action="deploy"><svg class="ic" viewBox="0 0 24 24"><path d="M5 12h14M13 5l7 7-7 7"/></svg> Deploy to Paper Trading</button>';
    const footHtml =
      '<div class="pane-foot">' +
        '<div class="left-side"><span class="when">' + esc(last.time) + '</span><span>Last · ' + esc(last.text) + '</span></div>' +
        '<div class="actions">' +
          '<div class="mode-seg">' +
            '<button class="' + (s.mode === 'paper' ? 'on paper' : '') + '" data-mode="paper">Paper</button>' +
            '<button class="' + (s.mode === 'live'  ? 'on live'  : '') + '" data-mode="live">Live</button>' +
          '</div>' +
          '<button class="btn btn-ghost btn-sm" data-action="save"><svg class="ic" viewBox="0 0 24 24"><path d="M5 12l4 4L19 6"/></svg> Save</button>' +
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

    pane.querySelectorAll('[data-mode]').forEach(b => {
      b.addEventListener('click', () => { s.mode = b.dataset.mode; renderPane(); });
    });

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
          setTimeout(() => { if (activeId === s.id) renderPane(); }, 1100);
          return;
        }
        if (a === 'undeploy') {
          s.deployed = false; s.running = false;
          flashButton(b, 'Removed');
          renderTiles();
          setTimeout(() => { if (activeId === s.id) renderPane(); }, 1100);
          return;
        }
        if (a === 'run-bt') {
          s.btSeed = String(Date.now());
          flashButton(b, 'Running…', 600);
          setTimeout(() => { if (activeId === s.id) renderPane(); }, 620);
          return;
        }
        if (a === 'save') { flashButton(b, 'Saved'); return; }
        renderTiles();
        renderPane();
      });
    });

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
    if (s.kind === 'math') bindMathPaneEvents(s);
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
})();
