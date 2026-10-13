"""GitHubOps — push/PR via git + gh api, com estado gravado na continuidade."""
import json
import os
import re

import pytest
from team_builder.db import ContinuityRepo
from team_builder.ghops import GitHubOps, GitHubOpsError

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def ops(db):
    return GitHubOps(workdir=REPO_ROOT, db=db)


class TestGitStatus:
    def test_real_repo_status(self, ops):
        status = ops.git_status()
        assert status["branch"], "branch não detectada"
        assert re.fullmatch(r"[0-9a-f]{40}", status["commit"])
        assert "github.com" in status["remote"]

    def test_repo_full_name(self, ops):
        name = ops.repo_full_name()
        assert re.fullmatch(r"[^/]+/[^/]+", name)


class TestPushCommand:
    def test_push_builds_git_command(self, ops, monkeypatch):
        calls = []

        def fake_run(argv, check=True):
            calls.append(argv)
            if argv[0] == "git" and argv[1:3] == ["rev-parse", "--abbrev-ref"]:
                return "arena/teste"
            if argv[0] == "git" and argv[1:3] == ["rev-parse", "HEAD"]:
                return "f" * 40
            if argv[0] == "git" and argv[1:2] == ["remote"]:
                return "git@github.com:camillanapoles/tui-regex.git"
            return ""

        monkeypatch.setattr(ops, "_run", fake_run)
        result = ops.push()
        assert result["ok"] is True
        assert result["branch"] == "arena/teste"
        assert ["git", "push", "origin", "arena/teste"] in calls
        # estado gravado na continuidade
        row = ContinuityRepo(ops.db).get("git_op", "branch/arena/teste")
        assert row is not None
        assert row.data["status"] == "pushed"
        assert row.data["commit"] == "f" * 40


class TestPrCommands:
    FAKE_PR = {
        "number": 42,
        "html_url": "https://github.com/camillanapoles/tui-regex/pull/42",
        "state": "open",
        "mergeable_state": "clean",
    }

    def _fake_run(self, ops, monkeypatch, pr=None):
        calls = []
        pr_data = pr or self.FAKE_PR

        def fake_run(argv, check=True):
            calls.append(argv)
            if argv[0] == "git" and argv[1:3] == ["rev-parse", "--abbrev-ref"]:
                return "arena/pr"
            if argv[0] == "git" and argv[1:3] == ["rev-parse", "HEAD"]:
                return "e" * 40
            if argv[0] == "git" and argv[1:2] == ["remote"]:
                return "https://github.com/camillanapoles/tui-regex.git"
            if argv[0] == "gh" and argv[1] == "api":
                return json.dumps(pr_data)
            return ""

        monkeypatch.setattr(ops, "_run", fake_run)
        return calls

    def test_create_pr_uses_gh_api(self, ops, monkeypatch):
        calls = self._fake_run(ops, monkeypatch)
        result = ops.create_pr("Título do PR", "corpo do PR", base="main")
        assert result["ok"] is True
        assert result["pr_number"] == 42
        assert result["pr_url"].endswith("/pull/42")
        gh_call = next(c for c in calls if c[0] == "gh")
        assert gh_call[1] == "api"
        assert gh_call[2] == "repos/camillanapoles/tui-regex/pulls"
        assert "-f" in gh_call
        assert any("head=arena/pr" == a for a in gh_call)
        assert any("base=main" == a for a in gh_call)
        assert any("body=corpo do PR" == a for a in gh_call)
        # continuidade gravada
        row = ContinuityRepo(ops.db).get("git_op", "branch/arena/pr")
        assert row.data["pr_number"] == 42
        assert row.data["status"] == "pr_open"

    def test_pr_status(self, ops, monkeypatch):
        self._fake_run(ops, monkeypatch)
        result = ops.pr_status(42)
        assert result["ok"] is True
        assert result["state"] == "open"
        assert result["mergeable_state"] == "clean"

    def test_push_failure_raises_with_raw(self, ops, monkeypatch):
        def boom(argv, check=True):
            if argv[0] == "git" and argv[1:3] == ["rev-parse", "--abbrev-ref"]:
                return "arena/x"
            if argv[0] == "git" and argv[1:3] == ["rev-parse", "HEAD"]:
                return "d" * 40
            if argv[0] == "git" and argv[1:2] == ["remote"]:
                return "git@github.com:camillanapoles/tui-regex.git"
            raise GitHubOpsError("simulated failure", raw="denied by remote")

        monkeypatch.setattr(ops, "_run", boom)
        with pytest.raises(GitHubOpsError):
            ops.push()
