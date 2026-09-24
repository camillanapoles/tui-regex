"""FSM engine — the state machine every agent runs on.

Every transition goes through the GATE PIPELINE:
  pre-gates  (ApiGate -> SdlcPhaseGate -> RolePermissionGate)
  transition + action handler (OOP, registered by the agent)
  post-gates (AuditGate)

The result of a trigger carries ALL gate outputs (with their UUID PKs),
so FSM <-> Gate <-> Input <-> Output is fully traceable. When a DB
session is attached, transitions are persisted to `fsm_transitions`.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from team_builder.gates import (
    GateInput,
    GateOutput,
    GateRegistry,
    build_post_pipeline,
    build_pre_pipeline,
)
from team_builder.ids import new_id

ActionHandler = Callable[[dict], Any] | Callable[[dict], Awaitable[Any]]


# ── States & events ──────────────────────────────────────────────────────
class FSMState(StrEnum):
    IDLE = "idle"
    PLANNING = "planning"
    EXECUTING = "executing"
    WAITING = "waiting"
    REVIEWING = "reviewing"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLBACK = "rollback"


class FSMEvent(StrEnum):
    TASK_RECEIVED = "task_received"
    PLAN_READY = "plan_ready"
    EXECUTE = "execute"
    WAIT_DEP = "wait_dependency"
    DEP_RESOLVED = "dependency_resolved"
    REQUEST_REVIEW = "request_review"
    APPROVE = "approve"
    REJECT = "reject"
    COMPLETE = "complete"
    FAIL = "fail"
    RETRY = "retry"
    ROLLBACK = "rollback"
    RESET = "reset"
    DEPLOY = "deploy"
    BLOCK = "block"


class Transition(BaseModel):
    transition_id: str = Field(default_factory=lambda: new_id("tr"))
    from_state: FSMState
    event: FSMEvent
    to_state: FSMState
    action_name: str | None = None
    description: str = ""


# ── Universal transition table ───────────────────────────────────────────
def _t(
    from_state: FSMState, event: FSMEvent, to_state: FSMState, action: str
) -> Transition:
    return Transition(
        from_state=from_state, event=event, to_state=to_state, action_name=action
    )


UNIVERSAL_TRANSITIONS: list[Transition] = [
    _t(FSMState.IDLE, FSMEvent.TASK_RECEIVED, FSMState.PLANNING, "on_task_received"),
    _t(FSMState.PLANNING, FSMEvent.PLAN_READY, FSMState.EXECUTING, "on_plan_ready"),
    _t(FSMState.PLANNING, FSMEvent.WAIT_DEP, FSMState.WAITING, "on_wait"),
    _t(FSMState.WAITING, FSMEvent.DEP_RESOLVED, FSMState.EXECUTING, "on_resume"),
    _t(FSMState.EXECUTING, FSMEvent.REQUEST_REVIEW, FSMState.REVIEWING, "on_review_request"),
    _t(FSMState.EXECUTING, FSMEvent.COMPLETE, FSMState.COMPLETED, "on_complete"),
    _t(FSMState.EXECUTING, FSMEvent.FAIL, FSMState.FAILED, "on_fail"),
    _t(FSMState.EXECUTING, FSMEvent.DEPLOY, FSMState.COMPLETED, "on_deploy"),
    _t(FSMState.REVIEWING, FSMEvent.APPROVE, FSMState.COMPLETED, "on_approved"),
    _t(FSMState.REVIEWING, FSMEvent.REJECT, FSMState.EXECUTING, "on_rejected"),
    _t(FSMState.FAILED, FSMEvent.RETRY, FSMState.PLANNING, "on_retry"),
    _t(FSMState.FAILED, FSMEvent.ROLLBACK, FSMState.ROLLBACK, "on_rollback"),
    _t(FSMState.ROLLBACK, FSMEvent.RESET, FSMState.IDLE, "on_reset"),
]


# ── Result object (carries gate FKs) ─────────────────────────────────────
class FSMTransitionResult(BaseModel):
    result_id: str = Field(default_factory=lambda: new_id("res"))
    success: bool
    from_state: FSMState
    event: FSMEvent
    to_state: FSMState | None = None
    gate_ids: list[str] = Field(default_factory=list)
    gate_outputs: list[GateOutput] = Field(default_factory=list)
    error: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ── Engine ───────────────────────────────────────────────────────────────
class FSMEngine:
    """Gate-driven FSM. One engine per agent (each agent = microservice).

    `transitions` may be replaced per-agent — but ONLY via GOD MODE
    (the API endpoint /god/fsm/edit), which is the sole mutation surface.
    """

    def __init__(
        self,
        agent_id: str,
        agent_role: str,
        transitions: list[Transition] | None = None,
        registry: GateRegistry | None = None,
        db: Any | None = None,  # SQLAlchemy Session (optional persistence)
    ):
        self.agent_id = agent_id
        self.agent_role = agent_role
        self.transitions = transitions if transitions is not None else UNIVERSAL_TRANSITIONS
        self.state = FSMState.IDLE
        self.db = db
        self.registry = registry or GateRegistry()
        self._map: dict[tuple[FSMState, FSMEvent], Transition] = {
            (t.from_state, t.event): t for t in self.transitions
        }
        self._actions: dict[str, ActionHandler] = {}
        self._pre_gates = build_pre_pipeline(self.registry)
        self._post_gates = build_post_pipeline(self.registry)

    # ── extension points ────────────────────────────────────────────────
    def register_action(self, name: str, fn: ActionHandler) -> None:
        self._actions[name] = fn

    def add_pre_gate(self, gate: Any) -> None:
        """Register an extra pre-transition gate (OOP object)."""
        self._pre_gates.append(gate)
        self._pre_gates.sort(key=lambda g: g.priority)

    def replace_transitions(self, transitions: list[Transition]) -> None:
        """GOD MODE ONLY in practice (guarded at the API layer)."""
        self.transitions = transitions
        self._map = {(t.from_state, t.event): t for t in transitions}

    # ── core ────────────────────────────────────────────────────────────
    async def trigger(
        self,
        event: FSMEvent,
        payload: dict[str, Any] | None = None,
        sdlc_phase: str = "development",
    ) -> FSMTransitionResult:
        payload = dict(payload or {})
        from_state = self.state
        transition = self._map.get((from_state, event))
        if transition is None:
            return FSMTransitionResult(
                success=False,
                from_state=from_state,
                event=event,
                error=f"Transição inválida: {from_state.value} + {event.value}",
            )

        # O role CHECA é o do EMITENTE do evento (vem da API), que pode
        # ser diferente do dono da FSM (ex.: QA aprova a FSM do developer).
        emit_role = str(payload.get("emit_role") or self.agent_role)
        gate_input = GateInput(
            agent_id=self.agent_id,
            payload=payload,
            sdlc_phase=sdlc_phase,
            agent_role=emit_role,
            api_context=bool(payload.get("_api_context", False)),
            event=event.value,
        )

        gate_outputs: list[GateOutput] = []

        # 1) pre-gate pipeline — first block wins
        for gate in self._pre_gates:
            out = await gate(gate_input)
            gate_outputs.append(out)
            if not out.allowed:
                self.state = FSMState.BLOCKED
                self._persist(from_state, FSMState.BLOCKED, event, payload, gate_outputs)
                return FSMTransitionResult(
                    success=False,
                    from_state=from_state,
                    event=event,
                    to_state=FSMState.BLOCKED,
                    gate_ids=[g.gate_id for g in gate_outputs],
                    gate_outputs=gate_outputs,
                    error=out.reason,
                )

        # 2) perform transition
        self.state = transition.to_state

        # 3) action handler (OOP, registered by the agent)
        if transition.action_name and transition.action_name in self._actions:
            handler = self._actions[transition.action_name]
            result = handler(payload)
            if hasattr(result, "__await__"):
                await result

        # 4) persist transition (with gate FKs)
        self._persist(from_state, self.state, event, payload, gate_outputs)

        # 5) post-gates (audit)
        for gate in self._post_gates:
            gate_outputs.append(await gate(gate_input))

        return FSMTransitionResult(
            success=True,
            from_state=from_state,
            event=event,
            to_state=self.state,
            gate_ids=[g.gate_id for g in gate_outputs],
            gate_outputs=gate_outputs,
        )

    def _persist(
        self,
        from_state: FSMState,
        to_state: FSMState,
        event: FSMEvent,
        payload: dict[str, Any],
        gate_outputs: list[GateOutput],
    ) -> None:
        if self.db is None:
            return
        try:
            from team_builder.db import FSMRepo

            FSMRepo(self.db).log_transition(
                agent_id=self.agent_id,
                from_state=from_state.value,
                to_state=to_state.value,
                event=event.value,
                payload={k: v for k, v in payload.items() if k != "_api_context"},
                gate_ids=[g.gate_id for g in gate_outputs],
            )
        except Exception:  # persistence must never break the state machine
            self.db.rollback()
