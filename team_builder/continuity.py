"""Continuity components — API-guaranteed session/state persistence.

O objetivo: um objeto que a sessão **seta e recupera** através da API,
persistido em SQLite (CRUD + query), onde CADA operação passa por
gate functions, e os componentes são criados por **factory** a partir de
um registry populado automaticamente por **meta-classe**.

Constituição aplicada (mesma da plataforma):
  * meta-classe `ContinuityMeta`: toda classe `ContinuityComponent` criada
    é registrada em `CONTINUITY_REGISTRY` no birth da classe (zero wiring);
  * `ContinuityFactory`: único criador/validador — deny-by-default p/ kind
    desconhecido (mesmo padrão do Factory de agentes);
  * gates OOP (PK UUID + FKs input/output): `ContinuityWriteGate` e
    `ContinuityReadGate` medeiam todo set/get/delete;
  * banco: tabela `continuity_objects` com (kind, key) único e
    versionamento otimista (expected_version) — recuperável em qualquer
    sessão futura: GET /continuity/{kind}/{key}.
"""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from pydantic._internal._model_construction import ModelMetaclass

from team_builder.gates import BaseGate, GateDirection, GateInput, GateOutput
from team_builder.ids import new_id

KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
MAX_DATA_BYTES = 64 * 1024  # 64 KB por objeto de continuidade


class UnknownContinuityKind(KeyError):
    """Kind não registrado — deny-by-default (mesma postura da platform)."""


class VersionConflictError(Exception):
    """Otimistic concurrency: expected_version não confere com o banco."""

    def __init__(self, current_version: int, expected_version: int):
        super().__init__(f"conflito de versão (atual={current_version}, esperado={expected_version})")
        self.current_version = current_version
        self.expected_version = expected_version


# ── Meta-class: registry automático no birth de cada componente ─────────
class ContinuityMeta(ModelMetaclass):
    """Registra automaticamente cada ContinuityComponent pelo seu `kind`.

    É a garantia de que a factory nunca fica desatualizada: criar uma
    classe nova é suficiente — o registry (e, por consequência, a API e
    as gates) passam a conhecê-la sem nenhuma linha de wiring.
    """

    CONTINUITY_REGISTRY: dict[str, type[ContinuityComponent]] = {}

    def __new__(mcls, name, bases, namespace, **kwargs):
        cls = super().__new__(mcls, name, bases, namespace, **kwargs)
        kind = namespace.get("kind")
        if isinstance(kind, str) and kind and name != "ContinuityComponent":
            mcls.CONTINUITY_REGISTRY[kind] = cls
        return cls


class ContinuityComponent(BaseModel, metaclass=ContinuityMeta):
    """Base de todo objeto de continuidade (pydantic => schema validado)."""

    kind: str = ""

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> ContinuityComponent:
        return cls.model_validate(data)


# ── Componentes (registry populado pela meta-classe) ────────────────────
class SessionState(ContinuityComponent):
    """Estado da sessão de trabalho (o que a PRÓXIMA sessão recupera)."""

    kind: str = "session"
    agent_id: str = ""
    branch: str = ""
    base_branch: str = "main"
    last_commit: str = ""
    pr_number: int | None = None
    pr_url: str = ""
    cursor: str = ""
    next_steps: list[str] = Field(default_factory=list)
    todos: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    notes: str = ""


class GitOpState(ContinuityComponent):
    """Estado das operações GitHub (push/PR) — continuável via gh api."""

    kind: str = "git_op"
    remote: str = ""
    branch: str = ""
    commit: str = ""
    pr_number: int | None = None
    pr_url: str = ""
    status: str = "pending"
    last_error: str = ""


class ArtifactPointer(ContinuityComponent):
    """Ponteiro para artefatos/evidências produzidos pela sessão."""

    kind: str = "artifact"
    path: str
    description: str = ""
    sha256: str = ""
    source_session: str = ""


class GenericKV(ContinuityComponent):
    """KV genérica — 'um objeto que eu seto e recupero' sem schema fixo."""

    kind: str = "kv"
    value: Any = None


# ── Factory (usa o registry da meta-classe; deny-by-default) ────────────
class ContinuityFactory:
    """Único criador/validador de componentes de continuidade.

    Idêntica filosofia da AgentFactory: nenhum if/elif por kind — o
    comportamento vem do registry (populado pela meta-classe).
    """

    registry = ContinuityMeta.CONTINUITY_REGISTRY

    @classmethod
    def kinds(cls) -> list[str]:
        return sorted(cls.registry)

    @classmethod
    def get_class(cls, kind: str) -> type[ContinuityComponent] | None:
        return cls.registry.get(kind)

    @classmethod
    def create(cls, kind: str, **data: Any) -> ContinuityComponent:
        comp_cls = cls.get_class(kind)
        if comp_cls is None:
            raise UnknownContinuityKind(
                f"kind '{kind}' não registrado (deny-by-default; kinds: {cls.kinds()})"
            )
        data.pop("kind", None)
        return comp_cls(**data)

    @classmethod
    def validate(cls, kind: str, data: dict[str, Any]) -> ContinuityComponent:
        """Valida o payload contra o schema do kind (usa em gates/API)."""
        comp_cls = cls.get_class(kind)
        if comp_cls is None:
            raise UnknownContinuityKind(
                f"kind '{kind}' não registrado (deny-by-default; kinds: {cls.kinds()})"
            )
        clean = dict(data)
        clean.pop("kind", None)
        return comp_cls.model_validate(clean)

    @classmethod
    def size_ok(cls, data: dict[str, Any]) -> bool:
        import json

        return len(json.dumps(data, default=str).encode("utf-8")) <= MAX_DATA_BYTES


