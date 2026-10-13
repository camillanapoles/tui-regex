"""Agent Factory — meta-creation of agents, zero hardcode.

  * `AgentFactory._creators` is a plain dict[AgentRole -> AgentCreator]:
    no if/else per role anywhere (verified by test).
  * New roles can be plugged at runtime via `register_creator` — the
    factory itself never changes.
  * Unregistered roles fall back to GenericAgent (dynamic spec-driven).
  * `create_team` turns a DevContext (LLM-extracted) into a live
    AgentTeam, persisting agents to the DB when a session is attached.
"""
from __future__ import annotations

import importlib
from abc import ABC, abstractmethod

from team_builder.agents import (
    BaseAgent,
    GenericAgent,
)
from team_builder.fsm import FSMEngine
from team_builder.gates import GateRegistry
from team_builder.ids import short_id
from team_builder.llm import LLMClient
from team_builder.models import AgentRole, AgentSpec, DevContext


class AgentCreator(ABC):
    """Factory Method: one creator per agent class."""

    prefix: str = "ag"

    @abstractmethod
    async def create(
        self,
        spec: AgentSpec,
        context: DevContext,
        llm: LLMClient,
        db: object | None = None,
        registry: GateRegistry | None = None,
        context_id: str | None = None,
    ) -> BaseAgent:
        ...

    def _build_fsm(
        self,
        agent_id: str,
        role: str,
        registry: GateRegistry | None,
        db: object | None,
    ) -> FSMEngine:
        return FSMEngine(
            agent_id=agent_id,
            agent_role=role,
            registry=registry,
            db=db,
        )

    def _persist_agent(
        self,
        db: object | None,
        agent_id: str,
        spec: AgentSpec,
        context_id: str | None,
    ) -> None:
        if db is None:
            return
        from team_builder.db import AgentRepo

        AgentRepo(db).save(
            agent_id=agent_id,
            role=spec.role.value,
            name=spec.name,
            state="idle",
            spec=spec.model_dump(mode="json"),
            context_id=context_id,
        )


class DynamicCreator(AgentCreator):
    """Creates agents by (module, class) reference — no hardcoded wiring."""

    def __init__(self, module: str, classname: str, prefix: str):
        self._module = module
        self._classname = classname
        self.prefix = prefix

    async def create(
        self,
        spec: AgentSpec,
        context: DevContext,
        llm: LLMClient,
        db: object | None = None,
        registry: GateRegistry | None = None,
        context_id: str | None = None,
    ) -> BaseAgent:
        module = importlib.import_module(self._module)
        klass = getattr(module, self._classname)
        agent_id = short_id(self.prefix)
        fsm = self._build_fsm(agent_id, spec.role.value, registry, db)
        agent = klass(agent_id, spec, context, fsm, llm)
        self._persist_agent(db, agent_id, spec, context_id)
        return agent


class _GenericCreator(AgentCreator):
    """Fallback creator for roles without a dedicated class."""

    prefix = "gen"

    async def create(
        self,
        spec: AgentSpec,
        context: DevContext,
        llm: LLMClient,
        db: object | None = None,
        registry: GateRegistry | None = None,
        context_id: str | None = None,
    ) -> BaseAgent:
        agent_id = short_id("gen")
        fsm = self._build_fsm(agent_id, spec.role.value, registry, db)
        agent = GenericAgent(agent_id, spec, context, fsm, llm)
        self._persist_agent(db, agent_id, spec, context_id)
        return agent


def _default_creators() -> dict[AgentRole, AgentCreator]:
    """Role -> creator mapping (data, not code paths)."""
    module = "team_builder.agents"
    return {
        AgentRole.PROJECT_MANAGER: DynamicCreator(module, "PMAgent", "pm"),
        AgentRole.ARCHITECT: DynamicCreator(module, "ArchitectAgent", "arc"),
        AgentRole.DEVELOPER: DynamicCreator(module, "DeveloperAgent", "dev"),
        AgentRole.QA_ENGINEER: DynamicCreator(module, "QAAgent", "qa"),
        AgentRole.DEVOPS: DynamicCreator(module, "DevOpsAgent", "dop"),
        AgentRole.SECURITY: DynamicCreator(module, "SecurityAgent", "sec"),
        AgentRole.TECH_WRITER: DynamicCreator(module, "TechWriterAgent", "tw"),
        AgentRole.DATA_ENGINEER: DynamicCreator(module, "DataEngineerAgent", "de"),
        AgentRole.ML_ENGINEER: DynamicCreator(module, "MLEngineerAgent", "ml"),
        AgentRole.UX_RESEARCHER: DynamicCreator(module, "UXResearcherAgent", "ux"),
        AgentRole.COMPLIANCE: DynamicCreator(module, "ComplianceAgent", "cmp"),
    }


class AgentFactory:
    """The single entry point for agent creation (Factory Pattern)."""

    _creators: dict[AgentRole, AgentCreator] = _default_creators()

    @classmethod
    def creators(cls) -> dict[AgentRole, AgentCreator]:
        return dict(cls._creators)

    @classmethod
    def register_creator(cls, role: AgentRole, creator: AgentCreator) -> None:
        """Runtime extension — plug a new role without touching this class."""
        cls._creators[role] = creator

    @classmethod
    def unregistered_roles(cls) -> list[AgentRole]:
        return [r for r in AgentRole if r not in cls._creators]

    @classmethod
    async def create_agent(
        cls,
        spec: AgentSpec,
        context: DevContext,
        llm: LLMClient,
        db: object | None = None,
        registry: GateRegistry | None = None,
        context_id: str | None = None,
    ) -> BaseAgent:
        creator = cls._creators.get(spec.role)
        if creator is None:
            creator = _GenericCreator()
        return await creator.create(spec, context, llm, db, registry, context_id)

    @classmethod
    async def create_team(
        cls,
        context: DevContext,
        llm: LLMClient,
        db: object | None = None,
        registry: GateRegistry | None = None,
    ) -> AgentTeam:
        """Creates the FULL team from a DevContext (one pass, all related)."""
        context_id: str | None = None
        if db is not None:
            from team_builder.db import save_dev_context

            context_id = save_dev_context(db, context)

        agents: list[BaseAgent] = []
        for spec in context.team_agents:
            agent = await cls.create_agent(
                spec, context, llm, db, registry, context_id
            )
            agents.append(agent)
        return AgentTeam(agents=agents, context=context, registry=registry)


class AgentTeam:
    """A live team of agents + the DevContext that composed it."""

    def __init__(
        self,
        agents: list[BaseAgent],
        context: DevContext,
        registry: GateRegistry | None = None,
    ):
        self.agents = agents
        self.context = context
        self.registry = registry
        self._by_role: dict[AgentRole, list[BaseAgent]] = {}
        for agent in agents:
            self._by_role.setdefault(agent.spec.role, []).append(agent)

    def get_by_role(self, role: AgentRole) -> list[BaseAgent]:
        return list(self._by_role.get(role, []))

    def get_by_id(self, agent_id: str) -> BaseAgent | None:
        return next((a for a in self.agents if a.agent_id == agent_id), None)

    def summary(self) -> dict:
        gate_stats = self.registry.stats() if self.registry else {"total": 0}
        return {
            "total_agents": len(self.agents),
            "roles": [a.spec.role.value for a in self.agents],
            "states": {a.agent_id: a.state.value for a in self.agents},
            "parallel_tracks": self.context.parallel_tracks,
            "gates": gate_stats,
        }
