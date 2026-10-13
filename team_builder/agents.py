"""Agents — each one is a microservice running on its own FSM engine.

BaseAgent contract (OOP, everything a function/method):
  * ALL communication happens through the FSM -> Gate pipeline. An agent
    can never bypass the API/gates (ApiGate enforces it).
  * ALL LLM outputs are typed Pydantic models via Instructor (PlanOutput
    for planning + a role-specific output model for execution).
  * `work(task)` is the full lifecycle: TASK_RECEIVED -> plan ->
    PLAN_READY -> run -> COMPLETE/FAIL, with every step gated.
"""
from __future__ import annotations

from abc import ABC
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from team_builder.fsm import FSMEngine, FSMEvent, FSMState, FSMTransitionResult
from team_builder.llm import LLMClient
from team_builder.models import AgentRole, AgentSpec, DevContext

HANDLER_NAMES = (
    "on_task_received", "on_plan_ready", "on_wait", "on_resume",
    "on_review_request", "on_complete", "on_fail", "on_approved",
    "on_rejected", "on_retry", "on_rollback", "on_reset", "on_deploy",
)


class PlanOutput(BaseModel):
    """Structured planning output (shared by all roles)."""

    approach: str = Field(default="", description="Abordagem técnica")
    steps: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class AgentOutput(BaseModel):
    """Standard output of any agent execution."""

    agent_id: str
    agent_role: str
    task_id: str
    result: Any
    artifacts: list[str] = Field(default_factory=list)
    next_event: FSMEvent = FSMEvent.COMPLETE
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)
    notes: str | None = None


class BaseAgent(ABC):
    """Abstract parent of all agents."""

    role_hint: ClassVar[AgentRole | None] = None
    output_model: ClassVar[type[BaseModel]]
    goal: ClassVar[str] = ""

    def __init__(
        self,
        agent_id: str,
        spec: AgentSpec,
        context: DevContext,
        fsm: FSMEngine,
        llm: LLMClient,
    ):
        self.agent_id = agent_id
        self.spec = spec
        self.context = context
        self.fsm = fsm
        self.llm = llm
        self._register_handlers()

    # ── FSM action handlers (OOP, async) ─────────────────────────────────
    def _register_handlers(self) -> None:
        for name in HANDLER_NAMES:
            self.fsm.register_action(name, getattr(self, name))

    async def on_task_received(self, payload: dict): pass
    async def on_plan_ready(self, payload: dict): pass
    async def on_wait(self, payload: dict): pass
    async def on_resume(self, payload: dict): pass
    async def on_review_request(self, payload: dict): pass
    async def on_complete(self, payload: dict): pass
    async def on_fail(self, payload: dict): pass
    async def on_approved(self, payload: dict): pass
    async def on_rejected(self, payload: dict): pass
    async def on_retry(self, payload: dict): pass
    async def on_rollback(self, payload: dict): pass
    async def on_reset(self, payload: dict): pass
    async def on_deploy(self, payload: dict): pass

    # ── public, API-driven surface ───────────────────────────────────────
    @property
    def state(self) -> FSMState:
        return self.fsm.state

    async def receive_task(self, task: dict) -> FSMTransitionResult:
        return await self.fsm.trigger(
            FSMEvent.TASK_RECEIVED,
            {**task, "_api_context": True},
            sdlc_phase=self.context.current_phase.value,
        )

    async def plan(self, task: dict) -> PlanOutput:
        return await self.llm.structured(
            self._system_prompt(), self._plan_prompt(task), PlanOutput
        )

    async def mark_plan_ready(self, plan: PlanOutput) -> FSMTransitionResult:
        return await self.fsm.trigger(
            FSMEvent.PLAN_READY,
            {"_api_context": True, "plan": plan.model_dump()},
            sdlc_phase=self.context.current_phase.value,
        )

    async def run(self, task: dict, plan: PlanOutput) -> AgentOutput:
        model_out = await self.llm.structured(
            self._system_prompt(), self._run_prompt(task, plan), self.output_model
        )
        return AgentOutput(
            agent_id=self.agent_id,
            agent_role=self.spec.role.value,
            task_id=task.get("task_id", f"task-{self.agent_id}"),
            result=model_out.model_dump(),
            artifacts=self._artifacts(model_out),
            next_event=FSMEvent.COMPLETE,
            confidence=0.9,
            notes=f"{type(self).__name__} concluiu a tarefa",
        )

    async def _finish(self, output: AgentOutput) -> FSMTransitionResult:
        return await self.fsm.trigger(
            output.next_event,
            {"_api_context": True, "result": output.model_dump(mode="json")},
            sdlc_phase=self.context.current_phase.value,
        )

    async def work(self, task: dict) -> AgentOutput:
        """Full gated lifecycle: receive -> plan -> execute -> finish."""
        await self.receive_task(task)
        plan = await self.plan(task)
        await self.mark_plan_ready(plan)
        output = await self.run(task, plan)
        await self._finish(output)
        return output

    # ── hooks for subclasses ─────────────────────────────────────────────
    def _artifacts(self, model_out: BaseModel) -> list[str]:
        value = getattr(model_out, "file_path", None)
        return [value] if value else []

    def _system_prompt(self) -> str:
        return (
            f"Você é {self.spec.name}, um agente autônomo com role "
            f"'{self.spec.role.value}'. Projeto: {self.context.project_type.value} | "
            f"Fase SDLC: {self.context.current_phase.value}. "
            f"Meta: {self.goal} Responsabilidades: "
            f"{', '.join(self.spec.responsibilities[:4]) or 'definidas pelo contexto'}. "
            f"Stack: {self.context.tech_stack.languages + self.context.tech_stack.frameworks}. "
            "Produza apenas o objeto estruturado, com precisão."
        )

    def _plan_prompt(self, task: dict) -> str:
        return (
            f"Planeje a execução desta tarefa.\n"
            f"Tarefa: {task.get('description') or task.get('title') or task}\n"
            f"Contexto: {self.context.project_type.value} em fase "
            f"{self.context.current_phase.value}."
        )

    def _run_prompt(self, task: dict, plan: PlanOutput) -> str:
        return (
            f"Execute a tarefa seguindo o plano.\n"
            f"Tarefa: {task.get('description') or task.get('title') or task}\n"
            f"Plano: {plan.model_dump()}"
        )

    def __repr__(self) -> str:
        return (
            f"<{type(self).__name__} id={self.agent_id} "
            f"role={self.spec.role.value} state={self.state.value}>"
        )


