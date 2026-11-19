from __future__ import annotations

from pathlib import Path

import pytest

from agent_engineering_kit.errors import AgentKitError
from agent_engineering_kit.git_provenance import commit, install_hook, mark_agent_worktree, prepare_commit_msg
from agent_engineering_kit.process import run_command


def _git(root: Path, *args: str) -> str:
    result = run_command(["git", "-C", str(root), *args])
    assert result.ok, result.stderr
    return result.stdout


def test_agent_commit_adds_normalized_provenance_without_changing_author(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.name", "Developer")
    _git(root, "config", "user.email", "developer@example.test")
    (root / "README.md").write_text("example\n", encoding="utf-8")
    _git(root, "add", "README.md")

    commit(root, client="opencode", message="feat(core): add example")

    message = _git(root, "log", "-1", "--format=%B")
    assert "Agent-Generated: true" in message
    assert "Agent-Client: opencode" in message
    assert _git(root, "log", "-1", "--format=%an").strip() == "Developer"


def test_project_hook_is_non_destructive_for_manual_commit(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.name", "Developer")
    _git(root, "config", "user.email", "developer@example.test")
    hook = install_hook(root)
    assert hook is not None and hook.is_file()
    (root / "README.md").write_text("manual\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-m", "docs(core): add manual file")
    assert "Agent-Generated" not in _git(root, "log", "-1", "--format=%B")


def test_strict_agent_worktree_rejects_direct_commit_message(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    _git(root, "init")
    mark_agent_worktree(root, client="cline")
    message = root / "message"
    message.write_text("feat(core): add example\n", encoding="utf-8")

    with pytest.raises(AgentKitError, match="прямой git commit запрещён"):
        prepare_commit_msg(root, message)

    _git(root, "config", "user.name", "Developer")
    _git(root, "config", "user.email", "developer@example.test")
    (root / "agent.txt").write_text("agent\n", encoding="utf-8")
    _git(root, "add", "agent.txt")
    commit(root, client="cline", message="feat(core): add agent file")
    assert "Agent-Client: cline" in _git(root, "log", "-1", "--format=%B")
