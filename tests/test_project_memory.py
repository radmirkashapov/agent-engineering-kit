from __future__ import annotations

import json
from pathlib import Path

from agent_engineering_kit.paths import KitPaths
from agent_engineering_kit.process import CommandResult
from agent_engineering_kit.project_memory import ProjectMemoryManager
from agent_engineering_kit.projects import LogicalProject


def _paths(tmp_path: Path, repository: Path) -> KitPaths:
    data = tmp_path / "data"
    return KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")


def _project(tmp_path: Path) -> LogicalProject:
    root = tmp_path / "workspace"
    root.mkdir()
    manifest = {
        "version": 1,
        "id": "platform",
        "repositories": [{"id": "root", "path": "."}],
        "memory": {"namespace": "platform"},
    }
    return LogicalProject(root, root / ".ai-team/project.yaml", manifest)


def test_full_index_runs_both_native_indexers_and_writes_report(tmp_path: Path) -> None:
    repository = tmp_path / "kit"
    project = _project(tmp_path)
    calls: list[list[str]] = []

    def runner(args: list[str], **_kwargs: object) -> CommandResult:
        calls.append(args)
        return CommandResult(tuple(args), 0, "indexed\n", "")

    report = ProjectMemoryManager(
        repository,
        _paths(tmp_path, repository),
        runner=runner,
        executables={"codebase-memory": Path("/tools/codebase-memory-mcp"), "serena": Path("/tools/serena")},
    ).index(project, mode="full")

    assert calls == [
        [
            "/tools/codebase-memory-mcp", "cli", "index_repository",
            "--repo-path", str(project.root), "--mode", "full", "--name", "platform--root",
        ],
        ["/tools/serena", "project", "index", str(project.root), "--name", "platform--root"],
    ]
    assert report["status"] == "PASS"
    stored = _paths(tmp_path, repository).projects / "platform/integrations/memory-index.json"
    assert json.loads(stored.read_text(encoding="utf-8"))["mode"] == "full"


def test_refresh_uses_fast_graph_index_and_fails_closed_on_indexer_error(tmp_path: Path) -> None:
    repository = tmp_path / "kit"
    project = _project(tmp_path)

    def runner(args: list[str], **_kwargs: object) -> CommandResult:
        code = 3 if Path(args[0]).name == "serena" else 0
        return CommandResult(tuple(args), code, "", "index failed" if code else "")

    report = ProjectMemoryManager(
        repository,
        _paths(tmp_path, repository),
        runner=runner,
        executables={"codebase-memory": Path("/tools/codebase-memory-mcp"), "serena": Path("/tools/serena")},
    ).index(project, mode="refresh")

    assert report["status"] == "FAIL"
    assert report["integrations"][0]["command"][6] == "fast"
    assert report["integrations"][1]["status"] == "FAIL"


def test_missing_indexers_are_reported_as_skipped(tmp_path: Path) -> None:
    repository = tmp_path / "kit"
    project = _project(tmp_path)

    report = ProjectMemoryManager(
        repository,
        _paths(tmp_path, repository),
        executables={},
    ).index(project, mode="full")

    assert report["status"] == "SKIPPED"
    assert {item["status"] for item in report["integrations"]} == {"SKIPPED"}
