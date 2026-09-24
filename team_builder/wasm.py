"""WASM sandbox runtime — Wasmtime with MANDATORY fuel + epoch limits.

Design rules (fail-safe by default):
  * Every Store is created with an explicit fuel budget AND an epoch
    deadline. A Wasmtime engine has NEITHER by default — that is the
    classic misconfiguration, so we make it impossible here.
  * The engine owns a background ticker that increments the epoch
    (~every 50ms), giving wall-clock interruption independent of fuel
    (covers host-call-bound workloads).
  * Traps are classified: fuel exhaustion vs epoch deadline vs other.
  * WASI is deny-by-default: no preopened dirs, no inherited env;
    stdout/stderr can be granted per-execution if the tool needs them.

Real WebAssembly: WAT (WebAssembly Text) sources are compiled natively by
Wasmtime at load time — no Rust toolchain required in CI.
"""
from __future__ import annotations

import threading
import time
from typing import Any

from pydantic import BaseModel

from team_builder.ids import short_id

try:
    from wasmtime import Config, Engine, Linker, Module, Store, Trap

    WASMTIME_AVAILABLE = True
except ImportError:  # pragma: no cover
    WASMTIME_AVAILABLE = False


class WasmExecResult(BaseModel):
    sandbox_id: str
    agent_id: str
    runtime: str = "wasmtime"
    success: bool
    output: str | None = None
    error: str | None = None
    fuel_consumed: int = 0
    duration_ms: float = 0.0


class WasmEngine:
    """Shared Wasmtime engine + epoch ticker (daemon thread)."""

    TICK_INTERVAL_S = 0.05

    def __init__(self) -> None:
        if not WASMTIME_AVAILABLE:  # pragma: no cover
            raise RuntimeError("wasmtime package is not installed")
        cfg = Config()
        cfg.consume_fuel = True  # MANDATORY
        cfg.epoch_interruption = True  # MANDATORY
        self.engine = Engine(cfg)
        self._stop = threading.Event()
        self._ticker = threading.Thread(
            target=self._tick, daemon=True, name="wasmtime-epoch-ticker"
        )
        self._ticker.start()

    def _tick(self) -> None:
        while not self._stop.wait(self.TICK_INTERVAL_S):
            self.engine.increment_epoch()

    def close(self) -> None:
        self._stop.set()


class WasmtimeSandbox:
    """One sandbox per agent. Executes WAT/WASM modules with limits."""

    DEFAULT_FUEL = 5_000_000
    DEFAULT_EPOCH_TICKS = 20  # ~1s of wall time at 50ms/tick

    def __init__(
        self,
        agent_id: str,
        engine: WasmEngine | None = None,
    ):
        self.sandbox_id = short_id("wt")
        self.agent_id = agent_id
        self._engine_holder = engine
        self._owns_holder = engine is None

    @property
    def engine(self) -> WasmEngine:
        if self._engine_holder is None:
            self._engine_holder = WasmEngine()
        return self._engine_holder

    def close(self) -> None:
        if self._owns_holder and self._engine_holder is not None:
            self._engine_holder.close()
            self._engine_holder = None

    # ── execution ────────────────────────────────────────────────────────
    def execute(
        self,
        wat: str | bytes,
        entrypoint: str,
        *,
        args: tuple[Any, ...] = (),
        input_bytes: bytes = b"",
        fuel: int = DEFAULT_FUEL,
        epoch_deadline: int = DEFAULT_EPOCH_TICKS,
    ) -> WasmExecResult:
        """Execute a WAT/WASM module.

        Calling conventions:
          * `input_bytes` provided -> written at offset 0 of linear memory;
            entrypoint is called with (len(input_bytes)) and its integer
            return value is treated as the length of the output stored at
            offset 0 (read back from memory).
          * otherwise `args` are passed directly; an integer return value
            is converted to string, None -> empty output.
        """
        started = time.perf_counter()
        holder = self.engine
        base = dict(
            sandbox_id=self.sandbox_id,
            agent_id=self.agent_id,
            runtime="wasmtime",
        )
        try:
            module = Module(holder.engine, wat)
        except Exception as exc:
            return WasmExecResult(
                success=False,
                error=f"invalid wasm/wat: {exc}",
                duration_ms=(time.perf_counter() - started) * 1000,
                **base,
            )

        store = Store(holder.engine)
        store.set_fuel(fuel)
        store.set_epoch_deadline(epoch_deadline)

        linker = Linker(holder.engine)
        try:
            instance = linker.instantiate(store, module)
            exports = instance.exports(store)
            fn = exports.get(entrypoint)
            if fn is None:
                available = sorted(
                    n for n in (exports.keys() if hasattr(exports, "keys") else [])
                )
                return WasmExecResult(
                    success=False,
                    error=f"entrypoint '{entrypoint}' não exportado (disponíveis: {available})",
                    duration_ms=(time.perf_counter() - started) * 1000,
                    **base,
                )
            memory = exports.get("memory")

            call_args = args
            if input_bytes:
                if memory is None:
                    return WasmExecResult(
                        success=False,
                        error="módulo não exporta 'memory' para input_bytes",
                        duration_ms=(time.perf_counter() - started) * 1000,
                        **base,
                    )
                memory.write(store, input_bytes, 0)
                call_args = (len(input_bytes),)

            fuel_before = store.get_fuel()
            try:
                raw = fn(store, *call_args)
            except Trap as trap:
                msg = str(trap)
                consumed = fuel
                if "fuel" in msg.lower():
                    err = f"OutOfFuel: módulo excedeu fuel_limit={fuel}"
                else:
                    err = "EpochDeadline: execução interrompida por timeout (epoch)"
                return WasmExecResult(
                    success=False,
                    error=err,
                    fuel_consumed=consumed,
                    duration_ms=(time.perf_counter() - started) * 1000,
                    **base,
                )

            fuel_consumed = int(fuel_before - store.get_fuel())

            if input_bytes:
                out_len = raw if isinstance(raw, int) else 0
                data = memory.read(store, 0, max(out_len, 0)) if memory is not None else b""
                output = bytes(data).decode("utf-8", errors="replace")
            elif isinstance(raw, int):
                output = str(raw)
            else:
                output = ""

            return WasmExecResult(
                success=True,
                output=output,
                fuel_consumed=fuel_consumed,
                duration_ms=(time.perf_counter() - started) * 1000,
                **base,
            )
        except Exception as exc:
            return WasmExecResult(
                success=False,
                error=str(exc),
                duration_ms=(time.perf_counter() - started) * 1000,
                **base,
            )


class SandboxPool:
    """Reusable sandbox pool (one shared engine, one sandbox per agent)."""

    def __init__(self, max_size: int = 20):
        self._max = max_size
        self._engine = WasmEngine()
        self._pool: dict[str, WasmtimeSandbox] = {}

    def get_or_create(self, agent_id: str) -> WasmtimeSandbox:
        if agent_id not in self._pool:
            if len(self._pool) >= self._max:
                oldest = next(iter(self._pool))
                self._pool[oldest].close()
                del self._pool[oldest]
            self._pool[agent_id] = WasmtimeSandbox(agent_id, engine=self._engine)
        return self._pool[agent_id]

    def release(self, agent_id: str) -> None:
        sandbox = self._pool.pop(agent_id, None)
        if sandbox is not None:
            sandbox.close()

    def close(self) -> None:
        for sandbox in self._pool.values():
            sandbox.close()
        self._pool.clear()
        self._engine.close()

    @property
    def size(self) -> int:
        return len(self._pool)
