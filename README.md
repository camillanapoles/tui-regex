# Team Builder WASM

Plataforma autônoma de **construção de times de agentes de software**: um
contexto de desenvolvimento (texto livre) vira um time vivo de agentes, cada um
com sua própria **Máquina de Estados Finitos** mediada por **gates** — e todo
cálculo de código não-confiável roda em **sandbox WebAssembly real** (Wasmtime,
fuel + epoch).

```
DevContext (LLM + Pydantic/Instructor)
        │
        ▼
AgentFactory (Factory Pattern — zero hardcode, 11 roles + generalista)
        │
        ▼
N Agentes (microserviços OOP) ── cada um com FSM própria
        │            ▲
        │            │ única porta de mutação
        ▼            │
   API central FastAPI  ←── GOD MODE (Engenheiro Sênior)
        │            │          • único editor da FSM API (impacto primeiro)
        ▼            │          • único forjador de tools
   GateFunctions ────┘          • tudo auditado
   (UUID PK, FK input↔output, deny-by-default)
        │
        ▼
   Sandbox Wasmtime (fuel + epoch, pool, tools em WAT/components)
        │
        ▼
   DB relacional (gate↔agent, gate↔tool, task↔agent, audit↔gate)
```

## Constituição (invariáveis testadas)

| Invariante | Mecanismo | Teste |
|---|---|---|
| Nada existe fora da API | `ApiGate` exige contexto de API — chamada direta ao engine falha | `test_fsm.py::test_blocked_when_no_api_context` |
| Toda gate é objeto com PK única | `GateRecord.gate_id` (UUID) — input/output imutáveis com FKs | `test_gates.py::TestGateUUIDPK` |
| Factory, nunca hardcode | `AgentFactory._creators: dict[Role → Creator]`; roles novos plugam em runtime | `test_factory.py::test_factory_not_hardcoded` |
| Deny-by-default | role desconhecido = bloqueado; tool sem permissão = bloqueada | `test_gates.py::test_unknown_role_denied_by_default` |
| WASM de verdade | WAT compilado no Wasmtime; fuel exhaustion e epoch trap testados | `test_wasm.py` |
| GOD MODE é o único editor | `PATCH /god/fsm/edit` exige `impact_analysis` (≥30 chars) + `refactor_reason`; `POST /god/tools/forge` valida o WAT antes | `test_api.py::TestGodMode` |

## Começando

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

# API viva (OpenAPI em http://localhost:8000/docs)
uvicorn team_builder.api:app --host 0.0.0.0 --port 8000
```

### LLM

Sem `OPENAI_API_KEY`, a plataforma roda 100% offline com o `MockLLM`
(sampler determinístico — ideal p/ dev/testes). Com a key, o `InstructorLLM`
(OpenAI-compatible, TOOLS mode) assume a análise de contexto e o planning.

### Banco

Padrão: SQLite local (`TEAM_BUILDER_DSN=sqlite:///./team_builder.db`).
Produção: `TEAM_BUILDER_DSN=postgresql+asyncpg://...`.

### GOD MODE

```bash
# forge de uma tool WASM (só o Engenheiro Sênior)
curl -X POST localhost:8000/god/tools/forge \
  -H "X-God-Mode: $SECRET" -H 'Content-Type: application/json' \
  -d '{"name":"double","wat":"(module ...)","entrypoint":"add",
       "param_names":["a","b"],"assigned_roles":["developer"]}'

# refator da FSM (impacto validado ANTES do apply)
curl -X PATCH localhost:8000/god/fsm/edit \
  -H "X-God-Mode: $SECRET" \
  -d '{"agent_id":"dev-x","impact_analysis":"...","refactor_reason":"...",
       "new_transitions":[...]}'
```

## Testando

```bash
pytest                 # 116 testes: unit (85) + integration (24) + e2e (7)
bash scripts/run_evidence.sh   # quality + validação WAT + suítes + cobertura
```

Cobertura atual: **94%** (ver `docs/evidence/pytest_final.txt`).

## CI/CD

`.github/workflows/team-builder-ci.yml` — incremental (`cancel-in-progress`):

1. **quality** — ruff (lint);
2. **wasm-validate** — todos os WAT compilados/smoke-testados no Wasmtime +
   `wasm-validate` (WABT) nos binários emitidos;
3. **tests** — matriz unit/integration/e2e com JUnit + cobertura como artifacts;
4. **god-mode-gate** — PR que toca `fsm.py`/`gates.py`/`api.py` exige
   `impact_analysis:` + `refactor_reason:` no corpo do PR;
5. **release (CD)** — em `main`, roda a suite completa e publica a wheel como
   release incremental.

## Estrutura

```
team_builder/
  models.py      # enums, AgentSpec, DevContext, ContextAnalyzer, Task
  llm.py         # LLMClient, InstructorLLM (TOOLS mode), MockLLM
  gates.py       # GateFunction OOP (PK UUID + FKs), 6 gates, registry
  fsm.py         # 9 estados / 15 eventos / pipeline pre+post gates
  agents.py      # BaseAgent + 11 roles + GenericAgent (outputs Pydantic)
  factory.py     # AgentFactory / AgentCreator / AgentTeam (zero hardcode)
  tools.py       # ToolSpec / ToolRegistry / ToolExecutor (atrás da gate)
  wasm.py        # Wasmtime: fuel, epoch (ticker), traps, pool
  wasm_tools.py  # WAT das tools builtin (uppercase/fib/add)
  db.py          # SQLAlchemy 2.0 — 7 tabelas, FKs obrigatórias
  api.py         # FastAPI — 20 endpoints + GOD MODE
tests/           # unit / integration / e2e (116 testes)
scripts/         # validate_wat.py, check_god_mode.py, run_evidence.sh
docs/            # STATUS_REPORT.md, CONTINUATION_PLAN.md, evidence/
```

## Documentação

- [`docs/STATUS_REPORT.md`](docs/STATUS_REPORT.md) — status, matriz de execução,
  análise da referência `auto-dev-wasm-apk`, alternativas 2026, evidência;
- [`docs/CONTINUATION_PLAN.md`](docs/CONTINUATION_PLAN.md) — epics/features/
  tarefas/gates/objetos da fase 2.
