"""Valida todos os módulos WAT embutidos na plataforma.

O que faz (evidência executável no CI):
  1. importa team_builder.wasm_tools (fonte única de WAT);
  2. COMPILA cada módulo no Wasmtime (validador oficial da Bytecode Alliance);
  3. instancia cada módulo e ASSERTA os entrypoints exportados;
  4. executa um smoke de cada tool (uppercase/fibonacci/add) em sandbox real;
  5. (opcional, --emit DIR) grava os .wasm binários para inspeção/auditoria.

Uso:
    python scripts/validate_wat.py [--emit out/]
Exit code 0 = tudo válido; 1 = falha.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from team_builder.wasm_tools import ADD_WAT, FIBONACCI_WAT, UPPERCASE_WAT  # noqa: E402
from wasmtime import Config, Engine, Linker, Module, Store  # noqa: E402

TOOLS = [
    # (nome, wat, entrypoint, modo, args/bytes, output esperado)
    ("uppercase", UPPERCASE_WAT, "run", "bytes", b"ci-wasm", "CI-WASM"),
    ("fibonacci", FIBONACCI_WAT, "fib", "args", (10,), "55"),
    ("add", ADD_WAT, "add", "args", (20, 22), "42"),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--emit-wat", default=None,
        help="diretório p/ gravar os arquivos .wat (2º validador, ex.: WABT)",
    )
    args = parser.parse_args()

    config = Config()
    config.consume_fuel = True
    # (epoch_interruption fica por conta do sandbox: a validação só precisa
    #  compilar/instanciar/executar — sem deadline, nenhum trap de epoch.)
    engine = Engine(config)

    failures = 0
    for name, wat, entrypoint, mode, data, expected in TOOLS:
        try:
            module = Module(engine, wat)
            print(f"[wasm-validate] {name}: WAT compilado com sucesso")
        except Exception as exc:
            print(f"[wasm-validate] {name}: FALHA ao compilar: {exc}")
            failures += 1
            continue

        # exporta o .wat para validação por 2º validador (WABT no CI)
        if args.emit_wat:
            os.makedirs(args.emit_wat, exist_ok=True)
            path = os.path.join(args.emit_wat, f"{name}.wat")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(wat)
            print(f"[wasm-validate] {name}: WAT em {path}")

        # instancia e confere export (mesma API do sandbox da plataforma)
        store = Store(engine)
        try:
            linker = Linker(engine)
            instance = linker.instantiate(store, module)
            exports = instance.exports(store)
            available = list(exports.keys()) if hasattr(exports, "keys") else []
            if entrypoint not in available:
                raise RuntimeError(f"export '{entrypoint}' ausente (disponíveis: {available})")
            fn = exports.get(entrypoint)
        except Exception as exc:
            print(f"[wasm-validate] {name}: FALHA na instanciação: {exc}")
            failures += 1
            continue

        # smoke execution (fuel: mesmo limite do sandbox da plataforma)
        store.set_fuel(5_000_000)
        try:
            if mode == "bytes":
                memory = exports.get("memory")
                data = bytes(data)
                memory.write(store, data, 0)  # (store, data, offset)
                raw = fn(store, len(data))    # retorna o length
                out = bytes(memory.read(store, 0, max(int(raw), 0))).decode(
                    "utf-8", errors="replace"
                )
            else:
                raw = fn(store, *data)
                out = str(raw)
        except Exception as exc:
            print(f"[wasm-validate] {name}: FALHA na execução: {exc}")
            failures += 1
            continue

        if out != expected:
            print(f"[wasm-validate] {name}: output {out!r} != esperado {expected!r}")
            failures += 1
            continue
        print(f"[wasm-validate] {name}: smoke OK -> {out!r}")

    if failures:
        print(f"[wasm-validate] {failures} FALHAS")
        return 1
    print("[wasm-validate] TODOS OS MÓDULOS WASM VÁLIDOS (wasmtime)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
