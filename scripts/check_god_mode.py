"""GOD MODE gate — check de PR para edições no núcleo da FSM.

Constituição da plataforma: o GOD MODE (Engenheiro Sênior de Orquestração)
é o ÚNICO editor da FSM API. Por isso, quando um PR toca em arquivos do
núcleo da FSM, o corpo do PR DEVE conter a análise de impacto e o motivo
do refator — os mesmos campos exigidos pela API em PATCH /god/fsm/edit.

Uso no CI:
    python scripts/check_god_mode.py --changed-files a.py,b.py --pr-body body.txt

Regras:
  * nenhum arquivo de núcleo alterado  -> OK (exit 0);
  * núcleo alterado                    -> o body precisa de
        impact_analysis:  (seção com >= 30 caracteres)
        refactor_reason:  (seção com >= 10 caracteres)
  * ausente                            -> FAIL (exit 1).
"""
from __future__ import annotations

import argparse
import re

CORE_FILES = {
    "team_builder/fsm.py",
    "team_builder/gates.py",
    "team_builder/api.py",
}


def section(body: str, marker: str, next_markers: tuple[str, ...]) -> str:
    m = re.search(rf"(?im)^\s*{re.escape(marker)}\s*:?\s*$", body)
    if not m:
        return ""
    start = m.end()
    end = len(body)
    for nxt in next_markers:
        m2 = re.search(rf"(?im)^\s*{re.escape(nxt)}\s*:?\s*$", body[start:])
        if m2:
            end = min(end, start + m2.start())
    return body[start:end].strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--changed-files", default="", help="caminhos separados por vírgula")
    parser.add_argument("--pr-body", default="", help="arquivo com o corpo do PR")
    args = parser.parse_args()

    changed = {p.strip() for p in args.changed_files.split(",") if p.strip()}
    touched = sorted(changed & CORE_FILES)
    if not touched:
        print("[god-mode-gate] Nenhum arquivo de núcleo da FSM alterado. OK.")
        return 0

    body = ""
    if args.pr_body:
        try:
            with open(args.pr_body, encoding="utf-8") as fh:
                body = fh.read()
        except OSError as exc:
            print(f"[god-mode-gate] ERRO lendo body do PR: {exc}")
            return 1

    impact = section(body, "impact_analysis", ("refactor_reason",))
    reason = section(body, "refactor_reason", ("impact_analysis",))

    print(f"[god-mode-gate] Núcleo da FSM alterado: {touched}")
    ok = True
    if len(impact) < 30:
        print(
            "[god-mode-gate] FALHA: seção 'impact_analysis:' ausente ou com menos de "
            "30 caracteres no corpo do PR. GOD MODE exige validação de impacto antes "
            "de editar a FSM API."
        )
        ok = False
    if len(reason) < 10:
        print(
            "[god-mode-gate] FALHA: seção 'refactor_reason:' ausente ou com menos de "
            "10 caracteres no corpo do PR."
        )
        ok = False

    if ok:
        print("[god-mode-gate] Análise de impacto presente. APROVADO para review.")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
