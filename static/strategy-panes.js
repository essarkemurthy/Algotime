/* static/strategy-panes.js
 *
 * Turns the three strategy rows (Intraday / Option / Custom) into expandable
 * panes. Collapsed they are just a header; expanded they show every strategy in
 * that group with its one-line summary and full description, alongside the
 * existing tiles.
 *
 * Built-in groups read window.STRATEGIES (the library strategies-app.js already
 * renders). The custom group reads /api/strategy/custom, so it describes what is
 * actually persisted and firing rather than an in-memory placeholder.
 *
 * Expanded/collapsed state is kept per group in localStorage.
 */
(function () {
  'use strict';

  var LS_KEY = 'algoStrategyPanes';

  var GROUPS = [
    { sec: 'row-intraday', row: 'tiles-intra', kind: 'intra',  key: 'intra' },
    { sec: 'row-options',  row: 'tiles-opt',   kind: 'opt',    key: 'opt' },
    { sec: 'row-custom',   row: 'tiles-cust',  kind: 'custom', key: 'cust' }
  ];

  function esc(s) {
    return String(s === null || s === undefined ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function readState() {
    try { return JSON.parse(localStorage.getItem(LS_KEY) || '{}'); }
    catch (e) { return {}; }
  }
  function writeState(st) {
    try { localStorage.setItem(LS_KEY, JSON.stringify(st)); } catch (e) { /* private mode */ }
  }

  function injectCss() {
    if (document.getElementById('sp-css')) return;
    var s = document.createElement('style');
    s.id = 'sp-css';
    s.textContent = [
      '.tile-section-head{cursor:pointer;user-select:none;}',
      '.tile-section-head .left{display:flex;align-items:center;gap:8px;}',
      // Chevron sits AFTER the title text: right-pointing when collapsed,
      // rotating down when the pane opens.
      '.sp-chev{display:inline-flex;align-items:center;justify-content:center;width:20px;height:20px;',
      '  border-radius:6px;color:var(--fg-3,#68727d);flex:none;transition:transform .18s ease;}',
      '.sp-chev svg{width:13px;height:13px;}',
      '.tile-section.sp-open .sp-chev{transform:rotate(90deg);}',
      '.sp-selcount{font-size:10.5px;font-weight:700;letter-spacing:.04em;padding:2px 8px;',
      '  border-radius:20px;background:#e6f1ee;color:#2f6f62;}',
      '.tile-section .tile-row,.tile-section .sp-list{display:none;}',
      // .tile-row is a 5-column grid; restore grid, not flex, or the tiles
      // reflow into a single row when the pane is opened.
      '.tile-section.sp-open .tile-row{display:grid;}',
      '.tile-section.sp-open .sp-list{display:grid;}',
      // Strategies render as rounded boxes in a responsive grid.
      '.sp-list{margin-top:16px;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:12px;}',
      '.sp-box{position:relative;background:var(--bg-surface,#fff);border:1px solid var(--border-2,#dfe3e6);',
      '  border-radius:12px;padding:14px 44px 14px 15px;transition:border-color .15s,box-shadow .15s;}',
      '.sp-box:hover{border-color:var(--fg-3,#b9c1c8);box-shadow:0 2px 10px rgba(0,0,0,.05);}',
      '.sp-box.sel{border-color:#2f6f62;box-shadow:0 0 0 1px #2f6f62 inset;}',
      // Checkbox pinned to the top-right corner of each box.
      '.sp-check{position:absolute;top:12px;right:12px;width:17px;height:17px;margin:0;',
      '  cursor:pointer;accent-color:#2f6f62;}',
      '.sp-top{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;}',
      '.sp-name{font-size:13.5px;font-weight:600;color:var(--fg-1,#16191c);}',
      '.sp-sub{font-size:11.5px;color:var(--fg-2,#48525c);}',
      '.sp-desc{font-size:11.5px;line-height:1.55;color:var(--fg-3,#68727d);margin-top:6px;}',
      '.sp-badge{font-size:9px;letter-spacing:.05em;font-weight:700;padding:2px 7px;border-radius:20px;',
      '  background:var(--bg-base,#f2f4f5);color:var(--fg-3,#68727d);text-transform:uppercase;}',
      '.sp-badge.live{background:#e6f1ee;color:#2f6f62;}',
      '.sp-badge.paused{background:#fbeceb;color:#b3392c;}',
      '.sp-rule{font-family:var(--font-mono,monospace);font-size:11px;color:var(--fg-2,#48525c);',
      '  background:var(--bg-base,#f7f8f9);padding:5px 9px;border-radius:7px;display:block;',
      '  margin-top:8px;overflow-wrap:anywhere;}',
      '.sp-empty{grid-column:1/-1;padding:18px 2px;font-size:12px;color:var(--fg-3,#68727d);}'
    ].join('\n');
    document.head.appendChild(s);
  }

  function chevron() {
    var span = document.createElement('span');
    span.className = 'sp-chev';
    span.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"'
      + ' stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">'
      + '<path d="M9 6l6 6-6 6"/></svg>';
    return span;
  }

  // ── selection ──────────────────────────────────────────────────────────────
  // Selected ids are kept per group so a selection survives collapse/expand and
  // page reloads; window.getSelectedStrategies() exposes them for bulk actions.

  function selKey(g) { return 'sel_' + g; }

  function readSel(g) {
    try { return JSON.parse(localStorage.getItem(LS_KEY + ':' + selKey(g)) || '[]'); }
    catch (e) { return []; }
  }
  function writeSel(g, ids) {
    try { localStorage.setItem(LS_KEY + ':' + selKey(g), JSON.stringify(ids)); }
    catch (e) { /* private mode */ }
  }

  function updateSelCount(groupKey, secId) {
    var sec = document.getElementById(secId);
    if (!sec) return;
    var left = sec.querySelector('.tile-section-head .left');
    if (!left) return;
    var n = readSel(groupKey).length;
    var chip = left.querySelector('.sp-selcount');
    if (!n) { if (chip) chip.remove(); return; }
    if (!chip) {
      chip = document.createElement('span');
      chip.className = 'sp-selcount';
      left.appendChild(chip);
    }
    chip.textContent = n + ' selected';
  }

  function itemHTML(o, groupKey) {
    var sel = readSel(groupKey).indexOf(o.id) >= 0;
    return '<div class="sp-box' + (sel ? ' sel' : '') + '" data-sp-id="' + esc(o.id) + '">'
      + '<input class="sp-check" type="checkbox" ' + (sel ? 'checked ' : '')
      + 'data-sp-group="' + esc(groupKey) + '" data-sp-pick="' + esc(o.id) + '"'
      + ' aria-label="Select ' + esc(o.name) + '">'
      + '<div class="sp-top">'
      + '<span class="sp-name">' + esc(o.name) + '</span>'
      + (o.badge ? '<span class="sp-badge ' + esc(o.badgeCls || '') + '">' + esc(o.badge) + '</span>' : '')
      + '</div>'
      + (o.sub ? '<div class="sp-sub">' + esc(o.sub) + '</div>' : '')
      + (o.desc ? '<div class="sp-desc">' + esc(o.desc) + '</div>' : '')
      + (o.rule ? '<div class="sp-rule">' + esc(o.rule) + '</div>' : '')
      + '</div>';
  }

  function wireChecks(listEl, groupKey, secId) {
    listEl.querySelectorAll('.sp-check').forEach(function (cb) {
      cb.addEventListener('click', function (e) { e.stopPropagation(); });
      cb.addEventListener('change', function () {
        var ids = readSel(groupKey);
        var id = cb.dataset.spPick;
        var i = ids.indexOf(id);
        if (cb.checked && i < 0) ids.push(id);
        if (!cb.checked && i >= 0) ids.splice(i, 1);
        writeSel(groupKey, ids);
        var box = cb.closest('.sp-box');
        if (box) box.classList.toggle('sel', cb.checked);
        updateSelCount(groupKey, secId);
      });
    });
    updateSelCount(groupKey, secId);
  }

  function fillBuiltin(g) {
    var list = document.querySelector('#' + g.sec + ' .sp-list');
    if (!list) return;
    var all = window.STRATEGIES || [];
    var rows = all.filter(function (s) { return s.kind === g.kind; });
    if (!rows.length) {
      list.innerHTML = '<div class="sp-empty">No strategies in this group.</div>';
      return;
    }
    list.innerHTML = rows.map(function (s) {
      return itemHTML({
        id: s.id,
        name: s.name,
        sub: s.sub,
        desc: s.desc,
        badge: s.running ? 'running' : (s.armed ? 'armed' : 'idle'),
        badgeCls: s.running ? 'live' : ''
      }, g.key);
    }).join('');
    wireChecks(list, g.key, g.sec);
  }

  function fillCustom() {
    var list = document.querySelector('#row-custom .sp-list');
    if (!list) return;
    fetch('/api/strategy/custom').then(function (r) { return r.json(); })
      .then(function (d) {
        var rows = d.strategies || [];
        if (!rows.length) {
          list.innerHTML = '<div class="sp-empty">'
            + 'No custom strategies yet &mdash; use <b>Add new strategy</b> to build one. '
            + 'Rules are evaluated by the signal engine on every bar close.</div>';
          return;
        }
        list.innerHTML = rows.map(function (s) {
          var scope = (s.symbols && s.symbols.length) ? s.symbols.join(', ') : 'all symbols';
          return itemHTML({
            id: s.id,
            name: s.name,
            sub: s.direction + ' · ' + scope,
            desc: 'Fires when ' + (String(s.match).toLowerCase() === 'any'
                    ? 'ANY of these conditions hold' : 'ALL of these conditions hold')
                  + ' on a closed bar.',
            rule: s.summary || '',
            badge: s.enabled ? 'live' : 'paused',
            badgeCls: s.enabled ? 'live' : 'paused'
          }, 'cust');
        }).join('');
        wireChecks(list, 'cust', 'row-custom');
      }).catch(function () {
        list.innerHTML = '<div class="sp-empty">Could not load custom strategies.</div>';
      });
  }

  function refresh(g) {
    if (g.kind === 'custom') fillCustom(); else fillBuiltin(g);
  }

  function setup() {
    injectCss();
    var st = readState();

    GROUPS.forEach(function (g) {
      var sec = document.getElementById(g.sec);
      if (!sec || sec.querySelector('.sp-chev')) return;
      var head = sec.querySelector('.tile-section-head');
      var left = head && head.querySelector('.left');
      if (!head || !left) return;

      // After the title text, not before it.
      left.appendChild(chevron());

      var list = document.createElement('div');
      list.className = 'sp-list';
      sec.appendChild(list);

      // Default open, so nothing appears to vanish for someone who has not
      // used the toggle before.
      var openNow = st[g.key] === undefined ? true : !!st[g.key];
      sec.classList.toggle('sp-open', openNow);
      head.setAttribute('role', 'button');
      head.setAttribute('tabindex', '0');
      head.setAttribute('aria-expanded', String(openNow));

      function toggle() {
        var nowOpen = !sec.classList.contains('sp-open');
        sec.classList.toggle('sp-open', nowOpen);
        head.setAttribute('aria-expanded', String(nowOpen));
        var s2 = readState();
        s2[g.key] = nowOpen;
        writeState(s2);
        if (nowOpen) refresh(g);
      }

      head.addEventListener('click', function (e) {
        // Let controls inside the header keep their own behaviour.
        if (e.target.closest('button, a, input, select')) return;
        toggle();
      });
      head.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); }
      });

      refresh(g);
    });

    // Saved strategies change from the builder; keep the custom pane honest.
    setInterval(fillCustom, 20000);
    window.refreshStrategyPanes = function () { GROUPS.forEach(refresh); };
    window.getSelectedStrategies = function () {
      return { intra: readSel('intra'), opt: readSel('opt'), cust: readSel('cust') };
    };
  }

  function boot() {
    // strategies-app.js populates window.STRATEGIES and the tiles; give it a
    // moment so the built-in lists are not rendered empty on a cold load.
    setTimeout(setup, 120);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else { boot(); }
})();
