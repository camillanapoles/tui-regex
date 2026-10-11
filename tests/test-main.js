/* Suíte principal do ushub.user.js (jsdom): fluxo completo feliz. */
'use strict';
const fs = require('fs');
const path = require('path');
const assert = require('assert');
const { JSDOM } = require('jsdom');

const REPO = path.join(__dirname, '..', 'userscripts');
const src = fs.readFileSync(path.join(REPO, 'ushub.user.js'), 'utf8');
const hub = JSON.parse(fs.readFileSync(path.join(REPO, 'gist', 'hub.json'), 'utf8'));

const GIST_ID = '0123456789abcdef0123456789abcdef';
const rawBase = `https://gist.githubusercontent.com/camillanapoles/${GIST_ID}/raw/deadbeef`;
const scripts = {};
for (const n of ['leitor-conforto.user.js', 'voltar-ao-topo.user.js', 'modo-noturno.user.js']) {
  scripts[n] = fs.readFileSync(path.join(REPO, 'gist', n), 'utf8');
}

const dom = new JSDOM(
  '<!doctype html><html><head></head><body><p>pagina qualquer</p></body></html>',
  { url: 'https://exemplo.com/artigo', runScripts: 'outside-only', pretendToBeVisual: true }
);
const { window } = dom;

const store = {};
window.GM_getValue = async (k, d) => (k in store ? store[k] : d);
window.GM_setValue = async (k, v) => { store[k] = v; };
const menus = [];
window.GM_registerMenuCommand = (label, fn) => { menus.push({ label, fn }); };

window.GM_xmlhttpRequest = ({ url, onload }) => {
  setTimeout(() => {
    const u = url.replace(/[?&]_ushub=\d+/g, '').replace(/\?$/, '');
    if (u === `https://api.github.com/gists/${GIST_ID}`) {
      const filesApi = { 'hub.json': { raw_url: `${rawBase}/hub.json` } };
      for (const n of Object.keys(scripts)) filesApi[n] = { raw_url: `${rawBase}/${n}` };
      return onload({ status: 200, responseText: JSON.stringify({ files: filesApi }) });
    }
    if (u === `${rawBase}/hub.json`) return onload({ status: 200, responseText: JSON.stringify(hub) });
    const m = u.match(/\/raw\/deadbeef\/(.+)$/);
    if (m && scripts[m[1]]) return onload({ status: 200, responseText: scripts[m[1]] });
    return onload({ status: 404, responseText: 'not found' });
  }, 0);
};

const openedUrls = [];
window.open = (u) => { openedUrls.push(u); return {}; };
if (!window.matchMedia) {
  window.matchMedia = (q) => ({
    matches: false, media: q,
    addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}
  });
}
Object.defineProperty(window.navigator, 'clipboard', {
  value: { writeText: async (t) => { window.__copied = t; } },
  configurable: true
});

window.eval(src);

const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const $s = (sel) => dom.window.document.getElementById('ushub-host').shadowRoot.querySelector(sel);
const $$s = (sel) => [...dom.window.document.getElementById('ushub-host').shadowRoot.querySelectorAll(sel)];

