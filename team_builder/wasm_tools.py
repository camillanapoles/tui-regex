"""Built-in WASM tool sources — real WebAssembly in WAT text format.

These modules are compiled natively by Wasmtime at load time (no Rust
toolchain needed). They are the reference implementations for:

  * memory-passing convention (input_bytes at offset 0, return length),
  * fuel limiting (fibonacci with a low budget traps deterministically),
  * epoch interruption (wall-clock timeout via the engine ticker).
"""
from __future__ import annotations

# In-place ASCII uppercase transform over linear memory.
# Convention: run(len) -> len, result stored at offset 0.
UPPERCASE_WAT = """
(module
  (memory (export "memory") 1)
  (func $run (export "run") (param $len i32) (result i32)
    (local $i i32)
    (local $byte i32)
    (local.set $i (i32.const 0))
    (block $done
      (loop $loop
        (br_if $done (i32.ge_s (local.get $i) (local.get $len)))
        (local.set $byte (i32.load8_u (local.get $i)))
        (if (i32.and
              (i32.ge_s (local.get $byte) (i32.const 97))
              (i32.le_s (local.get $byte) (i32.const 122)))
          (then
            (i32.store8 (local.get $i) (i32.sub (local.get $byte) (i32.const 32)))
          )
        )
        (local.set $i (i32.add (local.get $i) (i32.const 1)))
        (br $loop)
      )
    )
    (local.get $len)
  )
)
"""

# Exponential recursion — the canonical Wasmtime fuel-limiting example.
# fib(n) with a tiny fuel budget traps deterministically.
FIBONACCI_WAT = """
(module
  (memory (export "memory") 1)
  (func $fib (export "fib") (param $n i32) (result i32)
    local.get $n
    i32.const 2
    i32.lt_s
    if (result i32)
      local.get $n
    else
      local.get $n i32.const 1 i32.sub (call $fib)
      local.get $n i32.const 2 i32.sub (call $fib)
      i32.add
    end)
)
"""

# Simple two-arg arithmetic — proves direct-argument calling convention.
# (anonymous params: compatible with every WAT parser version)
ADD_WAT = """
(module
  (memory (export "memory") 1)
  (func (export "add") (param i32 i32) (result i32)
    local.get 0
    local.get 1
    i32.add)
)
"""

ALL_WAT = {
    "uppercase": UPPERCASE_WAT,
    "fibonacci": FIBONACCI_WAT,
    "add": ADD_WAT,
}
