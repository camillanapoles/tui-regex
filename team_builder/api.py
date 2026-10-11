"""Central FastAPI — the ONLY mutation surface of the platform.

Constitution enforced here:
  * every request that mutates state goes through a GateFunction pipeline;
  * agents register and act ONLY through these endpoints (ApiGate makes
    direct engine calls without api_context fail);
  * GOD MODE (header X-God-Mode == secret) is the sole editor of the FSM
    (PATCH /god/fsm/edit requires impact_analysis + refactor_reason) and
    the sole forger of tools (POST /god/tools/forge).
"""
from __future__ import annotations

import hmac
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from team_builder import __version__
from team_builder.continuity import (
    ContinuityFactory,
    ContinuityReadGate,
    ContinuityWriteGate,
    make_continuity_gate_input,
)
from team_builder.db import (
    AgentRepo,
    AuditRepo,
    ContinuityRepo,
    FSMRepo,
    GateRepo,
    TaskRepo,
    ToolRepo,
    init_db,
    make_engine,
    make_session,
)
from team_builder.factory import AgentFactory
from team_builder.fsm import FSMEvent, FSMState, Transition
from team_builder.gates import GateDirection, GateRegistry, GateStatus
from team_builder.llm import LLMClient, MockLLM
from team_builder.models import (
    AgentSpec,
    ComplexityLevel,
    ContextAnalyzer,
    DevContext,
    ProjectType,
    SDLCPhase,
    TechStack,
)
from team_builder.tools import (
    ToolBlockedError,
    ToolExecutor,
    ToolRegistry,
    ToolSpec,
    builtin_specs,
)
from team_builder.wasm import SandboxPool


# ── Request schemas (module level: Pydantic needs resolvable refs) ──────
class TriggerRequest(BaseModel):
    agent_id: str
    event: FSMEvent
    payload: dict[str, Any] = Field(default_factory=dict)
    sdlc_phase: str | None = None


class AgentCreateRequest(BaseModel):
    spec: AgentSpec
    context: DevContext | None = None


class TaskRequest(BaseModel):
    task: dict[str, Any] = Field(default_factory=dict)


class ToolExecuteRequest(BaseModel):
    agent_id: str
    params: dict[str, Any] = Field(default_factory=dict)


class BuildTeamRequest(BaseModel):
    project_description: str
    extra_info: dict[str, Any] = Field(default_factory=dict)


class FSMEditRequest(BaseModel):
    agent_id: str
    impact_analysis: str = Field(min_length=30)
    refactor_reason: str = Field(min_length=10)
    new_transitions: list[dict[str, Any]] = Field(default_factory=list)


class ForgeToolRequest(BaseModel):
    name: str
    description: str = ""
    wat: str
    entrypoint: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    param_names: list[str] = Field(default_factory=list)
    input_bytes_key: str | None = None
    assigned_roles: list[str] = Field(default_factory=list)
    fuel_limit: int = 5_000_000


class ContinuitySetRequest(BaseModel):
    data: dict[str, Any]
    expected_version: int | None = None


# ── Settings ─────────────────────────────────────────────────────────────
class Settings(BaseSettings):
    god_mode_secret: str = "god-mode-secret"
    db_url: str = "sqlite:///./team_builder.db"
    llm_name: str = "mock"

    model_config = SettingsConfigDict(env_prefix="team_builder_")


# ── In-process store (live agents + shared singletons) ───────────────────
class AppStore:
    def __init__(self, db: Any, llm: LLMClient):
        self.db = db
        self.llm = llm
        self.registry = GateRegistry()
        self.pool = SandboxPool(max_size=25)
        self.tool_registry = ToolRegistry()
        self.executor = ToolExecutor(self.registry, self.pool, self.tool_registry)
        self.agents: dict[str, Any] = {}
        self.teams: dict[str, Any] = {}
        # persist every gate execution (input -> gate -> output) to the DB
        self.registry.attach_persistence(self._persist_gate)
        self._seed_builtin_tools()

    def _persist_gate(self, record: Any) -> None:
        try:
            GateRepo(self.db).save(record)
        except Exception:
            self.db.rollback()

    def _seed_builtin_tools(self) -> None:
        repo = ToolRepo(self.db)
        for spec in builtin_specs():
            existing = self.tool_registry.get(spec.name)
            if existing is None:
                self.tool_registry.register(spec)
            if repo.get(spec.tool_id) is None:
                repo.save(spec)

    def close(self) -> None:
        self.pool.close()


