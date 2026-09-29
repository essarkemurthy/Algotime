/* static/signal-feed.js
 *
 * Drives the Signal feed table with real data and adds a strategy selector.
 *
 * The section shipped as static mock HTML - seven hardcoded rows, with the
 * All/Acted/Filtered buttons and Export CSV wired to nothing. This replaces the
 * rows with live decisions from /api/strategy/signals (backed by
 * paper_signal_decisions, which records every signal and why it did or did not
 * trade) and makes the existing controls work.
 *
 * The dropdown groups by what the signal actually was: Intraday (cash product),
 * Options (options/index product) or Custom (a user-defined strategy), plus an
 * entry per individual strategy.
 */
(function () {
  'use strict';

  var DAYS = 7;
  var rows = [];
  var customIds = [];
  var kindFilter = 'all';     // all | intraday | options | custom | <STRATEGY>
  var actFilter = 'all';      // all | acted | filtered

  function esc(s) {
    return String(s === null || s === undefined ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function section() { return document.getElementById('signal-log'); }

  function isCustom(r) {
    return customIds.indexOf(String(r.strategy || '').toUpperCase()) >= 0;
  }
  function kindOf(r) {
    if (isCustom(r)) return 'custom';
    var p = String(r.product || 'cash').toLowerCase();
    return (p === 'options' || p === 'index') ? 'options' : 'intraday';
  }

  function visible() {
    return rows.filter(function (r) {
      if (actFilter === 'acted' && r.decision !== 'EXECUTED') return false;
      if (actFilter === 'filtered' && r.decision === 'EXECUTED') return false;
      if (kindFilter === 'all') return true;
      if (kindFilter === 'intraday' || kindFilter === 'options' || kindFilter === 'custom') {
        return kindOf(r) === kindFilter;
      }
      return String(r.strategy || '').toUpperCase() === kindFilter;
    });
  }

  function injectCss() {
    if (document.getElementById('sf-css')) return;
    var s = document.createElement('style');
    s.id = 'sf-css';
    s.textContent = [
      '.sf-select{font-family:inherit;font-size:12px;font-weight:500;color:var(--fg-1,#16191c);',
      '  background:var(--bg-surface,#fff);border:1px solid var(--border-2,#dfe3e6);',
      '  border-radius:var(--r-pill,999px);padding:6px 30px 6px 12px;cursor:pointer;',
      '  appearance:none;-webkit-appearance:none;box-shadow:var(--shadow-1,0 1px 2px rgba(0,0,0,.05));',
      "  background-image:url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg'",
      "    viewBox='0 0 24 24' fill='none' stroke='%2368727d' stroke-width='2.4'",
      "    stroke-linecap='round'><path d='M6 9l6 6 6-6'/></svg>\");",
      '  background-repeat:no-repeat;background-position:right 9px center;background-size:12px;}',
      '.sf-select:hover{border-color:var(--tu-teal-300,#9ec4b8);}',
      '.sf-select:focus{outline:none;border-color:var(--tu-teal-500,#3f8574);',
      '  box-shadow:0 0 0 3px rgba(47,111,98,.14);}',
      '.sf-pill{display:inline-flex;align-items:center;gap:5px;font-size:10.5px;font-weight:600;',
      '  padding:3px 9px;border-radius:var(--r-pill,999px);background:var(--bg-sunken,#f2f4f5);',
      '  color:var(--fg-3,#68727d);white-space:nowrap;}',
      '.sf-pill.buy{background:var(--tu-teal-50,#e6f1ee);color:var(--tu-teal-700,#2f6f62);}',
      '.sf-pill.sell{background:var(--tu-rose-200,#fbeceb);color:var(--tu-danger,#b3392c);}',
      '.sf-pill.exec{background:var(--tu-teal-50,#e6f1ee);color:var(--tu-teal-700,#2f6f62);}',
      '.sf-dot{width:6px;height:6px;border-radius:999px;background:currentColor;flex:none;}',
      '.sf-mono{font-family:var(--font-mono,monospace);font-size:11.5px;}',
      '.sf-dim{color:var(--fg-3,#68727d);}',
      '.sf-empty{text-align:center;padding:26px;color:var(--fg-3,#68727d);font-size:12px;}'
    ].join('\n');
    document.head.appendChild(s);
  }

  function buildControls() {
    var sec = section();
    if (!sec || sec.querySelector('.sf-select')) return;
    var actions = sec.querySelector('.card-actions');
    if (!actions) return;

    var sel = document.createElement('select');
    sel.className = 'sf-select';
    sel.id = 'sf-kind';
    sel.setAttribute('aria-label', 'Filter signals by strategy');
    actions.insertBefore(sel, actions.firstChild);
    sel.addEventListener('change', function () { kindFilter = sel.value; render(); });

    // Make the existing All / Acted / Filtered buttons work.
    var segBtns = sec.querySelectorAll('.card-actions .seg button');
    segBtns.forEach(function (b) {
      b.addEventListener('click', function () {
        segBtns.forEach(function (x) { x.classList.remove('on'); });
        b.classList.add('on');
        actFilter = (b.textContent || '').trim().toLowerCase();
        if (actFilter !== 'acted' && actFilter !== 'filtered') actFilter = 'all';
        render();
      });
    });

    var csv = sec.querySelector('.filter-link');
    if (csv) {
      csv.addEventListener('click', function (e) { e.preventDefault(); exportCsv(); });
    }
  }

  function fillOptions() {
    var sel = document.getElementById('sf-kind');
    if (!sel) return;
    var counts = { intraday: 0, options: 0, custom: 0 };
    var per = {};
    rows.forEach(function (r) {
      counts[kindOf(r)]++;
      var s = String(r.strategy || '?').toUpperCase();
      per[s] = (per[s] || 0) + 1;
    });
    var html = '<option value="all">All strategies (' + rows.length + ')</option>'
      + '<optgroup label="By type">'
      + '<option value="intraday">Intraday (' + counts.intraday + ')</option>'
      + '<option value="options">Options (' + counts.options + ')</option>'
      + '<option value="custom">Custom (' + counts.custom + ')</option>'
      + '</optgroup>'
      + '<optgroup label="By strategy">'
      + Object.keys(per).sort().map(function (s) {
          return '<option value="' + esc(s) + '">' + esc(s.replace(/_/g, ' '))
            + ' (' + per[s] + ')</option>';
        }).join('')
      + '</optgroup>';
    sel.innerHTML = html;
    sel.value = kindFilter;
    if (!sel.value) { kindFilter = 'all'; sel.value = 'all'; }
  }

  function actionPill(r) {
    var d = String(r.direction || '').toUpperCase();
    var cls = d === 'LONG' ? 'buy' : (d === 'SHORT' ? 'sell' : '');
    return '<span class="sf-pill ' + cls + '"><span class="sf-dot"></span>' + esc(d || '—') + '</span>';
  }

  function outcomePill(r) {
    var ok = r.decision === 'EXECUTED';
    return '<span class="sf-pill ' + (ok ? 'exec' : '') + '">'
      + '<span class="sf-dot"></span>' + esc(ok ? 'Routed' : (r.reason || 'Skipped')) + '</span>';
  }

  function rationale(r) {
    var bits = [];
    if (r.trigger_price != null) bits.push('Trigger <b>' + esc(r.trigger_price) + '</b>');
    if (r.vwap != null) bits.push('VWAP ' + esc(r.vwap));
    if (r.atr != null) bits.push('ATR ' + esc(r.atr));
    if (r.decision === 'EXECUTED' && r.entry_price != null) {
      bits.push('entered at <b>' + esc(r.entry_price) + '</b>');
    } else if (r.reason) {
      bits.push('skipped &mdash; ' + esc(r.reason));
    }
    if (r.exec_lag_sec != null) bits.push('lag ' + esc(r.exec_lag_sec) + 's');
    return bits.join(' &middot; ') || '&mdash;';
  }

  function render() {
    var sec = section();
    if (!sec) return;
    var tb = sec.querySelector('tbody');
    if (!tb) return;
    var list = visible();

    tb.innerHTML = list.length ? list.slice(0, 200).map(function (r) {
      return '<tr>'
        + '<td class="sf-mono">' + esc(r.signal_ts || '—') + '</td>'
        + '<td><b>' + esc(String(r.strategy || '').replace(/_/g, ' ')) + '</b></td>'
        + '<td><b>' + esc(r.instrument || r.symbol || '') + '</b></td>'
        + '<td>' + actionPill(r) + '</td>'
        + '<td class="sf-mono sf-dim">' + esc(kindOf(r)) + '</td>'
        + '<td><span class="sf-pill">Paper</span></td>'
        + '<td class="sf-dim">' + rationale(r) + '</td>'
        + '<td>' + outcomePill(r) + '</td>'
        + '</tr>';
    }).join('')
      : '<tr><td colspan="8" class="sf-empty">No signals match this filter.</td></tr>';

    var meta = sec.querySelector('.section-head .meta');
    if (meta) {
      meta.innerHTML = 'All signals routed by any runner, regardless of mode &middot; <b>'
        + list.length + '</b> shown of ' + rows.length + ' in the last ' + DAYS + ' days';
    }
    var cnt = sec.querySelector('.card-title .count');
    if (cnt) cnt.textContent = 'last ' + DAYS + ' days';
  }

  function exportCsv() {
    var list = visible();
    var head = ['time', 'strategy', 'symbol', 'direction', 'kind', 'product',
                'trigger', 'decision', 'reason', 'entry', 'lag_sec'];
    var lines = [head.join(',')].concat(list.map(function (r) {
      return [r.signal_ts, r.strategy, r.instrument || r.symbol, r.direction, kindOf(r),
              r.product, r.trigger_price, r.decision, r.reason, r.entry_price, r.exec_lag_sec]
        .map(function (v) {
          var s = v === null || v === undefined ? '' : String(v);
          return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
        }).join(',');
    }));
    var blob = new Blob([lines.join('\n')], { type: 'text/csv' });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'signals_' + new Date().toISOString().slice(0, 10) + '.csv';
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 2000);
  }

  function load() {
    fetch('/api/strategy/custom').then(function (r) { return r.json(); })
      .then(function (d) {
        customIds = (d.strategies || []).map(function (s) {
          return String(s.id).toUpperCase();
        });
      }).catch(function () { customIds = []; })
      .then(function () {
        return fetch('/api/strategy/signals?days=' + DAYS + '&limit=500')
          .then(function (r) { return r.json(); });
      }).then(function (d) {
        rows = d.signals || [];
        fillOptions();
        render();
      }).catch(function () { /* leave the previous render in place */ });
  }

  function boot() {
    if (!section()) return;
    injectCss();
    buildControls();
    load();
    setInterval(load, 30000);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else { boot(); }
})();
