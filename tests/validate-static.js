/* Validação estática cruzada de completude do USHub. */
'use strict';
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const REPO = require('path').join(__dirname, '..', 'userscripts');
const us = fs.readFileSync(REPO + '/ushub.user.js', 'utf8');

/* 1. Metadados ==UserScript== completos */
const mb = us.match(/\/\/ ==UserScript==([\s\S]*?)\/\/ ==\/UserScript==/);
assert(mb, 'metablock existe');
const directives = {};
for (const line of mb[1].split('\n')) {
  const m = line.match(/^\s*\/\/ @(\S+)(?:[ \t]+(.*))?$/);
  if (m) (directives[m[1]] = directives[m[1]] || []).push((m[2] || '').trim());
}
for (const req of ['name', 'version', 'description', 'match', 'grant', 'connect', 'noframes', 'run-at', 'namespace', 'author', 'license']) {
  assert(directives[req], 'diretiva @' + req + ' presente');
}
assert(directives.match.includes('http://*/*') && directives.match.includes('https://*/*'), '@match http+https');
assert.strictEqual(directives['run-at'][0], 'document-idle', 'run-at document-idle');

/* 2. @grant cobre todas as variantes de API usadas no código */
const grants = new Set(directives.grant);
for (const g of ['GM.getValue', 'GM.setValue', 'GM.xmlHttpRequest', 'GM.registerMenuCommand',
                 'GM_getValue', 'GM_setValue', 'GM_xmlhttpRequest', 'GM_registerMenuCommand']) {
  assert(grants.has(g), '@grant ' + g);
}

/* 3. @connect cobre todos os hosts de rede usados em httpGet */
const connects = new Set(directives.connect);
for (const h of ['api.github.com', 'gist.githubusercontent.com', 'raw.githubusercontent.com']) {
  assert(connects.has(h), '@connect ' + h);
}
for (const m of us.matchAll(/httpGet\(\s*(?:bust\()?\s*'([^']+)'/g)) {
  const hm = m[1].match(/^https:\/\/([^/]+)/);
  if (hm) assert(connects.has(hm[1]), 'host literal de httpGet coberto por @connect: ' + hm[1]);
}

/* 4. Todo data-act do HTML tem case no switch (e vice-versa reportado) */
const acts = new Set([...us.matchAll(/data-act="([a-z0-9+-]+)"/gi)].map((m) => m[1]));
const cases = new Set([...us.matchAll(/case '([a-z0-9+-]+)':/g)].map((m) => m[1]));
const semHandler = [...acts].filter((a) => !cases.has(a));
assert.strictEqual(semHandler.length, 0, 'data-act SEM handler: ' + semHandler.join(','));
const orfaos = [...cases].filter((c) => !acts.has(c));
assert.strictEqual(orfaos.length, 0, 'handlers órfãos: ' + orfaos.join(','));

/* 5. Todo ID consultado via $('#x') existe como id="x" em algum template */
const usedIds = new Set([...us.matchAll(/\$\('#([A-Za-z0-9-]+)'\)/g)].map((m) => m[1]));
const definedIds = new Set([...us.matchAll(/id="([A-Za-z0-9-]+)"/g)].map((m) => m[1]));
const idsFaltando = [...usedIds].filter((i) => !definedIds.has(i));
assert.strictEqual(idsFaltando.length, 0, 'IDs consultados mas inexistentes: ' + idsFaltando.join(','));

/* 6. Todo ICONS.x usado está definido */
const iconsUsed = new Set([...us.matchAll(/ICONS\.([a-zA-Z]+)/g)].map((m) => m[1]));
const iconsDefined = new Set([...us.matchAll(/^ {4}([a-zA-Z]+): '<svg/gm)].map((m) => m[1]));
const iconsFaltando = [...iconsUsed].filter((i) => !iconsDefined.has(i));
assert.strictEqual(iconsFaltando.length, 0, 'ícones usados sem definição: ' + iconsFaltando.join(','));

/* 7. hub.json consistente com os arquivos físicos do gist */
const hub = JSON.parse(fs.readFileSync(REPO + '/gist/hub.json', 'utf8'));
assert(Array.isArray(hub.scripts) && hub.scripts.length >= 1, 'hub.json tem scripts');
const filesSeen = new Set();
const idsSeen = new Set();
for (const s of hub.scripts) {
  for (const f of ['id', 'name', 'version', 'file']) assert(s[f], `campo "${f}" obrigatório em ${s.id || s.name}`);
  assert(/^\d+\.\d+\.\d+/.test(s.version), 'semver em ' + s.id);
  assert(!idsSeen.has(s.id), 'id duplicado: ' + s.id);
  assert(!filesSeen.has(s.file), 'file duplicado: ' + s.file);
  idsSeen.add(s.id); filesSeen.add(s.file);
  const p = path.join(REPO, 'gist', s.file);
  assert(fs.existsSync(p), 'arquivo existe no diretório gist/: ' + s.file);
  assert.strictEqual(path.basename(p), s.file, 'nome/case do arquivo bate com hub.json: ' + s.file);
  const child = fs.readFileSync(p, 'utf8');
  const cmb = child.match(/\/\/ ==UserScript==([\s\S]*?)\/\/ ==\/UserScript==/);
  assert(cmb, 'metablock do filho ' + s.file);
  const cver = ((cmb[1].match(/\/\/ @version\s+(\S+)/)) || [])[1];
  assert.strictEqual(cver, s.version, `@version de ${s.file} (${cver}) == hub.json (${s.version})`);
  const cname = ((cmb[1].match(/\/\/ @name\s+(.+)/)) || [])[1].trim();
  assert.strictEqual(cname, s.name, `@name de ${s.file} == hub.json ("${cname}")`);
  assert(child.includes('@match'), '@match no filho ' + s.file);
}

/* 8. Afiando README contra a implementação (afirmações ↔ código) */
const readme = fs.readFileSync(REPO + '/README.md', 'utf8');
for (const claim of ['hub.json', 'bottom sheet', 'Shadow DOM', '48 px', '15 min', '38%', 'A− / A+', '@connect']) {
  assert(readme.includes(claim), 'README documenta: ' + claim);
}
assert(us.includes('CAT_CACHE_MAX_AGE = 15 * 60 * 1000'), 'cache de 15 min existe no código');
assert(us.includes("opacity: .38"), 'opacidade ociosa 38% no código');
assert(us.includes('--touch: 48px'), 'alvo de toque 48px no código');

/* 9. Higiene do artefato final */
assert(!/console\.log/.test(us.split('==/UserScript==')[1]), 'sem console.log no código final');
assert(!us.includes('document.write'), 'sem document.write');
assert(!/eval\(/.test(us), 'sem eval no userscript');

console.log('✅ ESTÁTICA OK — metablock ✓ grants ✓ connects ✓ data-act↔case (' +
  acts.size + ') ✓ IDs↔templates (' + usedIds.size + ') ✓ ícones (' + iconsUsed.size +
  ') ✓ hub.json↔arquivos (' + hub.scripts.length + ' scripts) ✓ README↔código ✓ higiene ✓');
