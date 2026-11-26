// chat-widget.js — floating "Ask" panel that talks to POST /api/chat.
// The page keeps the conversation (sessionStorage); each request sends the
// question plus the recent turns, and the server attaches a fresh snapshot of
// the app's state. Read-only: the bot explains, it never trades.
(function () {
  'use strict';
  if (document.getElementById('desk-chat')) return;

  var STORE_KEY = 'deskChatHistory';
  var MAX_TURNS = 20;
  var QUICK = [
    'What is my position right now?',
    'How is the algo doing today?',
    'Is live trading armed?',
    'What is the paper P&L overall?'
  ];

  var css = '' +
    '#desk-chat{position:fixed;right:18px;bottom:18px;z-index:9000;font-family:var(--font-sans,system-ui,sans-serif);}' +
    '#desk-chat .dc-fab{display:flex;align-items:center;gap:8px;padding:10px 14px;border-radius:999px;border:1px solid var(--border-2,#ccc);' +
      'background:var(--bg-brand,#3D6A60);color:var(--fg-on-brand,#fff);font-size:13px;font-weight:600;cursor:pointer;box-shadow:var(--shadow-2,0 4px 14px rgba(0,0,0,.18));}' +
    '#desk-chat .dc-fab:hover{filter:brightness(1.08);}' +
    '#desk-chat .dc-panel{display:none;flex-direction:column;width:min(400px,calc(100vw - 32px));height:min(560px,calc(100vh - 100px));' +
      'background:var(--bg-surface,#fff);color:var(--fg-1,#111);border:1px solid var(--border-2,#ccc);border-radius:var(--r-lg,14px);' +
      'box-shadow:var(--shadow-2,0 10px 30px rgba(0,0,0,.2));overflow:hidden;}' +
    '#desk-chat.open .dc-panel{display:flex;}#desk-chat.open .dc-fab{display:none;}' +
    '#desk-chat .dc-head{display:flex;align-items:center;justify-content:space-between;padding:10px 12px 10px 14px;border-bottom:1px solid var(--border-1,#eee);background:var(--bg-sunken,#f5f5f5);}' +
    '#desk-chat .dc-title{font-size:13px;font-weight:600;}#desk-chat .dc-sub{font-size:11px;color:var(--fg-3,#777);margin-top:1px;}' +
    '#desk-chat .dc-x,#desk-chat .dc-clear{border:0;background:transparent;color:var(--fg-3,#777);cursor:pointer;font-size:12px;padding:4px 6px;border-radius:6px;}' +
    '#desk-chat .dc-x:hover,#desk-chat .dc-clear:hover{background:var(--bg-muted,#eee);color:var(--fg-1,#111);}' +
    '#desk-chat .dc-log{flex:1;overflow-y:auto;padding:12px;display:flex;flex-direction:column;gap:10px;font-size:13px;line-height:1.45;}' +
    '#desk-chat .dc-msg{max-width:92%;padding:8px 11px;border-radius:12px;white-space:pre-wrap;word-wrap:break-word;}' +
    '#desk-chat .dc-msg.user{align-self:flex-end;background:var(--bg-brand,#3D6A60);color:var(--fg-on-brand,#fff);border-bottom-right-radius:4px;}' +
    '#desk-chat .dc-msg.bot{align-self:flex-start;background:var(--bg-sunken,#f3f3f3);border-bottom-left-radius:4px;}' +
    '#desk-chat .dc-msg.err{align-self:stretch;background:transparent;color:var(--tu-danger,#B66A5A);border:1px dashed var(--tu-danger,#B66A5A);font-size:12px;}' +
    '#desk-chat .dc-msg.wait{color:var(--fg-3,#777);font-style:italic;}' +
    '#desk-chat .dc-quick{display:flex;flex-wrap:wrap;gap:6px;padding:0 12px 8px;}' +
    '#desk-chat .dc-quick button{font-size:11px;padding:4px 9px;border-radius:999px;border:1px solid var(--border-2,#ccc);background:var(--bg-surface,#fff);color:var(--fg-2,#444);cursor:pointer;}' +
    '#desk-chat .dc-quick button:hover{background:var(--bg-sunken,#f3f3f3);}' +
    '#desk-chat form{display:flex;gap:8px;padding:10px 12px;border-top:1px solid var(--border-1,#eee);}' +
    '#desk-chat textarea{flex:1;resize:none;height:38px;max-height:120px;padding:8px 10px;font:inherit;font-size:13px;border:1px solid var(--border-3,#bbb);border-radius:10px;background:var(--bg-surface,#fff);color:var(--fg-1,#111);outline:none;}' +
    '#desk-chat textarea:focus{border-color:var(--border-brand,#3D6A60);}' +
    '#desk-chat .dc-send{padding:0 14px;border-radius:10px;border:0;background:var(--bg-brand,#3D6A60);color:var(--fg-on-brand,#fff);font-weight:600;cursor:pointer;}' +
    '#desk-chat .dc-send:disabled{opacity:.5;cursor:default;}';
  var style = document.createElement('style'); style.textContent = css; document.head.appendChild(style);

  var root = document.createElement('div'); root.id = 'desk-chat';
  root.innerHTML =
    '<button class="dc-fab" type="button" title="Ask about the current position">' +
      '<span>&#9679;</span><span>Ask</span></button>' +
    '<div class="dc-panel" role="dialog" aria-label="Desk assistant">' +
      '<div class="dc-head"><div><div class="dc-title">Desk assistant</div><div class="dc-sub">Read-only. Answers from the live app state.</div></div>' +
        '<div><button class="dc-clear" type="button" title="Clear conversation">clear</button>' +
        '<button class="dc-x" type="button" title="Close">&#10005;</button></div></div>' +
      '<div class="dc-log"></div>' +
      '<div class="dc-quick"></div>' +
      '<form><textarea placeholder="Ask about positions, P&amp;L, the algo, live arming…" rows="1"></textarea>' +
        '<button class="dc-send" type="submit">Send</button></form>' +
    '</div>';
  document.body.appendChild(root);

  var panelLog = root.querySelector('.dc-log'), form = root.querySelector('form'),
      input = root.querySelector('textarea'), sendBtn = root.querySelector('.dc-send'),
      sub = root.querySelector('.dc-sub'), quick = root.querySelector('.dc-quick');

  var history = [];
  try { history = JSON.parse(sessionStorage.getItem(STORE_KEY) || '[]'); if (!Array.isArray(history)) history = []; } catch (e) { history = []; }

  function save() { try { sessionStorage.setItem(STORE_KEY, JSON.stringify(history.slice(-MAX_TURNS))); } catch (e) {} }
  function bubble(cls, text) {
    var d = document.createElement('div'); d.className = 'dc-msg ' + cls; d.textContent = text;
    panelLog.appendChild(d); panelLog.scrollTop = panelLog.scrollHeight; return d;
  }
  function render() {
    panelLog.innerHTML = '';
    if (!history.length) bubble('bot', 'Ask me what is open, how the day is going, or whether live trading is armed. I answer from the app’s current state and never place orders.');
    history.forEach(function (m) { bubble(m.role === 'user' ? 'user' : 'bot', m.content); });
  }
  QUICK.forEach(function (q) {
    var b = document.createElement('button'); b.type = 'button'; b.textContent = q;
    b.addEventListener('click', function () { input.value = q; form.requestSubmit ? form.requestSubmit() : send(); });
    quick.appendChild(b);
  });

  var busy = false;
  function send() {
    var q = input.value.trim();
    if (!q || busy) return;
    busy = true; sendBtn.disabled = true; input.value = '';
    history.push({ role: 'user', content: q }); save(); bubble('user', q);
    var wait = bubble('bot wait', 'thinking…');
    fetch('/api/chat', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: q, history: history.slice(0, -1).slice(-MAX_TURNS) })
    }).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, status: r.status, body: j }; }); })
      .then(function (res) {
        wait.remove();
        if (!res.ok) {
          var msg = (res.body && (res.body.detail || res.body.error)) || ('HTTP ' + res.status);
          bubble('err', String(msg));
          history.pop(); save();           // keep the failed question out of the context
          return;
        }
        var a = (res.body && res.body.answer) || '(no answer)';
        history.push({ role: 'assistant', content: a }); save(); bubble('bot', a);
        if (res.body && res.body.model) sub.textContent = 'Read-only. ' + res.body.model;
      })
      .catch(function (e) { wait.remove(); bubble('err', 'Request failed: ' + e); history.pop(); save(); })
      .then(function () { busy = false; sendBtn.disabled = false; input.focus(); });
  }

  form.addEventListener('submit', function (e) { e.preventDefault(); send(); });
  input.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
  });
  root.querySelector('.dc-fab').addEventListener('click', function () {
    root.classList.add('open'); render(); input.focus();
    fetch('/api/chat/status').then(function (r) { return r.json(); }).then(function (s) {
      if (s && s.available === false) bubble('err', 'Chat is not configured: add ANTHROPIC_API_KEY to .env and restart the app.');
      else if (s && s.model) sub.textContent = 'Read-only. ' + s.model;
    }).catch(function () {});
  });
  root.querySelector('.dc-x').addEventListener('click', function () { root.classList.remove('open'); });
  root.querySelector('.dc-clear').addEventListener('click', function () { history = []; save(); render(); });
})();
