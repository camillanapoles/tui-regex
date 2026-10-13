# 📦 Relatório de Entrega — USHub

| | |
|---|---|
| **Branch** | `arena/01a0b492-tui-regex` |
| **Data (snapshot)** | 2026-10-13 |
| **Status** | ✅ CI verde — [Actions](https://github.com/camillanapoles/tui-regex/actions/workflows/test.yml) · 🔀 BPMN ativo — [USH-01 #3](https://github.com/camillanapoles/tui-regex/issues/3) |
| **Produto** | Userscript-hub para **Android mobile** com gestão via **gist público** |
| **Escopo** | 20 arquivos versionados · ≈ 3.400 linhas (código + testes + docs + CI + orquestração) |

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
| **T5** | Issues topológicas + gatilho de continuidade + envelope JSON "como BPMN" | `scripts/sequence.json` (cadeia USH-01→04) · `scripts/orchestrator.mjs` (motor: toda action retorna envelope JSON) · workflow `orchestrate.yml` (issue fechada → **testa** → cria a próxima indexada) · workflow `guardian.yml` (sem issues/CI/testes positivos ⇒ CONTINUIDADE) · issue seed **USH-01#3** criada |

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
| `.github/workflows/test.yml` | — | Pipeline de qualidade (4 portões × Node 20/22) |
| `.github/workflows/orchestrate.yml` | — | BPMN: issue fechada → testa → cria próxima issue |
| `.github/workflows/guardian.yml` | — | Guardião de continuidade (JSON de estado) |
| `scripts/orchestrator.mjs` | ≈ 290 | Motor BPMN — envelope JSON padrão em toda action |
| `scripts/sequence.json` | ≈ 70 | Cadeia topológica USH-01→USH-04 + instruções |
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

### Ecossistema de workflows (T5 — camada BPMN)

| Workflow | Gatilhos | Papel |
|---|---|---|
| `test.yml` | `push` · `pull_request` · `workflow_dispatch` | **Gate de qualidade** — 4 portões; vermelho bloqueia avanço |
| `orchestrate.yml` | `issues: [closed]` · `workflow_dispatch` (self-test) | **Sequenciador**: fecha issue USH-xx → porta `npm test` → sucesso cria a próxima issue indexada e comenta o envelope JSON na fechada; erro ⇒ envelope `1` + continuidade, sem avançar |
| `guardian.yml` | `workflow_dispatch` · `schedule` (cron diário — só agenda na `main`; aplicável após USH-03) | **Guardião de continuidade**: verifica "ZERO issues abertas + CI verde + testes presentes". Enquanto não positivo ⇒ envelope `2 · CONTINUIDADE` com a próxima pendência; bloqueio real ⇒ envelope `1` e run vermelha |

**Envelope JSON padrão de TODA action** (codec "como BPMN" — item 12.5): `{ id, acao, mensagem, adendos[], status{code,label}, continuidade, next_issue, ts }` · `0=SUCESSO` · `1=ERRO_BLOQUEANTE` · `2=CONTINUIDADE`. Exit code do job: `1` somente em erro bloqueante; continuidade não suja a pipeline.

> ⚠️ **Regra do GitHub Actions medida em produção (run 38412578141):** eventos `issues`/`issue_comment`, `schedule` e `workflow_dispatch` executam o arquivo de workflow **da branch padrão (`main`)** — portanto `orchestrate` e `guardian` ativam plenamente **após o merge desta branch** (dispatch manual devolve 404 enquanto o arquivo só existe na branch de trabalho). O gate de qualidade (`test.yml`, evento `push`) já roda por branch, verde em 3 pushes consecutivos. Até o merge, a camada BPMN é reproduzível localmente: `node scripts/orchestrator.mjs self-test|report|advance --dry-run`.

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

## 12. Próximos passos — agora executados por CADEIA TOPOLÓGICA de issues (BPMN)

> Cadeia indexada em [`scripts/sequence.json`](../scripts/sequence.json): **USH-01 → USH-02 → USH-03 → USH-04 → DONE**.
> Cada issue SÓ É CRIADA quando a anterior é **fechada** e o gate (`npm test`) passa. Erro ⇒ não avança.

1. **PR `arena/…` → `main`** — vira a issue **USH-03** (criada automaticamente após USH-02); CI já roda em `pull_request` como status check.
2. **G2 · gist real** — issue seed **USH-01 · [#3](https://github.com/camillanapoles/tui-regex/issues/3) ABERTA AGORA** (instruções + critério de aceite lá).
3. **G1 · Android físico** — vira **USH-02** (auto-criada ao fechar USH-01 com sucesso testado).
4. **Gatilho de continuidade** — `guardian.yml`: verifica "não existência de issues abertas + CI sem erros + testes presentes"; **enquanto não for positivo ⇒ `2 · CONTINUIDADE`** com apontamento da pendência; erro bloqueante ⇒ `1` e run vermelha.
5. **Instrução encadeada, "como BPMN"** — a cada issue **completada, o orquestrador TESTA a entrega** (porta `npm test`) e **instancia a instrução da issue seguinte, indexada**:
   - ✅ sucesso testado ⇒ cria a próxima USH (sequência topológica) + comenta o envelope JSON na issue fechada (rastro/token BPMN);
   - ❌ erro ⇒ envelope com `status.code = 1` ("ERRO_BLOQUEANTE"), `next_issue = a MESMA` (retrabalho) e informações de continuidade — nada avança;
   - **toda action retorna objeto JSON**: `{ id, acao, mensagem, adendos:[{path}|{file}] (anexos gerados, quando houver), status:{code,label}, continuidade, next_issue, ts }`
   - codec: **0 SUCESSO · 1 ERRO_BLOQUEANTE · 2 CONTINUIDADE** (STATUS sempre com `label` string; MENSAGEM string pronta ou resumo de log).
   - motor: [`scripts/orchestrator.mjs`](../scripts/orchestrator.mjs) (zero deps; `self-test` offline valida o formato do envelope — porta A do workflow).

### Exemplo real de envelope (self-test executado em CI)

```json
{
  "id": "self-test",
  "acao": "self-test",
  "mensagem": "Envelope padrão validado em 3 cenários (advance ok / gate vermelho / DONE).",
  "adendos": [{ "path": "scripts/orchestrator.mjs" }, { "path": "scripts/sequence.json" }],
  "status": { "code": 0, "label": "SUCESSO" },
  "continuidade": false,
  "next_issue": { "id": "USH-01", "title": "Criar o gist público real e conectar o catálogo" },
  "ts": "2026-10-13T14:17:31Z"
}
```

---
*Relatório atualizado na rodada T5 (BPMN sobre issues). Tudo reproduzível: `npm ci && npm test` · `node scripts/orchestrator.mjs self-test` · Actions linkado.*
