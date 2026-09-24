"""Team Builder WASM — Autonomous Agent Team Construction Platform.

Architecture (2026):
- FSM Core: every state transition is gated by GateFunction objects.
- GateFunction: first-class object with unique PK (UUID), mandatory
  input_object <-> output_object relation (FK), function- or event-driven.
- Factory Pattern: agents are meta-created from DevContext (zero hardcode).
- Pydantic + Instructor: every LLM output is typed and validated.
- WASM sandbox: Wasmtime (fuel + epoch mandatory) for untrusted code.
- FastAPI: the only mutation surface. GOD MODE (senior orchestrator) is the
  sole editor of the FSM API.
"""

__version__ = "2.0.0"

from team_builder.factory import (  # noqa: F401
    AgentCreator,
    AgentFactory,
    AgentTeam,
    DynamicCreator,
)
from team_builder.fsm import (  # noqa: F401
    UNIVERSAL_TRANSITIONS,
    FSMEngine,
    FSMEvent,
    FSMState,
    FSMTransitionResult,
    Transition,
)
from team_builder.gates import (  # noqa: F401
    ApiGate,
    AuditGate,
    BaseGate,
    GateDirection,
    GateInput,
    GateOutput,
    GateRecord,
    GateRegistry,
    GateStatus,
    RolePermissionGate,
    SdlcPhaseGate,
    ToolAuthorizationGate,
    WasmSandboxGate,
)
from team_builder.llm import InstructorLLM, LLMClient, MockLLM  # noqa: F401
from team_builder.models import (  # noqa: F401
    AgentRole,
    AgentSpec,
    ComplexityLevel,
    ContextAnalyzer,
    DevContext,
    ProjectType,
    SDLCPhase,
    TechStack,
)
