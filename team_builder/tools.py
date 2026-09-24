"""Tool layer — MCP-style tools, 100% related to gates and agents.

Every tool is a ToolSpec object (its own PK `tool_id`) that is:
  * registered in the ToolRegistry (in-memory) AND the `tools` table (DB),
  * authorized per invocation by the ToolAuthorizationGate (a GateFunction
    object whose record stores the tool_id FK),
  * executed by the ToolExecutor — WASM tools inside the Wasmtime sandbox.

GOD MODE forges new tools via the API (/god/tools/forge): the tool, its
gate and its DB row are created together (integrated, never orphaned).
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from team_builder.gates import GateInput, GateRegistry, ToolAuthorizationGate
from team_builder.ids import new_id
from team_builder.wasm import SandboxPool
from team_builder.wasm_tools import ADD_WAT, FIBONACCI_WAT, UPPERCASE_WAT


class ToolSpec(BaseModel):
    tool_id: str = Field(default_factory=lambda: new_id("tool"))
    name: str
    description: str = ""
    kind: str = "wasm"  # wasm | builtin
    entrypoint: str = ""  # wasm export name, or builtin key
    wat: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    param_names: list[str] = Field(default_factory=list)
    input_bytes_key: str | None = None
    assigned_roles: list[str] = Field(default_factory=list)
    fuel_limit: int = 5_000_000


class ToolRegistry:
    """In-memory tool registry (DB is the system of record)."""

    def __init__(self):
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.tool_id] = spec

    def get(self, tool_id_or_name: str) -> ToolSpec | None:
        if tool_id_or_name in self._tools:
            return self._tools[tool_id_or_name]
        for spec in self._tools.values():
            if spec.name == tool_id_or_name:
                return spec
        return None

    def list(self) -> list[ToolSpec]:
        return list(self._tools.values())


class ToolBlockedError(Exception):
    def __init__(self, reason: str, gate_id: str):
        super().__init__(reason)
        self.reason = reason
        self.gate_id = gate_id


# ── Built-in tools ───────────────────────────────────────────────────────
def builtin_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            name="uppercase",
            description="Transforma texto em maiúsculas dentro do sandbox WASM.",
            kind="wasm",
            entrypoint="run",
            wat=UPPERCASE_WAT,
            parameters={"text": {"type": "string", "description": "Texto de entrada"}},
            input_bytes_key="text",
            assigned_roles=["developer", "qa_engineer", "devops", "security",
                            "architect", "tech_writer", "data_engineer", "ml_engineer"],
        ),
        ToolSpec(
            name="fibonacci",
            description="fib(n) em WASM — referência para limitação por fuel.",
            kind="wasm",
            entrypoint="fib",
            wat=FIBONACCI_WAT,
            parameters={"n": {"type": "integer", "description": "n (use <= 25)"}},
            param_names=["n"],
            assigned_roles=["developer", "qa_engineer", "devops", "architect",
                            "data_engineer", "ml_engineer", "security"],
        ),
        ToolSpec(
            name="add",
            description="Soma de dois inteiros em WASM (convenção de argumentos).",
            kind="wasm",
            entrypoint="add",
            wat=ADD_WAT,
            parameters={
                "a": {"type": "integer"},
                "b": {"type": "integer"},
            },
            param_names=["a", "b"],
            assigned_roles=["developer", "devops", "architect",
                            "data_engineer", "ml_engineer"],
        ),
        ToolSpec(
            name="echo",
            description="Echo nativo (builtin) — devolve o texto enviado.",
            kind="builtin",
            entrypoint="echo",
            parameters={"text": {"type": "string"}},
            assigned_roles=["developer", "project_manager", "tech_writer"],
        ),
    ]


BUILTIN_FUNCS: dict[str, Callable[[dict], dict]] = {
    "echo": lambda params: {"echo": str(params.get("text", ""))},
    "now": lambda params: {"now": datetime.now(UTC).isoformat()},
}


class ToolExecutor:
    """The ONLY class that runs tools — always behind the gate pipeline."""

    def __init__(
        self,
        gate_registry: GateRegistry,
        pool: SandboxPool,
        tool_registry: ToolRegistry | None = None,
    ):
        self.gate_registry = gate_registry
        self.pool = pool
        self.tool_registry = tool_registry or ToolRegistry()

    async def execute(
        self,
        tool_id_or_name: str,
        params: dict,
        agent_id: str,
        agent_role: str,
    ) -> dict:
        tool = self.tool_registry.get(tool_id_or_name)
        if tool is None:
            raise KeyError(f"Tool '{tool_id_or_name}' não encontrada")

        gate = ToolAuthorizationGate(self.gate_registry)
        gate_input = GateInput(
            agent_id=agent_id,
            payload={"tool_id": tool.name, "tool_roles": tool.assigned_roles},
            agent_role=agent_role,
            api_context=True,  # tool execution always goes through the API
            tool_id=tool.tool_id,
            event="tool_call",
        )
        out = await gate(gate_input)
        if not out.allowed:
            raise ToolBlockedError(out.reason or "bloqueado pela gate", out.gate_id)

        if tool.kind == "builtin":
            func = BUILTIN_FUNCS.get(tool.entrypoint)
            if func is None:
                raise KeyError(f"Builtin '{tool.entrypoint}' inexistente")
            result = func(params)
        else:
            sandbox = self.pool.get_or_create(agent_id)
            if tool.input_bytes_key:
                data = str(params.get(tool.input_bytes_key, "")).encode("utf-8")
                res = sandbox.execute(
                    tool.wat, tool.entrypoint, fuel=tool.fuel_limit, input_bytes=data
                )
            else:
                args = tuple(int(params.get(p, 0)) for p in tool.param_names)
                res = sandbox.execute(
                    tool.wat, tool.entrypoint, fuel=tool.fuel_limit, args=args
                )
            result = {
                "success": res.success,
                "output": res.output,
                "error": res.error,
                "fuel_consumed": res.fuel_consumed,
                "duration_ms": res.duration_ms,
                "sandbox_id": res.sandbox_id,
            }
        return {**result, "tool": tool.name, "gate_id": out.gate_id}
