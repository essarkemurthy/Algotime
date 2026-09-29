/* static/custom-strategy.js
 *
 * Custom strategy builder + signals pane for the strategies page.
 *
 * A rule is data, not code: conditions comparing an indicator against a fixed
 * level or another indicator, joined by ALL/ANY. Saved rules are evaluated by
 * the signal engine on every bar close alongside the built-in detectors, so
 * they fire real (paper) signals and show up in the pane below.
 */
(function () {
  'use strict';

  var CAT = { indicators: [], operators: [] };
  var conds = [];
  var editingId = null;

  var OP_LABEL = {
    '>': 'is above', '>=': 'is at or above', '<': 'is below',
    '<=': 'is at or below', '==': 'equals', '!=': 'does not equal',
    'cross_above': 'crosses above', 'cross_below': 'crosses below'
  };

  function el(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s === null || s === undefined ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  // ── condition rows ─────────────────────────────────────────────────────────

  function needsPeriod(name) {
    var i = CAT.indicators.find(function (x) { return x.name === name; });
    return !!(i && i.args.indexOf('period') >= 0);
  }
  function needsMult(name) {
    var i = CAT.indicators.find(function (x) { return x.name === name; });
    return !!(i && i.args.indexOf('mult') >= 0);
  }

  function blankCond() {
    return {
      left: { kind: 'indicator', name: 'close', period: 14, mult: 2 },
      op: '>',
      right: { kind: 'indicator', name: 'vwap', period: 14, mult: 2 }
    };
  }

  function indicatorOptions(sel) {
    return CAT.indicators.map(function (i) {
      return '<option value="' + i.name + '"' + (i.name === sel ? ' selected' : '') + '>'
        + esc(i.label) + '</option>';
    }).join('');
  }

  function sideHTML(side, idx, spec) {
    var isVal = spec.kind === 'value';
    var h = '<select class="cs-in cs-kind" data-side="' + side + '" data-i="' + idx + '">'
      + '<option value="indicator"' + (isVal ? '' : ' selected') + '>Indicator</option>'
      + '<option value="value"' + (isVal ? ' selected' : '') + '>Level</option>'
      + '</select>';
    if (isVal) {
      h += '<input class="cs-in cs-val" data-side="' + side + '" data-i="' + idx + '"'
        + ' type="number" step="any" value="' + esc(spec.value !== undefined ? spec.value : 0) + '">';
    } else {
      h += '<select class="cs-in cs-name" data-side="' + side + '" data-i="' + idx + '">'
        + indicatorOptions(spec.name) + '</select>';
      if (needsPeriod(spec.name)) {
        h += '<input class="cs-in cs-period" data-side="' + side + '" data-i="' + idx + '"'
          + ' type="number" min="1" step="1" title="period" value="' + esc(spec.period || 14) + '">';
      }
      if (needsMult(spec.name)) {
        h += '<input class="cs-in cs-mult" data-side="' + side + '" data-i="' + idx + '"'
          + ' type="number" step="0.1" title="multiplier" value="' + esc(spec.mult || 2) + '">';
      }
    }
    return h;
  }

  function renderConds() {
    var box = el('cs-conds');
    if (!box) return;
    if (!conds.length) conds.push(blankCond());
    box.innerHTML = conds.map(function (c, i) {
      return '<div class="cs-cond">'
        + '<div class="cs-side">' + sideHTML('left', i, c.left) + '</div>'
        + '<select class="cs-in cs-op" data-i="' + i + '">'
        + CAT.operators.map(function (o) {
            return '<option value="' + o + '"' + (o === c.op ? ' selected' : '') + '>'
              + esc(OP_LABEL[o] || o) + '</option>';
          }).join('')
        + '</select>'
        + '<div class="cs-side">' + sideHTML('right', i, c.right) + '</div>'
        + '<button class="cs-del" data-i="' + i + '" type="button" title="remove">&times;</button>'
        + '</div>';
    }).join('');

    box.querySelectorAll('.cs-in').forEach(function (inp) {
      inp.addEventListener('change', onCondChange);
    });
    box.querySelectorAll('.cs-del').forEach(function (b) {
      b.addEventListener('click', function () {
        conds.splice(parseInt(b.dataset.i, 10), 1);
        renderConds();
      });
    });
  }

  function onCondChange(e) {
    var t = e.target, i = parseInt(t.dataset.i, 10), side = t.dataset.side;
    var c = conds[i];
    if (!c) return;
    if (t.classList.contains('cs-op')) { c.op = t.value; return; }
    var spec = c[side];
    if (t.classList.contains('cs-kind')) {
      spec.kind = t.value;
      if (spec.kind === 'value' && spec.value === undefined) spec.value = 0;
      renderConds();
      return;
    }
    if (t.classList.contains('cs-name')) { spec.name = t.value; renderConds(); return; }
    if (t.classList.contains('cs-period')) spec.period = parseInt(t.value, 10) || 14;
    if (t.classList.contains('cs-mult')) spec.mult = parseFloat(t.value) || 2;
    if (t.classList.contains('cs-val')) spec.value = parseFloat(t.value) || 0;
  }

  // ── build / save ───────────────────────────────────────────────────────────

  function collect() {
    var syms = (el('cs-symbols').value || '').split(',')
      .map(function (s) { return s.trim().toUpperCase(); })
      .filter(Boolean);
    return {
      id: editingId || undefined,
      name: (el('cs-name').value || '').trim(),
      direction: el('cs-direction').value,
      match: el('cs-match').value,
      symbols: syms,
      conditions: conds,
      enabled: true
    };
  }

  function msg(text, cls) {
    var m = el('cs-msg');
    if (m) { m.innerHTML = text; m.className = 'cs-msg ' + (cls || ''); }
  }

  function save() {
    var body = collect();
    if (!body.name) { msg('Give the strategy a name.', 'err'); return; }
    msg('Saving…', 'busy');
    fetch('/api/strategy/custom', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function (r) { return r.json(); }).then(function (d) {
      if (!d.ok) {
        msg('Cannot save:<br>• ' + (d.errors || ['unknown error']).map(esc).join('<br>• '), 'err');
        return;
      }
      msg('Saved as <b>' + esc(d.id) + '</b> — live from the next bar close.', 'ok');
      editingId = null;
      loadList();
      loadSignals();
    }).catch(function (e) { msg(esc(e.message || e), 'err'); });
  }

  function preview() {
    var body = collect();
    body.preview_symbol = (el('cs-prev-sym').value || 'NIFTY').toUpperCase();
    body.preview_interval = el('cs-prev-iv').value;
    body.preview_days = parseInt(el('cs-prev-days').value, 10) || 5;
    msg('Testing against stored bars…', 'busy');
    fetch('/api/strategy/custom/preview', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function (r) { return r.json(); }).then(function (d) {
      if (!d.ok) {
        msg('Cannot test:<br>• ' + (d.errors || ['unknown']).map(esc).join('<br>• '), 'err');
        return;
      }
      if (!d.fired) {
        msg('Valid, but it would <b>never have fired</b> on ' + esc(d.symbol)
          + ' over ' + d.bars + ' ' + esc(d.interval) + ' bars. Loosen the conditions.', 'err');
        return;
      }
      var days = Object.keys(d.by_day).sort().map(function (k) {
        return esc(k) + ' × ' + d.by_day[k];
      }).join(' · ');
      msg('Would have fired <b>' + d.fired + '×</b> on ' + esc(d.symbol)
        + ' across ' + d.bars + ' bars.<br><span class="cs-dim">' + days + '</span>', 'ok');
    }).catch(function (e) { msg(esc(e.message || e), 'err'); });
  }

  // ── saved list ─────────────────────────────────────────────────────────────

  function loadList() {
    fetch('/api/strategy/custom').then(function (r) { return r.json(); })
      .then(function (d) {
        var box = el('cs-list');
        if (!box) return;
        var list = d.strategies || [];
        if (!list.length) {
          box.innerHTML = '<div class="cs-empty">No custom strategies yet.</div>';
          return;
        }
        box.innerHTML = list.map(function (s) {
          return '<div class="cs-item">'
            + '<div><div class="cs-item-name">' + esc(s.name)
            + ' <span class="cs-tag">' + esc(s.direction) + '</span>'
            + (s.enabled ? '' : ' <span class="cs-tag off">paused</span>') + '</div>'
            + '<div class="cs-item-sum">' + esc(s.summary || '') + '</div>'
            + (s.symbols && s.symbols.length
                ? '<div class="cs-item-sum cs-dim">' + esc(s.symbols.join(', ')) + '</div>'
                : '<div class="cs-item-sum cs-dim">all symbols</div>')
            + '</div>'
            + '<div class="cs-item-act">'
            + '<button class="cs-btn" data-act="toggle" data-id="' + esc(s.id) + '" data-on="'
            + (s.enabled ? '0' : '1') + '">' + (s.enabled ? 'Pause' : 'Resume') + '</button>'
            + '<button class="cs-btn" data-act="signals" data-id="' + esc(s.id) + '">Signals</button>'
            + '<button class="cs-btn danger" data-act="del" data-id="' + esc(s.id) + '">Delete</button>'
            + '</div></div>';
        }).join('');
        box.querySelectorAll('button[data-act]').forEach(function (b) {
          b.addEventListener('click', function () { itemAction(b.dataset); });
        });
      }).catch(function () { });
  }

  function itemAction(ds) {
    if (ds.act === 'del') {
      if (!confirm('Delete "' + ds.id + '"? It stops firing immediately.')) return;
      fetch('/api/strategy/custom/' + encodeURIComponent(ds.id), { method: 'DELETE' })
        .then(function () { loadList(); loadSignals(); });
    } else if (ds.act === 'toggle') {
      fetch('/api/strategy/custom/' + encodeURIComponent(ds.id) + '/toggle', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: ds.on === '1' })
      }).then(function () { loadList(); });
    } else if (ds.act === 'signals') {
      el('cs-sig-filter').value = ds.id;
      loadSignals();
      el('cs-signals-card').scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }

  // ── signals pane ───────────────────────────────────────────────────────────

  function loadSignals() {
    var strat = (el('cs-sig-filter') && el('cs-sig-filter').value || '').trim();
    var days = parseInt(el('cs-sig-days') && el('cs-sig-days').value, 10) || 5;
    var url = '/api/strategy/signals?days=' + days
      + (strat ? '&strategy=' + encodeURIComponent(strat) : '');
    fetch(url).then(function (r) { return r.json(); }).then(function (d) {
      var sub = el('cs-sig-sub');
      if (sub) {
        sub.textContent = d.error ? d.error
          : (d.total || 0) + ' signals since ' + (d.from || '')
            + (d.strategy ? ' · ' + d.strategy : ' · all strategies');
      }
      var chips = el('cs-sig-counts');
      if (chips) {
        var c = d.counts || {};
        chips.innerHTML = Object.keys(c).sort().map(function (k) {
          return '<span class="cs-chip ' + (k === 'EXECUTED' ? 'ok' : '') + '">'
            + esc(k) + ' ' + c[k] + '</span>';
        }).join('');
      }
      var tb = el('cs-sig-body');
      if (!tb) return;
      var rows = d.signals || [];
      if (!rows.length) {
        tb.innerHTML = '<tr><td colspan="8" class="cs-empty">No signals in this window.</td></tr>';
        return;
      }
      tb.innerHTML = rows.map(function (s) {
        var dir = (s.direction || '').toUpperCase();
        return '<tr>'
          + '<td>' + esc(s.signal_ts || '—') + '</td>'
          + '<td>' + esc((s.strategy || '').replace(/_/g, ' ')) + '</td>'
          + '<td>' + esc(s.symbol || '') + '</td>'
          + '<td class="' + (dir === 'LONG' ? 'cs-long' : 'cs-short') + '">' + esc(dir) + '</td>'
          + '<td class="num">' + (s.trigger_price != null ? esc(s.trigger_price) : '—') + '</td>'
          + '<td>' + esc(s.decision || '') + '</td>'
          + '<td>' + esc(s.reason || '') + '</td>'
          + '<td class="num">' + (s.exec_lag_sec != null ? esc(s.exec_lag_sec) + 's' : '—') + '</td>'
          + '</tr>';
      }).join('');
    }).catch(function () { });
  }

  // ── boot ───────────────────────────────────────────────────────────────────

  function boot() {
    if (!el('cs-conds')) return;          // markup not on this page
    fetch('/api/strategy/catalogue').then(function (r) { return r.json(); })
      .then(function (c) {
        CAT = c;
        renderConds();
      }).catch(function () {
        msg('Could not load the indicator catalogue.', 'err');
      });

    el('cs-add').addEventListener('click', function () {
      conds.push(blankCond()); renderConds();
    });
    el('cs-save').addEventListener('click', save);
    el('cs-preview').addEventListener('click', preview);
    el('cs-sig-refresh').addEventListener('click', loadSignals);
    el('cs-sig-filter').addEventListener('change', loadSignals);
    el('cs-sig-days').addEventListener('change', loadSignals);

    loadList();
    loadSignals();
    setInterval(loadSignals, 30000);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else { boot(); }
})();
