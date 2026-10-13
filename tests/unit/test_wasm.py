"""WASM runtime tests — REAL WebAssembly execution on Wasmtime 49.

Covers: memory-passing convention, direct args, fuel exhaustion (trap),
epoch interruption (trap), invalid WAT, missing entrypoint, pool reuse.
"""
import pytest
from team_builder.wasm import SandboxPool, WasmEngine, WasmtimeSandbox
from team_builder.wasm_tools import ADD_WAT, FIBONACCI_WAT, UPPERCASE_WAT


@pytest.fixture
def engine():
    holder = WasmEngine()
    yield holder
    holder.close()


@pytest.fixture
def sandbox(engine):
    return WasmtimeSandbox("test-agent", engine=engine)


class TestWasmExecution:
    @pytest.mark.asyncio
    async def test_uppercase_transforms_memory(self, sandbox):
        result = sandbox.execute(
            UPPERCASE_WAT, "run", input_bytes=b"hello wasm agent"
        )
        assert result.success is True
        assert result.output == "HELLO WASM AGENT"
        assert result.fuel_consumed > 0
        assert result.duration_ms >= 0
        assert result.runtime == "wasmtime"
        assert result.sandbox_id.startswith("wt-")

    @pytest.mark.asyncio
    async def test_fibonacci_computes(self, sandbox):
        result = sandbox.execute(FIBONACCI_WAT, "fib", args=(10,))
        assert result.success is True
        assert result.output == "55"

    @pytest.mark.asyncio
    async def test_add_direct_args(self, sandbox):
        result = sandbox.execute(ADD_WAT, "add", args=(2, 3))
        assert result.success is True
        assert result.output == "5"

    @pytest.mark.asyncio
    async def test_fuel_exhaustion_traps_deterministically(self, sandbox):
        result = sandbox.execute(FIBONACCI_WAT, "fib", args=(40,), fuel=100)
        assert result.success is False
        assert "fuel" in (result.error or "")
        assert result.fuel_consumed > 0

    @pytest.mark.asyncio
    async def test_epoch_deadline_interrupts_runaway_module(self, sandbox):
        result = sandbox.execute(
            FIBONACCI_WAT, "fib", args=(45,), fuel=10**12, epoch_deadline=1
        )
        assert result.success is False
        assert "epoch" in (result.error or "")

    @pytest.mark.asyncio
    async def test_invalid_wat_reports_error(self, sandbox):
        result = sandbox.execute("(module broken", "run")
        assert result.success is False
        assert "invalid wasm/wat" in (result.error or "")

    @pytest.mark.asyncio
    async def test_missing_entrypoint_reports_error(self, sandbox):
        result = sandbox.execute(ADD_WAT, "does_not_exist")
        assert result.success is False
        assert "não exportado" in (result.error or "")


class TestSandboxPool:
    @pytest.mark.asyncio
    async def test_pool_reuses_sandbox_per_agent(self):
        pool = SandboxPool(max_size=5)
        try:
            a1 = pool.get_or_create("agent-a")
            a2 = pool.get_or_create("agent-a")
            assert a1 is a2
            assert pool.size == 1
        finally:
            pool.close()

    @pytest.mark.asyncio
    async def test_pool_evicts_when_full(self):
        pool = SandboxPool(max_size=3)
        try:
            for i in range(4):
                pool.get_or_create(f"agent-{i}")
            assert pool.size == 3
            assert "agent-0" not in pool._pool  # oldest evicted
        finally:
            pool.close()

    @pytest.mark.asyncio
    async def test_pool_release(self):
        pool = SandboxPool(max_size=5)
        try:
            pool.get_or_create("agent-x")
            pool.release("agent-x")
            assert pool.size == 0
        finally:
            pool.close()

    @pytest.mark.asyncio
    async def test_pooled_sandbox_executes_real_wasm(self):
        pool = SandboxPool(max_size=2)
        try:
            sandbox = pool.get_or_create("pool-agent")
            result = sandbox.execute(ADD_WAT, "add", args=(20, 22))
            assert result.success is True
            assert result.output == "42"
        finally:
            pool.close()
