"""Continuity tests — meta-class, factory, gates, repo (CRUD + query)."""
import pytest
from pydantic import ValidationError
from team_builder.continuity import (
    ContinuityComponent,
    ContinuityFactory,
    ContinuityMeta,
    ContinuityReadGate,
    ContinuityWriteGate,
    GenericKV,
    GitOpState,
    SessionState,
    UnknownContinuityKind,
    VersionConflictError,
    make_continuity_gate_input,
)
from team_builder.db import ContinuityRepo


# ── Meta-classe ─────────────────────────────────────────────────────────
class TestContinuityMeta:
    def test_builtin_kinds_registered(self):
        kinds = ContinuityFactory.kinds()
        assert {"session", "git_op", "artifact", "kv"} <= set(kinds)

    def test_new_component_auto_registered(self):
        """Criar uma classe nova = registrado (zero wiring)."""
        class ProbeState(ContinuityComponent):
            kind: str = "probe"
            flag: bool = False

        try:
            assert "probe" in ContinuityFactory.kinds()
            assert ContinuityFactory.get_class("probe") is ProbeState
            comp = ContinuityFactory.create("probe", flag=True)
            assert comp.flag is True
        finally:
            ContinuityMeta.CONTINUITY_REGISTRY.pop("probe", None)

    def test_base_class_not_registered(self):
        assert "ContinuityComponent" not in ContinuityFactory.registry
        assert "" not in ContinuityFactory.registry


# ── Factory (deny-by-default) ───────────────────────────────────────────
class TestContinuityFactory:
    def test_create_session(self):
        state = ContinuityFactory.create(
            "session", branch="b1", last_commit="abc123", next_steps=["x"]
        )
        assert isinstance(state, SessionState)
        assert state.kind == "session"
        assert state.branch == "b1"

    def test_create_git_op(self):
        state = ContinuityFactory.create("git_op", branch="b", commit="c", status="pushed")
        assert isinstance(state, GitOpState)
        assert state.status == "pushed"

    def test_unknown_kind_denied(self):
        with pytest.raises(UnknownContinuityKind):
            ContinuityFactory.create("hacker_kind")
        with pytest.raises(UnknownContinuityKind):
            ContinuityFactory.validate("hacker_kind", {})

    def test_invalid_schema_denied(self):
        with pytest.raises(ValidationError):
            ContinuityFactory.validate("artifact", {"description": "sem path"})

    def test_size_limit(self):
        assert ContinuityFactory.size_ok({"a": "x" * 100}) is True
        assert ContinuityFactory.size_ok({"a": "x" * (70 * 1024)}) is False

    def test_kind_in_ignored_payload(self):
        comp = ContinuityFactory.validate("kv", {"kind": "session", "value": 1})
        assert isinstance(comp, GenericKV)


# ── Repo (CRUD + query + version) ───────────────────────────────────────
class TestContinuityRepo:
    def test_crud_roundtrip(self, db):
        repo = ContinuityRepo(db)
        row = repo.save("session", "current", {"branch": "b1"})
        assert row.version == 1
        got = repo.get("session", "current")
        assert got.data == {"branch": "b1"}
        row2 = repo.save("session", "current", {"branch": "b2"})
        assert row2.version == 2
        assert repo.get("session", "current").data == {"branch": "b2"}
        assert repo.delete("session", "current") is True
        assert repo.get("session", "current") is None
        assert repo.delete("session", "current") is False

    def test_optimistic_version_conflict(self, db):
        repo = ContinuityRepo(db)
        repo.save("kv", "k", {"v": 1})
        repo.save("kv", "k", {"v": 2})  # version 2
        with pytest.raises(VersionConflictError) as excinfo:
            repo.save("kv", "k", {"v": 3}, expected_version=1)
        assert excinfo.value.current_version == 2
        assert repo.get("kv", "k").data == {"v": 2}  # intacto

    def test_expected_version_ok(self, db):
        repo = ContinuityRepo(db)
        repo.save("kv", "k", {"v": 1})
        row = repo.save("kv", "k", {"v": 2}, expected_version=1)
        assert row.version == 2

    def test_query_filters(self, db):
        repo = ContinuityRepo(db)
        repo.save("session", "current", {})
        repo.save("session", "archive/old", {})
        repo.save("kv", "current", {})
        assert len(repo.list()) == 3
        assert len(repo.list(kind="session")) == 2
        assert len(repo.list(kind="session", key_prefix="archive")) == 1
        assert len(repo.list(key_prefix="current")) == 2
        assert repo.count() == 3
        assert repo.all_kinds() == ["kv", "session"]


# ── Gates ───────────────────────────────────────────────────────────────
class TestContinuityGates:
    @pytest.mark.asyncio
    async def test_write_gate_allows_valid(self, registry):
        out = await ContinuityWriteGate(registry)(
            make_continuity_gate_input("set", "session", "current", {"branch": "b"})
        )
        assert out.allowed is True
        assert registry.get(out.gate_id).gate_name == "continuity_write_gate"

    @pytest.mark.asyncio
    async def test_write_gate_blocks_outside_api(self, registry):
        from team_builder.gates import GateInput

        gate = ContinuityWriteGate(registry)
        out = await gate(
            GateInput(
                agent_id="platform",
                payload={"op": "set", "kind": "session", "key": "current", "data": {}},
                api_context=False,  # VIOLAÇÃO
            )
        )
        assert out.allowed is False
        assert "FORA da API" in (out.reason or "")

    @pytest.mark.asyncio
    async def test_write_gate_blocks_unknown_kind(self, registry):
        out = await ContinuityWriteGate(registry)(
            make_continuity_gate_input("set", "nope", "current", {})
        )
        assert out.allowed is False
        assert "deny-by-default" in (out.reason or "")

    @pytest.mark.asyncio
    async def test_write_gate_blocks_bad_key(self, registry):
        out = await ContinuityWriteGate(registry)(
            make_continuity_gate_input("set", "kv", "bad key!../etc", {"value": 1})
        )
        assert out.allowed is False
        assert "key inválida" in (out.reason or "")

    @pytest.mark.asyncio
    async def test_write_gate_blocks_invalid_schema(self, registry):
        out = await ContinuityWriteGate(registry)(
            make_continuity_gate_input("set", "artifact", "a1", {"description": "x"})
        )
        assert out.allowed is False
        assert "schema inválido" in (out.reason or "")

    @pytest.mark.asyncio
    async def test_write_gate_blocks_oversized(self, registry):
        out = await ContinuityWriteGate(registry)(
            make_continuity_gate_input("set", "kv", "big", {"value": "x" * (70 * 1024)})
        )
        assert out.allowed is False
        assert "65536" in (out.reason or "")  # 64 KB em bytes

    @pytest.mark.asyncio
    async def test_read_gate_allows_and_blocks(self, registry):
        gate = ContinuityReadGate(registry)
        ok = await gate(make_continuity_gate_input("get", "session", "current"))
        assert ok.allowed is True
        bad = await gate(make_continuity_gate_input("get", "hacker", "x"))
        assert bad.allowed is False
        listed = await gate(make_continuity_gate_input("list", "", ""))
        assert listed.allowed is True

    @pytest.mark.asyncio
    async def test_gate_records_have_fk_invariants(self, registry):
        out = await ContinuityWriteGate(registry)(
            make_continuity_gate_input("set", "kv", "k", {"value": 1})
        )
        record = registry.get(out.gate_id)
        assert record.input_object is not None
        assert out.input_id == record.input_object.object_id
        assert record.agent_id == "platform"
