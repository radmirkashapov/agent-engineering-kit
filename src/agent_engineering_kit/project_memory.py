"""Индексация logical project в нативных хранилищах MCP."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from .io import atomic_write
from .paths import KitPaths, ensure_runtime
from .process import CommandResult, run_command

if TYPE_CHECKING:
    from .projects import LogicalProject


Runner = Callable[..., CommandResult]


class ProjectMemoryManager:
    """Оркестрировать индексы, не присваивая их native state."""

    def __init__(
        self,
        repository: Path,
        paths: KitPaths,
        *,
        runner: Runner = run_command,
        executables: dict[str, Path] | None = None,
    ) -> None:
        self.repository = repository
        self.paths = paths
        self.runner = runner
        self._executables = executables

    def _resolve_executables(self, project: LogicalProject) -> dict[str, Path]:
        if self._executables is not None:
            return dict(self._executables)
        # Local import keeps MCP manager free to type projects without an import cycle.
        from .mcp_manager import McpManager

        manager = McpManager(self.repository, self.paths, runner=self.runner)
        resolved: dict[str, Path] = {}
        for item in manager.available(project):
            if item["id"] not in {"codebase-memory", "serena"} or not item["enabled"]:
                continue
            executable = manager.executable(item)
            if executable:
                resolved[item["id"]] = executable
        return resolved

    def _repositories(self, project: LogicalProject) -> dict[str, Path]:
        # Local import breaks the projects <-> bindings initialization cycle.
        from .bindings import repository_paths

        return repository_paths(project, self.paths)

    def index(self, project: LogicalProject, *, mode: str) -> dict[str, Any]:
        if mode not in {"full", "refresh"}:
            raise ValueError(f"Неизвестный режим индексации: {mode}")
        ensure_runtime(self.paths)
        executables = self._resolve_executables(project)
        integrations: list[dict[str, Any]] = []
        graph_mode = "full" if mode == "full" else "fast"
        repositories = self._repositories(project)
        for repository_id, root in sorted(repositories.items()):
            name = f"{project.identifier}--{repository_id}"
            commands: list[tuple[str, list[str]]] = []
            if executable := executables.get("codebase-memory"):
                commands.append((
                    "codebase-memory",
                    [
                        str(executable), "cli", "index_repository",
                        "--repo-path", str(root), "--mode", graph_mode, "--name", name,
                    ],
                ))
            else:
                integrations.append({
                    "id": "codebase-memory",
                    "repository": repository_id,
                    "status": "SKIPPED",
                    "reason": "MCP отключён или executable недоступен",
                })
            if executable := executables.get("serena"):
                commands.append((
                    "serena",
                    [str(executable), "project", "index", str(root), "--name", name],
                ))
            else:
                integrations.append({
                    "id": "serena",
                    "repository": repository_id,
                    "status": "SKIPPED",
                    "reason": "MCP отключён или executable недоступен",
                })
            for identifier, command in commands:
                completed = self.runner(command, cwd=root)
                integrations.append({
                    "id": identifier,
                    "repository": repository_id,
                    "status": "PASS" if completed.ok else "FAIL",
                    "exit_code": completed.returncode,
                    "command": command,
                    "output": (completed.stdout + completed.stderr)[-4000:],
                })
        statuses = {item["status"] for item in integrations}
        status = "FAIL" if "FAIL" in statuses else ("PASS" if "PASS" in statuses else "SKIPPED")
        report = {
            "version": 1,
            "project_id": project.identifier,
            "mode": mode,
            "status": status,
            "integrations": integrations,
        }
        target = self.paths.projects / project.identifier / "integrations" / "memory-index.json"
        atomic_write(target, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        return report
