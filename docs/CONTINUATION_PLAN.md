# CONTINUATION PLAN — Team Builder WASM · Fase 2

Plano de continuidade estruturado em **Epics → Features → Tarefas**, com as
**gates** e **objetos** que cada um exige manter 100% relacionados (PK/FK).
Tudo parte do estado atual (v2.0.0, 116 testes verdes, 94% cobertura).

> Convenção: cada feature lista (a) objetivo, (b) stack, (c) conexões
> (objetos/gates existentes que ela toca), (d) tarefas, (e) nova gate quando
> houver e (f) novos objetos relacionais.

---

## Epic E1 — Produção: multi-tenant e escala

**Objetivo:** transformar o serviço single-tenant local em produto multi-tenant
com isolamento por tenant e escala horizontal dos sandboxes.

**Stack:** FastAPI + SQLAlchemy (PostgreSQL `asyncpg`) + Wasmtime AOT +
Redis (cache/locks) + Docker/K8s.

**Conexões:** `DevContextRow`, `AgentRow` (FK tenant), `SandboxPool`,
`GateRepo` (filtro por tenant), `TeamBuilder DSN`.

**Features / tarefas:**

| ID | Feature | Tarefas | Gate nova | Objetos novos |
|---|---|---|---|---|
| E1.1 | Tenant isolation | E1.1.1 coluna `tenant_id` em todas as tabelas (migração Alembic) · E1.1.2 dependência `require_tenant` na API · E1.1.3 tests de cross-tenant 404 | `TenantIsolationGate` (pre, priority 0) | `tenant_id` em 7 tabelas; `tenants` table |
| E1.2 | Sandbox scaling | E1.2.1 pool de sandboxes compartilhado + LRU por tenant · E1.2.2 AOT (`CompiledModule`) p/ cold-start · E1.2.3 métricas de fuel/epoch por tool | — | `sandbox_pool` metrics table |
| E1.3 | Postgres em produção | E1.3.1 swap de DSN + CI com service-container postgres · E1.3.2 Alembic baseline · E1.3.3 seed idempotente das tools builtin | — | migrações versionadas |

**Gates (resumo):** `TenantIsolationGate` — input: request+tenant claim;
output: verificação de posse do recurso (FK `resource_id`).

---

## Epic E2 — WASM: Component Model + WASI 0.2

**Objetivo:** evoluir das ferramentas WAT "raw" para **WASM components** com
interfaces WIT (contratos tipados entre host e tool), alinhando-se ao padrão
2026 (WASI 0.2/0.3, componentize).

**Stack:** Wasmtime 49+ (components), `wasm-tools component`, WIT,
`wit-component` (wabt p/ build das tools).

**Conexões:** `ToolSpec.wat` → `ToolSpec.component` (bytes), `ToolExecutor`,
`WasmSandboxGate`, `SandboxPool`.

| ID | Feature | Tarefas | Gate nova | Objetos novos |
|---|---|---|---|---|
| E2.1 | WIT p/ tools | E2.1.1 `tools/wit/*.wit` (uppercase/fib/add + world) · E2.1.2 build pipeline `wasm-tools component` no CI · E2.1.3 `ToolSpec.kind="component"` | — | `tools.component` (blob), `tools.wit_world` |
| E2.2 | Host interfaces WASI | E2.2.1 world host expõe `logging`/`random` via WIT · E2.2.2 tool pode consumir `wasi:logging` sem rede · E2.2.3 deny-by-default mantido (sem fs/net) | `WasiCapabilityGate` — valida capabilities pedidas vs. perfil do role | `tool_capabilities` (JSON) |
| E2.3 | Registry de components | E2.3.1 assinatura (Ed25519) de cada component · E2.3.2 verificação de assinatura no forge · E2.3.3 versionamento semântico | `ComponentSignatureGate` | `tool_signatures` table |

**Gates:** `WasiCapabilityGate` (pre, executa antes do WASM — valida o conjunto
de capabilities declarado no WIT contra o perfil do role); `ComponentSignatureGate`
(pode FORJOU a tool: assinatura válida + publisher autorizado).

---

## Epic E3 — LLM em produção: Instructor + avaliação

**Objetivo:** trocar o MockLLM por LLM real com **validação + retries +
avaliação** (o Mock passa a ser apenas fixture de teste).

**Stack:** instructor (TOOLS mode), OpenAI/Anthropic provider-agnostic,
langfuse/helicone tracing.

**Conexões:** `LLMClient`, `ContextAnalyzer`, `PlanOutput`, 11 output models,
`Agent.work()`.

| ID | Feature | Tarefas | Gate nova | Objetos novos |
|---|---|---|---|---|
| E3.1 | Provider abstrato | E3.1.1 `InstructorLLM` multi-provider (env `LLM_PROVIDER`) · E3.1.2 timeout + retries exponenciais · E3.1.3 fallback chain (provider A → B → mock-degraded) | `LLMContractGate` (post, sobre cada output estruturado — valida schema + heurísticas de qualidade) | `llm_calls` table (tokens, latência, retries) |
| E3.2 | Context grounding | E3.2.1 RAG opcional: docs do contexto indexados (embeddings) · E3.2.2 citação obrigatória no plano · E3.2.3 teste de grounding (score < limiar → gate falha) | `GroundingGate` (post, prioridade 1) | `context_chunks`, `plan_citations` |
| E3.3 | Avaliação contínua | E3.3.1 suite de cenários SDLC com scores · E3.3.2 CI de regressão de qualidade (score não pode cair) · E3.3.3 dashboard de scores por role | — | `eval_runs` table |

