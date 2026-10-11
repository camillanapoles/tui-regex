/* Casos-limite funcionais do USHub (jsdom): falhas de rede, gist malformado,
   fonte sem resolução de arquivo, catálogo vazio, ocultar botão, cache offline. */
'use strict';
const fs = require('fs');
const assert = require('assert');
const { JSDOM } = require('jsdom');

const REPO = require('path').join(__dirname, '..', 'userscripts');
const src = fs.readFileSync(REPO + '/ushub.user.js', 'utf8');
const GIST_ID = '0123456789abcdef0123456789abcdef';
const rawBase = `https://gist.githubusercontent.com/camillanapoles/${GIST_ID}/raw/deadbeef`;
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

function makeDom(netImpl, preset) {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', {
    url: 'https://exemplo.com/', runScripts: 'outside-only', pretendToBeVisual: true
  });
  const w = dom.window;
  const store = preset ? { 'ushub:state:v1': preset } : {};
  w.__store = store;
  w.GM_getValue = async (k, d) => (k in store ? store[k] : d);
  w.GM_setValue = async (k, v) => { store[k] = v; };
  w.__menus = [];
  w.GM_registerMenuCommand = (l, f) => { w.__menus.push({ label: l, fn: f }); };
  w.GM_xmlhttpRequest = netImpl;
  w.__opened = [];
  w.open = (u) => { w.__opened.push(u); return {}; };
  Object.defineProperty(w.navigator, 'clipboard', { value: { writeText: async (t) => { w.__copied = t; } }, configurable: true });
  return w;
}

function net({ apiFiles, hubBody, status = 200, fail = false }) {
  return ({ url, onload, onerror }) => setTimeout(() => {
    if (fail) return onerror(new Error('offline'));
    const u = url.replace(/[?&]_ushub=\d+/g, '').replace(/\?$/, '');
    if (u.includes('api.github.com/gists/')) {
      if (status !== 200) return onload({ status, responseText: '{"message":"rate limit"}' });
      return onload({ status: 200, responseText: JSON.stringify({ files: apiFiles }) });
    }
    if (u.endsWith('/hub.json') || u.startsWith('https://example.com/hub.json')) {
      if (status !== 200) return onload({ status, responseText: 'err' });
      return onload({ status: 200, responseText: hubBody });
    }
    return onload({ status: 404, responseText: 'nf' });
  }, 0);
}

async function configurarFonte(w, fonte) {
  const host = w.document.getElementById('ushub-host');
  w.__menus[0].fn(); // abre o painel
  host.shadowRoot.querySelector('[data-tab="config"]').dispatchEvent(new w.MouseEvent('click', { bubbles: true, composed: true }));
  host.shadowRoot.querySelector('#srcUrl').value = fonte;
  host.shadowRoot.querySelector('[data-act="save-url"]').dispatchEvent(new w.MouseEvent('click', { bubbles: true, composed: true }));
  await wait(70);
  return host;
}

const S = (w, sel) => w.document.getElementById('ushub-host').shadowRoot.querySelector(sel);

