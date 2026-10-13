// ==UserScript==
// @name         USHub · botão central de userscripts (Android)
// @namespace    https://github.com/camillanapoles/tui-regex
// @version      1.1.0
// @description  Botão flutuante de máxima usabilidade que abre um hub/catálogo de userscripts gerenciado por um gist público: gestão via hub.json + múltiplos arquivos .user.js em um único local. Otimizado para Android (Firefox + Tampermonkey/Violentmonkey).
// @author       camillanapoles
// @license      MIT
// @match        http://*/*
// @match        https://*/*
// @noframes
// @run-at       document-idle
// @grant        GM.getValue
// @grant        GM.setValue
// @grant        GM.xmlHttpRequest
// @grant        GM.registerMenuCommand
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_xmlhttpRequest
// @grant        GM_registerMenuCommand
// @connect      api.github.com
// @connect      gist.githubusercontent.com
// @connect      raw.githubusercontent.com
// ==/UserScript==

/* ============================================================
 * USHub — um botão, todos os seus userscripts.
 *
 * Arquitetura:
 *  - FAB (botão flutuante) isolado em Shadow DOM → o CSS da página
 *    nunca quebra o botão/painel, e o nosso CSS nunca vaza.
 *  - Painel "bottom sheet" (padrão nativo Android) com scrim.
 *  - Catálogo = um gist público: hub.json (manifesto) aponta para
 *    vários arquivos .user.js hospedados no MESMO gist.
 *  - Instalação entrega a URL crua ao gerenciador (Tampermonkey etc.),
 *    que abre sua tela de instalação — captura real, em um único local.
 * ========================================================== */
