"""Models + LLM layer tests — Instructor-style structured outputs."""
import pytest
from team_builder.llm import MockLLM
from team_builder.models import (
    AgentRole,
    AgentSpec,
    ContextAnalyzer,
    DevContext,
    ProjectType,
    Task,
)


class TestMockLLM:
    def test_sample_agent_spec_is_valid(self):
        spec = MockLLM.sample(AgentSpec)
        assert isinstance(spec, AgentSpec)
        assert spec.role in AgentRole
        assert 1 <= spec.priority <= 10
        assert spec.name

    def test_sample_dev_context_is_valid(self):
        ctx = MockLLM.sample(DevContext)
        assert isinstance(ctx, DevContext)
        assert ctx.project_type in ProjectType
        assert ctx.tech_stack.languages is not None
        assert all(isinstance(r, str) for r in ctx.tech_stack.languages)

    @pytest.mark.asyncio
    async def test_structured_returns_validated_model(self):
        llm = MockLLM()
        ctx = await llm.structured("system", "user", DevContext)
        assert isinstance(ctx, DevContext)
        assert isinstance(ctx.team_agents, list)

    def test_sample_respects_constraints(self):
        # coverage_pct has le=100 — sample must satisfy it
        from team_builder.agents import TestReport

        report = MockLLM.sample(TestReport)
        assert 0.0 <= report.coverage_pct <= 100.0

    def test_sample_nested_dict_and_list(self):
        from team_builder.agents import ExperimentLog

        log = MockLLM.sample(ExperimentLog)
        assert isinstance(log.metrics, dict)
        assert isinstance(log.model_type, str)


class TestContextAnalyzer:
    @pytest.mark.asyncio
    async def test_analyze_produces_valid_context(self):
        analyzer = ContextAnalyzer(MockLLM())
        ctx = await analyzer.analyze("Sistema de pagamento com API e mobile app")
        assert isinstance(ctx, DevContext)
        assert ctx.project_type in ProjectType
        assert len(ctx.team_agents) >= 1
        for spec in ctx.team_agents:
            assert spec.role in AgentRole

    @pytest.mark.asyncio
    async def test_analyzer_with_real_llm_config_fallback(self):
        """Without OPENAI_API_KEY, the analyzer falls back to MockLLM."""
        import os

        os.environ.pop("OPENAI_API_KEY", None)
        analyzer = ContextAnalyzer()
        assert analyzer.llm.name == "mock"


class TestTask:
    def test_task_defaults(self):
        task = Task(title="T1")
        assert task.task_id.startswith("task-")
        assert task.status == "pending"
        assert task.result == {}
