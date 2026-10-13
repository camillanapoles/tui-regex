// ==UserScript==
// @name         Leitor Conforto
// @namespace    https://github.com/camillanapoles/tui-regex
// @version      1.0.0
// @description  Leitura confortável com um toque: fonte maior, entrelinha generosa e largura de coluna ideal. Preferência salva por site.
// @author       camillanapoles
// @license      MIT
// @match        http://*/*
// @match        https://*/*
// @noframes
// @run-at       document-idle
// @grant        none
// ==/UserScript==

(function () {
  'use strict';
  if (window.__LC__) return;
  window.__LC__ = true;

  const KEY = 'leitor-conforto:' + location.hostname;
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.textContent = '📖';
  btn.setAttribute('aria-label', 'Alternar leitura confortável');
  btn.style.cssText = [
    'position:fixed', 'left:12px', 'bottom:calc(12px + env(safe-area-inset-bottom,0px))',
    'width:48px', 'height:48px', 'border-radius:14px', 'border:1px solid rgba(0,0,0,.12)',
    'background:#fff', 'color:#17212f', 'font-size:22px', 'z-index:2147483600',
    'box-shadow:0 4px 16px rgba(0,0,0,.18)', 'cursor:pointer', 'touch-action:manipulation',
    'transition:opacity .3s'
  ].join(';');

  const styleEl = document.createElement('style');
  styleEl.textContent = `
    article, main, .post, .article, .content, .entry-content, [role="main"] {
      font-size: 18px !important;
      line-height: 1.75 !important;
    }
    article p, main p, .post p, .article p, .content p, .entry-content p, [role="main"] p {
      max-width: 66ch !important;
      margin-left: auto !important;
      margin-right: auto !important;
      text-align: left !important;
    }
  `;

  function apply(on) {
    if (on && !styleEl.isConnected) document.head.appendChild(styleEl);
    if (!on && styleEl.isConnected) styleEl.remove();
    btn.style.opacity = on ? '1' : '.55';
    btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    try { localStorage.setItem(KEY, on ? '1' : '0'); } catch (e) { /* sem storage */ }
  }

  let on = false;
  try { on = localStorage.getItem(KEY) === '1'; } catch (e) { /* noop */ }
  btn.addEventListener('click', () => { on = !on; apply(on); });

  (document.body || document.documentElement).appendChild(btn);
  apply(on);
})();
