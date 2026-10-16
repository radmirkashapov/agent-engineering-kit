"""Изолированное состояние задач и локальные аренды области записи."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
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


def task_workspace_path(paths: KitPaths, *, project_id: str, task_id: str) -> Path:
    """Вернуть путь task workspace после проверки идентификаторов."""
    _validate_identifier("project_id", project_id)
    _validate_identifier("task_id", task_id)
    return paths.projects / project_id / "tasks" / task_id / "task-workspace.json"


def _load_task_workspace(paths: KitPaths, *, project_id: str, task_id: str) -> tuple[Path, dict[str, Any]]:
    target = task_workspace_path(paths, project_id=project_id, task_id=task_id)
    if not target.is_file():
        raise AgentKitError(f"Task workspace не найден: {target}")
    try:
        document = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise AgentKitError(f"Task workspace повреждён: {target}: {error}") from error
    return target, document


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


def find_lease_conflicts(
    paths: KitPaths,
    *,
    project_id: str,
    task_id: str,
    write_set: list[str],
) -> list[dict[str, Any]]:
    """Найти активные локальные брони с пересекающимися областями записи."""
    directory = paths.projects / project_id / "leases"
    conflicts: list[dict[str, Any]] = []
    if not directory.is_dir():
        return conflicts
    for path in sorted(directory.glob("*.json")):
        current = json.loads(path.read_text(encoding="utf-8"))
        current_task = str(current.get("task_id", ""))
        if current_task == task_id:
            continue
        current_write_set = [str(item) for item in current.get("write_set", [])]
        overlap = [
            pattern
            for pattern in [*current_write_set, *write_set]
            if write_sets_overlap([pattern], write_set if pattern in current_write_set else current_write_set)
        ]
        if overlap:
            conflicts.append({"task_id": current_task, "overlap": list(dict.fromkeys(overlap))})
    return conflicts


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
    target = task_workspace_path(paths, project_id=project_id, task_id=task_id)
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
        "created_at": datetime.now(timezone.utc).isoformat(),
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
        except ImportError:  # pragma: no cover — в Windows используется атомарная замена.
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
        _, workspace = _load_task_workspace(paths, project_id=project_id, task_id=task_id)
        if workspace.get("status") in {"completed", "failed"}:
            raise AgentKitError(f"Task workspace {task_id} уже имеет terminal status={workspace.get('status')}")
        if list(workspace.get("write_set", [])) != write_set:
            raise AgentKitError(f"Write set lease не совпадает с task workspace {task_id}")
        conflicts = find_lease_conflicts(
            paths,
            project_id=project_id,
            task_id=task_id,
            write_set=write_set,
        )
        if conflicts:
            blockers = ", ".join(str(item["task_id"]) for item in conflicts)
            raise AgentKitError(f"Write set задачи {task_id} пересекается с активными задачами: {blockers}")
        atomic_write(
            target,
            json.dumps({"project_id": project_id, "task_id": task_id, "write_set": write_set}, ensure_ascii=False, indent=2) + "\n",
        )
    return target


def release_leases(paths: KitPaths, *, project_id: str, task_id: str) -> list[Path]:
    """Удалить leases только после завершения указанной задачи."""
    _, workspace = _load_task_workspace(paths, project_id=project_id, task_id=task_id)
    if workspace.get("status") != "completed":
        raise AgentKitError(f"Lease можно освободить только для task workspace со status=completed: {task_id}")
    directory = paths.projects / project_id / "leases"
    target = directory / f"{task_id}.json"
    with _lease_lock(directory):
        if not target.exists():
            return []
        target.unlink()
    return [target]


def complete_task_workspace(paths: KitPaths, *, project_id: str, task_id: str) -> Path:
    """Перевести workspace в terminal status=completed без удаления lease."""
    directory = paths.projects / project_id / "leases"
    with _lease_lock(directory):
        target, document = _load_task_workspace(paths, project_id=project_id, task_id=task_id)
        status = document.get("status")
        if status == "completed":
            return target
        if status == "failed":
            raise AgentKitError(f"Task workspace {task_id} уже завершён со status=failed")
        document["status"] = "completed"
        document["completed_at"] = datetime.now(timezone.utc).isoformat()
        atomic_write(target, json.dumps(document, ensure_ascii=False, indent=2) + "\n")
    return target


def garbage_collect_task_workspace(paths: KitPaths, *, project_id: str, task_id: str) -> list[Path]:
    """Удалить завершённый state, если lease и managed worktree уже отсутствуют."""
    target, document = _load_task_workspace(paths, project_id=project_id, task_id=task_id)
    if document.get("status") != "completed":
        raise AgentKitError(f"GC разрешён только для task workspace со status=completed: {task_id}")
    lease = paths.projects / project_id / "leases" / f"{task_id}.json"
    if lease.exists():
        raise AgentKitError(f"GC запрещён, пока активен lease задачи {task_id}")
    existing_worktrees = [
        Path(str(item.get("target", "")))
        for item in document.get("worktrees", [])
        if item.get("target") and Path(str(item["target"])).exists()
    ]
    if existing_worktrees:
        raise AgentKitError(
            "GC запрещён, пока существуют managed worktree: "
            + ", ".join(str(path) for path in existing_worktrees)
        )
    directory = target.parent
    unexpected = [path for path in directory.iterdir() if path != target]
    if unexpected:
        raise AgentKitError(
            "GC не удаляет каталог с неизвестными файлами: "
            + ", ".join(str(path) for path in unexpected)
        )
    target.unlink()
    directory.rmdir()
    return [target]
