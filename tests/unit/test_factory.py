"""Factory tests — 11 roles, dynamic creators, no hardcode, team creation."""
import inspect

import pytest
from team_builder.agents import (
    ArchitectAgent,
    ComplianceAgent,
    DataEngineerAgent,
    DeveloperAgent,
    DevOpsAgent,
    GenericAgent,
    MLEngineerAgent,
    PMAgent,
    QAAgent,
    SecurityAgent,
    TechWriterAgent,
    UXResearcherAgent,
)
from team_builder.factory import AgentCreator, AgentFactory, AgentTeam
from team_builder.fsm import FSMEngine
from team_builder.ids import short_id
from team_builder.llm import MockLLM
from team_builder.models import AgentRole

from tests.helpers import make_context, make_spec


class TestAgentFactory:
    @pytest.mark.asyncio
    async def test_creates_developer_agent(self):
        spec, ctx, llm = make_spec(AgentRole.DEVELOPER), make_context(), MockLLM()
        agent = await AgentFactory.create_agent(spec, ctx, llm)
        assert isinstance(agent, DeveloperAgent)
        assert agent.agent_id.startswith("dev-")
        assert agent.spec.role == AgentRole.DEVELOPER

    @pytest.mark.asyncio
    async def test_creates_all_11_roles_with_distinct_classes(self, llm):
        ctx = make_context(list(AgentRole))
        agents = [
            await AgentFactory.create_agent(spec, ctx, llm)
            for spec in ctx.team_agents
        ]
        assert len(agents) == 11
        classes = {type(a) for a in agents}
        expected = {
            PMAgent, ArchitectAgent, DeveloperAgent, QAAgent, DevOpsAgent,
            SecurityAgent, TechWriterAgent, DataEngineerAgent, MLEngineerAgent,
            UXResearcherAgent, ComplianceAgent,
        }
        assert classes == expected

    @pytest.mark.asyncio
    async def test_agent_ids_are_unique(self, llm):
        spec, ctx = make_spec(), make_context()
        ids = {
            (await AgentFactory.create_agent(spec, ctx, llm)).agent_id
            for _ in range(10)
        }
        assert len(ids) == 10

    @pytest.mark.asyncio
    async def test_team_creation_from_context(self, llm, registry, db):
        ctx = make_context(
            [
                AgentRole.PROJECT_MANAGER, AgentRole.ARCHITECT,
                AgentRole.DEVELOPER, AgentRole.QA_ENGINEER, AgentRole.DEVOPS,
            ]
        )
        team = await AgentFactory.create_team(ctx, llm, db=db, registry=registry)
        assert isinstance(team, AgentTeam)
        assert len(team.agents) == 5
        assert len(team.get_by_role(AgentRole.DEVELOPER)) == 1
        summary = team.summary()
        assert summary["total_agents"] == 5
        assert "developer" in summary["roles"]

    @pytest.mark.asyncio
    async def test_dynamic_creator_registration(self, llm):
        """Extensibility: plug a new creator at runtime, factory unchanged."""
        from team_builder.agents import DeveloperAgent

        class CustomCreator(AgentCreator):
            prefix = "xx"

            async def create(self, spec, context, llm, db=None, registry=None, context_id=None):
                agent_id = short_id("xx")
                fsm = self._build_fsm(agent_id, spec.role.value, registry, db)
                return DeveloperAgent(agent_id, spec, context, fsm, llm)

        saved = AgentFactory._creators[AgentRole.DEVELOPER]
        AgentFactory.register_creator(AgentRole.DEVELOPER, CustomCreator())
        try:
            agent = await AgentFactory.create_agent(
                make_spec(AgentRole.DEVELOPER), make_context(), llm
            )
            assert agent.agent_id.startswith("xx-")
        finally:
            AgentFactory._creators[AgentRole.DEVELOPER] = saved

    @pytest.mark.asyncio
    async def test_fallback_to_generic_agent(self, llm):
        """Unregistered roles fall back to GenericAgent (dynamic spec)."""
        saved = AgentFactory._creators.pop(AgentRole.DEVELOPER)
        try:
            agent = await AgentFactory.create_agent(
                make_spec(AgentRole.DEVELOPER), make_context(), llm
            )
            assert isinstance(agent, GenericAgent)
            assert agent.agent_id.startswith("gen-")
        finally:
            AgentFactory._creators[AgentRole.DEVELOPER] = saved

    def test_factory_not_hardcoded(self):
        """Constitution: creation goes through a dict of creators, no if/else."""
        source = inspect.getsource(AgentFactory.create_agent)
        assert "if role ==" not in source
        assert "elif role" not in source
        assert "_creators.get" in source


class TestAgentBasics:
    @pytest.mark.asyncio
    async def test_agent_registers_fsm_handlers(self, llm, registry, db):
        agent = await AgentFactory.create_agent(
            make_spec(AgentRole.DEVELOPER), make_context(), llm, db=db, registry=registry
        )
        assert agent.fsm.state is not None
        assert isinstance(agent.fsm, FSMEngine)
        assert "on_task_received" in agent.fsm._actions
        assert "on_complete" in agent.fsm._actions
