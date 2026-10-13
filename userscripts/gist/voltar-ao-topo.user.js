// ==UserScript==
// @name         Voltar ao Topo
// @namespace    https://github.com/camillanapoles/tui-regex
// @version      1.0.0
// @description  Botão discreto que aparece depois de rolar a página e volta ao topo. Respeita "prefers-reduced-motion".
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
  if (window.__VTT__) return;
  window.__VTT__ = true;

  const btn = document.createElement('button');
  btn.type = 'button';
  btn.textContent = '⬆';
  btn.setAttribute('aria-label', 'Voltar ao topo da página');
  btn.style.cssText = [
    'position:fixed', 'right:12px', 'bottom:calc(76px + env(safe-area-inset-bottom,0px))',
    'width:48px', 'height:48px', 'border-radius:50%',
    'background:#17212f', 'color:#fff', 'font-size:20px', 'z-index:2147483600',
    'box-shadow:0 4px 16px rgba(0,0,0,.25)', 'cursor:pointer', 'touch-action:manipulation',
    'opacity:0', 'pointer-events:none', 'transition:opacity .25s, transform .25s',
    'transform:translateY(8px)'
  ].join(';');

  let visible = false;
  function update() {
    const show = window.scrollY > 600;
    if (show === visible) return;
    visible = show;
    btn.style.opacity = show ? '1' : '0';
    btn.style.pointerEvents = show ? 'auto' : 'none';
    btn.style.transform = show ? 'none' : 'translateY(8px)';
    btn.setAttribute('aria-hidden', show ? 'false' : 'true');
    btn.tabIndex = show ? 0 : -1;
  }

  const reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  btn.addEventListener('click', () => {
    window.scrollTo({ top: 0, behavior: reduced ? 'auto' : 'smooth' });
  });

  let ticking = false;
  window.addEventListener('scroll', () => {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(() => { update(); ticking = false; });
  }, { passive: true });

  (document.body || document.documentElement).appendChild(btn);
  update();
})();
