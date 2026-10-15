"""Высокоуровневый workflow задачи поверх task state, брони и Git worktree."""

from __future__ import annotations

import json
import re
import shlex
from datetime import date
from pathlib import Path
from typing import Any

from .errors import AgentKitError
from .io import atomic_write
from .paths import KitPaths
from .process import run_command
from .tasks import acquire_lease, create_task_workspace, find_lease_conflicts, task_workspace_path, write_sets_overlap
from .worktrees import create_managed_worktrees, plan_managed_worktrees


_BRANCH_TYPES = {"feat", "fix", "refactor", "docs", "test", "chore", "ci", "style", "ai"}


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def build_branch_name(task_id: str, summary: str | None, branch_type: str, today: date) -> str:
    """Сформировать имя ветки по правилам Kit."""
    if branch_type not in _BRANCH_TYPES:
        raise AgentKitError(f"Недопустимый тип ветки: {branch_type}")
    normalized_task = _slug(task_id)
    if not normalized_task:
        raise AgentKitError("Task ID не содержит допустимых символов для имени ветки")
    parts = [f"{branch_type}/{today:%d-%m-%Y}", normalized_task]
    normalized_summary = _slug(summary or "")
    if normalized_summary:
        parts.append(normalized_summary)
    return "-".join(parts)


def _next_workspace_id(paths: KitPaths, project_id: str, task_id: str) -> str:
    if not task_workspace_path(paths, project_id=project_id, task_id=task_id).exists():
        return task_id
    counter = 2
    while task_workspace_path(paths, project_id=project_id, task_id=f"{task_id}-copy-{counter}").exists():
        counter += 1
    return f"{task_id}-copy-{counter}"


def create_task_workflow(
    paths: KitPaths,
    *,
    project_id: str,
    task_id: str,
    repositories: list[dict[str, Any]],
    write_set: list[str],
    policy_digest: str,
    conventions_digest: str,
    branch_type: str,
    summary: str | None,
    today: date | None = None,
) -> dict[str, Any]:
    """Создать task state, локальную бронь и worktree одним проверяемым workflow."""
    effective_date = today or date.today()
    workspace_id = _next_workspace_id(paths, project_id, task_id)
    target = create_task_workspace(
        paths,
        project_id=project_id,
        task_id=workspace_id,
        repositories=repositories,
        write_set=write_set,
        policy_digest=policy_digest,
        conventions_digest=conventions_digest,
    )
    conflicts = find_lease_conflicts(
        paths,
        project_id=project_id,
        task_id=workspace_id,
        write_set=write_set,
    )
    if not conflicts:
        acquire_lease(paths, project_id=project_id, task_id=workspace_id, write_set=write_set)
    branch = build_branch_name(task_id, summary, branch_type, effective_date)
    plans = plan_managed_worktrees(
        paths,
        target,
        branch_prefix=branch,
        append_repository=len(repositories) > 1,
        copy_existing_branch=True,
    )
    worktrees = create_managed_worktrees(paths, target, plans)
    document = json.loads(target.read_text(encoding="utf-8"))
    document["requested_task_id"] = task_id
    document["branch_type"] = branch_type
    document["summary"] = summary
    if conflicts:
        document["status"] = "waiting"
        document["blocked_by"] = conflicts
    atomic_write(target, json.dumps(document, ensure_ascii=False, indent=2) + "\n")
    return {
        "project_id": project_id,
        "task_id": workspace_id,
        "requested_task_id": task_id,
        "status": str(document["status"]),
        "blocked_by": conflicts,
        "task_path": str(target),
        "worktrees": worktrees,
    }


def task_workflow_status(paths: KitPaths, *, project_id: str, task_id: str) -> dict[str, Any]:
    """Показать состояние задачи и возможность безопасного повтора."""
    target = task_workspace_path(paths, project_id=project_id, task_id=task_id)
    if not target.is_file():
        raise AgentKitError(f"Task workspace не найден: {target}")
    document = json.loads(target.read_text(encoding="utf-8"))
    conflicts = find_lease_conflicts(
        paths,
        project_id=project_id,
        task_id=task_id,
        write_set=[str(item) for item in document.get("write_set", [])],
    )
    return {
        **document,
        "task_path": str(target),
        "blocked_by": conflicts,
        "ready_to_retry": document.get("status") == "waiting" and not conflicts,
    }