(function () {
  'use strict';

  /* ---------- guarda contra injeção dupla (SPAs, turbo/pjax etc.) */
  if (window.__USHUB_V1__) return;
  window.__USHUB_V1__ = true;

  const VERSION = '1.1.0';
  const LS_KEY = 'ushub:state:v1';
  const CAT_CACHE_MAX_AGE = 15 * 60 * 1000; // 15 min de cache do catálogo
  const PLACEHOLDER_URL = 'https://gist.github.com/SEU_USUARIO/SEU_GIST_ID';
  /* Catálogo de fábrica: o próprio repositório público (raw). Funciona sem gist;
     para distribuir o SEU catálogo, aponte outra fonte nos Ajustes. */
  const DEFAULT_SOURCE = 'https://raw.githubusercontent.com/camillanapoles/tui-regex/main/userscripts/gist/hub.json';

  /* ============================================================
   * 1. STORAGE — GM_* com fallback para localStorage
   * ========================================================== */
  async function kvGet(key, fallback) {
    try {
      if (typeof GM_getValue === 'function') {
        const v = await GM_getValue(key, undefined);
        if (v !== undefined) return v;
      } else if (typeof GM !== 'undefined' && GM && typeof GM.getValue === 'function') {
        const v = await GM.getValue(key, undefined);
        if (v !== undefined) return v;
      }
    } catch (e) { /* cai para o fallback */ }
    try {
      const raw = localStorage.getItem(key);
      return raw == null ? fallback : JSON.parse(raw);
    } catch (e) {
      return fallback;
    }
  }

  async function kvSet(key, value) {
    try {
      if (typeof GM_setValue === 'function') { await GM_setValue(key, value); return; }
      if (typeof GM !== 'undefined' && GM && typeof GM.setValue === 'function') { await GM.setValue(key, value); return; }
    } catch (e) { /* cai para o fallback */ }
    try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* sem storage */ }
  }

  const defaultState = () => ({
    manifestUrl: '',
    ui: {
      theme: 'auto',          // 'auto' | 'light' | 'dark'
      fontScale: 1,           // 0.85 – 1.40
      tab: 'catalogo',        // 'catalogo' | 'config'
      autoRefresh: true,
      fab: { edge: 'right', yRatio: 0.72 }, // posição ajustável
      fabHidden: false
    },
    installed: {},            // { [id]: { version, at } } — registro local do aparelho
    cache: null               // { url, fetchedAt, data } — catálogo offline
  });

  let state = defaultState();
  let saveTimer = null;
  function save() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => kvSet(LS_KEY, state), 250);
  }

  /* ============================================================
   * 2. REDE — GM_xmlhttpRequest (ignora CSP/CORS da página)
   * ========================================================== */
  function httpGet(url, headers) {
    return new Promise((resolve, reject) => {
      let gmx = null;
      try {
        if (typeof GM_xmlhttpRequest === 'function') gmx = GM_xmlhttpRequest;
        else if (typeof GM !== 'undefined' && GM && typeof GM.xmlHttpRequest === 'function') gmx = GM.xmlHttpRequest.bind(GM);
      } catch (e) { /* noop */ }
      if (!gmx) { reject(new Error('Requisições entre sites não disponíveis neste gerenciador.')); return; }
      try {
        gmx({
          method: 'GET',
          url,
          headers: headers || {},
          timeout: 20000,
          onload: (r) => (r.status >= 200 && r.status < 300)
            ? resolve(r.responseText)
            : reject(new Error('HTTP ' + r.status)),
          onerror: () => reject(new Error('Falha de rede')),
          ontimeout: () => reject(new Error('Tempo esgotado'))
        });
      } catch (e) { reject(e); }
    });
  }

  const bust = (u) => u + (u.indexOf('?') >= 0 ? '&' : '?') + '_ushub=' + Date.now();

  /* Extrai o ID do gist de várias formas de URL (página do gist, raw, ou o próprio ID) */
  function parseGistId(input) {
    if (!input) return null;
    const s = String(input).trim();
    const m = s.match(/([0-9a-f]{20,64})/i);
    return m ? m[1] : null;
  }

  /* ============================================================
   * 3. CATÁLOGO — hub.json + resolução dos arquivos .user.js
   * ========================================================== */
  async function loadCatalog() {
    const source = (state.manifestUrl || '').trim();
    if (!source) {
      const err = new Error('Nenhuma fonte configurada');
      err.code = 'NO_SOURCE';
      throw err;
    }

    let apiFiles = null;
    let manifestRawUrl = null;
    const gistId = parseGistId(source);

    if (gistId) {
      // 1 chamada à API do GitHub → mapa de arquivos do gist (raw_url de cada um)
      const api = JSON.parse(await httpGet(
        'https://api.github.com/gists/' + gistId,
        { 'Accept': 'application/vnd.github+json' }
      ));
      apiFiles = api.files || {};
      const names = Object.keys(apiFiles);
      const hubName =
        names.find((f) => /^hub\.json$/i.test(f)) ||
        names.find((f) => /\.json$/i.test(f));
      if (!hubName) throw new Error('Esse gist não tem um arquivo hub.json');
      manifestRawUrl = apiFiles[hubName].raw_url;
    } else {
      // URL crua direta para o JSON (repo público, static host etc.)
      manifestRawUrl = source;
    }

    const manifest = JSON.parse(await httpGet(bust(manifestRawUrl)));
    /* Resolve "file": (1) mapa da API do gist quando houver; (2) fallback —
       arquivo-irmão ao lado do hub.json (raw do repo, GitHub Pages, S3…). */
    const sibling = (file) => {
      const i = manifestRawUrl.lastIndexOf('/');
      return i > 8 ? manifestRawUrl.slice(0, i + 1) + String(file).split('/').pop() : null;
    };
    const scripts = (Array.isArray(manifest.scripts) ? manifest.scripts : []).map((s) => {
      let raw = s.url || null;
      if (!raw && s.file && apiFiles) {
        if (apiFiles[s.file]) raw = apiFiles[s.file].raw_url;
        else {
          const k = Object.keys(apiFiles).find((f) => f.toLowerCase() === String(s.file).toLowerCase());
          if (k) raw = apiFiles[k].raw_url;
        }
      }
      if (!raw && s.file && !apiFiles) raw = sibling(s.file);
      return Object.assign({}, s, { raw });
    });

    return {
      manifest,
      scripts,
      fetchedAt: Date.now()
      // apiFiles é descartado de propósito: pode conter conteúdo embutido grande
    };
  }

  function cmpVer(a, b) {
    const pa = String(a || '0').replace(/^v/i, '').split('.').map((n) => parseInt(n, 10) || 0);
    const pb = String(b || '0').replace(/^v/i, '').split('.').map((n) => parseInt(n, 10) || 0);
    for (let i = 0; i < Math.max(pa.length, pb.length, 3); i++) {
      const x = pa[i] || 0, y = pb[i] || 0;
      if (x > y) return 1;
      if (x < y) return -1;
    }
    return 0;
  }

  function updatesAvailable() {
    const c = state.cache && state.cache.data;
    if (!c || !Array.isArray(c.scripts)) return 0;
    return c.scripts.reduce((n, s) => {
      const inst = state.installed[s.id];
      return n + (inst && cmpVer(s.version, inst.version) > 0 ? 1 : 0);
    }, 0);
  }

  /* ============================================================
   * 4. UI — Shadow DOM (isolamento total de estilos)
   * ========================================================== */
  const host = document.createElement('div');
  host.id = 'ushub-host';
  host.style.cssText = 'position:fixed;inset:0 auto auto 0;width:0;height:0;z-index:2147483647;';
  const shadow = host.attachShadow({ mode: 'open' });

  const CSS = `
    :host {
      all: initial;
      font-family: system-ui, -apple-system, "Segoe UI", Roboto, "Noto Sans", sans-serif;
      /* Escala de fonte personalizável (A-/A+) — tudo deriva de --fs */
      --fs: 1;
      --fab-size: 52px;
      --touch: 48px; /* WCAG 2.5.5 / Material: alvo de toque >= 48dp */
      --radius: 14px;
      --bg: #ffffff;
      --bg2: #f2f4f8;
      --chip: #e8eef9;
      --txt: #17212f;      /* contraste 15.4:1 sobre --bg */
      --mut: #4c5c77;      /* contraste 7.1:1 sobre --bg */
      --bord: #d8e0ec;
      --pri: #0b57d0;      /* contraste 6.6:1 com texto branco */
      --onpri: #ffffff;
      --good: #0e7a31;
      --warn: #9a3d00;
      --danger: #b3261e;
      --danger-ink: #ffffff;
      --scrim: rgba(10, 16, 28, .48);
      --shadow: 0 10px 32px rgba(10, 16, 28, .28);
      --ease: cubic-bezier(.2, .8, .2, 1);
      color-scheme: light;
    }
    :host([data-theme="dark"]) {
      --bg: #12161f;
      --bg2: #1b2230;
      --chip: #253048;
      --txt: #eef2fb;
      --mut: #aab7cf;
      --bord: #2c3850;
      --pri: #9dbdff;
      --onpri: #0a1c3f;
      --good: #86d9a2;
      --warn: #ffb59a;
      --danger: #f2b8b5;
      --danger-ink: #601410;
      --scrim: rgba(0, 0, 0, .6);
      --shadow: 0 12px 40px rgba(0, 0, 0, .55);
      color-scheme: dark;
    }
    * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
    button { font: inherit; color: inherit; border: 0; background: none; cursor: pointer; touch-action: manipulation; }
    input { font: inherit; color: inherit; }
    :focus-visible { outline: 3px solid var(--pri); outline-offset: 2px; border-radius: 8px; }

    /* ---------- FAB ---------- */
    #fab {
      position: fixed;
      left: 0; top: 0;
      width: var(--fab-size); height: var(--fab-size);
      border-radius: 16px;
      background: var(--pri);
      color: var(--onpri);
      box-shadow: var(--shadow), 0 0 0 1.5px rgba(255,255,255,.22) inset;
      display: flex; align-items: center; justify-content: center;
      z-index: 2147483647;
      touch-action: none;
      user-select: none; -webkit-user-select: none;
      cursor: grab;
      transition: opacity .35s var(--ease), box-shadow .2s var(--ease), transform .18s var(--ease);
    }
    #fab:active { cursor: grabbing; box-shadow: var(--shadow), 0 0 0 3px rgba(255,255,255,.30) inset; }
    #fab.idle { opacity: .38; } /* não compete com o texto quando parado */
    :host([data-fab="hidden"]) #fab { display: none; }
    #fab svg { width: 26px; height: 26px; pointer-events: none; }
    #fab .dot {
      position: absolute; top: -4px; right: -4px;
      min-width: 22px; height: 22px; padding: 0 5px;
      border-radius: 999px; background: var(--danger); color: var(--danger-ink);
      font-size: calc(12px * var(--fs)); font-weight: 700; line-height: 22px; text-align: center;
      box-shadow: 0 0 0 2px var(--bg);
    }

    /* ---------- Scrim ---------- */
    #scrim {
      position: fixed; inset: 0; background: var(--scrim);
      opacity: 0; pointer-events: none;
      transition: opacity .28s var(--ease);
      z-index: 2147483646;
      backdrop-filter: blur(2px);
    }
    #scrim.open { opacity: 1; pointer-events: auto; }

    /* ---------- Bottom sheet ---------- */
    #sheet {
      position: fixed;
      left: 0; right: 0; bottom: 0;
      margin-inline: auto;
      width: 100%; max-width: 620px;
      max-height: 86vh;           /* fallback */
      max-height: 86dvh;
      background: var(--bg); color: var(--txt);
      border-radius: 22px 22px 0 0;
      box-shadow: var(--shadow);
      transform: translateY(105%);
      transition: transform .3s var(--ease);
      display: flex; flex-direction: column;
      z-index: 2147483647;
      padding-bottom: env(safe-area-inset-bottom, 0px);
      font-size: calc(15px * var(--fs));
      line-height: 1.45;
    }
    #sheet.open { transform: translateY(0); }
    #sheet.dragging { transition: none; }

    #grab {
      padding: 12px 0 6px;
      display: flex; justify-content: center;
      touch-action: none; cursor: grab; flex: 0 0 auto;
    }
    #grab span { width: 42px; height: 5px; border-radius: 999px; background: var(--bord); }

    header.bar {
      display: flex; align-items: center; gap: 8px;
      padding: 2px 12px 10px;
      border-bottom: 1px solid var(--bord);
      flex: 0 0 auto;
    }
    header.bar h1 {
      font-size: calc(17px * var(--fs)); font-weight: 700; margin: 0;
      flex: 1 1 auto; min-width: 0;
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }
    .iconbtn {
      width: var(--touch); height: var(--touch);
      border-radius: 12px; display: inline-flex; align-items: center; justify-content: center;
      color: var(--mut); flex: 0 0 auto;
    }
    .iconbtn:active { background: var(--bg2); color: var(--txt); }
    .iconbtn svg { width: 22px; height: 22px; }

    /* Abas — alvos de toque grandes, estado claro */
    nav.tabs { display: flex; gap: 6px; padding: 10px 12px 0; flex: 0 0 auto; }
    nav.tabs button {
      flex: 1 1 0; min-height: var(--touch);
      border-radius: 12px 12px 0 0;
      color: var(--mut); font-weight: 600;
      font-size: calc(14px * var(--fs));
      border-bottom: 3px solid transparent;
      display: flex; align-items: center; justify-content: center; gap: 6px;
    }
    nav.tabs button[aria-selected="true"] { color: var(--pri); border-bottom-color: var(--pri); background: var(--bg2); }

    main { overflow-y: auto; -webkit-overflow-scrolling: touch; padding: 14px 12px 22px; flex: 1 1 auto; }

    /* Campo de busca — 16px+ evita zoom indesejado no mobile */
    .search { position: relative; margin-bottom: 12px; }
    .search input {
      width: 100%; min-height: var(--touch);
      padding: 10px 14px 10px 42px;
      border-radius: var(--radius); border: 1.5px solid var(--bord);
      background: var(--bg2); font-size: calc(16px * var(--fs));
    }
    .search svg { position: absolute; left: 12px; top: 50%; transform: translateY(-50%); width: 20px; height: 20px; color: var(--mut); }
    ::placeholder { color: var(--mut); opacity: .85; }

    /* ---------- Cartões de script ---------- */
    .meta { color: var(--mut); font-size: calc(12.5px * var(--fs)); margin: 0 2px 10px; }
    .card {
      background: var(--bg2);
      border: 1px solid var(--bord);
      border-radius: var(--radius);
      padding: 14px;
      margin-bottom: 12px;
    }
    .card .top { display: flex; gap: 10px; align-items: flex-start; }
    .card .emoji { font-size: 26px; line-height: 1; flex: 0 0 auto; padding-top: 2px; }
    .card .info { flex: 1 1 auto; min-width: 0; }
    .card h2 { margin: 0 0 2px; font-size: calc(16px * var(--fs)); font-weight: 700; overflow-wrap: anywhere; }
    .card .desc { margin: 4px 0 0; color: var(--mut); font-size: calc(13.5px * var(--fs)); overflow-wrap: anywhere; }
    .row { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; align-items: center; }
    .chip {
      display: inline-flex; align-items: center; gap: 4px;
      background: var(--chip); color: var(--txt);
      border-radius: 999px; padding: 3px 10px;
      font-size: calc(12px * var(--fs)); font-weight: 600;
    }
    .chip.ok { color: var(--good); }
    .chip.upd { color: var(--warn); }
    .card .actions { display: flex; gap: 8px; margin-top: 12px; flex-wrap: wrap; }
    .btn {
      min-height: var(--touch);
      padding: 10px 18px;
      border-radius: 12px;
      font-weight: 700; font-size: calc(14px * var(--fs));
      display: inline-flex; align-items: center; justify-content: center; gap: 8px;
      flex: 1 1 auto;
    }
    .btn.pri { background: var(--pri); color: var(--onpri); }
    .btn.pri:active { filter: brightness(.92); }
    .btn.ghost { background: transparent; color: var(--pri); border: 1.5px solid var(--pri); flex: 0 1 auto; }
    .btn[disabled] { opacity: .55; pointer-events: none; }
    .btn svg { width: 18px; height: 18px; }

    /* Estados vazios / erro / esqueleto */
    .empty, .err {
      text-align: center; color: var(--mut); padding: 26px 14px;
      font-size: calc(14px * var(--fs));
    }
    .empty .big, .err .big { font-size: 34px; display: block; margin-bottom: 8px; }
    .err b { color: var(--danger); }
    .skl { border-radius: var(--radius); background: var(--bg2); border: 1px solid var(--bord);
      height: 118px; margin-bottom: 12px; position: relative; overflow: hidden; }
    .skl::after { content: ""; position: absolute; inset: 0;
      background: linear-gradient(100deg, transparent 30%, rgba(140,160,200,.18) 50%, transparent 70%);
      animation: shimmer 1.3s infinite; }
    @keyframes shimmer { from { transform: translateX(-100%); } to { transform: translateX(100%); } }

    /* ---------- Configurações ---------- */
    .group { margin-bottom: 20px; }
    .group h3 { font-size: calc(13px * var(--fs)); text-transform: uppercase; letter-spacing: .06em;
      color: var(--mut); margin: 0 2px 8px; }
    .field input {
      width: 100%; min-height: var(--touch);
      padding: 10px 14px; border-radius: 12px;
      border: 1.5px solid var(--bord); background: var(--bg);
      font-size: calc(16px * var(--fs));
    }
    .seg { display: flex; gap: 8px; }
    .seg button {
      flex: 1 1 0; min-height: var(--touch);
      border-radius: 12px; border: 1.5px solid var(--bord);
      color: var(--mut); font-weight: 700; font-size: calc(14px * var(--fs));
    }
    .seg button[aria-pressed="true"] { background: var(--pri); border-color: var(--pri); color: var(--onpri); }
    .fontctl { display: flex; align-items: center; gap: 10px; }
    .fontctl button {
      width: var(--touch); height: var(--touch); border-radius: 12px;
      border: 1.5px solid var(--bord); font-weight: 800; font-size: calc(18px * var(--fs));
      color: var(--pri);
    }
    .fontctl .val { flex: 1 1 auto; text-align: center; font-weight: 700; font-size: calc(15px * var(--fs)); }
    .switchrow { display: flex; align-items: center; justify-content: space-between; gap: 12px;
      min-height: var(--touch); padding: 6px 2px; }
    .switchrow .lbl { font-size: calc(14.5px * var(--fs)); font-weight: 600; }
    .switchrow .lbl small { display: block; color: var(--mut); font-weight: 400; font-size: calc(12.5px * var(--fs)); }
    .switch { width: 56px; height: 32px; border-radius: 999px; background: var(--bord); position: relative; flex: 0 0 auto; transition: background .2s var(--ease); }
    .switch::after { content: ""; position: absolute; top: 3px; left: 3px; width: 26px; height: 26px; border-radius: 50%; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,.3); transition: transform .2s var(--ease); }
    .switch[aria-checked="true"] { background: var(--pri); }
    .switch[aria-checked="true"]::after { transform: translateX(24px); }
    .help { color: var(--mut); font-size: calc(12.5px * var(--fs)); margin-top: 6px; }
    details.helpbox { border: 1px solid var(--bord); border-radius: 12px; padding: 10px 12px; background: var(--bg2); }
    details.helpbox summary { min-height: var(--touch); display: flex; align-items: center; font-weight: 700; cursor: pointer; }
    details.helpbox ol, details.helpbox ul { padding-left: 20px; margin: 8px 0 4px; }
    details.helpbox li { margin-bottom: 6px; font-size: calc(13px * var(--fs)); }
    code { background: var(--chip); border-radius: 6px; padding: 1px 6px; font-size: .92em; overflow-wrap: anywhere; }

    /* ---------- Toasts ---------- */
    #toasts {
      position: fixed;
      top: calc(12px + env(safe-area-inset-top, 0px));
      left: 0; right: 0;
      display: flex; flex-direction: column; align-items: center; gap: 8px;
      pointer-events: none;
      z-index: 2147483647;
    }
    .toast {
      background: var(--txt); color: var(--bg);
      border-radius: 999px; padding: 10px 18px;
      font-size: calc(13.5px * var(--fs)); font-weight: 600;
      box-shadow: var(--shadow);
      max-width: min(92vw, 460px);
      animation: toast-in .25s var(--ease);
    }
    @keyframes toast-in { from { opacity: 0; transform: translateY(-10px); } to { opacity: 1; transform: none; } }

    /* ---------- Acessibilidade de movimento ---------- */
    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after { animation: none !important; transition: none !important; }
    }
    /* Cores forçadas (Windows HC / alguns modos de alto contraste) */
    @media (forced-colors: active) {
      #fab, .btn, .chip, nav.tabs button, .seg button { forced-color-adjust: auto; }
    }
  `;

  const ICONS = {
    logo: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 6l-5 6 5 6"/><path d="M16 6l5 6-5 6"/><path d="M13.5 4l-3 16"/></svg>',
    close: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M5 5l14 14M19 5L5 19"/></svg>',
    refresh: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 12a8 8 0 1 1-2.3-5.6"/><path d="M20 3v4h-4"/></svg>',
    gear: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="3.2"/><path d="M19 12a7 7 0 0 0-.1-1.2l2-1.5-2-3.4-2.3 1a7 7 0 0 0-2-1.2L14.2 3H9.8l-.4 2.7a7 7 0 0 0-2 1.2l-2.3-1-2 3.4 2 1.5A7 7 0 0 0 5 12a7 7 0 0 0 .1 1.2l-2 1.5 2 3.4 2.3-1a7 7 0 0 0 2 1.2l.4 2.7h4.4l.4-2.7a7 7 0 0 0 2-1.2l2.3 1 2-3.4-2-1.5A7 7 0 0 0 19 12z"/></svg>',
    list: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M8 6h13M8 12h13M8 18h13"/><circle cx="4" cy="6" r="1.3" fill="currentColor"/><circle cx="4" cy="12" r="1.3" fill="currentColor"/><circle cx="4" cy="18" r="1.3" fill="currentColor"/></svg>',
    search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>',
    down: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3v12"/><path d="M6 11l6 6 6-6"/><path d="M5 21h14"/></svg>',
    copy: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>'
  };

  shadow.innerHTML = `
    <style>${CSS}</style>
    <div id="scrim" aria-hidden="true"></div>
    <button id="fab" aria-label="Abrir USHub — central de userscripts">${ICONS.logo}<span class="dot" id="fabDot" hidden></span></button>
    <section id="sheet" role="dialog" aria-modal="true" aria-label="USHub, central de userscripts" aria-hidden="true">
      <div id="grab"><span></span></div>
      <header class="bar">
        <h1 id="sheetTitle">USHub</h1>
        <button class="iconbtn" id="btnRefresh" aria-label="Atualizar catálogo">${ICONS.refresh}</button>
        <button class="iconbtn" id="btnClose" aria-label="Fechar painel">${ICONS.close}</button>
      </header>
      <nav class="tabs" role="tablist" aria-label="Seções">
        <button role="tab" id="tabCat" data-tab="catalogo" aria-selected="true">${ICONS.list}&nbsp;Catálogo</button>
        <button role="tab" id="tabCfg" data-tab="config" aria-selected="false">${ICONS.gear}&nbsp;Ajustes</button>
      </nav>
      <main id="main"></main>
    </section>
    <div id="toasts" aria-live="polite" aria-atomic="false"></div>
  `;

  const $ = (sel) => shadow.querySelector(sel);
  const fab = $('#fab');
  const fabDot = $('#fabDot');
  const scrim = $('#scrim');
  const sheet = $('#sheet');
  const main = $('#main');
  const toasts = $('#toasts');
  const btnClose = $('#btnClose');
  const btnRefresh = $('#btnRefresh');

  /* ---------- toasts ---------- */
  function toast(msg, ms) {
    const el = document.createElement('div');
    el.className = 'toast';
    el.textContent = msg;
    toasts.appendChild(el);
    while (toasts.children.length > 3) toasts.firstChild.remove();
    setTimeout(() => { el.style.opacity = '0'; setTimeout(() => el.remove(), 300); }, ms || 3200);
  }

  /* ---------- tema / fonte ---------- */
  function applyAppearance() {
    const t = state.ui.theme;
    host.dataset.theme = t === 'auto'
      ? (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
      : t;
    host.style.setProperty('--fs', String(state.ui.fontScale));
    host.dataset.fab = state.ui.fabHidden || sheetOpen ? 'hidden' : 'visible';
  }
  try {
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    (mq.addEventListener ? mq.addEventListener.bind(mq, 'change') : mq.addListener.bind(mq))(() => {
      if (state.ui.theme === 'auto') applyAppearance();
    });
  } catch (e) { /* tema automático indisponível */ }

  /* ============================================================
   * 5. FAB — arrastável, encaixa na borda, some parado,
   *    nunca cobre o teclado nem prende o dedo do usuário
   * ========================================================== */
  let sheetOpen = false;

  function fabPlace(animate) {
    const m = 8; // margem mínima
    const vw = window.innerWidth, vh = window.innerHeight;
    const w = fab.offsetWidth || 52, h = fab.offsetHeight || 52;
    const x = state.ui.fab.edge === 'left' ? m : vw - w - m;
    const y = Math.max(m, Math.min(vh - h - m, state.ui.fab.yRatio * vh - h / 2));
    if (!animate) fab.style.transition = 'none';
    fab.style.transform = `translate3d(${Math.round(x)}px, ${Math.round(y)}px, 0)`;
    if (!animate) requestAnimationFrame(() => { fab.style.transition = ''; });
  }

  function dockNearest() {
    const r = fab.getBoundingClientRect();
    const cx = r.left + r.width / 2;
    state.ui.fab.edge = cx < window.innerWidth / 2 ? 'left' : 'right';
    const h = fab.offsetHeight || 52;
    state.ui.fab.yRatio = Math.max(0.05, Math.min(0.95, (r.top + h / 2) / window.innerHeight));
    save();
    fabPlace(true);
  }

  /* Ociosidade: depois de 4 s sem toque, o FAB “recua” (38% de opacidade)
     para não disputar a atenção com o conteúdo — volta a 100% no toque. */
  let idleTimer = null;
  function wake() {
    fab.classList.remove('idle');
    clearTimeout(idleTimer);
    idleTimer = setTimeout(() => { if (!sheetOpen) fab.classList.add('idle'); }, 4000);
  }

  /* Teclado virtual aberto → esconde o FAB para não atrapalhar a digitação */
  let kbdHidden = false;
  function onViewport() {
    const vv = window.visualViewport;
    if (!vv) { fabPlace(false); return; }
    const shrink = window.innerHeight - vv.height;
    if (shrink > 140 && !kbdHidden) { kbdHidden = true; fab.style.opacity = '0'; fab.style.pointerEvents = 'none'; }
    else if (shrink <= 140 && kbdHidden) { kbdHidden = false; fab.style.opacity = ''; fab.style.pointerEvents = ''; wake(); }
    fabPlace(false);
  }
  if (window.visualViewport) {
    window.visualViewport.addEventListener('resize', onViewport, { passive: true });
  } else {
    window.addEventListener('resize', () => fabPlace(false), { passive: true });
  }

  /* Gestos do FAB: toque (abre) vs. arraste (reposiciona); limiar de 8px */
  let drag = null;
  fab.addEventListener('pointerdown', (ev) => {
    wake();
    drag = { id: ev.pointerId, x0: ev.clientX, y0: ev.clientY, moved: false, L: 0, T: 0 };
    const r = fab.getBoundingClientRect();
    drag.L = r.left; drag.T = r.top;
    try { fab.setPointerCapture(ev.pointerId); } catch (e) { /* noop */ }
  });
  fab.addEventListener('pointermove', (ev) => {
    if (!drag || ev.pointerId !== drag.id) return;
    const dx = ev.clientX - drag.x0, dy = ev.clientY - drag.y0;
    if (!drag.moved && Math.hypot(dx, dy) > 8) drag.moved = true;
    if (drag.moved) {
      const m = 4, w = fab.offsetWidth, h = fab.offsetHeight;
      const x = Math.max(m, Math.min(window.innerWidth - w - m, drag.L + dx));
      const y = Math.max(m, Math.min(window.innerHeight - h - m, drag.T + dy));
      fab.style.transform = `translate3d(${Math.round(x)}px, ${Math.round(y)}px, 0)`;
    }
  });
  function endDrag(ev, cancelled) {
    if (!drag || ev.pointerId !== drag.id) return;
    const wasTap = !drag.moved;
    drag = null;
    if (cancelled) { fabPlace(true); return; }
    if (wasTap) { openSheet(); return; }
    dockNearest();
  }
  fab.addEventListener('pointerup', (ev) => endDrag(ev, false));
  fab.addEventListener('pointercancel', (ev) => endDrag(ev, true));
  fab.addEventListener('contextmenu', (ev) => ev.preventDefault());
  /* Ativação por teclado/leitor de tela: click "sintético" tem detail === 0;
     os cliques de ponteiro/toque já são tratados pela lógica de gestos acima. */
  fab.addEventListener('click', (ev) => { if (ev.detail === 0) { ev.preventDefault(); openSheet(); } });

  /* ============================================================
   * 6. PAINEL (bottom sheet)
   * ========================================================== */
  let lastFocus = null;

  function openSheet() {
    sheetOpen = true;
    lastFocus = document.activeElement;
    applyAppearance(); // esconde o FAB enquanto o painel está aberto
    sheet.classList.add('open');
    scrim.classList.add('open');
    sheet.setAttribute('aria-hidden', 'false');
    document.documentElement.style.setProperty('overflow', 'hidden'); // trava o scroll da página
    render();
    if (state.ui.autoRefresh) refreshCatalog(false).catch(() => {});
    btnClose.focus({ preventScroll: true });
  }

  function closeSheet() {
    sheetOpen = false;
    sheet.classList.remove('open');
    scrim.classList.remove('open');
    sheet.setAttribute('aria-hidden', 'true');
    sheet.style.transform = '';
    document.documentElement.style.removeProperty('overflow');
    applyAppearance();
    wake();
    if (lastFocus && typeof lastFocus.focus === 'function') {
      try { lastFocus.focus({ preventScroll: true }); } catch (e) { /* noop */ }
    }
  }

  btnClose.addEventListener('click', closeSheet);
  scrim.addEventListener('click', closeSheet);
  shadow.querySelectorAll('nav.tabs [data-tab]').forEach((b) => {
    b.addEventListener('click', () => {
      state.ui.tab = b.dataset.tab;
      save();
      render();
    });
  });
  shadow.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape' && sheetOpen) { ev.preventDefault(); closeSheet(); }
  });
  window.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape' && sheetOpen) { ev.preventDefault(); closeSheet(); }
  });

  /* Deslizar para baixo fecha — com mola de retorno ao soltar */
  let swipe = null;
  const grab = $('#grab');
  grab.addEventListener('pointerdown', (ev) => {
    swipe = { id: ev.pointerId, y0: ev.clientY, dy: 0 };
    sheet.classList.add('dragging');
    try { grab.setPointerCapture(ev.pointerId); } catch (e) { /* noop */ }
  });
  grab.addEventListener('pointermove', (ev) => {
    if (!swipe || ev.pointerId !== swipe.id) return;
    swipe.dy = Math.max(0, ev.clientY - swipe.y0);
    sheet.style.transform = `translateY(${swipe.dy}px)`;
    scrim.style.opacity = String(Math.max(0, 1 - swipe.dy / 320) * 1);
  });
  function endSwipe(ev) {
    if (!swipe || ev.pointerId !== swipe.id) return;
    const dy = swipe.dy;
    swipe = null;
    sheet.classList.remove('dragging');
    scrim.style.opacity = '';
    if (dy > 110) closeSheet();
    else sheet.style.transform = '';
  }
  grab.addEventListener('pointerup', endSwipe);
  grab.addEventListener('pointercancel', endSwipe);

  /* ============================================================
   * 7. RENDER
   * ========================================================== */
  const esc = (s) => String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');

  const norm = (s) => String(s || '')
    .normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();

  let query = '';
  let loading = false;
  let loadError = null;

  function setTabs() {
    shadow.querySelectorAll('nav.tabs [role="tab"]').forEach((b) => {
      const on = b.dataset.tab === state.ui.tab;
      b.setAttribute('aria-selected', on ? 'true' : 'false');
    });
  }

  function cardHTML(s) {
    const inst = state.installed[s.id];
    const hasUpdate = inst && cmpVer(s.version, inst.version) > 0;
    const missing = !s.raw; // hub.json aponta para um "file" que não existe no gist
    const tags = (s.tags || []).map((t) => `<span class="chip">${esc(t)}</span>`).join('');
    const status = missing
      ? `<span class="chip upd">⚠ arquivo “${esc(s.file || '?')}” ausente no gist</span>`
      : hasUpdate
        ? `<span class="chip upd">⬆ nova v${esc(s.version)} (você tem v${esc(inst.version)})</span>`
        : inst
          ? `<span class="chip ok">✓ instalado v${esc(inst.version)}</span>`
          : '';
    const btnMain = missing
      ? `<button class="btn pri" disabled aria-disabled="true">${ICONS.down} Indisponível</button>`
      : hasUpdate
        ? `<button class="btn pri" data-act="install" data-id="${esc(s.id)}" data-ver="${esc(s.version)}">${ICONS.down} Atualizar p/ v${esc(s.version)}</button>`
        : inst
          ? `<button class="btn pri" data-act="install" data-id="${esc(s.id)}" data-ver="${esc(s.version)}">${ICONS.down} Reinstalar</button>`
          : `<button class="btn pri" data-act="install" data-id="${esc(s.id)}" data-ver="${esc(s.version)}">${ICONS.down} Instalar</button>`;
    const btnCopy = missing
      ? `<button class="btn ghost" disabled aria-disabled="true">${ICONS.copy} Código</button>`
      : `<button class="btn ghost" data-act="copy" data-id="${esc(s.id)}" aria-label="Copiar código de ${esc(s.name || s.id)}">${ICONS.copy} Código</button>`;
    return `
      <article class="card" data-card="${esc(s.id)}">
        <div class="top">
          <span class="emoji" aria-hidden="true">${esc(s.emoji || '🧩')}</span>
          <div class="info">
            <h2>${esc(s.name || s.id)} <span class="chip">v${esc(s.version || '?')}</span></h2>
            <p class="desc">${esc(s.description || '')}</p>
            <div class="row">${status}${tags}</div>
          </div>
        </div>
        <div class="actions">
          ${btnMain}
          ${btnCopy}
        </div>
      </article>`;
  }

  function resultsHTML() {
    const c = state.cache && state.cache.data;
    if (!c || !Array.isArray(c.scripts)) return '';
    let scripts = c.scripts;
    if (query) {
      const q = norm(query);
      scripts = scripts.filter((s) =>
        norm(s.name).includes(q) || norm(s.description).includes(q) ||
        (Array.isArray(s.tags) && s.tags.some((t) => norm(t).includes(q))));
    }
    return scripts.length
      ? scripts.map(cardHTML).join('')
      : `<div class="empty"><span class="big" aria-hidden="true">🔍</span><p>Nada encontrado para “${esc(query)}”.</p></div>`;
  }

  function catalogHTML() {
    if (!state.manifestUrl.trim()) {
      return `
        <div class="empty">
          <span class="big" aria-hidden="true">📦</span>
          <p><b>Catálogo vazio.</b></p>
          <p>Abra <b>Ajustes</b> e <b>salve com o campo vazio</b> para restaurar o catálogo de fábrica — ou aponte um gist/URL crua seu.</p>
          <div class="actions" style="display:flex;gap:8px;margin-top:14px">
            <button class="btn pri" data-act="go-config">${ICONS.gear} Abrir Ajustes</button>
          </div>
        </div>`;
    }
    if (loading && !(state.cache && state.cache.data)) {
      return '<div class="skl"></div><div class="skl"></div><div class="skl"></div>';
    }
    if (loadError && !(state.cache && state.cache.data)) {
      return `
        <div class="err">
          <span class="big" aria-hidden="true">⚠️</span>
          <p><b>Não deu para carregar o catálogo</b></p>
          <p>${esc(loadError)}</p>
          <div class="actions" style="display:flex;gap:8px;margin-top:12px">
            <button class="btn pri" data-act="refresh">${ICONS.refresh} Tentar de novo</button>
          </div>
        </div>`;
    }
    const c = state.cache && state.cache.data;
    if (!c) return '';
    const all = Array.isArray(c.scripts) ? c.scripts : [];
    const upd = updatesAvailable();
    const ago = c.fetchedAt ? Math.max(0, Math.round((Date.now() - c.fetchedAt) / 60000)) : 0;
    const title = esc((c.manifest && c.manifest.hub) || 'Catálogo');
    return `
      <div class="search">
        ${ICONS.search}
        <input id="q" type="search" inputmode="search" enterkeyhint="search" autocomplete="off" autocapitalize="off"
               placeholder="Buscar scripts…" value="${esc(query)}" aria-label="Buscar scripts">
      </div>
      <p class="meta">${title} · ${all.length} script(s)${upd ? ' · ⬆ ' + upd + ' atualização(ões)' : ''} · atualizado há ${ago} min</p>
      ${loadError ? `<p class="meta" style="color:var(--warn)">Sem conexão agora — exibindo cópia em cache. (${esc(loadError)})</p>` : ''}
      <div id="results">${resultsHTML()}</div>`;
  }

  function configHTML() {
    const u = state.ui;
    const pct = Math.round(u.fontScale * 100);
    return `
      <section class="group" aria-labelledby="g-fonte">
        <h3 id="g-fonte">Fonte do catálogo (gist público)</h3>
        <div class="field">
          <input id="srcUrl" type="url" inputmode="url" autocomplete="off" autocapitalize="off" spellcheck="false"
                 placeholder="${esc(PLACEHOLDER_URL)}"
                 value="${esc(state.manifestUrl)}" aria-label="URL do gist ou do hub.json">
          <p class="help">Aceita URL do <b>gist</b>, <b>ID do gist</b> ou <b>URL crua</b> do <code>hub.json</code> (repo público/host estático — arquivos ao lado são resolvidos). <b>Vazio = catálogo de fábrica</b>.</p>
        </div>
        <div class="actions" style="display:flex;gap:8px;margin-top:10px">
          <button class="btn pri" data-act="save-url" style="flex:1 1 auto">Salvar e carregar</button>
        </div>
      </section>

      <section class="group" aria-labelledby="g-aparencia">
        <h3 id="g-aparencia">Aparência</h3>
        <div class="seg" role="group" aria-label="Tema de cores">
          <button data-act="theme" data-v="auto"  aria-pressed="${u.theme === 'auto'}">Auto</button>
          <button data-act="theme" data-v="light" aria-pressed="${u.theme === 'light'}">Claro</button>
          <button data-act="theme" data-v="dark"  aria-pressed="${u.theme === 'dark'}">Escuro</button>
        </div>
        <p class="help">Contraste do texto: 15:1 (claro) e 13:1 (escuro) — muito acima do mínimo WCAG 4.5:1.</p>
        <div class="fontctl" style="margin-top:12px">
          <button data-act="font-" aria-label="Diminuir tamanho da fonte">A−</button>
          <div class="val" aria-live="polite">Tamanho da fonte: ${pct}%</div>
          <button data-act="font+" aria-label="Aumentar tamanho da fonte">A+</button>
        </div>
      </section>

      <section class="group" aria-labelledby="g-botao">
        <h3 id="g-botao">Botão flutuante</h3>
        <div class="switchrow">
          <span class="lbl">Ocultar o botão<small>Reabra pelo menu do seu gerenciador (USHub · abrir catálogo).</small></span>
          <button class="switch" role="switch" aria-checked="${u.fabHidden}" data-act="fab-hidden" aria-label="Ocultar botão flutuante"></button>
        </div>
        <div class="switchrow">
          <span class="lbl">Atualizar catálogo ao abrir<small>Busca novidades; mantém cache de 15 min para uso offline.</small></span>
          <button class="switch" role="switch" aria-checked="${u.autoRefresh}" data-act="auto-refresh" aria-label="Atualizar catálogo ao abrir"></button>
        </div>
        <div class="actions" style="display:flex;gap:8px;margin-top:6px">
          <button class="btn ghost" data-act="fab-reset">Recentralizar botão</button>
        </div>
      </section>

      <section class="group" aria-labelledby="g-ajuda">
        <h3 id="g-ajuda">Como criar meu gist-hub</h3>
        <details class="helpbox">
          <summary>📚 Passo a passo (1 minuto)</summary>
          <ol>
            <li>Em <code>gist.github.com</code>, crie um gist <b>público</b> chamado <code>hub.json</code>.</li>
            <li>No <b>mesmo gist</b>, adicione quantos arquivos <code>*.user.js</code> quiser (um por script).</li>
            <li>No <code>hub.json</code>, liste cada script com <code>id</code>, <code>name</code>, <code>version</code>, <code>description</code> e <code>file</code> (nome <b>exato</b> do arquivo no gist).</li>
            <li>Cole a URL do gist aqui em Ajustes → pronto: o botão vira a central de tudo.</li>
            <li>Para lançar atualização: edite o arquivo no gist e <b>suba a versão</b> no <code>hub.json</code> — o selo ⬆ aparece sozinho.</li>
          </ol>
        </details>
      </section>

      <p class="help" style="text-align:center">USHub v${esc(VERSION)} · gestão via hub.json + n arquivos no gist</p>`;
  }

  function updateResults() {
    const box = $('#results');
    if (!box) return;
    box.innerHTML = resultsHTML();
  }

  function render() {
    setTabs();
    if (state.ui.tab === 'config') {
      main.innerHTML = configHTML();
    } else {
      main.innerHTML = catalogHTML();
      const q = $('#q');
      if (q) {
        // Atualiza SÓ os resultados: recriar o <input> a cada tecla quebraria
        // a composição do teclado (acentos/swipe do Gboard) no Android.
        q.addEventListener('input', () => { query = q.value; updateResults(); });
      }
    }
    const upd = updatesAvailable();
    fabDot.hidden = !upd;
    fabDot.textContent = String(upd);
    const t = $('#sheetTitle');
    if (t) t.textContent = upd ? `USHub · ${upd}⬆` : 'USHub';
  }

  /* ============================================================
   * 8. AÇÕES
   * ========================================================== */
  async function refreshCatalog(manual) {
    loadError = null;
    loading = true;
    if (sheetOpen) render();
    try {
      const cat = await loadCatalog();
      state.cache = { url: state.manifestUrl, fetchedAt: cat.fetchedAt, data: cat };
      save();
      if (manual) toast('Catálogo atualizado ✓');
    } catch (e) {
      loadError = e.code === 'NO_SOURCE' ? null : (e && e.message) || 'Erro desconhecido';
      if (manual && !e.code) toast('Falha ao atualizar: ' + loadError);
    } finally {
      loading = false;
      if (sheetOpen) render(); else { const u = updatesAvailable(); fabDot.hidden = !u; fabDot.textContent = String(u); }
    }
  }

  function findScript(id) {
    const c = state.cache && state.cache.data;
    return c ? c.scripts.find((s) => s.id === id) : null;
  }

  async function install(id, ver) {
    const s = findScript(id);
    if (!s) { toast('Script não encontrado no catálogo.'); return; }
    if (!s.raw) { toast('Arquivo "' + (s.file || '?') + '" não achado no gist. Confira o hub.json.'); return; }
    const url = bust(s.raw);
    // Registro otimista no aparelho → o selo "✓ instalado" já aparece.
    state.installed[s.id] = { version: ver || s.version, at: Date.now() };
    save();
    render();
    let opened = null;
    try { opened = window.open(url, '_blank'); } catch (e) { /* noop */ }
    if (opened) {
      toast('Abrindo o instalador… confirme no Tampermonkey ✓');
    } else {
      toast('Popup bloqueado — use “Código” para copiar e instalar manualmente.');
    }
  }

  async function copyCode(id) {
    const s = findScript(id);
    if (!s || !s.raw) { toast('Fonte indisponível para copiar.'); return; }
    toast('Baixando código…');
    try {
      const code = await httpGet(bust(s.raw));
      let ok = false;
      try { await navigator.clipboard.writeText(code); ok = true; }
      catch (e) {
        try {
          const ta = document.createElement('textarea');
          ta.value = code;
          ta.style.cssText = 'position:fixed;top:0;left:0;opacity:0;';
          document.body.appendChild(ta);
          ta.select();
          ok = document.execCommand('copy');
          ta.remove();
        } catch (e2) { ok = false; }
      }
      toast(ok ? 'Código copiado ✓ — cole no editor do gerenciador.' : 'Não consegui copiar. Toque em Instalar.');
    } catch (e) {
      toast('Falha ao baixar: ' + (e && e.message ? e.message : 'rede'));
    }
  }

  /* Delegação de eventos dentro do Shadow DOM */
  shadow.addEventListener('click', (ev) => {
    const el = ev.target && ev.target.closest ? ev.target.closest('[data-act]') : null;
    if (!el) return;
    const act = el.dataset.act;
    switch (act) {
      case 'install': install(el.dataset.id, el.dataset.ver); break;
      case 'copy': copyCode(el.dataset.id); break;
      case 'refresh': refreshCatalog(true); break;
      case 'go-config': state.ui.tab = 'config'; save(); render(); break;
      case 'theme': state.ui.theme = el.dataset.v; save(); applyAppearance(); render(); break;
      case 'font-': state.ui.fontScale = clampFont(state.ui.fontScale - 0.05); save(); applyAppearance(); render(); break;
      case 'font+': state.ui.fontScale = clampFont(state.ui.fontScale + 0.05); save(); applyAppearance(); render(); break;
      case 'fab-hidden':
        state.ui.fabHidden = !state.ui.fabHidden;
        save(); applyAppearance(); render();
        toast(state.ui.fabHidden ? 'Botão oculto — reabra pelo menu do gerenciador.' : 'Botão visível novamente ✓');
        break;
      case 'auto-refresh': state.ui.autoRefresh = !state.ui.autoRefresh; save(); render(); break;
      case 'fab-reset': state.ui.fab = { edge: 'right', yRatio: 0.72 }; save(); fabPlace(true); toast('Posição do botão restaurada.'); break;
      case 'save-url': {
        const inp = $('#srcUrl');
        let v = inp ? inp.value.trim() : '';
        if (!v) v = DEFAULT_SOURCE; // vazio = restaura o catálogo de fábrica
        state.manifestUrl = v;
        state.cache = null; // fonte mudou → cache antigo não vale mais
        save();
        toast(v === DEFAULT_SOURCE ? 'Catálogo de fábrica restaurado ✓' : 'Fonte salva — carregando catálogo…');
        state.ui.tab = 'catalogo';
        save();
        refreshCatalog(true);
        break;
      }
    }
  });

  btnRefresh.addEventListener('click', () => refreshCatalog(true));

  function clampFont(v) { return Math.max(0.85, Math.min(1.4, Math.round(v * 100) / 100)); }

  /* ============================================================
   * 9. MENU DO GERENCIADOR + BOOT
   * ========================================================== */
  function registerMenu() {
    let gm = null;
    try {
      if (typeof GM_registerMenuCommand === 'function') gm = GM_registerMenuCommand;
      else if (typeof GM !== 'undefined' && GM && typeof GM.registerMenuCommand === 'function') gm = GM.registerMenuCommand.bind(GM);
    } catch (e) { /* noop */ }
    if (!gm) return;
    try {
      gm('📦 USHub · abrir catálogo', openSheet);
      gm(state.ui.fabHidden ? '👁 USHub · mostrar botão' : '🙈 USHub · ocultar botão', () => {
        state.ui.fabHidden = !state.ui.fabHidden;
        save(); applyAppearance();
        toast(state.ui.fabHidden ? 'Botão oculto — reabra por este menu.' : 'Botão de volta ✓');
      });
    } catch (e) { /* menu indisponível */ }
  }

  async function boot() {
    state = Object.assign(defaultState(), await kvGet(LS_KEY, {}));
    state.ui = Object.assign(defaultState().ui, state.ui || {});
    state.ui.fab = Object.assign(defaultState().ui.fab, (state.ui && state.ui.fab) || {});
    state.installed = state.installed || {};

    // Primeira execução: catálogo de fábrica já vem ligado (troque nos Ajustes).
    if (!String(state.manifestUrl || '').trim()) {
      state.manifestUrl = DEFAULT_SOURCE;
      save();
    }

    (document.body || document.documentElement).appendChild(host);
    applyAppearance();
    fabPlace(false);
    wake();
    registerMenu();

    // Pré-carrega o catálogo em segundo plano (uma vez por sessão, respeitando o cache)
    const stale = !state.cache || (Date.now() - (state.cache.fetchedAt || 0) > CAT_CACHE_MAX_AGE);
    if (state.manifestUrl && stale) {
      refreshCatalog(false).catch(() => {});
    } else {
      const upd = updatesAvailable();
      fabDot.hidden = !upd;
      fabDot.textContent = String(upd);
    }
  }

  if (document.body) boot();
  else document.addEventListener('DOMContentLoaded', boot, { once: true });
})();
