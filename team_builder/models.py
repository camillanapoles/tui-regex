"""Domain models — Pydantic v2.

DevContext is the *single source of truth* for team composition: the
ContextAnalyzer extracts it from a free-text project description (LLM via
Instructor) and the AgentFactory turns it into a live team. Nothing is
hardcoded — roles, parallelism and tools all come from this object.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from team_builder.ids import new_id
from team_builder.llm import InstructorLLM, LLMClient, MockLLM


# ── Enums ────────────────────────────────────────────────────────────────
class ProjectType(StrEnum):
    WEB_APP = "web_app"
    API_SERVICE = "api_service"
    DATA_PIPELINE = "data_pipeline"
    ML_PLATFORM = "ml_platform"
    MOBILE_APP = "mobile_app"
    MICROSERVICES = "microservices"
    CLI_TOOL = "cli_tool"
    EMBEDDED = "embedded"
    GAME = "game"
    GENERIC = "generic"


class ComplexityLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EXPERT = "expert"


class SDLCPhase(StrEnum):
    DISCOVERY = "discovery"
    PLANNING = "planning"
    ARCHITECTURE = "architecture"
    DEVELOPMENT = "development"
    TESTING = "testing"
    REVIEW = "review"
    DEPLOYMENT = "deployment"
    MONITORING = "monitoring"
    MAINTENANCE = "maintenance"


class AgentRole(StrEnum):
    # Core squad
    PROJECT_MANAGER = "project_manager"
    ARCHITECT = "architect"
    DEVELOPER = "developer"
    QA_ENGINEER = "qa_engineer"
    DEVOPS = "devops"
    # 2026 extended roles
    SECURITY = "security"
    TECH_WRITER = "tech_writer"
    DATA_ENGINEER = "data_engineer"
    ML_ENGINEER = "ml_engineer"
    UX_RESEARCHER = "ux_researcher"
    COMPLIANCE = "compliance"


class DomainExpertise(StrEnum):
    BACKEND = "backend"
    FRONTEND = "frontend"
    MOBILE = "mobile"
    DATA_SCIENCE = "data_science"
    MACHINE_LEARNING = "machine_learning"
    CLOUD_INFRA = "cloud_infra"
    CYBERSECURITY = "cybersecurity"
    DATABASE = "database"
    API_DESIGN = "api_design"
    WASM_RUNTIME = "wasm_runtime"


class AgentSkill(StrEnum):
    PYTHON = "python"
    RUST = "rust"
    TYPESCRIPT = "typescript"
    GO = "go"
    SQL = "sql"
    WASM = "wasm"
    WASI = "wasi"
    FASTAPI = "fastapi"
    REACT = "react"
    TDD = "tdd"
    CI_CD = "ci_cd"
    CODE_REVIEW = "code_review"
    SECURITY_AUDIT = "security_audit"
    COMPLIANCE = "compliance"
    TECH_WRITING = "tech_writing"
    DATA_MODELING = "data_modeling"
    ML_OPS = "ml_ops"
    UX_RESEARCH = "ux_research"


# ── Context objects ──────────────────────────────────────────────────────
class TechStack(BaseModel):
    languages: list[str] = Field(default_factory=list, description="Linguagens identificadas")
    frameworks: list[str] = Field(default_factory=list, description="Frameworks principais")
    databases: list[str] = Field(default_factory=list, description="Bancos de dados")
    cloud: list[str] = Field(default_factory=list, description="Providers cloud")
    tools: list[str] = Field(default_factory=list, description="Ferramentas de dev")


class AgentClient(BaseModel):
    """Stakeholder/cliente que o agente serve."""

    client_id: str
    client_type: str = "internal"  # internal | external | regulatory | llm_model
    name: str
    expectations: list[str] = Field(default_factory=list)


class AgentSpec(BaseModel):
    """Especificação completa de um agente — gerada pelo ContextAnalyzer."""

    role: AgentRole
    name: str
    responsibilities: list[str] = Field(default_factory=list)
    tools_needed: list[str] = Field(default_factory=list)
    clients_served: list[AgentClient] = Field(default_factory=list)
    parallel_with: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    priority: int = Field(default=5, ge=1, le=10)
    skills: list[AgentSkill] = Field(default_factory=list)
    domain_expertise: list[DomainExpertise] = Field(default_factory=list)
    wasm_sandboxed: bool = True


class DevContext(BaseModel):
    """Contexto de desenvolvimento — gera o time inteiro via Factory."""

    project_type: ProjectType
    complexity: ComplexityLevel
    current_phase: SDLCPhase
    tech_stack: TechStack
    team_agents: list[AgentSpec] = Field(default_factory=list)
    parallel_tracks: list[list[str]] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    estimated_cycles: int = Field(default=10, ge=1)
    mcp_tools_needed: list[str] = Field(default_factory=list)


class Task(BaseModel):
    task_id: str = Field(default_factory=lambda: new_id("task"))
    title: str
    description: str = ""
    status: str = "pending"  # pending | planning | running | completed | failed
    result: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[str] = Field(default_factory=list)
    gate_ids: list[str] = Field(default_factory=list)


# ── Context Analyzer (Instructor-powered) ────────────────────────────────
_ANALYZER_SYSTEM = (
    "Você é um arquiteto de software sênior. Analise a descrição do projeto e "
    "extraia o contexto completo de desenvolvimento: tipo de projeto, "
    "complexidade, fase SDLC atual, tech stack, e o time de agentes "
    "NECESSÁRIOS (roles, responsabilidades, tools, paralelismo e dependências). "
    "Seja preciso e abrangente. Produza apenas o objeto estruturado."
)


def default_llm() -> LLMClient:
    """Real LLM when a key is available, deterministic mock otherwise."""
    import os

    if os.getenv("OPENAI_API_KEY"):
        try:
            return InstructorLLM()
        except Exception:  # pragma: no cover
            pass
    return MockLLM()


class ContextAnalyzer:
    """Extrai um DevContext validado (Pydantic) de uma descrição livre."""

    def __init__(self, llm: LLMClient | None = None):
        self.llm = llm or default_llm()

    async def analyze(
        self, project_description: str, extra_info: dict | None = None
    ) -> DevContext:
        user = f"Projeto: {project_description}"
        if extra_info:
            user += f"\nInformação adicional: {extra_info}"
        return await self.llm.structured(_ANALYZER_SYSTEM, user, DevContext)
