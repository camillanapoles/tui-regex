"""Gera o snapshot de continuidade a partir do servidor da plataforma.

Lê os objetos de continuidade (session + git_op do branch atual) da API
rodando e grava `docs/evidence/continuity_snapshot.json` — que é
**commitado no repositório** para que o workflow `Session Continuity`
embuta o último estado persistido no documento de handoff.

Uso:
    python scripts/snapshot_continuity.py [--url http://localhost:8000]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from urllib import request
from urllib.error import HTTPError, URLError

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_json(url: str):
    try:
        with request.urlopen(url, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except (HTTPError, URLError, TimeoutError) as exc:
        return {"_error": str(exc)}


def current_branch() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=15,
        ).stdout.strip()
    except Exception:
        return "HEAD"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--out", default=os.path.join(REPO_ROOT, "docs", "evidence",
                                                      "continuity_snapshot.json"))
    args = parser.parse_args()
    base = args.url.rstrip("/")

    branch = current_branch()
    keys = [
        "session/current",
        f"git_op/branch/{branch}",
    ]
    snapshot = {
        "captured_at": datetime.now(UTC).isoformat(),
        "source": base,
        "branch": branch,
        "head": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
            capture_output=True, text=True, timeout=15,
        ).stdout.strip(),
        "stats": get_json(base + "/continuity/stats"),
        "objects": {key: get_json(base + f"/continuity/{key}") for key in keys},
    }

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(snapshot, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(f"OK: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
