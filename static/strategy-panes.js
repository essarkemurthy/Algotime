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
      '.sp-chev{display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;',
      '  margin-right:8px;border-radius:6px;color:var(--fg-3,#68727d);flex:none;',
      '  transition:transform .18s ease;}',
      '.sp-chev svg{width:14px;height:14px;}',
      '.tile-section.sp-open .sp-chev{transform:rotate(90deg);}',
      '.tile-section .tile-row,.tile-section .sp-list{display:none;}',
            // .tile-row is a 5-column grid; restore grid, not flex, or the tiles
      // reflow into a single row when the pane is opened.
      '.tile-section.sp-open .tile-row{display:grid;}',
      '.tile-section.sp-open .sp-list{display:block;}',
      '.sp-list{margin-top:14px;border-top:1px solid var(--border-1,#eef1f3);}',
      '.sp-item{padding:13px 2px;border-bottom:1px solid var(--border-1,#eef1f3);}',
      '.sp-item:last-child{border-bottom:none;}',
      '.sp-top{display:flex;align-items:baseline;gap:9px;flex-wrap:wrap;}',
      '.sp-name{font-size:13.5px;font-weight:600;color:var(--fg-1,#16191c);}',
      '.sp-sub{font-size:12px;color:var(--fg-2,#48525c);}',
      '.sp-desc{font-size:12px;line-height:1.6;color:var(--fg-3,#68727d);margin-top:5px;max-width:78ch;}',
      '.sp-badge{font-size:9.5px;letter-spacing:.05em;font-weight:700;padding:2px 7px;border-radius:20px;',
      '  background:var(--bg-base,#f2f4f5);color:var(--fg-3,#68727d);text-transform:uppercase;}',
      '.sp-badge.live{background:#e6f1ee;color:#2f6f62;}',
      '.sp-badge.paused{background:#fbeceb;color:#b3392c;}',
      '.sp-rule{font-family:var(--font-mono,monospace);font-size:11.5px;color:var(--fg-2,#48525c);',
      '  background:var(--bg-base,#f7f8f9);padding:5px 9px;border-radius:6px;display:inline-block;margin-top:6px;}',
      '.sp-empty{padding:18px 2px;font-size:12px;color:var(--fg-3,#68727d);}'
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

  function itemHTML(o) {
    return '<div class="sp-item">'
      + '<div class="sp-top">'
      + '<span class="sp-name">' + esc(o.name) + '</span>'
      + (o.sub ? '<span class="sp-sub">' + esc(o.sub) + '</span>' : '')
      + (o.badge ? '<span class="sp-badge ' + esc(o.badgeCls || '') + '">' + esc(o.badge) + '</span>' : '')
      + '</div>'
      + (o.desc ? '<div class="sp-desc">' + esc(o.desc) + '</div>' : '')
      + (o.rule ? '<div class="sp-rule">' + esc(o.rule) + '</div>' : '')
      + '</div>';
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
        name: s.name,
        sub: s.sub,
        desc: s.desc,
        badge: s.running ? 'running' : (s.armed ? 'armed' : 'idle'),
        badgeCls: s.running ? 'live' : ''
      });
    }).join('');
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
            name: s.name,
            sub: s.direction + ' · ' + scope,
            desc: 'Fires when ' + (String(s.match).toLowerCase() === 'any'
                    ? 'ANY of these conditions hold' : 'ALL of these conditions hold')
                  + ' on a closed bar.',
            rule: s.summary || '',
            badge: s.enabled ? 'live' : 'paused',
            badgeCls: s.enabled ? 'live' : 'paused'
          });
        }).join('');
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

      left.insertBefore(chevron(), left.firstChild);

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