(async () => {
  /* S1 — offline sem cache → cartão de erro com "Tentar de novo" */
  {
    const w = makeDom(net({ fail: true }));
    w.eval(src); await wait(25);
    await configurarFonte(w, `https://gist.github.com/camillanapoles/${GIST_ID}`);
    const html = S(w, '#main').innerHTML;
    assert(html.includes('Não deu para carregar'), 'S1: erro exibido');
    assert(html.includes('Tentar de novo'), 'S1: ação de retry clara');
    console.log('S1 ✓ offline sem cache → erro amigável + retry');
  }

  /* S2 — gist sem hub.json → mensagem específica */
  {
    const w = makeDom(net({ apiFiles: { 'foo.user.js': { raw_url: rawBase + '/foo.user.js' } } }));
    w.eval(src); await wait(25);
    await configurarFonte(w, `https://gist.github.com/camillanapoles/${GIST_ID}`);
    assert(S(w, '#main').innerHTML.includes('não tem um arquivo hub.json'), 'S2: diagnóstico do hub.json ausente');
    console.log('S2 ✓ gist sem hub.json → diagnóstico específico');
  }

  /* S3 — hub.json com JSON quebrado → erro tratado (não quebra o painel) */
  {
    const w = makeDom(net({ apiFiles: { 'hub.json': { raw_url: rawBase + '/hub.json' } }, hubBody: '{ isso nao e json' }));
    w.eval(src); await wait(25);
    await configurarFonte(w, `https://gist.github.com/camillanapoles/${GIST_ID}`);
    const html = S(w, '#main').innerHTML;
    assert(html.includes('Não deu para carregar'), 'S3: erro de parse exibido');
    assert(!html.includes('undefined'), 'S3: sem "undefined" vazando na UI');
    console.log('S3 ✓ JSON quebrado → erro tratado, painel íntegro');
  }

  /* S4 — catálogo vazio (scripts: []) → UI estável */
  {
    const w = makeDom(net({
      apiFiles: { 'hub.json': { raw_url: rawBase + '/hub.json' } },
      hubBody: JSON.stringify({ hub: 'Vazio', scripts: [] })
    }));
    w.eval(src); await wait(25);
    const host = await configurarFonte(w, `https://gist.github.com/camillanapoles/${GIST_ID}`);
    assert(S(w, '#main').innerHTML.includes('0 script(s)'), 'S4: contagem zero exibida');
    assert(S(w, '#q'), 'S4: busca presente mesmo vazio');
    assert.strictEqual(S(w, '#fabDot').hidden, true, 'S4: badge oculto sem updates');
    console.log('S4 ✓ catálogo vazio → UI consistente, badge oculto');
  }

  /* S5 — URL crua direta (sem ID de gist): "file" não resolve → botões desabilitam com aviso */
  {
    const hubBody = JSON.stringify({ hub: 'Externo', scripts: [
      { id: 'x', name: 'Sem Arquivo', version: '1.0.0', file: 'x.user.js', description: 'teste' }
    ] });
    const w = makeDom(net({ hubBody }));
    w.eval(src); await wait(25);
    await configurarFonte(w, 'https://example.com/hub.json');
    const html = S(w, '#main').innerHTML;
    assert(html.includes('ausente no gist'), 'S5: aviso de arquivo ausente');
    assert(html.includes('Indisponível'), 'S5: botão principal desabilitado');
    assert(!S(w, '[data-act="install"]'), 'S5: nenhum instalável sem fonte');
    S(w, '#main').querySelector('button[disabled]');
    console.log('S5 ✓ fonte sem resolução de arquivo → estado “Indisponível” explícito');
  }

  /* S6 — ocultar/mostrar botão flutuante (config + menu do gerenciador) */
  {
    const w = makeDom(net({
      apiFiles: { 'hub.json': { raw_url: rawBase + '/hub.json' } },
      hubBody: JSON.stringify({ hub: 'X', scripts: [] })
    }));
    w.eval(src); await wait(25);
    const host = w.document.getElementById('ushub-host');
    assert.strictEqual(host.dataset.fab, 'visible', 'S6: visível por padrão');
    w.__menus[0].fn();
    host.shadowRoot.querySelector('[data-tab="config"]').dispatchEvent(new w.MouseEvent('click', { bubbles: true, composed: true }));
    host.shadowRoot.querySelector('[data-act="fab-hidden"]').dispatchEvent(new w.MouseEvent('click', { bubbles: true, composed: true }));
    await wait(350); // debounce do save
    assert.strictEqual(JSON.parse(JSON.stringify(w.__store['ushub:state:v1'])).ui.fabHidden, true, 'S6: preferência persistida');
    // menu "mostrar botão" numa NOVA página com o mesmo storage
    const w2 = makeDom(net({ hubBody: '{}' }), JSON.parse(JSON.stringify(w.__store['ushub:state:v1'])));
    w2.eval(src); await wait(25);
    const host2 = w2.document.getElementById('ushub-host');
    assert.strictEqual(host2.dataset.fab, 'hidden', 'S6: botão oculto restaurado');
    assert(w2.__menus.some((m) => m.label.includes('mostrar botão')), 'S6: menu oferece reexibir');
    w2.__menus.find((m) => m.label.includes('mostrar botão')).fn();
    assert.strictEqual(host2.dataset.fab, 'visible', 'S6: menu reexibe o botão');
    console.log('S6 ✓ ocultar/mostrar FAB (config + menu) com persistência');
  }

  /* S7 — API fora (rate limit 403) MAS com cache → mostra cache + aviso */
  {
    const cache = { url: 'x', fetchedAt: Date.now(), data: {
      manifest: { hub: 'Cache Hub' },
      scripts: [{ id: 'a', name: 'Do Cache', emoji: '📦', version: '1.0.0', file: 'a.user.js', raw: 'https://r/a.user.js' }],
      fetchedAt: Date.now()
    } };
    const w = makeDom(net({ status: 403 }), { manifestUrl: `https://gist.github.com/u/${GIST_ID}`, cache, ui: { autoRefresh: true } });
    w.eval(src); await wait(25);
    w.__menus[0].fn();
    await wait(70);
    const html = S(w, '#main').innerHTML;
    assert(html.includes('Do Cache'), 'S7: conteúdo do cache visível');
    assert(html.includes('cópia em cache'), 'S7: aviso de cache exibido');
    console.log('S7 ✓ 403/rate-limit com cache → degradação elegante');
  }

  /* S8 — injeção dupla (SPA/turbo) → um único host */
  {
    const w = makeDom(net({ hubBody: '{}' }));
    w.eval(src); w.eval(src); await wait(25);
    assert.strictEqual(w.document.querySelectorAll('#ushub-host').length, 1, 'S8: guarda contra injeção dupla');
    console.log('S8 ✓ execução dupla neutralizada');
  }

  console.log('\n✅ TODOS OS CASOS-LIMITE PASSARAM (S1–S8)');
  process.exit(0);
})().catch((e) => { console.error('\n❌ FALHOU:', e.message); process.exit(1); });
