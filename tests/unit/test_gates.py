"""Gate core tests — UUID PK, input/output FKs, immutability, concrete gates."""
import pytest
from team_builder.gates import (
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


# ── ID / PK invariants ───────────────────────────────────────────────────
class TestGateUUIDPK:
    def test_gate_input_has_unique_prefixed_id(self):
        a = GateInput(agent_id="ag1", payload={}, api_context=True)
        b = GateInput(agent_id="ag2", payload={}, api_context=True)
        assert a.object_id != b.object_id
        assert a.object_id.startswith("inp-")

    def test_gate_output_has_unique_prefixed_id(self):
        a = GateOutput(input_id="inp-a", gate_id="gate-a", allowed=True)
        b = GateOutput(input_id="inp-b", gate_id="gate-b", allowed=True)
        assert a.object_id != b.object_id
        assert a.object_id.startswith("out-")

    def test_gate_record_pk_unique_100x(self):
        ids = {
            GateRecord(gate_name=f"g{i}", direction=GateDirection.PRE_TRANSITION).gate_id
            for i in range(100)
        }
        assert len(ids) == 100
        assert all(i.startswith("gate-") for i in ids)

    def test_gate_input_is_immutable(self):
        inp = GateInput(agent_id="ag1", payload={}, api_context=True)
        with pytest.raises(Exception):
            inp.agent_id = "changed"  # frozen model

    def test_gate_output_is_immutable(self):
        out = GateOutput(input_id="inp-a", gate_id="gate-a", allowed=True)
        with pytest.raises(Exception):
            out.allowed = False  # frozen model


# ── ApiGate — the "no action outside the API" enforcer ──────────────────
class TestApiGate:
    @pytest.mark.asyncio
    async def test_allows_with_api_context(self, registry):
        gate = ApiGate(registry)
        inp = GateInput(agent_id="dev-1", payload={"event": "execute"}, api_context=True)
        out = await gate(inp)
        assert out.allowed is True
        assert out.input_id == inp.object_id  # FK

    @pytest.mark.asyncio
    async def test_blocks_without_api_context(self, registry):
        gate = ApiGate(registry)
        inp = GateInput(agent_id="dev-1", payload={"event": "execute"}, api_context=False)
        out = await gate(inp)
        assert out.allowed is False
        assert "FORA da API" in (out.reason or "")

    @pytest.mark.asyncio
    async def test_records_allowed_status(self, registry):
        gate = ApiGate(registry)
        inp = GateInput(agent_id="dev-1", payload={}, api_context=True)
        out = await gate(inp)
        record = registry.get(out.gate_id)
        assert record is not None
        assert record.status == GateStatus.ALLOWED
        assert record.gate_name == "api_gate"
        assert record.input_object is inp
        assert record.output_object is out

    @pytest.mark.asyncio
    async def test_records_blocked_status(self, registry):
        gate = ApiGate(registry)
        inp = GateInput(agent_id="dev-1", payload={}, api_context=False)
        out = await gate(inp)
        assert registry.get(out.gate_id).status == GateStatus.BLOCKED
        assert registry.list_blocked() and registry.list_blocked()[0].gate_id == out.gate_id

    @pytest.mark.asyncio
    async def test_fk_invariants_enforced(self, registry):
        gate = ApiGate(registry)
        inp = GateInput(agent_id="dev-1", payload={}, api_context=True)
        out = await gate(inp)
        assert out.gate_id == registry.get(out.gate_id).gate_id
        assert out.input_id == inp.object_id


# ── SDLC phase gate ──────────────────────────────────────────────────────
class TestSdlcPhaseGate:
    @pytest.mark.asyncio
    async def test_allowed_event_in_phase(self, registry):
        gate = SdlcPhaseGate(registry)
        inp = GateInput(
            agent_id="dev-1", payload={"event": "execute"},
            sdlc_phase="development", agent_role="developer", api_context=True,
            event="execute",
        )
        assert (await gate(inp)).allowed is True

    @pytest.mark.asyncio
    async def test_blocked_event_wrong_phase(self, registry):
        gate = SdlcPhaseGate(registry)
        inp = GateInput(
            agent_id="dev-1", payload={"event": "deploy"},
            sdlc_phase="development", agent_role="developer", api_context=True,
            event="deploy",
        )
        out = await gate(inp)
        assert out.allowed is False
        assert "development" in (out.reason or "")

    @pytest.mark.asyncio
    async def test_testing_phase_allows_review_events(self, registry):
        gate = SdlcPhaseGate(registry)
        inp = GateInput(
            agent_id="qa-1", payload={"event": "approve"},
            sdlc_phase="testing", agent_role="qa_engineer", api_context=True,
            event="approve",
        )
        assert (await gate(inp)).allowed is True


# ── Role permission gate ─────────────────────────────────────────────────
class TestRolePermissionGate:
    def _inp(self, role, event):
        return GateInput(
            agent_id=f"{role}-1", payload={"event": event},
            agent_role=role, api_context=True, event=event,
        )

    @pytest.mark.asyncio
    async def test_developer_can_execute(self, registry):
        out = await RolePermissionGate(registry)(self._inp("developer", "execute"))
        assert out.allowed is True

    @pytest.mark.asyncio
    async def test_developer_can_emit_plan_ready(self, registry):
        out = await RolePermissionGate(registry)(self._inp("developer", "plan_ready"))
        assert out.allowed is True

    @pytest.mark.asyncio
    async def test_developer_cannot_deploy(self, registry):
        out = await RolePermissionGate(registry)(self._inp("developer", "deploy"))
        assert out.allowed is False
        assert "developer" in (out.reason or "")

    @pytest.mark.asyncio
    async def test_devops_can_deploy(self, registry):
        out = await RolePermissionGate(registry)(self._inp("devops", "deploy"))
        assert out.allowed is True

    @pytest.mark.asyncio
    async def test_developer_cannot_approve(self, registry):
        out = await RolePermissionGate(registry)(self._inp("developer", "approve"))
        assert out.allowed is False

    @pytest.mark.asyncio
    async def test_unknown_role_denied_by_default(self, registry):
        out = await RolePermissionGate(registry)(self._inp("wizard", "execute"))
        assert out.allowed is False

    def test_all_11_roles_configured(self):
        from team_builder.models import AgentRole

        gate = RolePermissionGate(GateRegistry())
        assert set(gate.ROLE_EVENTS) == {r.value for r in AgentRole}


# ── WASM sandbox gate ────────────────────────────────────────────────────
class TestWasmSandboxGate:
    def _inp(self, role, code):
        return GateInput(
            agent_id=f"{role}-1", payload={"code": code, "agent_role": role},
            agent_role=role, api_context=True,
        )

    @pytest.mark.asyncio
    async def test_developer_can_run_safe_code(self, registry):
        out = await WasmSandboxGate(registry)(self._inp("developer", "print('ok')"))
        assert out.allowed is True

    @pytest.mark.asyncio
    async def test_dangerous_code_blocked(self, registry):
        out = await WasmSandboxGate(registry)(self._inp("developer", "import os; os.system('x')"))
        assert out.allowed is False
        assert "import os" in (out.reason or "")

    @pytest.mark.asyncio
    async def test_pm_cannot_run_wasm(self, registry):
        out = await WasmSandboxGate(registry)(self._inp("project_manager", "print(1)"))
        assert out.allowed is False
        assert "project_manager" in (out.reason or "")

    @pytest.mark.asyncio
    async def test_oversized_code_blocked(self, registry):
        big = "x = 1\n" * 250_000  # > 1 MiB
        out = await WasmSandboxGate(registry)(self._inp("developer", big))
        assert out.allowed is False
        assert "1MiB" in (out.reason or "")


# ── Tool authorization gate ──────────────────────────────────────────────
class TestToolAuthorizationGate:
    def _inp(self, role, tool, tool_roles=None):
        payload = {"tool_id": tool}
        if tool_roles is not None:
            payload["tool_roles"] = tool_roles
        return GateInput(
            agent_id=f"{role}-1", payload=payload,
            agent_role=role, api_context=True, event="tool_call",
        )

    @pytest.mark.asyncio
    async def test_developer_uses_static_map(self, registry):
        out = await ToolAuthorizationGate(registry)(self._inp("developer", "uppercase"))
        assert out.allowed is True

    @pytest.mark.asyncio
    async def test_pm_cannot_use_developer_tool(self, registry):
        out = await ToolAuthorizationGate(registry)(self._inp("project_manager", "uppercase"))
        assert out.allowed is False
        assert "project_manager" in (out.reason or "")

    @pytest.mark.asyncio
    async def test_forged_tool_assigned_roles(self, registry):
        gate = ToolAuthorizationGate(registry)
        ok = await gate(self._inp("developer", "my_forged", tool_roles=["developer"]))
        assert ok.allowed is True
        bad = await gate(self._inp("compliance", "my_forged", tool_roles=["developer"]))
        assert bad.allowed is False
        assert "assigned_roles" in (bad.reason or "")


# ── Audit gate + failure safety ──────────────────────────────────────────
class TestAuditAndSafety:
    @pytest.mark.asyncio
    async def test_audit_gate_always_allows(self, registry):
        inp = GateInput(agent_id="a1", payload={}, api_context=True)
        out = await AuditGate(registry)(inp)
        assert out.allowed is True

    @pytest.mark.asyncio
    async def test_gate_exception_never_crashes_pipeline(self, registry):
        class ExplodingGate(BaseGate):
            gate_name = "exploding"

            async def execute(self, inp, record):
                raise RuntimeError("boom")

        out = await ExplodingGate(registry)(
            GateInput(agent_id="a1", payload={}, api_context=True)
        )
        assert out.allowed is False
        assert "boom" in (out.reason or "")
        assert registry.get(out.gate_id).status == GateStatus.FAILED


# ── Registry ─────────────────────────────────────────────────────────────
class TestGateRegistry:
    @pytest.mark.asyncio
    async def test_stores_and_filters(self, registry):
        gate = ApiGate(registry)
        for i in range(3):
            await gate(GateInput(agent_id=f"agent-{i}", payload={}, api_context=True))
        await gate(GateInput(agent_id="agent-1", payload={}, api_context=False))

        assert len(registry.list_all()) == 4
        assert len(registry.list_by_agent("agent-1")) == 2
        blocked = registry.list_blocked()
        assert len(blocked) == 1
        stats = registry.stats()
        assert stats["total"] == 4
        assert stats["by_status"]["allowed"] == 3
        assert stats["by_status"]["blocked"] == 1
