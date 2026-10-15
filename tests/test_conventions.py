from __future__ import annotations

from pathlib import Path

import pytest

from agent_engineering_kit.conventions import load_conventions, validate_conventions
from agent_engineering_kit.errors import AgentKitError
from agent_engineering_kit.projects import LogicalProject
from conftest import write_yaml


REPOSITORY = Path(__file__).resolve().parents[1]


def _project(root: Path, conventions: list[str]) -> LogicalProject:
    return LogicalProject(root, root / ".ai-team" / "project.yaml", {"id": "sample", "conventions": conventions})


def test_project_conventions_append_without_replacing_kit_conventions(tmp_path: Path) -> None:
    project = _project(tmp_path, [".ai-team/conventions.yaml"])
    write_yaml(tmp_path / ".ai-team" / "conventions.yaml", {
        "version": 1,
        "conventions": [{"id": "sample-review", "description": "Review sample changes", "requirements": ["Review before merge"]}],
    })

    items = load_conventions(REPOSITORY, project)

    assert "sample-review" in {item["id"] for item in items}
    assert "documentation-ownership" in {item["id"] for item in items}
    assert len(items) == len({item["id"] for item in items})
    assert any(item["source"].startswith("project:") for item in items)


def test_invalid_project_conventions_fail_schema_validation(tmp_path: Path) -> None:
    project = _project(tmp_path, [".ai-team/conventions.yaml"])
    write_yaml(tmp_path / ".ai-team" / "conventions.yaml", {
        "version": 1,
        "conventions": [{"id": "invalid", "description": "Missing requirements"}],
    })

    result = validate_conventions(REPOSITORY, project)

    assert not result.ok
    assert any("requirements" in item.message for item in result.diagnostics)
    with pytest.raises(AgentKitError, match="conventions"):
        load_conventions(REPOSITORY, project)


@pytest.mark.parametrize("declared", ["../outside.yaml", "/tmp/outside.yaml", "C:\\outside.yaml", "..\\outside.yaml", ".ai-team/link.yaml"])
def test_project_convention_path_cannot_escape_root(tmp_path: Path, declared: str) -> None:
    project = _project(tmp_path / "project", [declared])
    project.root.mkdir()
    outside = tmp_path / "outside.yaml"
    write_yaml(outside, {"version": 1, "conventions": []})
    if declared == ".ai-team/link.yaml":
        link = project.root / declared
        link.parent.mkdir()
        link.symlink_to(outside)

    result = validate_conventions(REPOSITORY, project)

    assert not result.ok
    assert any("выходит за" in item.message or "абсолютный" in item.message.casefold() for item in result.diagnostics)


def test_project_cannot_replace_kit_convention_by_id(tmp_path: Path) -> None:
    project = _project(tmp_path, [".ai-team/conventions.yaml"])
    write_yaml(tmp_path / ".ai-team" / "conventions.yaml", {
        "version": 1,
        "conventions": [{"id": "documentation-ownership", "description": "Take over docs", "requirements": ["No review"]}],
    })

    result = validate_conventions(REPOSITORY, project)

    assert not result.ok
    assert any("documentation-ownership" in item.message for item in result.diagnostics)
