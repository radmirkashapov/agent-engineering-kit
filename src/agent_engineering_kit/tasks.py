"""Изолированное состояние задач и локальные leases на область записи."""

from __future__ import annotations

import json
import os
import re
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any, Iterator

from .errors import AgentKitError
from .io import atomic_write
from .paths import KitPaths


_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$")


def _validate_identifier(label: str, value: str) -> None:
    if not _ID_PATTERN.fullmatch(value):
        raise AgentKitError(f"Некорректный {label}: {value!r}")


def _pattern_root(pattern: str) -> tuple[str, ...]:
    pure = PurePosixPath(pattern.replace("\\", "/"))
    if pure.is_absolute() or ".." in pure.parts:
        raise AgentKitError(f"Write set содержит небезопасный путь: {pattern}")
    root: list[str] = []
    for part in pure.parts:
        if any(marker in part for marker in "*?["):
            break
        root.append(part)
    return tuple(root)


def write_sets_overlap(left: list[str], right: list[str]) -> bool:
    """Консервативно определить пересечение двух наборов путей/glob."""
    for left_pattern in left:
        left_root = _pattern_root(left_pattern)
        for right_pattern in right:
            right_root = _pattern_root(right_pattern)
            common = min(len(left_root), len(right_root))
            if left_root[:common] == right_root[:common]:
                return True
    return False


def create_task_workspace(
    paths: KitPaths,
    *,
    project_id: str,
    task_id: str,
    repositories: list[dict[str, Any]],
    write_set: list[str],
    policy_digest: str,
    conventions_digest: str,
) -> Path:
    """Создать immutable planning snapshot без изменения checkout."""
    _validate_identifier("project_id", project_id)
    _validate_identifier("task_id", task_id)
    for pattern in write_set:
        _pattern_root(pattern)
    revision_vector: dict[str, str] = {}
    safe_repositories: list[dict[str, str]] = []
    for item in repositories:
        identifier = str(item.get("id", ""))
        commit = str(item.get("commit", ""))
        repository_path = Path(str(item.get("path", ""))).expanduser().resolve()
        _validate_identifier("repository ID", identifier)
        if not commit:
            raise AgentKitError(f"Repository {identifier} не содержит base commit")
        if identifier in revision_vector:
            raise AgentKitError(f"Повторяющийся repository ID: {identifier}")
        revision_vector[identifier] = commit
        safe_repositories.append({"id": identifier, "path": str(repository_path), "commit": commit})
    target = paths.projects / project_id / "tasks" / task_id / "task-workspace.json"
    if target.exists():
        raise AgentKitError(f"Task workspace уже существует: {target}")
    document = {
        "schema": "agent-engineering-kit/task-workspace/v1",
        "project_id": project_id,
        "task_id": task_id,
        "status": "planned",
        "repositories": safe_repositories,
        "repository_revision_vector": revision_vector,
        "write_set": list(write_set),
        "policy_digest": policy_digest,
        "conventions_digest": conventions_digest,
        "worktrees": [],
    }
    atomic_write(target, json.dumps(document, ensure_ascii=False, indent=2) + "\n")
    return target


@contextmanager
def _lease_lock(directory: Path) -> Iterator[None]:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ".lock"
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_EX)
        except ImportError:  # pragma: no cover - Windows uses atomic replacement below.
            pass
        yield
    finally:
        try:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_UN)
        except ImportError:  # pragma: no cover
            pass
        os.close(descriptor)


def acquire_lease(
    paths: KitPaths,
    *,
    project_id: str,
    task_id: str,
    write_set: list[str],
) -> Path:
    """Получить machine-local lease, отклонив пересекающуюся запись."""
    _validate_identifier("project_id", project_id)
    _validate_identifier("task_id", task_id)
    directory = paths.projects / project_id / "leases"
    target = directory / f"{task_id}.json"
    with _lease_lock(directory):
        for path in sorted(directory.glob("*.json")):
            current = json.loads(path.read_text(encoding="utf-8"))
            if current.get("task_id") == task_id:
                continue
            if write_sets_overlap(write_set, list(current.get("write_set", []))):
                raise AgentKitError(
                    f"Write set задачи {task_id} пересекается с активной задачей {current.get('task_id')}"
                )
        atomic_write(
            target,
            json.dumps({"project_id": project_id, "task_id": task_id, "write_set": write_set}, ensure_ascii=False, indent=2) + "\n",
        )
    return target


def release_leases(paths: KitPaths, *, project_id: str, task_id: str) -> list[Path]:
    """Удалить только leases указанной задачи."""
    directory = paths.projects / project_id / "leases"
    target = directory / f"{task_id}.json"
    with _lease_lock(directory):
        if not target.exists():
            return []
        target.unlink()
    return [target]
