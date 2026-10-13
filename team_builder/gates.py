"""Gate layer — the mandatory action-interception core.

Constitution (Art. 1):
  * Every action in the platform is mediated by a GateFunction.
  * A GateFunction is a FIRST-CLASS OBJECT with a unique PK (`gate_id`).
  * Every gate execution relates an input object (GateInput) to an output
    object (GateOutput) — `GateOutput.input_id` and `GateOutput.gate_id`
    are mandatory FKs. Event-driven or function-driven, ALWAYS.
  * Gates are OOP: every gate is a callable object (async `__call__`).
  * Every gate execution is persisted to the GateRegistry (and to the DB
    when a repository is attached), producing an immutable audit trail.
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from team_builder.ids import new_id

logger = logging.getLogger("team_builder.audit")


def utcnow() -> datetime:
    return datetime.now(UTC)


class GateStatus(StrEnum):
    PENDING = "pending"
    EXECUTING = "executing"
    ALLOWED = "allowed"
    BLOCKED = "blocked"
    FAILED = "failed"


class GateDirection(StrEnum):
    PRE_TRANSITION = "pre_transition"
    POST_TRANSITION = "post_transition"
    TOOL_CALL = "tool_call"
    API_REQUEST = "api_request"
    WASM_EXEC = "wasm_exec"


# ── Related objects ──────────────────────────────────────────────────────
class GateInput(BaseModel):
    """Input object of a gate execution — frozen (immutable) after creation."""

    model_config = ConfigDict(frozen=True)

    object_id: str = Field(default_factory=lambda: new_id("inp"))
    agent_id: str
    payload: dict[str, Any] = Field(default_factory=dict)
    sdlc_phase: str = "development"
    agent_role: str = ""
    api_context: bool = False  # MANDATORY: did this action come through the API?
    tool_id: str | None = None
    event: str = ""
    timestamp: datetime = Field(default_factory=utcnow)


class GateOutput(BaseModel):
    """Output object — mandatory FKs back to the input and the gate record."""

    model_config = ConfigDict(frozen=True)

    object_id: str = Field(default_factory=lambda: new_id("out"))
    input_id: str  # FK -> GateInput.object_id
    gate_id: str  # FK -> GateRecord.gate_id
    allowed: bool
    result: Any | None = None
    reason: str | None = None
    duration_ms: float = 0.0
    timestamp: datetime = Field(default_factory=utcnow)


class GateRecord(BaseModel):
    """Persistent record of one gate execution (PK: gate_id)."""

    gate_id: str = Field(default_factory=lambda: new_id("gate"))
    gate_name: str
    direction: GateDirection
    status: GateStatus = GateStatus.PENDING
    agent_id: str | None = None
    tool_id: str | None = None
    event: str | None = None
    input_object: GateInput | None = None
    output_object: GateOutput | None = None
    created_at: datetime = Field(default_factory=utcnow)
    completed_at: datetime | None = None


# ── Registry ─────────────────────────────────────────────────────────────
class GateRegistry:
    """In-memory registry of all gate executions (DB-backed when attached).

    Guarantees platform-wide traceability: input -> gate -> output -> agent.
    """

    def __init__(self, on_record: Callable[[GateRecord], None] | None = None):
        self._records: dict[str, GateRecord] = {}
        self._on_record = on_record

    def attach_persistence(self, on_record: Callable[[GateRecord], None]) -> None:
        self._on_record = on_record

    def record(self, rec: GateRecord) -> None:
        self._records[rec.gate_id] = rec
        if self._on_record is not None:
            self._on_record(rec)

    def get(self, gate_id: str) -> GateRecord | None:
        return self._records.get(gate_id)

    def list_all(self) -> list[GateRecord]:
        return list(self._records.values())

    def list_by_agent(self, agent_id: str) -> list[GateRecord]:
        return [r for r in self._records.values() if r.agent_id == agent_id]

    def list_blocked(self) -> list[GateRecord]:
        return [
            r for r in self._records.values() if r.status == GateStatus.BLOCKED
        ]

    def stats(self) -> dict[str, Any]:
        records = list(self._records.values())
        by_status: dict[str, int] = {}
        for r in records:
            by_status[r.status.value] = by_status.get(r.status.value, 0) + 1
        return {"total": len(records), "by_status": by_status}


# ── Base gate (OOP, callable) ────────────────────────────────────────────
class BaseGate(ABC):
    """Abstract gate. Subclasses implement `execute()`.

    The `__call__` protocol guarantees, for EVERY gate in the platform:
      1. a GateRecord with unique PK is created (status=executing),
      2. the handler runs (function-driven here; event-driven gates are
         registered the same way and invoked by the event bus),
      3. the GateOutput is linked to the input and the record (FKs),
      4. the record is finalized (allowed/blocked/failed) and persisted.
    """

    gate_name: str = "base_gate"
    direction: GateDirection = GateDirection.PRE_TRANSITION
    priority: int = 100

    def __init__(self, registry: GateRegistry):
        self.registry = registry

    async def __call__(self, inp: GateInput) -> GateOutput:
        started = time.perf_counter()
        record = GateRecord(
            gate_name=self.gate_name,
            direction=self.direction,
            agent_id=inp.agent_id,
            tool_id=inp.tool_id,
            event=inp.event or None,
            input_object=inp,
            status=GateStatus.EXECUTING,
        )
        self.registry.record(record)
        try:
            out = await self.execute(inp, record)
            # Enforce FK invariants: output must point to this record/input.
            if out.gate_id != record.gate_id or out.input_id != inp.object_id:
                out = GateOutput(
                    object_id=out.object_id,
                    input_id=inp.object_id,
                    gate_id=record.gate_id,
                    allowed=out.allowed,
                    result=out.result,
                    reason=out.reason,
                    duration_ms=out.duration_ms,
                )
            record.output_object = out
            record.status = GateStatus.ALLOWED if out.allowed else GateStatus.BLOCKED
        except Exception as exc:  # a gate must never crash the pipeline
            out = GateOutput(
                input_id=inp.object_id,
                gate_id=record.gate_id,
                allowed=False,
                reason=f"gate '{self.gate_name}' raised: {exc}",
                duration_ms=(time.perf_counter() - started) * 1000,
            )
            record.output_object = out
            record.status = GateStatus.FAILED
        record.completed_at = utcnow()
        self.registry.record(record)
        return out

    @abstractmethod
    async def execute(self, inp: GateInput, record: GateRecord) -> GateOutput:
        """Gate logic — must return a GateOutput linked to (inp, record)."""
        ...

    # convenience for subclasses
    def _out(
        self,
        inp: GateInput,
        record: GateRecord,
        allowed: bool,
        result: Any | None = None,
        reason: str | None = None,
        started: float | None = None,
    ) -> GateOutput:
        duration = (time.perf_counter() - started) * 1000 if started else 0.0
        return GateOutput(
            input_id=inp.object_id,
            gate_id=record.gate_id,
            allowed=allowed,
            result=result,
            reason=reason,
            duration_ms=duration,
        )


# ── Concrete gates ───────────────────────────────────────────────────────
class ApiGate(BaseGate):
    """CRITICAL: blocks any action that did NOT come through the central API.

    This is the enforcement point of the constitution rule 'nenhuma ação
    acontece fora da API' — agents acting directly (without api_context)
    are blocked here and audited.
    """

    gate_name = "api_gate"
    direction = GateDirection.API_REQUEST
    priority = 0

    async def execute(self, inp: GateInput, record: GateRecord) -> GateOutput:
        started = time.perf_counter()
        if not inp.api_context:
            return self._out(
                inp,
                record,
                allowed=False,
                reason="VIOLAÇÃO: ação detectada FORA da API Central. Bloqueada.",
                started=started,
            )
        return self._out(
            inp,
            record,
            allowed=True,
            result={"verified": "api_context_ok"},
            started=started,
        )


class SdlcPhaseGate(BaseGate):
    """Blocks FSM events that are invalid for the current SDLC phase."""

    gate_name = "sdlc_phase_gate"
    direction = GateDirection.PRE_TRANSITION
    priority = 1

    PHASE_ALLOWED: dict[str, list[str]] = {
        "discovery": ["task_received", "plan_ready"],
        "planning": ["task_received", "plan_ready", "wait_dependency"],
        "architecture": ["task_received", "plan_ready", "execute", "request_review"],
        "development": [
            "task_received", "plan_ready", "execute",
            "complete", "fail", "retry", "request_review",
            "approve", "reject", "rollback", "reset",
        ],
        "testing": ["task_received", "execute", "request_review", "approve", "reject"],
        "review": ["request_review", "approve", "reject"],
        "deployment": ["task_received", "execute", "complete", "rollback", "deploy"],
        "monitoring": ["task_received", "execute", "complete", "fail"],
        "maintenance": [
            "task_received", "execute", "complete", "fail", "retry", "rollback",
        ],
    }

    async def execute(self, inp: GateInput, record: GateRecord) -> GateOutput:
        started = time.perf_counter()
        allowed_events = self.PHASE_ALLOWED.get(inp.sdlc_phase)
        if allowed_events and inp.event and inp.event not in allowed_events:
            return self._out(
                inp,
                record,
                allowed=False,
                reason=f"Evento '{inp.event}' não permitido na fase SDLC '{inp.sdlc_phase}'.",
                started=started,
            )
        return self._out(
            inp,
            record,
            allowed=True,
            result={"phase": inp.sdlc_phase, "event": inp.event},
            started=started,
        )


def _build_role_events(core: list[str], extra: dict[str, list[str]]) -> dict[str, list[str]]:
    return {role: list(core) + list(x) for role, x in extra.items()}


class RolePermissionGate(BaseGate):
    """Blocks FSM events that the agent's role is not allowed to emit."""

    gate_name = "role_permission_gate"
    direction = GateDirection.PRE_TRANSITION
    priority = 2

    # Every role drives its own FSM lifecycle (task -> plan -> execute ->
    # finish). Roles differ in EXTRA powers they may emit: approvals,
    # deployments, blocks...
    _CORE_EVENTS: list[str] = [
        "task_received", "plan_ready", "execute", "wait_dependency",
        "dependency_resolved", "request_review", "complete", "fail",
        "retry", "reset",
    ]
    _EXTRA_EVENTS: dict[str, list[str]] = {
        "project_manager": ["approve", "reject"],
        "architect": ["approve"],
        "developer": [],
        "qa_engineer": ["approve", "reject"],
        "devops": ["approve", "deploy", "rollback"],
        "security": ["approve", "reject", "block"],
        "tech_writer": [],
        "data_engineer": [],
        "ml_engineer": [],
        "ux_researcher": [],
        "compliance": ["approve", "reject"],
    }

    @classmethod
    def _role_events(cls) -> dict[str, list[str]]:
        return {
            role: list(cls._CORE_EVENTS) + list(extra)
            for role, extra in cls._EXTRA_EVENTS.items()
        }

    # materialized for introspection/tests
    ROLE_EVENTS: dict[str, list[str]] = _build_role_events(_CORE_EVENTS, _EXTRA_EVENTS)

    async def execute(self, inp: GateInput, record: GateRecord) -> GateOutput:
        started = time.perf_counter()
        allowed = self._role_events().get(inp.agent_role)
        if allowed is None:
            return self._out(
                inp,
                record,
                allowed=False,
                reason=f"Role '{inp.agent_role}' desconhecida — negado por padrão.",
                started=started,
            )
        if inp.event and inp.event not in allowed:
            return self._out(
                inp,
                record,
                allowed=False,
                reason=f"Role '{inp.agent_role}' não pode emitir evento '{inp.event}'.",
                started=started,
            )
        return self._out(
            inp,
            record,
            allowed=True,
            result={"role": inp.agent_role, "event": inp.event},
            started=started,
        )


