"""Воспроизводимые контракты между управляющим слоем и внешней средой выполнения."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import AgentKitError
from .io import atomic_write
from .paths import KitPaths
from .redaction import redact


_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_RESULT_STATUSES = frozenset({"passed", "failed", "blocked", "cancelled"})


def canonical_digest(value: object) -> str:
    """Вычислить стабильный SHA-256 JSON-документа."""
    serialized = json.dumps(redact(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def build_run_request(
    *,
    kit_revision: str,
    project_id: str | None,
    policy: dict[str, Any],
    conventions: dict[str, Any],
    harness: dict[str, Any],
    roles: list[dict[str, Any]],
    skills: list[dict[str, Any]],
    mcp: list[dict[str, Any]],
    requested_model: str | None,
    permissions: dict[str, Any],
    repositories: list[dict[str, Any]],
    verification_steps: list[str],
    bypasses: list[dict[str, Any]],
    run_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Собрать request manifest без фактических результатов выполнения."""
    safe_policy = redact(policy)
    safe_conventions = redact(conventions)
    safe_repositories = redact(repositories)
    return {
        "schema": "agent-engineering-kit/run-manifest/v1",
        "phase": "request",
        "run_id": run_id or str(uuid.uuid4()),
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        "kit_revision": kit_revision,
        "project_id": project_id,
        "policy_sha256": canonical_digest(safe_policy),
        "conventions_sha256": canonical_digest(safe_conventions),
        "harness": redact(harness),
        "roles": redact(roles),
        "skills": redact(skills),
        "mcp": redact(mcp),
        "requested_model": requested_model,
        "permissions": redact(permissions),
        "repositories": safe_repositories,
        "repository_revision_vector": {
            str(item["id"]): str(item["commit"])
            for item in safe_repositories
            if isinstance(item, dict) and item.get("id") and item.get("commit")
        },
        "verification_steps": list(verification_steps),
        "bypasses": redact(bypasses),
    }


def _run_directory(paths: KitPaths, project_id: str | None, run_id: str) -> Path:
    if not _SAFE_IDENTIFIER.fullmatch(run_id):
        raise AgentKitError(f"Некорректный run_id: {run_id!r}")
    if project_id is not None and not _SAFE_IDENTIFIER.fullmatch(project_id):
        raise AgentKitError(f"Некорректный project_id: {project_id!r}")
    namespace = project_id or "_global"
    return paths.projects / namespace / "runs" / run_id


def run_events_path(paths: KitPaths, *, project_id: str | None, run_id: str) -> Path:
    """Вернуть безопасный путь append-only журнала запуска."""
    return _run_directory(paths, project_id, run_id) / "events.jsonl"


def write_run_request(paths: KitPaths, manifest: dict[str, Any]) -> Path:
    """Атомарно сохранить request manifest в памяти проекта."""
    if manifest.get("phase") != "request" or not manifest.get("run_id"):
        raise AgentKitError("Run request должен содержать phase=request и run_id")
    target = _run_directory(paths, manifest.get("project_id"), str(manifest["run_id"])) / "request.json"
    if target.exists():
        raise AgentKitError(f"Run request уже существует: {target}")
    atomic_write(target, json.dumps(redact(manifest), ensure_ascii=False, indent=2) + "\n")
    return target


def record_run_result(
    paths: KitPaths,
    *,
    project_id: str | None,
    run_id: str,
    status: str,
    actual_model: str | None,
    verification: list[dict[str, Any]],
    details: dict[str, Any],
    recorded_at: str | None = None,
) -> Path:
    """Сохранить фактический результат отдельно от неизменяемого request."""
    if status not in _RESULT_STATUSES:
        raise AgentKitError(f"Некорректный status результата запуска: {status!r}")
    run_directory = _run_directory(paths, project_id, run_id)
    request = run_directory / "request.json"
    if not request.is_file():
        raise AgentKitError(f"Run request не найден: {request}")
    result = {
        "schema": "agent-engineering-kit/run-manifest/v1",
        "phase": "result",
        "run_id": run_id,
        "project_id": project_id,
        "recorded_at": recorded_at or datetime.now(timezone.utc).isoformat(),
        "request": request.name,
        "status": status,
        "actual_model": actual_model,
        "verification": redact(verification),
        "details": redact(details, redact_result_fields=True),
    }
    target = run_directory / "result.json"
    atomic_write(target, json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return target