# ── Role-specific structured output models ───────────────────────────────
class ProjectPlan(BaseModel):
    goals: list[str] = Field(default_factory=list)
    milestones: list[str] = Field(default_factory=list)
    tasks: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    timeline: str = ""


class ArchitectureDecision(BaseModel):
    components: list[str] = Field(default_factory=list)
    tech_choices: list[str] = Field(default_factory=list)
    data_model: str = ""
    contracts: list[str] = Field(default_factory=list)
    rationale: str = ""


class CodeResult(BaseModel):
    file_path: str = ""
    language: str = "python"
    code: str = ""
    test_code: str = ""
    docs: str = ""


class TestReport(BaseModel):
    cases: list[str] = Field(default_factory=list)
    passed: int = 0
    failed: int = 0
    coverage_pct: float = Field(default=80.0, ge=0.0, le=100.0)
    verdict: str = ""


class DeployPlan(BaseModel):
    steps: list[str] = Field(default_factory=list)
    dockerfile: str = ""
    rollback_plan: str = ""


class SecurityAudit(BaseModel):
    findings: list[str] = Field(default_factory=list)
    severity: str = "low"
    recommendations: list[str] = Field(default_factory=list)


class DocOutput(BaseModel):
    title: str = ""
    sections: list[str] = Field(default_factory=list)
    body: str = ""


class PipelineSpec(BaseModel):
    sources: list[str] = Field(default_factory=list)
    transforms: list[str] = Field(default_factory=list)
    targets: list[str] = Field(default_factory=list)
    data_schema: str = ""


class ExperimentLog(BaseModel):
    model_type: str = ""
    metrics: dict[str, float] = Field(default_factory=dict)
    decision: str = ""


class UserStories(BaseModel):
    stories: list[str] = Field(default_factory=list)
    personas: list[str] = Field(default_factory=list)
    wireframe_notes: str = ""


class ComplianceReport(BaseModel):
    framework: str = "LGPD/GDPR"
    checks: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    verdict: str = ""


class GenericOutput(BaseModel):
    summary: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


# ── Concrete agents (one class per role — all registered via Factory) ────
class PMAgent(BaseAgent):
    role_hint = AgentRole.PROJECT_MANAGER
    output_model = ProjectPlan
    goal = "Planejar o projeto, decompor em tarefas e coordenar o time."


class ArchitectAgent(BaseAgent):
    role_hint = AgentRole.ARCHITECT
    output_model = ArchitectureDecision
    goal = "Definir arquitetura, contratos e decisões técnicas (ADRs)."


class DeveloperAgent(BaseAgent):
    role_hint = AgentRole.DEVELOPER
    output_model = CodeResult
    goal = "Implementar código, testes e documentação com boas práticas."


class QAAgent(BaseAgent):
    role_hint = AgentRole.QA_ENGINEER
    output_model = TestReport
    goal = "Garantir qualidade: planos de teste, execução e veredito."


class DevOpsAgent(BaseAgent):
    role_hint = AgentRole.DEVOPS
    output_model = DeployPlan
    goal = "Operar deploys, CI/CD incremental e rollback seguro."


class SecurityAgent(BaseAgent):
    role_hint = AgentRole.SECURITY
    output_model = SecurityAudit
    goal = "Auditar segurança (SAST/OWASP) e recomendar mitigações."


class TechWriterAgent(BaseAgent):
    role_hint = AgentRole.TECH_WRITER
    output_model = DocOutput
    goal = "Produzir documentação técnica, ADRs e runbooks."


class DataEngineerAgent(BaseAgent):
    role_hint = AgentRole.DATA_ENGINEER
    output_model = PipelineSpec
    goal = "Projetar pipelines de dados, schemas e validações."


class MLEngineerAgent(BaseAgent):
    role_hint = AgentRole.ML_ENGINEER
    output_model = ExperimentLog
    goal = "Conduzir experimentos de ML, métricas e decisões de modelo."


class UXResearcherAgent(BaseAgent):
    role_hint = AgentRole.UX_RESEARCHER
    output_model = UserStories
    goal = "Pesquisa de UX: user stories, personas e wireframes."


class ComplianceAgent(BaseAgent):
    role_hint = AgentRole.COMPLIANCE
    output_model = ComplianceReport
    goal = "Verificar conformidade (LGPD/GDPR/SOC2) e reportar gaps."


class GenericAgent(BaseAgent):
    """Fallback for dynamic roles not pre-registered in the Factory."""

    role_hint = None
    output_model = GenericOutput
    goal = "Executar a tarefa conforme as responsabilidades do spec."