class WasmSandboxGate(BaseGate):
    """Authorizes code execution inside the WASM sandbox.

    Checks: role eligibility, code size limit, and a static blocklist of
    dangerous Python constructs. Defense-in-depth only — the real
    isolation is Wasmtime's fuel/epoch + linear memory.
    """

    gate_name = "wasm_sandbox_gate"
    direction = GateDirection.WASM_EXEC
    priority = 3

    ALLOWED_ROLES = {
        "developer", "qa_engineer", "devops", "ml_engineer", "data_engineer",
    }
    MAX_CODE_SIZE = 1_048_576  # 1 MiB
    DANGEROUS_PATTERNS = (
        "import os", "subprocess", "__import__", "eval(", "exec(",
        "open(", "socket", "shutil.rmtree",
    )

    async def execute(self, inp: GateInput, record: GateRecord) -> GateOutput:
        started = time.perf_counter()
        role = inp.payload.get("agent_role", inp.agent_role)
        code = inp.payload.get("code", "")

        if role not in self.ALLOWED_ROLES:
            return self._out(
                inp, record, allowed=False,
                reason=f"Role '{role}' não autorizada a executar no sandbox WASM.",
                started=started,
            )
        code_bytes = len(str(code).encode("utf-8"))
        if code_bytes > self.MAX_CODE_SIZE:
            return self._out(
                inp, record, allowed=False,
                reason=f"Código excede o limite de 1MiB ({code_bytes} bytes).",
                started=started,
            )
        for pattern in self.DANGEROUS_PATTERNS:
            if pattern in code:
                return self._out(
                    inp, record, allowed=False,
                    reason=f"Padrão perigoso detectado: '{pattern}'. Bloqueado.",
                    started=started,
                )
        return self._out(
            inp, record, allowed=True,
            result={"code_bytes": code_bytes, "role": role},
            started=started,
        )


