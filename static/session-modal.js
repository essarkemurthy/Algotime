/* static/session-modal.js
 *
 * Breeze session tokens expire every midnight. Without this the app simply comes
 * up disconnected - live prices, signals and the paper algo all silently stop,
 * with nothing on screen explaining why.
 *
 * Watches /api/setup/status and, when the broker session is down, raises a modal
 * asking ONLY for the session token: the api key and secret are pre-filled from
 * whatever is already stored (.env, falling back to data/setup.json), so there
 * is nothing to re-enter.
 *
 * Saving posts to /api/setup/broker/save, which reconnects the session in
 * process and mirrors the credentials back to .env - no restart needed.
 */
(function () {
  'use strict';
  if (window.__sessionModalLoaded) return;
  window.__sessionModalLoaded = true;

  var POLL_MS = 15000;
  var SNOOZE_MS = 600000;           // "Later" stays quiet for 10 minutes
  var creds = { api_key: '', api_secret: '' };
  var open = false;
  var dismissedAt = 0;

  var CSS = [
    '.sess-ov{position:fixed;inset:0;background:rgba(15,18,20,.55);z-index:9998;',
    '  display:flex;align-items:center;justify-content:center;padding:20px;}',
    '.sess-card{background:var(--bg-surface,#fff);color:var(--fg-1,#16191c);',
    '  border:1px solid var(--border-2,#dfe3e6);border-radius:14px;',
    '  box-shadow:0 18px 50px rgba(0,0,0,.25);width:100%;max-width:460px;padding:22px 24px;}',
    '.sess-card h3{margin:0 0 6px;font-size:16px;font-weight:600;}',
    '.sess-card p{margin:0 0 16px;font-size:12.5px;line-height:1.55;color:var(--fg-3,#68727d);}',
    '.sess-row{margin-bottom:12px;}',
    '.sess-row label{display:block;font-size:10.5px;letter-spacing:.05em;',
    '  text-transform:uppercase;color:var(--fg-3,#68727d);margin-bottom:5px;font-weight:600;}',
    '.sess-row input{width:100%;box-sizing:border-box;padding:9px 11px;font-size:13px;',
    '  font-family:inherit;border:1px solid var(--border-2,#dfe3e6);border-radius:8px;',
    '  background:var(--bg-base,#fafafa);color:var(--fg-1,#16191c);}',
    '.sess-row input:focus{outline:none;border-color:#2f6f62;}',
    '.sess-hint{font-size:11px;color:var(--fg-3,#68727d);margin-top:4px;}',
    '.sess-actions{display:flex;gap:9px;justify-content:flex-end;margin-top:18px;}',
    '.sess-btn{padding:9px 15px;font-size:12.5px;font-weight:600;border-radius:8px;',
    '  cursor:pointer;border:1px solid var(--border-2,#dfe3e6);font-family:inherit;',
    '  background:var(--bg-base,#fafafa);color:var(--fg-1,#16191c);}',
    '.sess-btn.primary{background:#2f6f62;border-color:#2f6f62;color:#fff;}',
    '.sess-btn:disabled{opacity:.55;cursor:not-allowed;}',
    '.sess-msg{margin-top:12px;font-size:12px;min-height:16px;}',
    '.sess-msg.err{color:#b3392c;}',
    '.sess-msg.ok{color:#2f6f62;}',
    '.sess-msg.busy{color:var(--fg-3,#68727d);}',
    '.sess-link{color:#2f6f62;font-weight:600;}'
  ].join('\n');

  function injectCss() {
    if (document.getElementById('sess-modal-css')) return;
    var s = document.createElement('style');
    s.id = 'sess-modal-css';
    s.textContent = CSS;
    document.head.appendChild(s);
  }

  function close() {
    var ov = document.getElementById('sess-overlay');
    if (ov) ov.remove();
    open = false;
  }

  function msg(text, cls) {
    var m = document.getElementById('sess-msg');
    if (m) { m.textContent = text; m.className = 'sess-msg ' + (cls || ''); }
  }

  function show() {
    if (open || document.getElementById('sess-overlay')) return;
    injectCss();
    open = true;

    var ov = document.createElement('div');
    ov.className = 'sess-ov';
    ov.id = 'sess-overlay';
    ov.innerHTML = [
      '<div class="sess-card" role="dialog" aria-modal="true" aria-labelledby="sess-title">',
      '  <h3 id="sess-title">Broker session expired</h3>',
      '  <p>ICICI session tokens expire every 24 hours. Paste a fresh one to reconnect &mdash;',
      '     live prices, signals and the paper algo stay paused until you do.<br>',
      '     <a class="sess-link" href="https://api.icicidirect.com/apiuser/login"',
      '        target="_blank" rel="noopener">Open the ICICI login page &#8599;</a>',
      '     and copy the <code>apisession</code> value.</p>',
      '  <div class="sess-row"><label>API key</label>',
      '    <input id="sess-key" type="text" autocomplete="off" spellcheck="false"></div>',
      '  <div class="sess-row"><label>API secret</label>',
      '    <input id="sess-secret" type="password" autocomplete="off" spellcheck="false"></div>',
      '  <div class="sess-row"><label>Session token</label>',
      '    <input id="sess-token" type="text" autocomplete="off" spellcheck="false"',
      '           placeholder="paste apisession here">',
      '    <div class="sess-hint">Saved to .env and data/setup.json; reconnects without a restart.</div></div>',
      '  <div class="sess-msg" id="sess-msg"></div>',
      '  <div class="sess-actions">',
      '    <button class="sess-btn" id="sess-later" type="button">Later</button>',
      '    <button class="sess-btn primary" id="sess-save" type="button">Connect</button>',
      '  </div>',
      '</div>'
    ].join('');
    document.body.appendChild(ov);

    // Pre-fill whatever is already stored, so only the token needs typing.
    document.getElementById('sess-key').value = creds.api_key || '';
    document.getElementById('sess-secret').value = creds.api_secret || '';

    var tok = document.getElementById('sess-token');
    tok.focus();
    tok.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') submit();
    });

    document.getElementById('sess-later').addEventListener('click', function () {
      dismissedAt = Date.now();
      close();
    });
    document.getElementById('sess-save').addEventListener('click', submit);
  }

  function submit() {
    var key = (document.getElementById('sess-key').value || '').trim();
    var sec = (document.getElementById('sess-secret').value || '').trim();
    var tok = (document.getElementById('sess-token').value || '').trim();
    if (!key || !sec || !tok) {
      msg('All three fields are required.', 'err');
      return;
    }

    var btn = document.getElementById('sess-save');
    btn.disabled = true;
    msg('Validating with the broker...', 'busy');

    // Test before saving, so a bad token cannot tear down a working session.
    fetch('/api/setup/broker/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ api_key: key, api_secret: sec, session_token: tok })
    }).then(function (r) { return r.json(); }).then(function (t) {
      if (!t.ok) throw new Error(t.error || 'Token rejected by the broker');
      msg('Verified' + (t.name ? ' - ' + t.name : '') + '. Connecting...', 'busy');
      return fetch('/api/setup/broker/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type: 'icici', api_key: key, api_secret: sec, session_token: tok })
      }).then(function (r) { return r.json(); });
    }).then(function (s) {
      if (s.connected) {
        msg('Connected. Reloading...', 'ok');
        setTimeout(function () { location.reload(); }, 900);
      } else {
        throw new Error(s.error || 'Saved, but the session did not come up');
      }
    }).catch(function (e) {
      msg(String((e && e.message) || e), 'err');
      btn.disabled = false;
    });
  }

  function poll() {
    fetch('/api/setup/status').then(function (r) {
      return r.json();
    }).then(function (d) {
      // /api/setup/status nests the saved credentials under `broker`; it already
      // falls back to the .env values there, so this is the single source.
      var b = d.broker || {};
      if (b.api_key) creds.api_key = b.api_key;
      if (b.api_secret) creds.api_secret = b.api_secret;
      var down = !d.broker_ok;
      if (down && !open && Date.now() - dismissedAt > SNOOZE_MS) show();
      if (!down && open) close();
    }).catch(function () { /* transient - try again next tick */ });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', poll);
  } else {
    poll();
  }
  setInterval(poll, POLL_MS);
})();
