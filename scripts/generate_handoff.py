"""Gera o documento de handoff de sessão (continuidade garantida por CI/CD).

Usado pelo workflow `session-continuity.yml` (push em `main` ou
`workflow_dispatch`) para produzir `docs/handoff/SESSION_HANDOFF.md`:
o "ponto de retomada" que permite a próxima sessão/janela (second way)
continuar o trabalho com todo o contexto, sem depender desta sessão.

Determinístico: deriva tudo do estado do repositório (git) + snapshot de
continuidade commitado (`docs/evidence/continuity_snapshot.json`) quando
existente. Não depende do sandbox nem do servidor local.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAPSHOT_PATH = os.path.join(REPO_ROOT, "docs", "evidence", "continuity_snapshot.json")
NEXT_STEPS_PATH = os.path.join(REPO_ROOT, "docs", "CONTINUATION_PLAN.md")


def sh(*cmd: str) -> str:
    """Executa comando e retorna stdout (texto, sem crash em erro)."""
    try:
        return subprocess.run(
            cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=30
        ).stdout.strip()
    except Exception:
        return ""


def github_pr_status() -> str:
    """Status de PRs abertos para o branch atual (via gh, se disponível)."""
    branch = sh("git", "rev-parse", "--abbrev-ref", "HEAD")
    if not branch or branch == "HEAD":
        return "(nenhum branch de trabalho)"
    raw = sh(
        "gh", "pr", "list", "--head", branch, "--state", "open",
        "--json", "number,title,mergeStateStatus,url",
    )
    if not raw:
        return f"(nenhum PR aberto para `{branch}` ou `gh` indisponível no runner)"
    try:
        lines = [
            f"- PR #{p['number']}: {p['title']} — {p['mergeStateStatus']} — {p['url']}"
            for p in json.loads(raw)
        ]
        return "\n".join(lines)
    except Exception:
        return "(falha ao interpretar `gh pr list`)"


def continuity_snapshot() -> str:
    """Snapshot de continuidade commitado (gravado fora da API + via API)."""
    if os.path.exists(SNAPSHOT_PATH):
        with open(SNAPSHOT_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        return "```json\n" + json.dumps(data, indent=2, ensure_ascii=False) + "\n```"
    return "(snapshot não commitado — gere com `scripts/snapshot_continuity.py`)"


def next_steps() -> str:
    """Próximos passos: cabeçalhos E0/Ex do plano de continuidade."""
    if not os.path.exists(NEXT_STEPS_PATH):
        return "(`docs/CONTINUATION_PLAN.md` ausente)"
    steps = []
    with open(NEXT_STEPS_PATH, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("## ") and ("E0" in line or "E1" in line or "E2" in line
                                            or "E3" in line or "E4" in line or "E6" in line):
                steps.append(f"- {line.strip()}")
    return "\n".join(steps[:12]) if steps else "(seção de próximos passos não encontrada)"


def build_handoff() -> str:
    head = sh("git", "rev-parse", "HEAD")
    short = sh("git", "rev-parse", "--short", "HEAD")
    branch = sh("git", "rev-parse", "--abbrev-ref", "HEAD")
    log = sh("git", "log", "--oneline", "-8")
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    docs = [
        p for p in (
            "docs/DELIVERY_REPORT.md",
            "docs/STATUS_REPORT.md",
            "docs/CONTINUATION_PLAN.md",
            "docs/evidence/pytest_final.txt",
            "docs/evidence/live_server.txt",
        ) if os.path.exists(os.path.join(REPO_ROOT, p))
    ]

    return f"""# 🔁 HANDOFF DE SESSÃO — continuidade garantida por CI/CD

> Gerado automaticamente pelo workflow **Session Continuity** (GitHub Actions).
> Este arquivo é o **ponto de retomada**: a próxima sessão/janela (second way)
> deve começar lendo este documento.

## Estado atual (fatos do repositório)
- **Commit base:** `{head}` (`{short}`)
- **Branch que disparou:** `{branch}`
- **Gerado em:** {now}
- **Últimos commits:**
```
{log}
```
- **PRs abertos:**
{github_pr_status()}

## Como retomar (second way) — passo a passo
1. Criar/abrir nova sessão de agente neste repositório e apontá-la para o branch
   `handoff/…` deste PR (ou para `main` após merge).
2. Ler, nesta ordem: **este arquivo**, `docs/DELIVERY_REPORT.md`, `docs/CONTINUATION_PLAN.md`.
3. Subir a plataforma e **recuperar o estado de continuidade pela API** (nenhum estado vive só no chat):
   ```bash
   python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
   .venv/bin/uvicorn team_builder.api:app --host 0.0.0.0 --port 8000
   curl localhost:8000/continuity/stats
   curl localhost:8000/continuity/session/current
   curl localhost:8000/continuity/git_op/branch/{branch}
   ```
4. Validar o estado antes de agir: `pytest -q` (158 testes) e `python scripts/validate_wat.py`.
5. Atualizar `session/current` via `PUT /continuity/session/current`
   (com `expected_version` do objeto recuperado) antes do primeiro trabalho.
6. Se `docs/handoff/PR_CREATION_BLOCKED.txt` existir neste branch, seguir as
   instruções dele (criar o PR em 1 clique ou ativar a permissão de Actions).

## Snapshot de continuidade (última gravação persistida)
{continuity_snapshot()}

## Documentação de referência (neste repositório)
{chr(10).join(f"- `{d}`" for d in docs) if docs else "- (nenhuma)"}

## Próximos passos (plano de continuidade)
{next_steps()}

## Regras de ouro (não regressar)
- Factory (sem hardcode de equipe) · Pydantic+Instructor · tudo via API (hooks bloqueiam o resto)
- Gates OOP com UUID PK + FKs · 100% objetos conectados
- God Mode: único editor da FSM/tools, sempre com análise de impacto
- Evidência real testada — nenhuma alegação sem prova
- CI/CD incremental; merge em `main` dispara release **e** este mecanismo de handoff
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=None, help="arquivo de saída (padrão: stdout)")
    args = parser.parse_args()
    doc = build_handoff()
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(doc)
        print(f"OK: {args.out}")
    else:
        print(doc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
