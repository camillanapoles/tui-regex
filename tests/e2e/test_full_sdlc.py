"""E2E — full SDLC flow with a real team, parallel execution, gate
violations and DB evidence. No LLM network calls (MockLLM), but the whole
pipeline (factory -> fsm -> gates -> tools -> wasm -> db) runs for real.
"""
import asyncio

import pytest
from team_builder.db import AgentRepo, FSMRepo, GateRepo, TaskRepo
from team_builder.factory import AgentFactory
from team_builder.fsm import FSMEvent, FSMState
from team_builder.gates import GateInput, WasmSandboxGate
from team_builder.models import AgentRole
from team_builder.tools import ToolExecutor, ToolRegistry, builtin_specs
from team_builder.wasm import SandboxPool

from tests.helpers import make_context

FIVE_ROLES = [
    AgentRole.PROJECT_MANAGER,
    AgentRole.ARCHITECT,
    AgentRole.DEVELOPER,
    AgentRole.QA_ENGINEER,
    AgentRole.DEVOPS,
]


def attach_db_persistence(registry, db) -> None:
    """Conecta o registry de gates ao banco (mesmo contrato da API)."""

    def persist(record):
        try:
            GateRepo(db).save(record)
        except Exception:
            db.rollback()

    registry.attach_persistence(persist)


class TestFullSDLCFlow:
    @pytest.mark.asyncio
    async def test_team_creation_and_full_lifecycle_per_agent(self, llm, registry, db):
        ctx = make_context(FIVE_ROLES)
        team = await AgentFactory.create_team(ctx, llm, db=db, registry=registry)

        assert len(team.agents) == 5
        for agent in team.agents:
            assert agent.state == FSMState.IDLE
            output = await agent.work(
                {"title": f"tarefa-{agent.spec.role.value}", "description": "E2E"}
            )
            assert agent.state == FSMState.COMPLETED, agent.agent_id
            assert output.agent_role == agent.spec.role.value
            assert isinstance(output.result, dict)
            assert output.next_event == FSMEvent.COMPLETE

    @pytest.mark.asyncio
    async def test_parallel_agent_execution(self, llm, registry, db):
        """SDLC paralelo: todos os agentes avançam simultaneamente."""
        ctx = make_context(FIVE_ROLES)
        team = await AgentFactory.create_team(ctx, llm, db=db, registry=registry)

        async def run(agent):
            output = await agent.work({"title": "paralela", "description": "E2E"})
            return agent.state, output.agent_role

        results = await asyncio.gather(*[run(a) for a in team.agents])
        assert all(state == FSMState.COMPLETED for state, _ in results)
        assert len({role for _, role in results}) == 5

    @pytest.mark.asyncio
    async def test_gate_violation_blocks_all_agents(self, llm, registry):
        ctx = make_context(FIVE_ROLES)
        team = await AgentFactory.create_team(ctx, llm, registry=registry)

        for agent in team.agents:
            result = await agent.fsm.trigger(
                FSMEvent.TASK_RECEIVED, payload={"_api_context": False}  # VIOLAÇÃO
            )
            assert result.success is False
            assert agent.state == FSMState.BLOCKED
            assert "FORA da API" in (result.error or "")

        assert len(registry.list_blocked()) >= 5

    @pytest.mark.asyncio
    async def test_gate_registry_tracks_everything(self, llm, registry, db):
        attach_db_persistence(registry, db)
        ctx = make_context(FIVE_ROLES)
        team = await AgentFactory.create_team(ctx, llm, db=db, registry=registry)
        for agent in team.agents:
            await agent.work({"title": "t", "description": "E2E"})

        # cada work() = 3 transições x 4 gates = 12 gate executions
        # 5 agentes => 60 gate executions no mínimo
        total = len(registry.list_all())
        assert total >= 60, f"esperado >= 60 gates, obtido {total}"

        # evidência relacional no banco
        assert AgentRepo(db).list() and len(AgentRepo(db).list()) == 5
        assert FSMRepo(db).count() >= 15
        assert len(GateRepo(db).list_all()) >= 60

    @pytest.mark.asyncio
    async def test_wasm_tool_end_to_end(self, llm, registry, db):
        ctx = make_context(FIVE_ROLES)
        team = await AgentFactory.create_team(ctx, llm, db=db, registry=registry)
        dev = team.get_by_role(AgentRole.DEVELOPER)[0]

        pool = SandboxPool(max_size=5)
        tool_registry = ToolRegistry()
        for spec in builtin_specs():
            tool_registry.register(spec)
        executor = ToolExecutor(registry, pool, tool_registry)

        try:
            result = await executor.execute(
                "uppercase", {"text": "wasm e2e ok"}, dev.agent_id, "developer"
            )
            assert result["success"] is True
            assert result["output"] == "WASM E2E OK"
            assert result["gate_id"].startswith("gate-")

            fib = await executor.execute("fibonacci", {"n": 12}, dev.agent_id, "developer")
            assert fib["output"] == "144"

            # tool bloqueada para o role errado — gate visível no registry
            pm = team.get_by_role(AgentRole.PROJECT_MANAGER)[0]
            with pytest.raises(Exception) as excinfo:
                await executor.execute(
                    "uppercase", {"text": "x"}, pm.agent_id, "project_manager"
                )
            assert "project_manager" in str(excinfo.value)
            assert len(registry.list_blocked()) >= 1
        finally:
            pool.close()

    @pytest.mark.asyncio
    async def test_wasm_sandbox_gate_blocks_dangerous_code(self, registry):
        gate = WasmSandboxGate(registry)
        out = await gate(
            GateInput(
                agent_id="dev-1",
                payload={"code": "import os; os.system('rm -rf /')", "agent_role": "developer"},
                agent_role="developer",
                api_context=True,
            )
        )
        assert out.allowed is False
        assert "import os" in (out.reason or "")

    @pytest.mark.asyncio
    async def test_task_persisted_with_gate_fks(self, llm, registry, db):
        ctx = make_context([AgentRole.DEVELOPER])
        team = await AgentFactory.create_team(ctx, llm, db=db, registry=registry)
        dev = team.get_by_role(AgentRole.DEVELOPER)[0]

        task_id = f"task-e2e-{dev.agent_id}"
        TaskRepo(db).create(dev.agent_id, "E2E task", task_id=task_id, status="running")
        output = await dev.work({"title": "E2E", "description": "persistir", "task_id": task_id})
        assert output.task_id == task_id
        # a transição final (complete) carrega os gate_ids no banco
        rows = FSMRepo(db).list_by_agent(dev.agent_id)
        assert rows[-1].event == "complete"
        assert len(rows[-1].gate_ids) >= 3