# ── App factory ──────────────────────────────────────────────────────────
def create_app(
    *,
    db_url: str = "sqlite://",
    llm: LLMClient | None = None,
    god_secret: str = "god-mode-secret",
) -> FastAPI:
    llm = llm or MockLLM()
    settings = Settings(god_mode_secret=god_secret, db_url=db_url, llm_name=llm.name)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = make_engine(db_url)
        init_db(engine)
        session = make_session(engine)
        app.state.store = AppStore(session, llm)
        app.state.settings = settings
        yield
        app.state.store.close()
        session.close()
        engine.dispose()

    app = FastAPI(
        title="Team Builder WASM — FSM Orchestration API",
        version=__version__,
        description=(
            "Plataforma de construção de times de agentes autônomos: "
            "FSM com GateFunctions (UUID PK + input/output FKs), Factory "
            "Pattern dinâmico, Pydantic+Instructor, sandbox Wasmtime "
            "(fuel+epoch) e GOD MODE como único editor da FSM API."
        ),
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def platform_header(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Team-Builder"] = f"wasm-fsm/{__version__}"
        return response

    @app.exception_handler(Exception)
    async def global_handler(request: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content={"error": str(exc), "type": type(exc).__name__},
        )

    # ── dependencies ────────────────────────────────────────────────────
    async def get_store(request: Request) -> AppStore:
        return request.app.state.store

    async def require_god(
        request: Request,
        x_god_mode: str = Header(default="", alias="X-God-Mode"),
    ) -> None:
        secret = request.app.state.settings.god_mode_secret
        if not hmac.compare_digest(x_god_mode, secret):
            raise HTTPException(
                status_code=403,
                detail="GOD MODE: credential 'X-God-Mode' inválida. "
                "Apenas o Engenheiro Sênior pode editar a FSM API.",
            )

    store_dep = Depends(get_store)
    god_dep = Depends(require_god)

    # ══ Health ══════════════════════════════════════════════════════════
    @app.get("/health", tags=["Health"])
    async def health(store: AppStore = store_dep):
        return {
            "status": "healthy",
            "platform": "team-builder-wasm",
            "version": __version__,
            "wasm_runtime": "wasmtime",
            "llm": store.llm.name,
            "agents_live": len(store.agents),
            "tools": len(store.tool_registry.list()),
            "gates_executed": len(store.registry.list_all()),
        }

    # ══ Gates (UUID PK objects, full trace) ════════════════════════════
    @app.get("/gates/blocked", tags=["Gates"])
    async def list_blocked_gates(store: AppStore = store_dep):
        blocked = store.registry.list_blocked()
        return {
            "total_blocked": len(blocked),
            "records": [
                {
                    "gate_id": r.gate_id,
                    "gate_name": r.gate_name,
                    "agent_id": r.agent_id,
                    "status": r.status.value,
                    "reason": r.output_object.reason if r.output_object else None,
                    "input_id": r.input_object.object_id if r.input_object else None,
                }
                for r in blocked
            ],
        }

    @app.get("/gates/", tags=["Gates"])
    async def list_gates(
        store: AppStore = store_dep,
        agent_id: str | None = Query(None),
        status: GateStatus | None = Query(None),
        direction: GateDirection | None = Query(None),
        limit: int = Query(100, ge=1, le=1000),
    ):
        records = store.registry.list_all()
        if agent_id:
            records = [r for r in records if r.agent_id == agent_id]
        if status:
            records = [r for r in records if r.status == status]
        if direction:
            records = [r for r in records if r.direction == direction]
        return {
            "total": len(records),
            "stats": store.registry.stats(),
            "records": [r.model_dump(mode="json") for r in records[:limit]],
        }

    @app.get("/gates/{gate_id}", tags=["Gates"])
    async def gate_trace(gate_id: str, store: AppStore = store_dep):
        record = store.registry.get(gate_id)
        if record is None:
            raise HTTPException(404, f"Gate '{gate_id}' não encontrada")
        return {
            "gate_id": record.gate_id,
            "gate_name": record.gate_name,
            "direction": record.direction.value,
            "status": record.status.value,
            "agent_id": record.agent_id,
            "tool_id": record.tool_id,
            "event": record.event,
            "input": record.input_object.model_dump(mode="json") if record.input_object else None,
            "output": record.output_object.model_dump(mode="json") if record.output_object else None,
            "duration_ms": record.output_object.duration_ms if record.output_object else None,
            "created_at": record.created_at.isoformat(),
            "completed_at": record.completed_at.isoformat() if record.completed_at else None,
        }

    # ══ FSM (event trigger — always through the gate pipeline) ═════════
    @app.post("/fsm/trigger", tags=["FSM"])
    async def fsm_trigger(req: TriggerRequest, store: AppStore = store_dep):
        agent = store.agents.get(req.agent_id)
        if agent is None:
            raise HTTPException(404, f"Agente '{req.agent_id}' não encontrado")
        phase = req.sdlc_phase or agent.context.current_phase.value
        payload = dict(req.payload)
        payload["_api_context"] = True  # this call IS the API
        result = await agent.fsm.trigger(req.event, payload, sdlc_phase=phase)
        AgentRepo(store.db).set_state(agent.agent_id, agent.state.value)
        return result.model_dump(mode="json")

    # ══ Agents (created ONLY via the Factory) ══════════════════════════
    @app.post("/agents/", status_code=201, tags=["Agents"])
    async def create_agent(req: AgentCreateRequest, store: AppStore = store_dep):
        context = req.context or DevContext(
            project_type=ProjectType.GENERIC,
            complexity=ComplexityLevel.LOW,
            current_phase=SDLCPhase.DEVELOPMENT,
            tech_stack=TechStack(),
            team_agents=[req.spec],
        )
        agent = await AgentFactory.create_agent(
            req.spec, context, store.llm, db=store.db, registry=store.registry
        )
        store.agents[agent.agent_id] = agent
        return {
            "agent_id": agent.agent_id,
            "role": agent.spec.role.value,
            "name": agent.spec.name,
            "state": agent.state.value,
            "fsm_transitions": len(agent.fsm.transitions),
        }

    @app.get("/agents/", tags=["Agents"])
    async def list_agents(store: AppStore = store_dep):
        return {
            "total": len(store.agents),
            "agents": [
                {
                    "agent_id": a.agent_id,
                    "role": a.spec.role.value,
                    "name": a.spec.name,
                    "state": a.state.value,
                    "gates": len(store.registry.list_by_agent(a.agent_id)),
                }
                for a in store.agents.values()
            ],
        }

    @app.get("/agents/{agent_id}", tags=["Agents"])
    async def get_agent(agent_id: str, store: AppStore = store_dep):
        agent = store.agents.get(agent_id)
        if agent is None:
            raise HTTPException(404, f"Agente '{agent_id}' não encontrado")
        row = AgentRepo(store.db).get(agent_id)
        transitions = FSMRepo(store.db).list_by_agent(agent_id)
        return {
            "agent_id": agent.agent_id,
            "role": agent.spec.role.value,
            "name": agent.spec.name,
            "state": agent.state.value,
            "spec": agent.spec.model_dump(mode="json"),
            "transitions_count": len(transitions),
            "db_state": row.state if row else None,
        }

    @app.post("/agents/{agent_id}/task", tags=["Agents"])
    async def assign_task(agent_id: str, req: TaskRequest, store: AppStore = store_dep):
        agent = store.agents.get(agent_id)
        if agent is None:
            raise HTTPException(404, f"Agente '{agent_id}' não encontrado")
        task_id = req.task.get("task_id", f"task-{agent_id}")
        result = await agent.receive_task(req.task)
        if result.success:
            TaskRepo(store.db).create(
                agent_id,
                title=str(req.task.get("title", "tarefa")),
                description=str(req.task.get("description", "")),
                task_id=task_id,
                status="planning",
            )
        return result.model_dump(mode="json")

    @app.post("/agents/{agent_id}/work", tags=["Agents"])
    async def run_work(agent_id: str, req: TaskRequest, store: AppStore = store_dep):
        """Full gated lifecycle (receive -> plan -> run -> finish)."""
        agent = store.agents.get(agent_id)
        if agent is None:
            raise HTTPException(404, f"Agente '{agent_id}' não encontrado")
        task_id = req.task.get("task_id", f"task-{agent_id}")
        repo = TaskRepo(store.db)
        repo.create(
            agent_id,
            title=str(req.task.get("title", "tarefa")),
            description=str(req.task.get("description", "")),
            task_id=task_id,
            status="running",
        )
        try:
            output = await agent.work(req.task)
        except Exception as exc:
            repo.update(task_id, status="failed", result={"error": str(exc)})
            raise HTTPException(500, f"Falha na execução: {exc}") from exc
        transitions = FSMRepo(store.db).list_by_agent(agent_id)
        gate_ids: list[str] = []
        for row in transitions[-3:]:
            gate_ids.extend(row.gate_ids or [])
        repo.update(
            task_id,
            status="completed" if output.next_event == FSMEvent.COMPLETE else "failed",
            result=output.model_dump(mode="json"),
            artifacts=output.artifacts,
            gate_ids=gate_ids,
        )
        AgentRepo(store.db).set_state(agent.agent_id, agent.state.value)
        return output.model_dump(mode="json")

    # ══ Tasks ═══════════════════════════════════════════════════════════
    @app.get("/tasks/", tags=["Tasks"])
    async def list_tasks(
        store: AppStore = store_dep, agent_id: str | None = Query(None)
    ):
        rows = TaskRepo(store.db).list(agent_id)
        return {
            "total": len(rows),
            "tasks": [
                {
                    "task_id": t.task_id,
                    "agent_id": t.agent_id,
                    "title": t.title,
                    "status": t.status,
                    "artifacts": t.artifacts,
                    "gate_ids": t.gate_ids,
                }
                for t in rows
            ],
        }

    @app.get("/tasks/{task_id}", tags=["Tasks"])
    async def get_task(task_id: str, store: AppStore = store_dep):
        row = TaskRepo(store.db).get(task_id)
        if row is None:
            raise HTTPException(404, f"Task '{task_id}' não encontrada")
        return {
            "task_id": row.task_id,
            "agent_id": row.agent_id,
            "title": row.title,
            "status": row.status,
            "result": row.result,
            "artifacts": row.artifacts,
            "gate_ids": row.gate_ids,
        }

    # ══ Tools ═══════════════════════════════════════════════════════════
    @app.get("/tools/", tags=["Tools"])
    async def list_tools(store: AppStore = store_dep):
        return {
            "total": len(store.tool_registry.list()),
            "tools": [
                {
                    "tool_id": t.tool_id,
                    "name": t.name,
                    "description": t.description,
                    "kind": t.kind,
                    "entrypoint": t.entrypoint,
                    "parameters": t.parameters,
                    "assigned_roles": t.assigned_roles,
                }
                for t in store.tool_registry.list()
            ],
        }

    @app.post("/tools/{tool_name}/execute", tags=["Tools"])
    async def execute_tool(
        tool_name: str, req: ToolExecuteRequest, store: AppStore = store_dep
    ):
        agent = store.agents.get(req.agent_id)
        if agent is None:
            raise HTTPException(404, f"Agente '{req.agent_id}' não encontrado")
        try:
            return await store.executor.execute(
                tool_name, req.params, agent.agent_id, agent.spec.role.value
            )
        except ToolBlockedError as exc:
            raise HTTPException(403, detail=exc.reason) from exc
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc

    # ══ Continuity — objetos de sessão set/recover via API ════════════
    @app.get("/continuity/kinds", tags=["Continuity"])
    async def continuity_kinds(store: AppStore = store_dep):
        """Registry dos kinds — populado pela META-CLASSE (auto-discovery)."""
        kinds = ContinuityFactory.kinds()
        return {
            "kinds": kinds,
            "total": len(kinds),
            "registry": {k: ContinuityFactory.get_class(k).__name__ for k in kinds},
        }

    @app.get("/continuity/stats", tags=["Continuity"])
    async def continuity_stats(store: AppStore = store_dep):
        repo = ContinuityRepo(store.db)
        return {
            "total_objects": repo.count(),
            "kinds_in_db": repo.all_kinds(),
            "registered_kinds": ContinuityFactory.kinds(),
        }

    @app.get("/continuity/", tags=["Continuity"])
    async def continuity_list(
        store: AppStore = store_dep,
        kind: str | None = Query(None),
        key_prefix: str | None = Query(None),
        limit: int = Query(100, ge=1, le=1000),
    ):
        gate = ContinuityReadGate(store.registry)
        out = await gate(
            make_continuity_gate_input("list", kind or "", key_prefix or "")
        )
        if not out.allowed:
            raise HTTPException(403, detail=out.reason or "bloqueado pela gate")
        rows = ContinuityRepo(store.db).list(kind, key_prefix, limit)
        return {
            "total": len(rows),
            "objects": [
                {
                    "kind": r.kind,
                    "key": r.key,
                    "version": r.version,
                    "data": r.data,
                    "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                }
                for r in rows
            ],
        }

    @app.get("/continuity/{kind}/{key:path}", tags=["Continuity"])
    async def continuity_get(kind: str, key: str, store: AppStore = store_dep):
        """RECUPERAR: get do objeto de continuidade (set/recover via API)."""
        gate = ContinuityReadGate(store.registry)
        out = await gate(make_continuity_gate_input("get", kind, key))
        if not out.allowed:
            raise HTTPException(403, detail=out.reason or "bloqueado pela gate")
        row = ContinuityRepo(store.db).get(kind, key)
        if row is None:
            raise HTTPException(404, f"Continuidade '{kind}/{key}' não encontrada")
        return {
            "kind": row.kind,
            "key": row.key,
            "version": row.version,
            "data": row.data,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "gate_id": out.gate_id,
        }

    async def _continuity_set(
        kind: str, key: str, req: ContinuitySetRequest, store: AppStore
    ) -> dict:
        gate = ContinuityWriteGate(store.registry)
        out = await gate(make_continuity_gate_input("set", kind, key, req.data))
        if not out.allowed:
            raise HTTPException(403, detail=out.reason or "bloqueado pela gate")
        from team_builder.continuity import VersionConflictError

        try:
            row = ContinuityRepo(store.db).save(
                kind, key, dict(req.data), expected_version=req.expected_version
            )
        except VersionConflictError as exc:
            raise HTTPException(
                409,
                detail={
                    "error": "conflito de versão",
                    "current_version": exc.current_version,
                    "expected_version": exc.expected_version,
                },
            ) from exc
        return {
            "kind": row.kind,
            "key": row.key,
            "version": row.version,
            "data": row.data,
            "gate_id": out.gate_id,
        }

    @app.put("/continuity/{kind}/{key:path}", tags=["Continuity"])
    async def continuity_put(
        kind: str, key: str, req: ContinuitySetRequest, store: AppStore = store_dep
    ):
        """SETAR: upsert versionado do objeto de continuidade."""
        return await _continuity_set(kind, key, req, store)

    @app.post("/continuity/{kind}/{key:path}", tags=["Continuity"])
    async def continuity_set(
        kind: str, key: str, req: ContinuitySetRequest, store: AppStore = store_dep
    ):
        """SETAR (alias do PUT)."""
        return await _continuity_set(kind, key, req, store)

    @app.delete("/continuity/{kind}/{key:path}", tags=["Continuity"])
    async def continuity_delete(kind: str, key: str, store: AppStore = store_dep):
        gate = ContinuityWriteGate(store.registry)
        out = await gate(make_continuity_gate_input("delete", kind, key))
        if not out.allowed:
            raise HTTPException(403, detail=out.reason or "bloqueado pela gate")
        deleted = ContinuityRepo(store.db).delete(kind, key)
        if not deleted:
            raise HTTPException(404, f"Continuidade '{kind}/{key}' não encontrada")
        return {"ok": True, "kind": kind, "key": key, "gate_id": out.gate_id}

    # ══ GOD MODE — sole editor of the FSM API ══════════════════════════
    @app.post("/god/build-team", tags=["GOD MODE"])
    async def build_team(
        req: BuildTeamRequest, store: AppStore = store_dep, _: None = god_dep
    ):
        """ContextAnalyzer (Instructor) -> DevContext -> AgentFactory."""
        context = await ContextAnalyzer(store.llm).analyze(
            req.project_description, req.extra_info
        )
        team = await AgentFactory.create_team(
            context, store.llm, db=store.db, registry=store.registry
        )
        team_key = f"team-{len(store.teams) + 1}"
        store.teams[team_key] = team
        for agent in team.agents:
            store.agents[agent.agent_id] = agent
        AuditRepo(store.db).log(
            "god.build_team",
            agent_id=None,
            payload={"team": team_key, "agents": team.summary()["total_agents"]},
        )
        return {
            "team": team_key,
            "context": context.model_dump(mode="json"),
            "summary": team.summary(),
        }

    @app.patch("/god/fsm/edit", tags=["GOD MODE"])
    async def edit_fsm(
        req: FSMEditRequest, store: AppStore = store_dep, _: None = god_dep
    ):
        """SOLE FSM editor. Impact analysis is mandatory before applying."""
        if req.new_transitions:
            try:
                transitions = [
                    Transition(
                        from_state=FSMState(t["from_state"]),
                        event=FSMEvent(t["event"]),
                        to_state=FSMState(t["to_state"]),
                        action_name=t.get("action_name"),
                        description=t.get("description", ""),
                    )
                    for t in req.new_transitions
                ]
            except (KeyError, ValueError) as exc:
                raise HTTPException(
                    400, f"Transições inválidas (verifique estados/eventos): {exc}"
                ) from exc
            agent = store.agents.get(req.agent_id)
            if agent is None:
                raise HTTPException(404, f"Agente '{req.agent_id}' não encontrado")
            agent.fsm.replace_transitions(transitions)

        AuditRepo(store.db).log(
            "god.fsm_edit",
            agent_id=req.agent_id,
            payload={
                "impact_analysis": req.impact_analysis,
                "refactor_reason": req.refactor_reason,
                "transitions": len(req.new_transitions),
            },
        )
        return {
            "status": "applied",
            "agent_id": req.agent_id,
            "transitions_applied": len(req.new_transitions),
            "impact_analysis": req.impact_analysis,
            "refactor_reason": req.refactor_reason,
        }

    @app.post("/god/tools/forge", status_code=201, tags=["GOD MODE"])
    async def forge_tool(
        req: ForgeToolRequest, store: AppStore = store_dep, _: None = god_dep
    ):
        """GOD MODE forges a new WASM tool — validated + registered + persisted."""
        from wasmtime import Module

        spec = ToolSpec(
            name=req.name,
            description=req.description,
            kind="wasm",
            entrypoint=req.entrypoint,
            wat=req.wat,
            parameters=req.parameters,
            param_names=req.param_names,
            input_bytes_key=req.input_bytes_key,
            assigned_roles=req.assigned_roles,
            fuel_limit=req.fuel_limit,
        )
        # validate the WAT compiles before registering (fail fast)
        try:
            engine_holder = store.pool.get_or_create("god-forge")
            Module(engine_holder.engine.engine, req.wat)
        except Exception as exc:
            raise HTTPException(400, f"WAT inválida: {exc}") from exc

        store.tool_registry.register(spec)
        ToolRepo(store.db).save(spec)
        AuditRepo(store.db).log(
            "god.forge_tool",
            payload={"tool": spec.name, "tool_id": spec.tool_id},
        )
        return {
            "tool_id": spec.tool_id,
            "name": spec.name,
            "entrypoint": spec.entrypoint,
            "assigned_roles": spec.assigned_roles,
            "status": "registered",
        }

    @app.get("/god/audit", tags=["GOD MODE"])
    async def god_audit(
        store: AppStore = store_dep, limit: int = Query(100, ge=1, le=500),
        _: None = god_dep,
    ):
        rows = AuditRepo(store.db).list(limit)
        return {
            "total": len(rows),
            "entries": [
                {
                    "action": r.action,
                    "agent_id": r.agent_id,
                    "allowed": r.allowed,
                    "reason": r.reason,
                    "payload": r.payload,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ],
        }

    return app


# Default app for `uvicorn team_builder.api:app` — usa o DSN configurado
# (TEAM_BUILDER_DSN ou sqlite file) para que API e escritores externos
# (ex.: GitHubOps) compartilhem o MESMO banco de continuidade.
_default_settings = Settings()
app = create_app(
    db_url=_default_settings.db_url,
    god_secret=_default_settings.god_mode_secret,
)
