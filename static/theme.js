/* Techultime — global theme switcher.
   - Applies the saved theme class to <body> on every page load.
   - On pages that include <div id="theme-picker-mount">, renders
     a small floating picker bottom-right for switching themes.
   Themes: default | olive | tidal | wheat | cedar | moss
*/
(function () {
  'use strict';

  const KEY = 'tuTheme';
  const THEMES = [
    { id: 'default', name: 'Calm Teal',     brand: '#3D6A60', bg: '#FAF7F1', accent: '#152B27' },
    { id: 'olive',   name: 'Olive Grove',   brand: '#6B7F4E', bg: '#F6F1E6', accent: '#C97A5D' },
    { id: 'tidal',   name: 'Tidal Dusk',    brand: '#4A6B7A', bg: '#F1F4F4', accent: '#C89B95' },
    { id: 'wheat',   name: 'Wheat & Indigo',brand: '#3F4D6B', bg: '#F4EFE2', accent: '#B8924A' },
    { id: 'cedar',   name: 'Cedar Bloom',   brand: '#8A5A4A', bg: '#F6ECE2', accent: '#6B4860' },
    { id: 'moss',    name: 'Moss & Linen',  brand: '#3F5141', bg: '#EFEBE0', accent: '#C9A14A' },
  ];

  function applyTheme(id) {
    const body = document.body;
    if (!body) return;
    // Strip all theme-* classes
    body.className = body.className.split(/\s+/).filter(c => !c.startsWith('theme-')).join(' ');
    if (id && id !== 'default') body.classList.add('theme-' + id);
  }

  function getSaved() {
    try { return localStorage.getItem(KEY) || 'default'; } catch (e) { return 'default'; }
  }
  function save(id) {
    try { localStorage.setItem(KEY, id); } catch (e) {}
  }

  // ── Apply on load (before paint if possible) ────────────────────
  function init() { applyTheme(getSaved()); mountPicker(); }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // ── Picker UI (only renders if mount point exists) ──────────────
  function mountPicker() {
    const mount = document.getElementById('theme-picker-mount');
    if (!mount) return;

    const current = getSaved();
    const trigger = document.createElement('button');
    trigger.className = 'theme-trigger';
    trigger.type = 'button';
    trigger.setAttribute('aria-label', 'Brand theme');
    trigger.innerHTML =
      '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">' +
        '<circle cx="12" cy="12" r="9"/>' +
        '<path d="M12 3a9 9 0 0 0 0 18M3 12h18M12 3c2 3 3 6 3 9s-1 6-3 9M12 3c-2 3-3 6-3 9s1 6 3 9"/>' +
      '</svg>' +
      '<span class="theme-trigger-label">' + currentName(current) + '</span>';
    mount.appendChild(trigger);

    const panel = document.createElement('div');
    panel.className = 'theme-panel';
    panel.innerHTML =
      '<div class="theme-panel-head">' +
        '<span class="theme-panel-title">Brand theme</span>' +
        '<button class="theme-panel-close" type="button" aria-label="Close">' +
          '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>' +
        '</button>' +
      '</div>' +
      '<div class="theme-panel-grid">' +
        THEMES.map(t => themeCardHtml(t, t.id === current)).join('') +
      '</div>' +
      '<div class="theme-panel-foot">Saved across pages.</div>';
    mount.appendChild(panel);

    function open() { panel.classList.add('show'); }
    function close() { panel.classList.remove('show'); }
    function toggle() { panel.classList.toggle('show'); }

    trigger.addEventListener('click', toggle);
    panel.querySelector('.theme-panel-close').addEventListener('click', close);
    document.addEventListener('click', (e) => {
      if (!panel.classList.contains('show')) return;
      if (mount.contains(e.target)) return;
      close();
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') close();
    });

    panel.addEventListener('click', (e) => {
      const card = e.target.closest('.theme-card');
      if (!card) return;
      const id = card.dataset.theme;
      save(id);
      applyTheme(id);
      panel.querySelectorAll('.theme-card').forEach(c => c.classList.toggle('on', c.dataset.theme === id));
      trigger.querySelector('.theme-trigger-label').textContent = currentName(id);
    });
  }

  function themeCardHtml(t, on) {
    return (
      '<button type="button" class="theme-card' + (on ? ' on' : '') + '" data-theme="' + t.id + '">' +
        '<span class="theme-card-swatches">' +
          '<span class="sw" style="background:' + t.brand  + ';"></span>' +
          '<span class="sw" style="background:' + t.bg     + ';"></span>' +
          '<span class="sw" style="background:' + t.accent + ';"></span>' +
        '</span>' +
        '<span class="theme-card-name">' + t.name + '</span>' +
      '</button>'
    );
  }

  function currentName(id) {
    const t = THEMES.find(x => x.id === id);
    return t ? t.name : 'Calm Teal';
  }

  // Inject picker CSS once
  if (!document.getElementById('theme-picker-style')) {
    const s = document.createElement('style');
    s.id = 'theme-picker-style';
    s.textContent = `
      #theme-picker-mount {
        position: fixed; right: 20px; bottom: 20px; z-index: 200;
      }
      .theme-trigger {
        display: inline-flex; align-items: center; gap: 8px;
        font-family: var(--font-sans, sans-serif);
        font-size: 12px; font-weight: 500;
        padding: 8px 12px;
        background: var(--bg-surface, #fff);
        border: 1px solid var(--border-2, rgba(0,0,0,0.14));
        border-radius: 999px;
        color: var(--fg-2, #4A4538);
        box-shadow: var(--shadow-2, 0 2px 6px rgba(0,0,0,0.06));
        cursor: pointer;
        transition: background 200ms, color 200ms, transform 120ms;
      }
      .theme-trigger:hover { color: var(--fg-1, #14130E); transform: translateY(-1px); }
      .theme-trigger-label { letter-spacing: 0.02em; }
      .theme-panel {
        position: absolute; right: 0; bottom: 48px;
        width: 280px;
        background: var(--bg-surface, #fff);
        border: 1px solid var(--border-2, rgba(0,0,0,0.14));
        border-radius: 12px;
        box-shadow: var(--shadow-3, 0 12px 32px rgba(0,0,0,0.12));
        padding: 14px;
        display: none;
        animation: theme-up 180ms cubic-bezier(0.22,0.61,0.36,1);
      }
      .theme-panel.show { display: block; }
      @keyframes theme-up { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
      .theme-panel-head {
        display: flex; justify-content: space-between; align-items: center;
        margin-bottom: 10px;
      }
      .theme-panel-title {
        font-family: var(--font-sans, sans-serif);
        font-size: 12px; font-weight: 600;
        letter-spacing: 0.04em; text-transform: uppercase;
        color: var(--fg-3, #6E6859);
      }
      .theme-panel-close {
        width: 22px; height: 22px;
        border: 0; background: transparent;
        color: var(--fg-3, #6E6859);
        cursor: pointer; border-radius: 4px;
        display: inline-flex; align-items: center; justify-content: center;
      }
      .theme-panel-close:hover { background: var(--bg-sunken, #F3EDE0); color: var(--fg-1, #14130E); }
      .theme-panel-grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 6px;
      }
      .theme-card {
        display: flex; flex-direction: column; gap: 8px;
        padding: 10px 10px 9px;
        background: transparent;
        border: 1.5px solid transparent;
        border-radius: 8px;
        cursor: pointer;
        font-family: var(--font-sans, sans-serif);
        text-align: left;
        transition: background 150ms, border-color 150ms;
      }
      .theme-card:hover { background: var(--bg-sunken, #F3EDE0); }
      .theme-card.on {
        border-color: var(--tu-teal-400, #588479);
        background: var(--bg-sunken, #F3EDE0);
      }
      .theme-card-swatches { display: flex; gap: 0; }
      .theme-card-swatches .sw {
        width: 22px; height: 22px;
        border-radius: 50%;
        border: 1px solid rgba(0,0,0,0.08);
      }
      .theme-card-swatches .sw + .sw { margin-left: -8px; }
      .theme-card-name {
        font-size: 11.5px; font-weight: 500;
        color: var(--fg-1, #14130E);
        letter-spacing: -0.005em;
      }
      .theme-panel-foot {
        margin-top: 10px;
        font-size: 10.5px; color: var(--fg-3, #6E6859);
        text-align: center;
        font-family: var(--font-sans, sans-serif);
        letter-spacing: 0.02em;
      }
    `;
    document.head.appendChild(s);
  }
})();