# ── Gates OOP da continuidade (PK UUID + FKs, mesmas garantias) ─────────
class ContinuityWriteGate(BaseGate):
    """Medeia set/delete: kind registrado, key válida, schema OK, size OK,
    e a ação veio pela API."""

    gate_name = "continuity_write_gate"
    direction = GateDirection.API_REQUEST
    priority = 5

    async def execute(self, inp: GateInput, record: Any) -> GateOutput:
        if not inp.api_context:
            return GateOutput(
                input_id=inp.object_id, gate_id=record.gate_id, allowed=False,
                reason="Continuidade: escrita FORA da API bloqueada.",
            )
        kind = str(inp.payload.get("kind", ""))
        key = str(inp.payload.get("key", ""))
        data = inp.payload.get("data") or {}
        op = str(inp.payload.get("op", "set"))

        if kind not in ContinuityFactory.registry:
            return GateOutput(
                input_id=inp.object_id, gate_id=record.gate_id, allowed=False,
                reason=f"Continuidade: kind '{kind}' não registrado (deny-by-default).",
            )
        if not KEY_RE.match(key):
            return GateOutput(
                input_id=inp.object_id, gate_id=record.gate_id, allowed=False,
                reason="Continuidade: key inválida (máx 128 chars; [A-Za-z0-9._/-]).",
            )
        if op in ("set", "put") and not isinstance(data, dict):
            return GateOutput(
                input_id=inp.object_id, gate_id=record.gate_id, allowed=False,
                reason="Continuidade: data deve ser um objeto JSON no set.",
            )
        if op in ("set", "put") and not ContinuityFactory.size_ok(data):
            return GateOutput(
                input_id=inp.object_id, gate_id=record.gate_id, allowed=False,
                reason=f"Continuidade: data excede {MAX_DATA_BYTES} bytes.",
            )
        if op in ("set", "put"):
            try:
                ContinuityFactory.validate(kind, data)
            except (ValidationError, UnknownContinuityKind) as exc:
                return GateOutput(
                    input_id=inp.object_id, gate_id=record.gate_id, allowed=False,
                    reason=f"Continuidade: schema inválido p/ '{kind}': {exc}",
                )
        return GateOutput(
            input_id=inp.object_id, gate_id=record.gate_id, allowed=True,
            result={"op": op, "kind": kind, "key": key},
        )


class ContinuityReadGate(BaseGate):
    """Medeia get/list: kind registrado (ou vazio no list), key válida, API."""

    gate_name = "continuity_read_gate"
    direction = GateDirection.API_REQUEST
    priority = 5

    async def execute(self, inp: GateInput, record: Any) -> GateOutput:
        if not inp.api_context:
            return GateOutput(
                input_id=inp.object_id, gate_id=record.gate_id, allowed=False,
                reason="Continuidade: leitura FORA da API bloqueada.",
            )
        kind = str(inp.payload.get("kind", ""))
        key = str(inp.payload.get("key", ""))
        if kind and kind not in ContinuityFactory.registry:
            return GateOutput(
                input_id=inp.object_id, gate_id=record.gate_id, allowed=False,
                reason=f"Continuidade: kind '{kind}' não registrado (deny-by-default).",
            )
        if key and not KEY_RE.match(key):
            return GateOutput(
                input_id=inp.object_id, gate_id=record.gate_id, allowed=False,
                reason="Continuidade: key inválida (máx 128 chars; [A-Za-z0-9._/-]).",
            )
        return GateOutput(
            input_id=inp.object_id, gate_id=record.gate_id, allowed=True,
            result={"op": str(inp.payload.get("op", "get")), "kind": kind, "key": key},
        )


def make_continuity_gate_input(
    op: str, kind: str, key: str, data: dict | None = None
) -> GateInput:
    payload: dict[str, Any] = {"op": op, "kind": kind, "key": key}
    if data is not None:
        payload["data"] = data
    return GateInput(
        agent_id="platform",
        payload=payload,
        api_context=True,  # estas gates só rodam dentro do endpoint da API
        event=f"continuity_{op}",
    )


def new_continuity_id() -> str:
    return new_id("cont")
