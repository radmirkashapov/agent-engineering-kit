from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from agent_engineering_kit.errors import AgentKitError
from agent_engineering_kit.paths import KitPaths
from agent_engineering_kit.tasks import create_task_workspace
from agent_engineering_kit.worktrees import create_managed_worktrees, plan_managed_worktrees


def _git(repository: Path, *args: str) -> str:
    completed = subprocess.run(["git", *args], cwd=repository, text=True, capture_output=True, check=True)
    return completed.stdout.strip()


def _repository(path: Path) -> Path:
    path.mkdir()
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.email", "tests@example.invalid")
    _git(path, "config", "user.name", "Tests")
    (path / "README.md").write_text("# Demo\n", encoding="utf-8")
    _git(path, "add", "README.md")
    _git(path, "commit", "-m", "docs(readme): add demo")
    return path


def test_worktree_plan_uses_managed_directory_and_preserves_primary_checkout(tmp_path: Path) -> None:
    paths = KitPaths(tmp_path / "kit", tmp_path / "data", tmp_path / "runtime", tmp_path / "projects", tmp_path / "overrides")
    repository = _repository(tmp_path / "backend")
    commit = _git(repository, "rev-parse", "HEAD")
    task_path = create_task_workspace(
        paths,
        project_id="commerce",
        task_id="task-01",
        repositories=[{"id": "backend", "path": str(repository), "commit": commit}],
        write_set=["src/**"],
        policy_digest="policy",
        conventions_digest="conventions",
    )

    plans = plan_managed_worktrees(paths, task_path, branch_prefix="feat/12-10-2026-task-01")
    assert plans[0]["target"] == str(paths.projects / "commerce" / "worktrees" / "task-01" / "backend")
    assert not Path(plans[0]["target"]).exists()

    created = create_managed_worktrees(paths, task_path, plans)
    assert Path(created[0]["target"]).is_dir()
    assert _git(repository, "branch", "--show-current") == "main"
    document = json.loads(task_path.read_text())
    assert document["status"] == "active"
    assert document["worktrees"][0]["branch"].endswith("-backend")


def test_worktree_plan_rejects_repository_path_outside_task_snapshot(tmp_path: Path) -> None:
    paths = KitPaths(tmp_path / "kit", tmp_path / "data", tmp_path / "runtime", tmp_path / "projects", tmp_path / "overrides")
    task = paths.projects / "commerce" / "tasks" / "task-01" / "task-workspace.json"
    task.parent.mkdir(parents=True)
    task.write_text('{"project_id":"commerce","task_id":"task-01","repositories":[{"id":"bad","path":"/missing","commit":"a"}]}')

    with pytest.raises(AgentKitError, match="Git repository"):
        plan_managed_worktrees(paths, task, branch_prefix="feat/12-10-2026-task-01")
