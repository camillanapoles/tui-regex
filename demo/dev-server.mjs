#!/usr/bin/env node
/* Demo dev-server do USHub — validar no Android SEM instalar nada.
 * Sobe: página de teste + o ushub.user.js real + proxy /gm (emula GM_xmlhttpRequest).
 * Uso: node demo/dev-server.mjs   (bind 0.0.0.0:4173)
 */
'use strict';

import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, join, normalize } from 'node:path';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const PORT = process.env.PORT || 4173;
/* Egresso restrito: só api.github.com sai do sandbox. URLs raw.* são mapeadas
 * para a Contents API (conteúdo cru idêntico). */
function mapAllowed(target) {
  const m = target.match(/^https:\/\/raw\.githubusercontent\.com\/([^/]+)\/([^/]+)\/([^/]+)\/(.+)$/);
  if (m) {
    return {
      url: `https://api.github.com/repos/${m[1]}/${m[2]}/contents/${m[4]}?ref=${m[3]}`,
      headers: { 'Accept': 'application/vnd.github.raw+json', 'User-Agent': 'ushub-demo' }
    };
  }
  if (/^https:\/\/api\.github\.com\//.test(target)) {
    return { url: target, headers: { 'Accept': 'application/vnd.github+json', 'User-Agent': 'ushub-demo' } };
  }
  return null;
}

const MIME = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.json': 'application/json; charset=utf-8' };

const server = createServer(async (req, res) => {
  try {
    const u = new URL(req.url, 'http://x');
    if (u.pathname === '/gm') {
      const target = mapAllowed(u.searchParams.get('u') || '');
      if (!target) { res.writeHead(403, { 'content-type': 'text/plain' }); res.end('host fora da allowlist (use raw.githubusercontent.com ou api.github.com; gists exigem a API /gists do repositório dono)'); return; }
      const r = await fetch(target.url, { headers: target.headers, redirect: 'follow' });
      const body = await r.text();
      res.writeHead(r.status, { 'content-type': 'text/plain; charset=utf-8', 'access-control-allow-origin': '*' });
      res.end(body);
      return;
    }
    const p = u.pathname === '/' ? '/demo/index.html' : decodeURIComponent(u.pathname);
    const file = normalize(join(ROOT, p));
    if (!file.startsWith(ROOT)) { res.writeHead(403); res.end(); return; }
    const data = await readFile(file).catch(() => null);
    if (!data) { res.writeHead(404); res.end('nf'); return; }
    res.writeHead(200, { 'content-type': MIME[p.slice(p.lastIndexOf('.'))] || 'text/plain; charset=utf-8' });
    res.end(data);
  } catch (e) {
    res.writeHead(500); res.end(String(e && e.message || e));
  }
});

server.listen(PORT, '0.0.0.0', () => console.log(`USHub demo em http://0.0.0.0:${PORT}/`));
