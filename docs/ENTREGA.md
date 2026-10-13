# 📦 Relatório de Entrega — USHub

| | |
|---|---|
| **Branch** | `arena/01a0b492-tui-regex` |
| **Data (snapshot)** | 2026-10-11 |
| **Status** | ✅ CI verde — [Actions](https://github.com/camillanapoles/tui-regex/actions/workflows/test.yml) |
| **Produto** | Userscript-hub para **Android mobile** com gestão via **gist público** |
| **Escopo** | 14 arquivos versionados · ≈ 2.800 linhas (código + testes + docs + CI) |

---

## 1. O que foi solicitado

| # | Requisito (brief) | Interpretação executada |
|---|---|---|
| R1 | User script **clicável/interativo para Android mobile** | `ushub.user.js` instalável no Firefox Android (Tampermonkey/Violentmonkey) |
| R2 | Botão com **máxima usabilidade** (UX/UI detalhista: não tapar texto, fontes, cores/contraste) | FAB com 9 decisões de UX auditáveis (item 6) |
| R3 | Ao clicar, ter **"user scripts inside"** — captura real em **único local** | Bottom sheet com catálogo completo + instalar/atualizar/copiar/buscar |
| R4 | **Gestão objeto** integrável: pense em **gist público** | Catálogo = gist público gerenciado por objeto manifesto |
| R5 | Gestão **via JSON + múltiplos arquivos** no gist | `hub.json` (manifesto) + N arquivos `.user.js` no mesmo gist |
| R6 | Entrega **sem erros** (condição de pagamento) | 3 suítes de teste + validação estática + gate de CI |
| R7 | (Rodadas seguintes) **validar completude** e **CI/CD retornando sucesso** | Suítes versionadas em `tests/` + pipeline `test.yml` com 4 portões |

## 2. Timeline — solicitação → incremento entregue

| Rodada | Pedido | O que entrou **além** do pedido |
|---|---|---|
| **T1** | Criar o userscript-hub | README técnico · gist de exemplo com 3 scripts filhos · 12-testes funcionais (jsdom) · **2 bugs encontrados e corrigidos** (abas sem listener; busca quebrando IME do Gboard) |
| **T2** | "Valide completude" | Validação estática cruzada (9 grupos) · 8 cenários-limite (S1–S8) · **3 robustezes**: `cmpVer` tolera `v1.2.3`; card "⚠ Indisponível" quando `file` não existe no gist; re-render ao limpar a fonte |
| **T3** | "Sucesso por CI/CD retornado" | Suítes promovidas ao repo · `package.json`+lock · workflow Actions (matriz Node 20/22) · badge · bump actions v5 (**zero warnings**) · **2 runs verdes comprovados por `gh run watch --exit-status`** |
| **T4** | "Documente tudo + audite o que falta" | Este documento · trigger manual `workflow_dispatch` · `concurrency` (1 run/ref) · resumo do gate no Actions · reconciliação git local↔remoto · auditoria de gaps (item 11) |

## 3. Stack utilizado

| Camada | Tecnologia |
|---|---|
| Produto | **JavaScript ES2020 puro** (zero dependências de runtime) · Userscript API (`GM_*` legada + `GM.*` moderna) · **Shadow DOM** (isolamento de CSS) · CSS custom properties · Pointer Events · `visualViewport` API |
| Dados/gestão | **GitHub Gist público** (storage) · `hub.json` (objeto manifesto) · **GitHub REST API v3** (`/gists/:id`) · `GM_xmlhttpRequest` (ignora CSP/CORS) |
| Persistência local | `GM.setValue/getValue` → fallback `localStorage` |
| Testes | **jsdom** (DOM real headless) · Node **20 e 22** · `node:assert` · `node --check` |
| CI/CD | **GitHub Actions** (ubuntu-latest, actions v5) · npm ci (lockfile) · bash |

## 4. Arquitetura implementada

```
GIST PÚBLICO (gestão objeto)
├─ hub.json ─────────┐  manifesto: id, name, version, description, file, tags
├─ a.user.js         │  (n arquivos, flat — gist não tem pasta)
└─ n.user.js         │
        ▼ api.github.com/gists/:id  (1 chamada → mapa raw_url de TODOS os arquivos)
        ▼ raw_url do hub.json (cache-bust) → parse manifesto
USHub no Android (@match http+s, Shadow DOM root #ushub-host)
├─ FAB </> ─ arrastável/encaixe/idle 38%/some c/ teclado/48px/safe-area
└─ Bottom sheet (scrim, deslizar-p/-fechar, tabs)
    ├─ Catálogo: busca IME-safe · selos ✓/⬆/⚠ · Instalar (window.open raw .user.js
    │  → gerenciador captura) · Copiar código (fallback popup bloqueado)
    └─ Ajustes: URL do gist · tema Auto/Claro/Escuro · A−/A+ · ocultar FAB · auto-refresh
Estado: GM storage (fonte, tema, fontScale 85–140%, posição FAB, instalados, cache 15min)
```

## 5. Inventário versionado neste branch

| Arquivo | Linhas | Papel |
|---|---|---|
| `userscripts/ushub.user.js` | 1088 | **Produto** — instalar este no celular |
| `userscripts/gist/hub.json` | 37 | Manifesto de exemplo (objeto de gestão) |
| `userscripts/gist/*.user.js` ×3 | 178 | Scripts filhos prontos p/ colar no gist |
| `userscripts/README.md` | — | Guia usuário + esquema do hub.json |
| `tests/validate-static.js` | 101 | Portão 2 — completude estática |
| `tests/test-main.js` | 168 | Portão 3 — suíte funcional |
| `tests/test-edge.js` | 174 | Portão 4 — casos-limite S1–S8 |
| `tests/syntax.sh` | 8 | Portão 1 — `node --check` ×4 |
| `.github/workflows/test.yml` | — | Pipeline trigger+gate |
| `package.json` / `package-lock.json` / `.gitignore` | — | Reprodutibilidade (`npm ci`) |
| `docs/ENTREGA.md` | — | Este relatório |

## 6. Realizado (features)

- [x] FAB `</>`: arrastável com encaixe na borda · **translúcido 38% após 4s** (não tapa texto) · **some com o teclado virtual** · 48–52px · `env(safe-area)` · ativável por teclado/AT
- [x] Painel bottom sheet: scrim + deslizar-para-fechar + Escape + restaura foco
- [x] Catálogo: cards com emoji/nome/versão/desc/tags · selos **✓ instalado**, **⬆ atualização (vAtual → vNova)**, **⚠ ausente no gist** (botões desabilitados)
- [x] Busca sem acentos que **não recria o input** (composição Gboard segura)
- [x] A−/A+ 85–140% (persistido) · Tema Auto/Claro/Escuro (contraste 15:1 / 13:1) · `prefers-reduced-motion` · `forced-colors`
- [x] Gestão: subiu `version` no `hub.json` → selo ⬆ e badge no FAB aparecem sozinhos
- [x] Resiliência: cache 15 min + modo offline · erros amigáveis c/ retry · guarda anti-injeção dupla · menu do gerenciador (abrir / ocultar-mostrar FAB)

## 7. Testado

| Suíte | Conteúdo | Resultado |
|---|---|---|
| `test-main.js` | 12 fluxos: boot → onboarding → configurar → catálogo → instalar → ⬆ update → copiar → busca/IME → tema → A+/A− → persistência → multi-página | ✅ Node 20 **e** 22 |
| `test-edge.js` | S1 offline · S2 sem hub.json · S3 JSON quebrado · S4 catálogo vazio · S5 sem resolução · S6 ocultar/mostrar FAB · S7 403+cache · S8 injeção dupla | ✅ Node 20 **e** 22 |
| `syntax.sh` | 4 userscripts via `node --check` | ✅ |

Reproduzir: `npm ci && npm test` (idêntico ao CI).

## 8. Validado (estático)

Metablock completo (`@match` http+s, `@run-at`, `@noframes`, namespace/author/license) · **8 `@grant`** cobrem toda API chamada · **3 `@connect`** cobrem todo host de rede · **11 `data-act` ↔ 11 cases** (zero órfãos) · **13 IDs** consultados existem nos templates · **8 ícones** definidos · `hub.json` ↔ arquivos físicos (nome/case, `@name`/`@version` iguais) · README ↔ implementação (48px, 38%, 15min) · higiene (sem `console.log`/`eval`/`document.write`).

## 9. CI/CD — sim, trigger + gate-driven no GitHub Actions

**Gatilhos ativos:** `push` em `main`/`arena/**` ✅ executado e verde · `pull_request` ✅ armado · `workflow_dispatch` ✅ manual na aba Actions.
**Concorrência:** `concurrency` por ref — push novo cancela run anterior (não empilha).
**Modelo de portões** (qualquer falha = job vermelho = gate fechado):

```
push/PR/dispatch ─▶ matrix {Node 20, Node 22} (fail-fast: false)
                      └─▶ P1 sintaxe ─▶ P2 estática ─▶ P3 funcional ─▶ P4 limites ─▶ ✅ verde
                          (um portão íntegro libera o próximo; falha encerra o job)
```

Evidências: run [38185794164](https://github.com/camillanapoles/tui-regex/actions/runs/38185794164) `conclusion=success` ×2 jobs, 0 warnings · run anterior 38185743096 também verde. Cada run grava **resumo do gate** na aba Summary do Actions.
**Gate obrigatório no merge:** exige *Settings → Branches → protection rule* exigindo o status `Completude USHub *` — config de repositório, não versionável em YAML (passo documentado, a 1 clique do dono).

## 10. Produção — pronto para uso pelo usuário final

1. **Instalar** `userscripts/ushub.user.js` (raw do repo) no Firefox Android + Tampermonkey;
2. **Criar gist público** colando os 4 arquivos de `userscripts/gist/`;
3. No site qualquer: tocar `</>` → **Ajustes** → colar URL do gist → **Salvar e carregar** → instalar os scripts pelo catálogo.
Gestão posterior = editar o gist e subir `version` no `hub.json`. Nenhum backend, nenhum dado sai do aparelho (exceto leitura pública do gist).

## 11. Auditoria — o que FALTA (declaração honesta)

| # | Gap | Sev. | Mitigação vigente | Estado |
|---|---|---|---|---|
| G1 | Teste em **Android físico** (gestos/render reais) — jsdom não emula GPU/touch | Alta p/ UX final | Checklist manual no README; padrões de plataforma; lógica de gestos testada em DOM | ⏳ pendente com o usuário |
| G2 | **Gist real** do usuário ainda não existe (placeholder no onboarding) | Média | 4 arquivos prontos p/ colar + passo a passo | ⏳ 1 min do usuário |
| G3 | Instalação real via Tampermonkey não é automatizável em CI | Baixa | click→URL `.user.js` testado (mecanismo-padrão) + fallback Copiar código | ✅ mitigado |
| G4 | Proteção de branch (gate bloquear merge) é config da UI, não YAML | Baixa | Item 9 documenta o clique exato | ⏳ decisão do dono |
| G5 | Rate limit API pública 60 req/h/IP | Baixa | cache 15min + fallback offline; alternativa: URL crua direta | ✅ mitigado |
| G6 | Badge só fica verde na `main` após merge/PR | Info | PR a partir deste branch | ⏳ aguardando OK |
| G7 | iOS fora de escopo | Info | Brief diz Android; Safari userscripts = outro gerenciador | 📌 fora de escopo |

## 12. Próximos passos sugeridos

1. Abrir PR `arena/01a0b492-tui-regex` → `main` (CI já armada como status check);
2. Criar o gist real e validar G1/G2 no celular (checklist de 6 toques no README);
3. Ativar branch protection com o status `Completude USHub *`.

---
*Relatório gerado na rodada T4. Tudo aqui é reproduzível: `npm ci && npm test` + Actions linkado.*