def retry_task_workflow(paths: KitPaths, *, project_id: str, task_id: str) -> dict[str, Any]:
    """Повторить только незавершённое получение локальной брони."""
    status = task_workflow_status(paths, project_id=project_id, task_id=task_id)
    if status["status"] != "waiting" or status["blocked_by"]:
        return status
    acquire_lease(
        paths,
        project_id=project_id,
        task_id=task_id,
        write_set=[str(item) for item in status.get("write_set", [])],
    )
    target = Path(str(status["task_path"]))
    document = json.loads(target.read_text(encoding="utf-8"))
    document["status"] = "active"
    document.pop("blocked_by", None)
    _advance_waiting_lanes(list(document.get("lanes", [])), parent_active=True)
    atomic_write(target, json.dumps(document, ensure_ascii=False, indent=2) + "\n")
    return task_workflow_status(paths, project_id=project_id, task_id=task_id)


def _run_git(repository: Path, *arguments: str) -> str:
    result = run_command(["git", "-C", str(repository), *arguments])
    if not result.ok:
        raise AgentKitError(result.stderr.strip() or "Git command завершилась с ошибкой")
    return result.stdout.strip()


def _unique_lane_branch(repository: Path, requested: str) -> str:
    candidate = requested
    counter = 2
    while run_command(
        ["git", "-C", str(repository), "show-ref", "--verify", "--quiet", f"refs/heads/{candidate}"]
    ).ok:
        candidate = f"{requested}-copy-{counter}"
        counter += 1
    return candidate


def _advance_waiting_lanes(lanes: list[dict[str, Any]], *, parent_active: bool) -> None:
    """Активировать ожидающие lanes по порядку, если родительская задача получила lease."""
    if not parent_active:
        return
    active = [item for item in lanes if item.get("status") == "active"]
    for waiting in lanes:
        if waiting.get("status") != "waiting":
            continue
        blockers = [
            str(item["id"])
            for item in active
            if write_sets_overlap(
                [str(pattern) for pattern in waiting.get("write_set", [])],
                [str(pattern) for pattern in item.get("write_set", [])],
            )
        ]
        waiting["blocked_by"] = blockers
        if not blockers:
            waiting["status"] = "active"
            active.append(waiting)


