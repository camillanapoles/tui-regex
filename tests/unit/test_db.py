"""DB tests — repositories + relational invariants (FKs really enforced)."""
import pytest
from sqlalchemy.exc import IntegrityError
from team_builder.db import (
    AgentRepo,
    AuditRepo,
    FSMRepo,
    GateRepo,
    TaskRepo,
    ToolRepo,
    save_dev_context,
)
from team_builder.gates import GateDirection, GateInput, GateRecord, GateStatus
from team_builder.models import (
    ComplexityLevel,
    DevContext,
    ProjectType,
    SDLCPhase,
    TechStack,
)
from team_builder.tools import ToolSpec


def make_context_row() -> DevContext:
    return DevContext(
        project_type=ProjectType.WEB_APP,
        complexity=ComplexityLevel.LOW,
        current_phase=SDLCPhase.DEVELOPMENT,
        tech_stack=TechStack(languages=["python"]),
    )


def make_record(agent_id=None, tool_id=None) -> GateRecord:
    inp = GateInput(agent_id=agent_id or "ghost", payload={}, api_context=True)
    return GateRecord(
        gate_name="api_gate",
        direction=GateDirection.PRE_TRANSITION,
        status=GateStatus.ALLOWED,
        agent_id=agent_id,
        tool_id=tool_id,
        event="task_received",
        input_object=inp,
    )


class TestAgentRepo:
    def test_save_and_get(self, db):
        repo = AgentRepo(db)
        repo.save("dev-1", "developer", "Dev One")
        row = repo.get("dev-1")
        assert row is not None
        assert row.role == "developer"
        assert row.state == "idle"

    def test_upsert_same_agent_id(self, db):
        repo = AgentRepo(db)
        repo.save("dev-1", "developer", "Dev One")
        repo.save("dev-1", "developer", "Dev Renamed", state="planning")
        assert len(repo.list()) == 1
        assert repo.get("dev-1").name == "Dev Renamed"
        assert repo.get("dev-1").state == "planning"

    def test_context_fk_required(self, db):
        repo = AgentRepo(db)
        with pytest.raises(IntegrityError), db.begin_nested():
            repo.save("dev-2", "developer", "Dev Two", context_id="ctx-does-not-exist")
            db.commit()


class TestGateRepo:
    def test_save_roundtrip(self, db):
        AgentRepo(db).save("dev-1", "developer", "Dev One")
        repo = GateRepo(db)
        record = make_record(agent_id="dev-1")
        repo.save(record)
        row = repo.get(record.gate_id)
        assert row is not None
        assert row.gate_name == "api_gate"
        assert row.status == "allowed"
        assert row.input_object["agent_id"] == "dev-1"

    def test_upsert_by_pk(self, db):
        AgentRepo(db).save("dev-1", "developer", "Dev One")
        repo = GateRepo(db)
        record = make_record(agent_id="dev-1")
        repo.save(record)
        repo.save(record)
        assert len(repo.list_all()) == 1

    def test_agent_fk_enforced(self, db):
        repo = GateRepo(db)
        with pytest.raises(IntegrityError), db.begin_nested():
            repo.save(make_record(agent_id="agent-never-created"))
            db.commit()


class TestToolRepo:
    def test_save_and_list(self, db):
        spec = ToolSpec(name="t1", description="d", wat="(module)")
        ToolRepo(db).save(spec)
        rows = ToolRepo(db).list()
        assert len(rows) == 1
        assert rows[0].name == "t1"

    def test_gate_tool_fk_enforced(self, db):
        record = make_record(tool_id="tool-never-created")
        with pytest.raises(IntegrityError), db.begin_nested():
            GateRepo(db).save(record)
            db.commit()


class TestFSMRepo:
    def test_log_and_list(self, db):
        AgentRepo(db).save("dev-1", "developer", "Dev One")
        repo = FSMRepo(db)
        repo.log_transition("dev-1", "idle", "planning", "task_received",
                            payload={"a": 1}, gate_ids=["gate-1"])
        rows = repo.list_by_agent("dev-1")
        assert len(rows) == 1
        assert rows[0].gate_ids == ["gate-1"]
        assert repo.count() == 1

    def test_agent_fk_enforced(self, db):
        repo = FSMRepo(db)
        with pytest.raises(IntegrityError), db.begin_nested():
            repo.log_transition("ghost", "idle", "planning", "task_received")
            db.commit()


class TestTaskAndAudit:
    def test_task_lifecycle(self, db):
        AgentRepo(db).save("dev-1", "developer", "Dev One")
        repo = TaskRepo(db)
        repo.create("dev-1", "T1", "desc", task_id="task-1")
        repo.update("task-1", status="completed", result={"ok": True},
                    artifacts=["a.py"], gate_ids=["gate-x"])
        got = repo.get("task-1")
        assert got.status == "completed"
        assert got.result == {"ok": True}
        assert got.artifacts == ["a.py"]
        assert got.gate_ids == ["gate-x"]
        assert got.completed_at is not None

    def test_task_fk_enforced(self, db):
        repo = TaskRepo(db)
        with pytest.raises(IntegrityError), db.begin_nested():
            repo.create("ghost", "T")
            db.commit()

    def test_audit_log(self, db):
        repo = AuditRepo(db)
        repo.log("god.build_team", payload={"agents": 5})
        rows = repo.list()
        assert len(rows) == 1
        assert rows[0].action == "god.build_team"
        assert rows[0].allowed is True


class TestDevContext:
    def test_save_dev_context(self, db):
        ctx_id = save_dev_context(db, make_context_row())
        assert ctx_id.startswith("ctx-")
        # agent can reference it
        AgentRepo(db).save("dev-1", "developer", "Dev One", context_id=ctx_id)
        assert AgentRepo(db).get("dev-1").context_id == ctx_id
