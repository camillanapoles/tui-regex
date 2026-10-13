"""GitHub operations — push via `git`, PR e metadados via `gh api`
(o secret/autenticação é o do ambiente `gh auth`; nunca sai daqui).

Cada operação escrita também no objeto de continuidade `git_op`
(tabela continuity_objects) — o estado de push/PR é, portanto,
**recuperável pela API** em qualquer sessão futura:

    GET /continuity/git_op/{branch}
"""
from __future__ import annotations

import json
import subprocess
from typing import Any
from urllib.parse import urlparse

from team_builder.continuity import ContinuityFactory
from team_builder.db import ContinuityRepo


class GitHubOpsError(Exception):
    def __init__(self, message: str, raw: str = ""):
        super().__init__(message)
        self.raw = raw


class GitHubOps:
    """Operações GitHub com continuidade: cada ação persiste seu estado."""

    def __init__(self, workdir: str, db: Any | None = None):
        self.workdir = workdir
        self.db = db

    # ── plumbing ───────────────────────────────────────────────────────
    def _run(self, argv: list[str], check: bool = True) -> str:
        proc = subprocess.run(  # noqa: S603 - argv explícito, sem shell
            argv, cwd=self.workdir, capture_output=True, text=True, timeout=120
        )
        out = (proc.stdout or "").strip()
        if check and proc.returncode != 0:
            raise GitHubOpsError(
                f"comando '{argv[0]}' falhou (rc={proc.returncode})",
                raw=(proc.stderr or "") + "\n" + out,
            )
        return out

    def repo_full_name(self) -> str:
        """owner/repo a partir do remote origin (sem rede)."""
        url = self._run(["git", "remote", "get-url", "origin"])
        if url.startswith("git@"):
            return url.split(":", 1)[1].removesuffix(".git")
        path = urlparse(url).path.lstrip("/")
        return path.removesuffix(".git")

    # ── estado (read) ──────────────────────────────────────────────────
    def git_status(self) -> dict[str, Any]:
        branch = self._run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
        commit = self._run(["git", "rev-parse", "HEAD"])
        remote = self._run(["git", "remote", "get-url", "origin"])
        return {"branch": branch, "commit": commit, "remote": remote}

    def save_git_state(self, **extra: Any) -> dict[str, Any] | None:
        """Grava/atualiza o estado git_op na continuidade (se houver db)."""
        if self.db is None:
            return None
        status = self.git_status()
        existing = ContinuityRepo(self.db).get(
            "git_op", f"branch/{status['branch']}"
        )
        base = {
            "remote": status["remote"],
            "branch": status["branch"],
            "commit": status["commit"],
        }
        if existing is not None:
            base.update(existing.data or {})
        base.update(extra)
        state = ContinuityFactory.create("git_op", **base)
        row = ContinuityRepo(self.db).save(
            "git_op", f"branch/{status['branch']}", state.model_dump()
        )
        return {
            "kind": "git_op",
            "key": f"branch/{status['branch']}",
            "version": row.version,
            "data": state.model_dump(),
        }

    # ── escrita (push / PR) ────────────────────────────────────────────
    def push(self, branch: str | None = None) -> dict[str, Any]:
        status = self.git_status()
        branch = branch or status["branch"]
        if branch == "HEAD":
            raise GitHubOpsError("branch desconhecida (detached HEAD?)")
        self._run(["git", "push", "origin", branch])
        saved = self.save_git_state(status="pushed")
        return {"ok": True, "branch": branch, "state": saved}

    def create_pr(
        self,
        title: str,
        body: str,
        head: str | None = None,
        base: str = "main",
    ) -> dict[str, Any]:
        status = self.git_status()
        head = head or status["branch"]
        repo = self.repo_full_name()
        out = self._run(
            [
                "gh", "api", f"repos/{repo}/pulls",
                "-f", f"title={title}",
                "-f", f"head={head}",
                "-f", f"base={base}",
                "-f", f"body={body}",
            ]
        )
        data = json.loads(out)
        number = int(data["number"])
        url = data.get("html_url", "")
        saved = self.save_git_state(
            status="pr_open", pr_number=number, pr_url=url
        )
        return {"ok": True, "pr_number": number, "pr_url": url, "state": saved}

    def pr_status(self, number: int) -> dict[str, Any]:
        repo = self.repo_full_name()
        out = self._run(["gh", "api", f"repos/{repo}/pulls/{number}"])
        data = json.loads(out)
        return {
            "ok": True,
            "pr_number": number,
            "state": data.get("state"),
            "mergeable_state": data.get("mergeable_state"),
            "html_url": data.get("html_url"),
        }

    def merge_pr(self, number: int, method: str = "squash") -> dict[str, Any]:
        repo = self.repo_full_name()
        self._run(["gh", "api", f"repos/{repo}/pulls/{number}/merge", "-f", f"merge_method={method}"])
        saved = self.save_git_state(status="merged")
        return {"ok": True, "pr_number": number, "method": method, "state": saved}