class ToolAuthorizationGate(BaseGate):
    """Authorizes an agent to invoke a specific tool (MCP tool-call gate).

    Two-level policy:
      1. tool has explicit `assigned_roles` (set when GOD forges it) ->
         allow iff agent role is in that list;
      2. otherwise fall back to the static per-role tool map
         (deny-by-default for unknown roles).
    """

    gate_name = "tool_authorization_gate"
    direction = GateDirection.TOOL_CALL
    priority = 4

    ROLE_TOOLS: dict[str, list[str]] = {
        "developer": [
            "uppercase", "fibonacci", "add", "code_exec", "lint", "test_run",
            "file_write", "git_commit",
        ],
        "qa_engineer": ["uppercase", "test_run", "coverage_report", "bug_report"],
        "devops": ["uppercase", "add", "deploy", "docker_build", "monitor"],
        "security": ["uppercase", "scan_code", "audit_log", "penetration_test"],
        "architect": ["uppercase", "add", "diagram_gen", "adr_write", "code_review"],
        "project_manager": ["report_gen", "task_create"],
        "tech_writer": ["uppercase", "doc_write", "doc_publish"],
        "data_engineer": ["uppercase", "add", "data_fetch", "pipeline_run", "schema_validate"],
        "ml_engineer": ["uppercase", "add", "model_train", "code_exec", "experiment_log"],
        "ux_researcher": ["doc_write", "survey_gen"],
        "compliance": ["audit_log", "report_gen"],
    }

    async def execute(self, inp: GateInput, record: GateRecord) -> GateOutput:
        started = time.perf_counter()
        tool_name = inp.payload.get("tool_id", "") or (inp.tool_id or "")
        tool_roles = inp.payload.get("tool_roles") or []

        if tool_roles:  # explicit assignment (GOD-forged tool)
            if inp.agent_role in tool_roles:
                return self._out(
                    inp, record, allowed=True,
                    result={"tool": tool_name, "via": "assigned_roles"},
                    started=started,
                )
            return self._out(
                inp, record, allowed=False,
                reason=f"Role '{inp.agent_role}' não está nos assigned_roles da tool '{tool_name}'.",
                started=started,
            )

        allowed = self.ROLE_TOOLS.get(inp.agent_role)
        if allowed is None:
            return self._out(
                inp, record, allowed=False,
                reason=f"Role '{inp.agent_role}' desconhecida — negado por padrão.",
                started=started,
            )
        if tool_name not in allowed:
            return self._out(
                inp, record, allowed=False,
                reason=f"Role '{inp.agent_role}' não autorizada a usar a tool '{tool_name}'.",
                started=started,
            )
        return self._out(
            inp, record, allowed=True, result={"tool": tool_name}, started=started
        )


class AuditGate(BaseGate):
    """Post-transition gate — always allows, records everything."""

    gate_name = "audit_gate"
    direction = GateDirection.POST_TRANSITION
    priority = 99

    async def execute(self, inp: GateInput, record: GateRecord) -> GateOutput:
        started = time.perf_counter()
        logger.info(
            "[AUDIT] gate=%s agent=%s role=%s phase=%s event=%s",
            record.gate_id, inp.agent_id, inp.agent_role, inp.sdlc_phase, inp.event,
        )
        return self._out(
            inp,
            record,
            allowed=True,
            result={"audited": True, "agent_id": inp.agent_id},
            started=started,
        )


# ── Pipelines ────────────────────────────────────────────────────────────
def build_pre_pipeline(registry: GateRegistry) -> list[BaseGate]:
    """Ordered pre-transition gates (first block wins)."""
    gates = [
        ApiGate(registry),
        SdlcPhaseGate(registry),
        RolePermissionGate(registry),
    ]
    return sorted(gates, key=lambda g: g.priority)


def build_post_pipeline(registry: GateRegistry) -> list[BaseGate]:
    gates = [AuditGate(registry)]
    return sorted(gates, key=lambda g: g.priority)
