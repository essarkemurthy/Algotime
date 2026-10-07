/* static/watchlist-eq.js
 *
 * Populates the intraday watchlist (#watch-eq) from /api/watchlist/equity.
 *
 * The rows were hardcoded HTML: twelve instruments, two of them indices, and a
 * "5 watching" chip that never matched. Indices do not belong here - you cannot
 * buy a spot index in cash, so the paper engine skips them (index_no_cash) and
 * routes the optionable ones to the options engine instead. Every symbol served
 * here is already WebSocket-subscribed, so prices fill in immediately.
 *
 * Row shape matches the original exactly, because applyLtp() and the signal
 * updater both find rows via .watch-row[data-symbol="..."].
 */
(function () {
  'use strict';

  function esc(s) {
    return String(s === null || s === undefined ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function rowHTML(r) {
    var meta = esc(r.exchange || 'NSE') + ' · ' + esc(r.code || '');
    return '<div class="watch-row" data-symbol="' + esc(r.symbol) + '">'
      + '<span class="sym"><span class="ticker">' + esc(r.symbol) + '</span>'
      + '<span class="meta"><span class="tag-eq">EQ</span> ' + meta + '</span></span>'
      + '<span class="chg">—</span>'
      + '<span class="ltp">—</span>'
      + '<span class="prev">—</span>'
      + '<span class="signal-cell"><span class="signal flat">'
      + '<span class="blip"></span>No signal</span></span>'
      + '<button class="row-del" aria-label="Remove ' + esc(r.symbol) + '" type="button">'
      + '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg></button>'
      + '</div>';
  }

  function load() {
    var list = document.getElementById('watch-eq');
    if (!list) return;
    fetch('/api/watchlist/equity').then(function (r) { return r.json(); })
      .then(function (d) {
        var rows = d.rows || [];
        if (!rows.length) return;          // keep whatever is already there

        // Preserve the header row; replace only the instrument rows.
        var head = list.querySelector('.watch-row.head');
        list.innerHTML = (head ? head.outerHTML : '') + rows.map(rowHTML).join('');

        var chip = document.getElementById('eq-count');
        if (chip) chip.textContent = rows.length + ' watching';
        var title = list.closest('.card');
        title = title && title.querySelector('.card-head .card-title .count');
        if (title) title.textContent = rows.length + ' watching';

        // Seed from the LTP cache so the table is not blank until the next tick.
        fetch('/api/ltp').then(function (r) { return r.json(); }).then(function (ltp) {
          Object.keys(ltp || {}).forEach(function (sym) {
            if (typeof window.applyLtp === 'function') window.applyLtp(sym, ltp[sym]);
          });
        }).catch(function () { });
      }).catch(function () { /* leave the static rows in place */ });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', load);
  } else { load(); }
})();
