"""Shared test helpers."""
from __future__ import annotations

from team_builder.models import (
    AgentRole,
    AgentSpec,
    ComplexityLevel,
    DevContext,
    ProjectType,
    SDLCPhase,
    TechStack,
)

GOD = "test-god-secret"


def make_spec(role: AgentRole = AgentRole.DEVELOPER, name: str | None = None) -> AgentSpec:
    return AgentSpec(
        role=role,
        name=name or f"{role.value}-agent",
        responsibilities=[f"responsibilities of {role.value}"],
        tools_needed=["uppercase"],
    )


def make_context(roles: list[AgentRole] | None = None) -> DevContext:
    roles = roles or [AgentRole.DEVELOPER]
    return DevContext(
        project_type=ProjectType.API_SERVICE,
        complexity=ComplexityLevel.MEDIUM,
        current_phase=SDLCPhase.DEVELOPMENT,
        tech_stack=TechStack(
            languages=["python"],
            frameworks=["fastapi"],
            databases=["sqlite"],
            cloud=[],
            tools=["pytest"],
        ),
        team_agents=[make_spec(r) for r in roles],
        parallel_tracks=[["developer", "qa_engineer"]] if len(roles) > 1 else [],
        constraints=["all code runs in wasm sandboxes"],
        estimated_cycles=10,
        mcp_tools_needed=["uppercase", "test_run"],
    )


def create_agent(client, role: AgentRole = AgentRole.DEVELOPER, name: str | None = None) -> dict:
    resp = client.post(
        "/agents/",
        json={
            "spec": {
                "role": role.value,
                "name": name or f"{role.value}-agent",
                "responsibilities": [f"resp of {role.value}"],
                "tools_needed": ["uppercase"],
            }
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()
