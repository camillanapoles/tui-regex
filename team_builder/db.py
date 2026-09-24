"""Database layer — SQLAlchemy 2.0 (sync session).

Relational invariants (the "100% related" mandate):
  * gate_records.gate_id is the PK of a gate execution;
  * gate_records.agent_id -> agents.agent_id (FK, SET NULL);
  * gate_records.tool_id  -> tools.tool_id  (FK, SET NULL);
  * fsm_transitions.agent_id -> agents.agent_id (FK);
  * tasks.agent_id -> agents.agent_id (FK);
  * audit_log.gate_id -> gate_records.gate_id (FK).
  * fsm_transitions.gate_ids stores the gate PKs of the transition.

SQLite (with PRAGMA foreign_keys=ON) is the default so the whole platform
runs — and is tested — with zero external services. Point
TEAM_BUILDER_DSN at postgresql+asyncpg://... in production.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    event,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
)
from sqlalchemy.pool import StaticPool

from team_builder.gates import GateRecord
from team_builder.ids import new_id


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


# ── Tables ───────────────────────────────────────────────────────────────
class DevContextRow(Base):
    __tablename__ = "dev_contexts"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_type: Mapped[str] = mapped_column(String(50))
    complexity: Mapped[str] = mapped_column(String(20))
    current_phase: Mapped[str] = mapped_column(String(30))
    tech_stack: Mapped[dict] = mapped_column(JSON, default=dict)
    raw_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AgentRow(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    state: Mapped[str] = mapped_column(String(30), default="idle")
    spec: Mapped[dict] = mapped_column(JSON, default=dict)
    context_id: Mapped[str | None] = mapped_column(
        ForeignKey("dev_contexts.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ToolRow(Base):
    __tablename__ = "tools"

    tool_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(20), default="wasm")
    entrypoint: Mapped[str] = mapped_column(String(200), default="")
    wat: Mapped[str] = mapped_column(Text, default="")
    parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    param_names: Mapped[list] = mapped_column(JSON, default=list)
    input_bytes_key: Mapped[str | None] = mapped_column(String(60), nullable=True)
    assigned_roles: Mapped[list] = mapped_column(JSON, default=list)
    fuel_limit: Mapped[int] = mapped_column(Integer, default=5_000_000)
    created_by: Mapped[str] = mapped_column(String(60), default="god_mode")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GateRecordRow(Base):
    __tablename__ = "gate_records"

    gate_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    gate_name: Mapped[str] = mapped_column(String(80), index=True)
    direction: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), index=True)
    agent_id: Mapped[str | None] = mapped_column(
        ForeignKey("agents.agent_id", ondelete="SET NULL"), nullable=True, index=True
    )
    tool_id: Mapped[str | None] = mapped_column(
        ForeignKey("tools.tool_id", ondelete="SET NULL"), nullable=True, index=True
    )
    event: Mapped[str | None] = mapped_column(String(50), nullable=True)
    input_object: Mapped[dict] = mapped_column(JSON, default=dict)
    output_object: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    duration_ms: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class FSMTransitionRow(Base):
    __tablename__ = "fsm_transitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[str] = mapped_column(
        ForeignKey("agents.agent_id"), index=True, nullable=False
    )
    from_state: Mapped[str] = mapped_column(String(30))
    to_state: Mapped[str] = mapped_column(String(30))
    event: Mapped[str] = mapped_column(String(50), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    gate_ids: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TaskRow(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    agent_id: Mapped[str] = mapped_column(
        ForeignKey("agents.agent_id"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    artifacts: Mapped[list] = mapped_column(JSON, default=list)
    gate_ids: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AuditRow(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    gate_id: Mapped[str | None] = mapped_column(
        ForeignKey("gate_records.gate_id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(120))
    allowed: Mapped[bool] = mapped_column(Boolean, default=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ── Engine / session factory ─────────────────────────────────────────────
def make_engine(url: str | None = None) -> Engine:
    url = url or os.getenv("TEAM_BUILDER_DSN", "sqlite:///./team_builder.db")
    kwargs: dict[str, Any] = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in url or url.rstrip("/") == "sqlite:":
            kwargs["poolclass"] = StaticPool
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _enable_fk(dbapi_conn, _record):  # pragma: no cover - trivial
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    return engine


def init_db(engine: Engine) -> None:
    Base.metadata.create_all(engine)


def save_dev_context(db: Session, context: Any) -> str:
    """Persists a DevContext and returns its id (FK target for agents)."""
    row = DevContextRow(
        id=new_id("ctx"),
        project_type=context.project_type.value,
        complexity=context.complexity.value,
        current_phase=context.current_phase.value,
        tech_stack=context.tech_stack.model_dump(),
        raw_description=None,
    )
    db.add(row)
    db.commit()
    return row.id


# ── Repositories (OOP) ───────────────────────────────────────────────────
class AgentRepo:
    def __init__(self, db: Session):
        self.db = db

    def save(
        self,
        agent_id: str,
        role: str,
        name: str,
        state: str = "idle",
        spec: dict | None = None,
        context_id: str | None = None,
    ) -> AgentRow:
        row = (
            self.db.query(AgentRow).filter(AgentRow.agent_id == agent_id).one_or_none()
        )
        if row is None:
            row = AgentRow(id=new_id("ag"), agent_id=agent_id)
            self.db.add(row)
        row.role = role
        row.name = name
        row.state = state
        row.spec = spec or {}
        row.context_id = context_id
        self.db.commit()
        return row

    def get(self, agent_id: str) -> AgentRow | None:
        return (
            self.db.query(AgentRow).filter(AgentRow.agent_id == agent_id).first()
        )

    def set_state(self, agent_id: str, state: str) -> None:
        row = self.db.get(AgentRow, agent_id)
        if row is not None:
            row.state = state
            self.db.commit()

    def list(self) -> list[AgentRow]:
        return list(self.db.query(AgentRow).all())


class GateRepo:
    def __init__(self, db: Session):
        self.db = db

    def save(self, record: GateRecord) -> None:
        row = self.db.get(GateRecordRow, record.gate_id, populate_existing=True)
        if row is None:
            row = GateRecordRow(gate_id=record.gate_id)
            self.db.add(row)
        row.gate_name = record.gate_name
        row.direction = record.direction.value
        row.status = record.status.value
        row.agent_id = record.agent_id
        row.tool_id = record.tool_id
        row.event = record.event
        row.input_object = (
            record.input_object.model_dump(mode="json") if record.input_object else {}
        )
        row.output_object = (
            record.output_object.model_dump(mode="json") if record.output_object else None
        )
        row.duration_ms = (
            record.output_object.duration_ms if record.output_object else 0.0
        )
        row.created_at = record.created_at
        row.completed_at = record.completed_at
        self.db.commit()

    def get(self, gate_id: str) -> GateRecordRow | None:
        return self.db.get(GateRecordRow, gate_id)

    def list_all(self) -> list[GateRecordRow]:
        return list(self.db.query(GateRecordRow).all())

    def list_blocked(self) -> list[GateRecordRow]:
        return list(
            self.db.query(GateRecordRow).filter(GateRecordRow.status == "blocked").all()
        )


class FSMRepo:
    def __init__(self, db: Session):
        self.db = db

    def log_transition(
        self,
        agent_id: str,
        from_state: str,
        to_state: str,
        event: str,
        payload: dict | None = None,
        gate_ids: list[str] | None = None,
    ) -> None:
        self.db.add(
            FSMTransitionRow(
                agent_id=agent_id,
                from_state=from_state,
                to_state=to_state,
                event=event,
                payload=payload or {},
                gate_ids=gate_ids or [],
            )
        )
        self.db.commit()

    def list_by_agent(self, agent_id: str) -> list[FSMTransitionRow]:
        return list(
            self.db.query(FSMTransitionRow)
            .filter(FSMTransitionRow.agent_id == agent_id)
            .order_by(FSMTransitionRow.id)
            .all()
        )

    def count(self) -> int:
        return self.db.query(FSMTransitionRow).count()


class TaskRepo:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        agent_id: str,
        title: str,
        description: str = "",
        task_id: str | None = None,
        status: str = "pending",
    ) -> TaskRow:
        row = TaskRow(
            id=new_id("task"),
            task_id=task_id or new_id("task"),
            agent_id=agent_id,
            title=title,
            description=description,
            status=status,
        )
        self.db.add(row)
        self.db.commit()
        return row

    def get(self, task_id: str) -> TaskRow | None:
        return (
            self.db.query(TaskRow).filter(TaskRow.task_id == task_id).first()
        )

    def update(
        self,
        task_id: str,
        status: str | None = None,
        result: dict | None = None,
        artifacts: list | None = None,
        gate_ids: list | None = None,
    ) -> TaskRow | None:
        row = self.db.query(TaskRow).filter(TaskRow.task_id == task_id).first()
        if row is None:
            return None
        if status is not None:
            row.status = status
        if result is not None:
            row.result = result
        if artifacts is not None:
            row.artifacts = artifacts
        if gate_ids is not None:
            row.gate_ids = gate_ids
        if status in ("completed", "failed"):
            row.completed_at = utcnow()
        self.db.commit()
        return row

    def list(self, agent_id: str | None = None) -> list[TaskRow]:
        query = self.db.query(TaskRow)
        if agent_id:
            query = query.filter(TaskRow.agent_id == agent_id)
        return list(query.all())


class ToolRepo:
    def __init__(self, db: Session):
        self.db = db

    def save(self, spec: Any) -> None:
        row = self.db.get(ToolRow, spec.tool_id, populate_existing=True)
        if row is None:
            row = ToolRow(tool_id=spec.tool_id)
            self.db.add(row)
        row.name = spec.name
        row.description = spec.description
        row.kind = spec.kind
        row.entrypoint = spec.entrypoint
        row.wat = spec.wat
        row.parameters = spec.parameters
        row.param_names = spec.param_names
        row.input_bytes_key = spec.input_bytes_key
        row.assigned_roles = spec.assigned_roles
        row.fuel_limit = spec.fuel_limit
        self.db.commit()

    def get(self, tool_id: str) -> ToolRow | None:
        return self.db.get(ToolRow, tool_id)

    def list(self) -> list[ToolRow]:
        return list(self.db.query(ToolRow).all())


class AuditRepo:
    def __init__(self, db: Session):
        self.db = db

    def log(
        self,
        action: str,
        allowed: bool = True,
        agent_id: str | None = None,
        gate_id: str | None = None,
        reason: str | None = None,
        payload: dict | None = None,
    ) -> None:
        self.db.add(
            AuditRow(
                agent_id=agent_id,
                gate_id=gate_id,
                action=action,
                allowed=allowed,
                reason=reason,
                payload=payload or {},
            )
        )
        self.db.commit()

    def list(self, limit: int = 100) -> list[AuditRow]:
        return list(
            self.db.query(AuditRow).order_by(AuditRow.id.desc()).limit(limit).all()
        )


def make_session(engine: Engine) -> Session:
    return Session(engine, expire_on_commit=False)
