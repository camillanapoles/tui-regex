// ==UserScript==
// @name         Modo Noturno Universal
// @namespace    https://github.com/camillanapoles/tui-regex
// @version      1.0.0
// @description  Escurece qualquer site com inversão inteligente (fotos e vídeos preservados). Preferência salva por site.
// @author       camillanapoles
// @license      MIT
// @match        http://*/*
// @match        https://*/*
// @noframes
// @run-at       document-start
// @grant        none
// ==/UserScript==

(function () {
  'use strict';
  if (window.__MN__) return;
  window.__MN__ = true;

  const KEY = 'modo-noturno:' + location.hostname;

  const styleEl = document.createElement('style');
  styleEl.textContent = `
    html { filter: invert(1) hue-rotate(180deg) !important; background: #fff !important; }
    img, video, canvas, svg image, [style*="background-image"], iframe {
      filter: invert(1) hue-rotate(180deg) !important;
    }
  `;

  const btn = document.createElement('button');
  btn.type = 'button';
  btn.textContent = '🌙';
  btn.setAttribute('aria-label', 'Alternar modo noturno');
  btn.style.cssText = [
    'position:fixed', 'left:12px', 'bottom:calc(72px + env(safe-area-inset-bottom,0px))',
    'width:48px', 'height:48px', 'border-radius:14px', 'border:1px solid rgba(0,0,0,.12)',
    'background:#fff', 'color:#17212f', 'font-size:22px', 'z-index:2147483600',
    'box-shadow:0 4px 16px rgba(0,0,0,.18)', 'cursor:pointer', 'touch-action:manipulation',
    'transition:opacity .3s'
  ].join(';');

  function apply(on) {
    if (on && !styleEl.isConnected) (document.head || document.documentElement).appendChild(styleEl);
    if (!on && styleEl.isConnected) styleEl.remove();
    btn.style.opacity = on ? '1' : '.55';
    btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    try { localStorage.setItem(KEY, on ? '1' : '0'); } catch (e) { /* sem storage */ }
  }

  let on = false;
  try { on = localStorage.getItem(KEY) === '1'; } catch (e) { /* noop */ }
  btn.addEventListener('click', () => { on = !on; apply(on); });

  const mount = () => (document.body || document.documentElement).appendChild(btn);
  if (document.body) mount();
  else document.addEventListener('DOMContentLoaded', mount, { once: true });
  apply(on);
})();