def create_task_lane(
    paths: KitPaths,
    *,
    project_id: str,
    task_id: str,
    lane_id: str,
    write_set: list[str],
    today: date | None = None,
) -> dict[str, Any]:
    """Создать дочернюю agent-ветку и worktree с локальной очередью общих файлов."""
    target = task_workspace_path(paths, project_id=project_id, task_id=task_id)
    if not target.is_file():
        raise AgentKitError(f"Task workspace не найден: {target}")
    document = json.loads(target.read_text(encoding="utf-8"))
    lanes = list(document.get("lanes", []))
    if any(item.get("id") == lane_id for item in lanes):
        raise AgentKitError(f"Lane уже существует: {lane_id}")
    if document.get("status") == "waiting":
        blocked_by = [
            f"task:{item['task_id']}"
            for item in document.get("blocked_by", [])
            if isinstance(item, dict) and item.get("task_id")
        ]
    else:
        blocked_by = [
            str(item["id"])
            for item in lanes
            if item.get("status") == "active"
            and write_sets_overlap(write_set, [str(pattern) for pattern in item.get("write_set", [])])
        ]
    lane_status = "waiting" if blocked_by else "active"
    lane_worktrees: list[dict[str, Any]] = []
    effective_date = today or date.today()
    requested = f"agent/{effective_date:%d-%m-%Y}-{_slug(str(document.get('requested_task_id', task_id)))}-{_slug(lane_id)}"
    for task_worktree in document.get("worktrees", []):
        source = Path(str(task_worktree["source"]))
        integration_branch = str(task_worktree["branch"])
        branch = _unique_lane_branch(source, requested)
        base_commit = _run_git(source, "rev-parse", integration_branch)
        lane_target = (
            paths.projects / project_id / "worktrees" / task_id / "lanes" / _slug(lane_id) / str(task_worktree["repository"])
        ).resolve()
        lane_target.parent.mkdir(parents=True, exist_ok=True)
        if lane_target.exists():
            raise AgentKitError(f"Lane worktree уже существует: {lane_target}")
        created = run_command(
            ["git", "-C", str(source), "worktree", "add", "-b", branch, str(lane_target), integration_branch]
        )
        if not created.ok:
            raise AgentKitError(created.stderr.strip() or f"Не удалось создать lane worktree {lane_target}")
        lane_worktrees.append(
            {
                "repository": str(task_worktree["repository"]),
                "source": str(source),
                "target": str(lane_target),
                "branch": branch,
                "integration_branch": integration_branch,
                "base_commit": base_commit,
            }
        )
    lane = {
        "id": lane_id,
        "status": lane_status,
        "write_set": write_set,
        "blocked_by": blocked_by,
        "worktrees": lane_worktrees,
    }
    lanes.append(lane)
    document["lanes"] = lanes
    atomic_write(target, json.dumps(document, ensure_ascii=False, indent=2) + "\n")
    return lane


def integration_plan(
    paths: KitPaths,
    *,
    project_id: str,
    task_id: str,
    lane_id: str,
) -> dict[str, Any]:
    """Проверить lane и вывести Git-команды, не выполняя merge."""
    status = task_workflow_status(paths, project_id=project_id, task_id=task_id)
    lane = next((item for item in status.get("lanes", []) if item.get("id") == lane_id), None)
    if lane is None:
        raise AgentKitError(f"Lane не найден: {lane_id}")
    if lane.get("status") != "active":
        raise AgentKitError(f"Lane {lane_id} ожидает: {', '.join(lane.get('blocked_by', []))}")
    integration_targets = {
        str(worktree["repository"]): str(worktree["target"])
        for worktree in status.get("worktrees", [])
    }
    commands = [
        "git -C {target} merge --no-ff {branch}".format(
            target=shlex.quote(integration_targets[str(worktree["repository"])]),
            branch=shlex.quote(str(worktree["branch"])),
        )
        for worktree in lane.get("worktrees", [])
    ]
    return {"performs_merge": False, "lane_id": lane_id, "commands": commands}


def complete_task_lane(
    paths: KitPaths,
    *,
    project_id: str,
    task_id: str,
    lane_id: str,
) -> dict[str, Any]:
    """Подтвердить внешний Git merge и передать очередь следующим lanes."""
    target = task_workspace_path(paths, project_id=project_id, task_id=task_id)
    if not target.is_file():
        raise AgentKitError(f"Task workspace не найден: {target}")
    document = json.loads(target.read_text(encoding="utf-8"))
    lanes = list(document.get("lanes", []))
    lane = next((item for item in lanes if item.get("id") == lane_id), None)
    if lane is None:
        raise AgentKitError(f"Lane не найден: {lane_id}")
    for worktree in lane.get("worktrees", []):
        verified = run_command(
            [
                "git",
                "-C",
                str(worktree["source"]),
                "merge-base",
                "--is-ancestor",
                str(worktree["branch"]),
                str(worktree["integration_branch"]),
            ]
        )
        if not verified.ok:
            raise AgentKitError(
                f"Lane {lane_id} ещё не интегрирована в {worktree['integration_branch']}; выполните Git merge"
            )
    lane["status"] = "completed"
    lane["blocked_by"] = []
    _advance_waiting_lanes(lanes, parent_active=document.get("status") == "active")
    document["lanes"] = lanes
    atomic_write(target, json.dumps(document, ensure_ascii=False, indent=2) + "\n")
    return dict(lane)
