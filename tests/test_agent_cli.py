from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from agent_engineering_kit.agent_cli import run
from agent_engineering_kit.paths import KitPaths
from agent_engineering_kit.projects import init_project


REPOSITORY = Path(__file__).resolve().parents[1]


def test_agent_task_create_falls_back_to_id_and_honors_explicit_type(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data = tmp_path / "data"
    monkeypatch.setenv("AGENT_KIT_DATA_HOME", str(data))
    monkeypatch.setenv("AGENT_KIT_REPOSITORY", str(REPOSITORY))
    root = tmp_path / "project"
    root.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "tests@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Tests"], cwd=root, check=True)
    (root / "README.md").write_text("# Project\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-m", "docs(readme): add project"], cwd=root, check=True, capture_output=True)
    paths = KitPaths(REPOSITORY, data, data / "runtime", data / "projects", data / "overrides")
    init_project(root, REPOSITORY, paths, identifier="agent-project")
    monkeypatch.chdir(root)

    assert run(["task", "create", "SOME-ID", "--type", "fix", "--write", "src/**"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["worktrees"][0]["branch"].endswith("-some-id")
    assert result["worktrees"][0]["branch"].startswith("fix/")