---

## Epic E4 — Orquestração: múltiplos times e dependências

**Objetivo:** orquestrar **N times em paralelo por contexto** com grafo de
dependências entre tarefas (o `parallel_tracks` do DevContext vira máquina).

**Stack:** FastAPI (background tasks), Redis streams (eventos), FSM por agente
(conectado por hub de eventos).

**Conexões:** `AgentTeam`, `FSMEngine` (novo evento `DEP_RESOLVED` já existe),
`TaskRepo`, `GateRegistry`.

| ID | Feature | Tarefas | Gate nova | Objetos novos |
|---|---|---|---|---|
| E4.1 | Grafo de tarefas | E4.1.1 `task_dependencies` (FK task→task) · E4.1.2 topological scheduler · E4.1.3 eventos `wait_dependency`/`dependency_resolved` orquestrados | `DependencyOrderGate` (pre, sobre `execute`: todos os deps concluídos?) | `task_dependencies` table |
| E4.2 | Hub de eventos | E4.2.1 pub/sub Redis: transições de FSM → notifica deps · E4.2.2 idempotência por `result_id` · E4.2.3 replay de eventos (debug) | — | `event_log` table (append-only) |
| E4.3 | Coordenação multi-time | E4.3.1 `OrchestratorAgent` (role GOD, FSM própria) · E4.3.2 merge de deliverables com QA cross-team · E4.3.3 limites de concorrência por tenant | `TeamQuotaGate` | `orchestration_runs` table |

---

## Epic E5 — GOD MODE avançado: refator com verificação

**Objetivo:** implementar o ciclo completo do GOD: **análise de impacto →
refator → verificação de impacto** (loop), com a FSM editável por dif.

**Stack:** AST diff das transições, shadow-run do FSM antigo vs. novo.

**Conexões:** `FSMEngine.replace_transitions`, `PATCH /god/fsm/edit`,
`AuditRepo`, `FSMRepo`.

| ID | Feature | Tarefas | Gate nova | Objetos novos |
|---|---|---|---|---|
| E5.1 | Análise de impacto real | E5.1.1 simular 100 traces históricos contra a nova tabela · E5.1.2 diff de alcance (transições alcançáveis antes/depois) · E5.1.3 endpoint retorna o impacto calculado | `ImpactVerificationGate` (post, sobre o edit: impacto medido == impacto declarado?) | `fsm_edit_proposals` table (status: proposed/verified/applied) |
| E5.2 | Shadow-run | E5.2.1 FSM paralela em shadow com as novas transições · E5.2.2 divergências → relatório · E5.2.3 rollback automático em divergência crítica | — | `shadow_transitions` table |
| E5.3 | Refator assistido | E5.3.1 GOD propõe refator (LLM) com diff · E5.3.2 aprovação humana na UI · E5.3.3 auditoria imutável (hash chain) | — | `audit_log.signature` (hash chain) |

---

## Epic E6 — Observabilidade e segurança

**Objetivo:** tornar a plataforma auditável de ponta a ponta (trilha de gate ↔
DB ↔ logs) e adicionar segurança de transporte/acesso.

**Stack:** OpenTelemetry, Prometheus, OIDC.

| ID | Feature | Tarefas | Gate nova | Objetos novos |
|---|---|---|---|---|
| E6.1 | Tracing distribuído | E6.1.1 span por gate execução · E6.1.2 `gate_id` propagado em headers · E6.1.3 Jaeger/Tempo | — | spans exportados |
| E6.2 | AuthN/AuthZ | E6.2.1 OIDC p/ agentes (client-credentials) · E6.2.2 roles de acesso na API · E6.2.3 rate-limit por agente | `AgentAuthGate` (substitui a expansão manual do `_api_context` — o contexto de API passa a vir do token verificado) | `agent_credentials` table |
| E6.3 | Segurança WASM | E6.3.1 fuzzing de tools no CI (libFuzzer sobre WAT) · E6.3.2 CVE watch do wasmtime · E6.3.3 sandbox hardening (stack sizing, limits) | — | job CI `wasm-fuzz` |

---

## Sequência recomendada (2 trimestres)

```
Q1:  E1 (produção) → E3 (LLM real) → E4 (orquestração)
Q2:  E2 (components/WASI) → E5 (GOD avançado) → E6 (obs/seg)
```

Cada feature termina só com: (1) testes verdes, (2) gate(s) nova(s) testada(s),
(3) objetos relacionais com FKs documentadas, (4) evidência em `docs/evidence/`.

## Matriz de dependências entre epics

```
E1 ──┬─→ E2 (sandbox em escala)
     ├─→ E4 (tenants por time)
     └─→ E6 (auth por tenant)
E3 ──┬─→ E5 (refator assistido usa LLM)
E4 ──┴─→ E6 (tracing do hub de eventos)
E2 ──────→ E6 (fuzzing de components)
```

## Novo perfil de trabalho (reflexão sobre domínios/clientes)

A fase 2 cria 3 perfis que a fase 1 apenas insinua:

1. **WASM Platform Engineer** — dono do runtime (fuel/epoch/limits, components,
   AOT); cliente: qualquer produto que execute código de terceiros;
2. **Agent Orchestration Engineer (GOD)** — dono da FSM + gates + auditoria;
   cliente: plataformas multi-agente com requisito de conformidade;
3. **AI Evaluation Engineer** — dono da qualidade dos outputs estruturados
   (Instructor + evals); cliente: times que colocam LLM em loop crítico.
