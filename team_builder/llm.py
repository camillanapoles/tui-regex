"""LLM layer — Pydantic + Instructor structured outputs.

Every LLM call in the platform goes through LLMClient.structured(), which
always returns a *validated* Pydantic model (never free text). Two
implementations:

- InstructorLLM: real LLM via `instructor` + OpenAI-compatible API
  (used when OPENAI_API_KEY is available).
- MockLLM: deterministic sample generator — powers the full test suite
  without any network call, and any demo run without a key.
"""
from __future__ import annotations

import os
import types
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Union, get_args, get_origin

from pydantic import BaseModel, ValidationError

try:  # Python 3.10+ union operator
    _UNION_TYPES = (Union, types.UnionType)
except AttributeError:  # pragma: no cover
    _UNION_TYPES = (Union,)


class LLMClient(ABC):
    """Contract for structured LLM access (OOP, sync or async internally)."""

    name: str = "base"

    @abstractmethod
    async def structured(
        self, system: str, user: str, response_model: type[BaseModel]
    ) -> BaseModel:
        """Return a validated instance of `response_model`."""
        ...


class InstructorLLM(LLMClient):
    """Production client — instructor + OpenAI-compatible API (TOOLS mode)."""

    name = "instructor-openai"

    def __init__(self, model: str | None = None, api_key: str | None = None):
        import instructor
        from openai import AsyncOpenAI

        key = api_key or os.getenv("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY is required for InstructorLLM")
        self.model = model or os.getenv("LLM_MODEL", "gpt-4o")
        self._client = instructor.from_openai(
            AsyncOpenAI(api_key=key), mode=instructor.Mode.TOOLS
        )

    async def structured(
        self, system: str, user: str, response_model: type[BaseModel]
    ) -> BaseModel:
        return await self._client.chat.completions.create(
            model=self.model,
            response_model=response_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )


class MockLLM(LLMClient):
    """Deterministic LLM: generates a valid sample instance per model.

    Samples respect Pydantic constraints (ge/le), nested models, enums,
    optionals and containers, so the *entire* pipeline (context analysis,
    planning, execution) can run end-to-end offline and reproducibly.
    """

    name = "mock"

    async def structured(
        self, system: str, user: str, response_model: type[BaseModel]
    ) -> BaseModel:
        return self.sample(response_model)

    # ── sample generation ────────────────────────────────────────────────
    @classmethod
    def sample(cls, model: type[BaseModel]) -> BaseModel:
        data: dict[str, Any] = {}
        for name, field in model.model_fields.items():
            has_value = (not field.is_required()) and field.default_factory is None
            # default vazio ("" / None) => ainda assim amostra conteúdo real
            if has_value and field.default not in ("", None):
                data[name] = field.default
            else:
                data[name] = cls._sample_annotation(field.annotation, name, field)
        try:
            return model.model_validate(data)
        except ValidationError as exc:  # pragma: no cover - defensive
            raise ValueError(f"MockLLM could not sample {model.__name__}") from exc

    @classmethod
    def _sample_field_default(cls, field: Any, name: str) -> Any:
        return field.default

    @classmethod
    def _sample_annotation(cls, annotation: Any, name: str, field: Any) -> Any:
        origin = get_origin(annotation)

        if origin in _UNION_TYPES:  # Optional[X] / X | None
            non_none = [a for a in get_args(annotation) if a is not type(None)]
            if non_none:
                return cls._sample_annotation(non_none[0], name, field)
            return None

        if origin in (list, tuple, set):
            inner = get_args(annotation)
            inner = inner[0] if inner else str
            return [cls._sample_annotation(inner, name, field)]

        if origin is dict:
            return {}

        if isinstance(annotation, type):
            if issubclass(annotation, BaseModel):
                return cls.sample(annotation)
            if issubclass(annotation, Enum):
                return list(annotation)[0]
            if annotation is str:
                return f"mock-{name}"
            if annotation is bool:
                return True
            if annotation is int:
                ge = getattr(field, "ge", None)
                return ge if ge is not None else 1
            if annotation is float:
                le = getattr(field, "le", None)
                if le is not None:
                    return le / 2
                ge = getattr(field, "ge", None)
                return ge if ge is not None else 1.0
            if annotation is datetime:
                return datetime.now(UTC)
            if annotation is bytes:
                return b"mock"

        return f"mock-{name}"
