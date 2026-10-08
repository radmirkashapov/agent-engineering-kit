from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_engineering_kit.errors import AgentKitError
from agent_engineering_kit.paths import KitPaths
from agent_engineering_kit.projects import find_project, init_project, register_memory, validate_project


@pytest.fixture
def kit_repository() -> Path:
    return Path(__file__).resolve().parents[1]


def paths(tmp_path: Path, repository: Path) -> KitPaths:
    data = tmp_path / "data"
    return KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")


def test_single_repo_project(tmp_path: Path, kit_repository: Path) -> None:
    root = tmp_path / "single-repository"
    (root / ".git").mkdir(parents=True)
    project = init_project(root, kit_repository, paths(tmp_path, kit_repository))
    assert project.manifest["repositories"] == [{"id": "root", "path": "."}]
    assert project.manifest["harness"] == {
        "preferred_client": "auto",
        "required_capabilities": ["instructions", "skills", "mcp"],
    }
    assert (root / "docs/INDEX.md").is_file()
    assert validate_project(project, kit_repository).ok


def test_monorepo_detects_nested_components(tmp_path: Path, kit_repository: Path) -> None:
    root = tmp_path / "platform-monorepo"
    (root / ".git").mkdir(parents=True)
    (root / "backend").mkdir()
    (root / "backend/pyproject.toml").write_text("[project]\nname='backend'\n", encoding="utf-8")
    (root / "frontend").mkdir()
    (root / "frontend/package.json").write_text("{}", encoding="utf-8")
    (root / "backend/services/worker").mkdir(parents=True)
    (root / "backend/services/worker/pyproject.toml").write_text("[project]\nname='worker'\n", encoding="utf-8")
    project = init_project(root, kit_repository, paths(tmp_path, kit_repository))
    assert {item["id"] for item in project.manifest["components"]} == {"backend", "frontend", "worker"}
    assert any(item["path"] == "backend/services/worker" for item in project.manifest["components"])


def test_multi_repo_workspace(tmp_path: Path, kit_repository: Path) -> None:
    root = tmp_path / "platform-workspace"
    for name in ("backend", "frontend", "infrastructure"):
        (root / name / ".git").mkdir(parents=True)
    project = init_project(root, kit_repository, paths(tmp_path, kit_repository), identifier="platform-v2")
    assert {item["path"] for item in project.manifest["repositories"]} == {"backend", "frontend", "infrastructure"}
    nested = root / "backend/services/api"
    nested.mkdir(parents=True)
    assert find_project(nested).identifier == "platform-v2"


def test_stable_project_id_and_idempotent_init(tmp_path: Path, kit_repository: Path) -> None:
    root = tmp_path / "stable-project"
    first = init_project(root, kit_repository, paths(tmp_path, kit_repository), identifier="stable-id")
    second = init_project(root, kit_repository, paths(tmp_path, kit_repository), identifier="ignored-new-id")
    assert first.identifier == second.identifier == "stable-id"


def test_project_id_collision_fails(tmp_path: Path, kit_repository: Path) -> None:
    kit_paths = paths(tmp_path, kit_repository)
    first = init_project(tmp_path / "first-project", kit_repository, kit_paths, identifier="shared-id")
    register_memory(first, kit_paths)
    with pytest.raises(AgentKitError, match="Collision"):
        init_project(tmp_path / "second-project", kit_repository, kit_paths, identifier="shared-id")


def test_memory_has_expected_isolated_shape(tmp_path: Path, kit_repository: Path) -> None:
    kit_paths = paths(tmp_path, kit_repository)
    project = init_project(tmp_path / "isolated-project", kit_repository, kit_paths)
    memory = kit_paths.projects / project.identifier
    assert {path.name for path in memory.iterdir()} == {
        "state", "sessions", "summaries", "checkpoints", "integrations", "identity.json"
    }
    assert json.loads((memory / "identity.json").read_text())["project_id"] == project.identifier