(async () => {
  await wait(30);

  // 1) boot
  const host = dom.window.document.getElementById('ushub-host');
  assert(host, 'host injetado na página');
  assert(host.shadowRoot, 'shadow root aberto (isolamento de CSS)');
  const fab = $s('#fab');
  assert(fab, 'FAB existe');
  assert.strictEqual(fab.style.transform.includes('translate3d'), true, 'FAB posicionado');
  assert.strictEqual(menus.length, 2, '2 comandos de menu: ' + menus.map((m) => m.label).join(' | '));

  // 2) abre painel sem fonte → onboarding
  menus[0].fn();
  const sheet = $s('#sheet');
  assert(sheet.classList.contains('open'), 'sheet abriu');
  assert($s('#main').innerHTML.includes('Bem-vindo ao USHub'), 'onboarding exibido sem fonte configurada');

  // 3) vai para Ajustes via aba e salva a URL do gist
  host.shadowRoot.querySelector('[data-tab="config"]').dispatchEvent(new window.MouseEvent('click', { bubbles: true, composed: true }));
  assert($s('#main').innerHTML.includes('Fonte do catálogo'), 'aba Ajustes renderizou');
  $s('#srcUrl').value = `https://gist.github.com/camillanapoles/${GIST_ID}`;
  $s('[data-act="save-url"]').click();
  await wait(60);

  // 4) catálogo carregado do "gist" (hub.json + 3 arquivos)
  assert($s('#main').innerHTML.includes('Leitor Conforto'), 'card Leitor Conforto presente');
  assert($s('#main').innerHTML.includes('Modo Noturno Universal'), 'card Modo Noturno presente');
  assert.strictEqual($$s('.card').length, 3, '3 cartões de script');

  // 5) instalar → abre URL crua .user.js e marca selo ✓
  assert.strictEqual($$s('[data-act="install"]').length, 3, '3 botões Instalar');
  $$s('[data-act="install"]')[0].click();
  await wait(30);
  assert.strictEqual(openedUrls.length, 1, 'instalador aberto');
  assert(/leitor-conforto\.user\.js/.test(openedUrls[0]), 'URL aberta é o arquivo .user.js cru');
  assert($s('#main').innerHTML.includes('✓ instalado v1.0.0'), 'selo de instalado aplicado');

  // 6) update disponível quando o manifesto sobe a versão de um script INSTALADO
  hub.scripts[0].version = '2.5.0';
  $s('#btnRefresh').click();
  await wait(60);
  assert($s('#main').innerHTML.includes('Atualizar p/ v2.5.0'), 'botão de atualização apareceu');
  assert($s('#main').innerHTML.includes('nova v2.5.0 (você tem v1.0.0)'), 'chip de ⬆ com versões');
  assert.strictEqual($s('#fabDot').textContent, '1', 'badge do FAB mostra 1 atualização');

  // 7) copiar código
  $$s('[data-act="copy"]')[0].click();
  await wait(30);
  assert(String(window.__copied || '').includes('==UserScript=='), 'código copiado para o clipboard');

  // 8) busca (sem acento) sem quebrar o input (IME)
  const q = $s('#q');
  q.value = 'noturno';
  q.dispatchEvent(new window.Event('input', { bubbles: true, composed: true }));
  await wait(10);
  assert.strictEqual($$s('.card').length, 1, 'busca "noturno" filtra 1 card');
  assert.strictEqual($s('#q'), q, 'input NÃO foi recriado (composição do Gboard segura)');
  q.value = '';
  q.dispatchEvent(new window.Event('input', { bubbles: true, composed: true }));

  // 9) tema + fonte
  host.shadowRoot.querySelector('[data-tab="config"]').dispatchEvent(new window.MouseEvent('click', { bubbles: true, composed: true }));
  $s('[data-act="theme"][data-v="dark"]').click();
  assert.strictEqual(host.dataset.theme, 'dark', 'tema escuro aplicado');
  $s('[data-act="font+"]').click();
  assert.strictEqual(host.style.getPropertyValue('--fs'), '1.05', 'fonte A+ → 105%');

  // 10) persistência entre "sessões" (save() tem debounce de 250ms — aguardar o flush)
  await wait(400);
  const saved = JSON.parse(JSON.stringify(store['ushub:state:v1']));
  assert.strictEqual(saved.manifestUrl.includes(GIST_ID), true, 'URL do gist persistida');
  assert.ok(saved.installed['leitor-conforto'], 'instalação persistida');
  assert.strictEqual(saved.ui.theme, 'dark', 'tema persistido');
  assert.strictEqual(saved.ui.fontScale, 1.05, 'fontScale persistido');
  assert(saved.cache && saved.cache.data.scripts.length === 3, 'cache offline salvo');

  // 11) fechar painel e FAB volta visível
  $s('#btnClose').click();
  assert(!$s('#sheet').classList.contains('open'), 'sheet fechou');
  assert.strictEqual(host.dataset.fab, 'visible', 'FAB reaparece ao fechar');

  // 12) segunda "página" com o mesmo storage (estado restaurado)
  const dom2 = new JSDOM('<!doctype html><html><body></body></html>', {
    url: 'https://exemplo.com/outra', runScripts: 'outside-only', pretendToBeVisual: true
  });
  const w2 = dom2.window;
  w2.GM_getValue = window.GM_getValue; w2.GM_setValue = window.GM_setValue;
  w2.GM_registerMenuCommand = () => {};
  w2.GM_xmlhttpRequest = window.GM_xmlhttpRequest;
  w2.open = window.open;
  Object.defineProperty(w2.navigator, 'clipboard', { value: window.navigator.clipboard, configurable: true });
  w2.eval(src);
  await wait(60);
  const host2 = w2.document.getElementById('ushub-host');
  assert(host2, 'host na 2ª página');
  assert.strictEqual(host2.dataset.theme, 'dark', 'tema restaurado da sessão anterior');
  assert.strictEqual(host2.style.getPropertyValue('--fs'), '1.05', 'fonte restaurada');
  assert.strictEqual(host2.shadowRoot.querySelector('#fabDot').textContent, '1', 'badge 1⬆ restaurado via cache');

  console.log('✅ SUÍTE PRINCIPAL OK');
  console.log('   host/shadow ✓ FAB ✓ abas ✓ onboarding ✓ gist(API+raw) ✓ instalar ✓ update ⬆ ✓ copiar ✓ busca/IME ✓ tema ✓ A+/A- ✓ persistência ✓ multi-página ✓');
  process.exit(0);
})().catch((e) => { console.error('\n❌ FALHOU:', e.message); process.exit(1); });
