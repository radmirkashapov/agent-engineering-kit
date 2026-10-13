"""Планирование и создание рабочих деревьев в управляемом состоянии проекта."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .errors import AgentKitError
from .io import atomic_write
from .paths import KitPaths
from .process import run_command


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-")


def _git(repository: Path, *arguments: str) -> str:
    result = run_command(["git", "-C", str(repository), *arguments])
    if not result.ok:
        raise AgentKitError(result.stderr.strip() or f"Git command завершилась с кодом {result.returncode}")
    return result.stdout.strip()


def plan_managed_worktrees(paths: KitPaths, task_path: Path, *, branch_prefix: str) -> list[dict[str, Any]]:
    """Построить план без создания веток и каталогов."""
    document = json.loads(task_path.read_text(encoding="utf-8"))
    project_id = str(document["project_id"])
    task_id = str(document["task_id"])
    managed_root = (paths.projects / project_id / "worktrees" / task_id).resolve()
    plans: list[dict[str, Any]] = []
    for repository in document.get("repositories", []):
        identifier = str(repository["id"])
        source = Path(str(repository["path"])).resolve()
        if not source.is_dir() or _git(source, "rev-parse", "--is-inside-work-tree") != "true":
            raise AgentKitError(f"Git repository не найден для {identifier}: {source}")
        commit = str(repository["commit"])
        _git(source, "cat-file", "-e", f"{commit}^{{commit}}")
        target = (managed_root / _slug(identifier)).resolve()
        try:
            target.relative_to(managed_root)
        except ValueError as error:
            raise AgentKitError(f"Worktree выходит за managed root: {target}") from error
        plans.append(
            {
                "repository": identifier,
                "source": str(source),
                "commit": commit,
                "target": str(target),
                "branch": f"{branch_prefix}-{_slug(identifier)}",
            }
        )
    return plans


def create_managed_worktrees(
    paths: KitPaths,
    task_path: Path,
    plans: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Создать worktree по предварительно проверенному плану и обновить task state."""
    document = json.loads(task_path.read_text(encoding="utf-8"))
    project_id = str(document["project_id"])
    task_id = str(document["task_id"])
    managed_root = (paths.projects / project_id / "worktrees" / task_id).resolve()
    created: list[dict[str, Any]] = []
    for plan in plans:
        source = Path(str(plan["source"])).resolve()
        target = Path(str(plan["target"])).resolve()
        try:
            target.relative_to(managed_root)
        except ValueError as error:
            raise AgentKitError(f"Worktree выходит за managed root: {target}") from error
        if target.exists():
            raise AgentKitError(f"Worktree target уже существует: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        result = run_command(
            ["git", "-C", str(source), "worktree", "add", "-b", str(plan["branch"]), str(target), str(plan["commit"])]
        )
        if not result.ok:
            raise AgentKitError(result.stderr.strip() or f"Не удалось создать worktree {target}")
        created.append(dict(plan))
    document["status"] = "active"
    document["worktrees"] = created
    atomic_write(task_path, json.dumps(document, ensure_ascii=False, indent=2) + "\n")
    return created
