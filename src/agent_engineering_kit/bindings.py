"""Machine-local repository bindings and component inventory reconciliation."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

from .discovery import discover_components
from .errors import AgentKitError
from .io import atomic_write, load_yaml
from .paths import KitPaths
from .projects import LogicalProject, register_memory, slugify
from .schema import validate_instance


def _descriptor_path(paths: KitPaths, identifier: str) -> Path:
    return paths.projects / identifier / "project.yaml"


def load_attached_project(identifier: str, paths: KitPaths) -> LogicalProject | None:
    path = _descriptor_path(paths, identifier)
    if not path.is_file():
        return None
    manifest = load_yaml(path)
    bindings = _bindings_path(paths, identifier)
    root = paths.projects / identifier
    if bindings.is_file():
        entries = load_yaml(bindings).get("repositories", [])
        root_entry = next((entry for entry in entries if entry.get("id") == "root"), None)
        if root_entry:
            root = Path(root_entry["path"])
    return LogicalProject(root.resolve(), path, manifest)


def _bindings_path(paths: KitPaths, identifier: str) -> Path:
    return paths.projects / identifier / "bindings.yaml"


def _bindings(project: LogicalProject, paths: KitPaths) -> dict[str, Any]:
    path = _bindings_path(paths, project.identifier)
    if path.is_file():
        data = load_yaml(path)
        result = validate_instance(data, paths.repository / "schemas" / "project-bindings.schema.json", str(path))
        if not result.ok or data.get("project_id") != project.identifier:
            raise AgentKitError("Некорректные local repository bindings")
        return data
    return {"version": 1, "project_id": project.identifier, "repositories": []}


def _save_bindings(project: LogicalProject, paths: KitPaths, data: dict[str, Any]) -> Path:
    path = _bindings_path(paths, project.identifier)
    result = validate_instance(data, paths.repository / "schemas" / "project-bindings.schema.json", str(path))
    if not result.ok:
        raise AgentKitError("Некорректные local repository bindings")
    atomic_write(path, "# Локальные пути репозиториев этой машины; файл не добавляется в Git.\n" + yaml.safe_dump(data, allow_unicode=True, sort_keys=False))
    return path


def bind_repository(project: LogicalProject, paths: KitPaths, repository_id: str, path: Path) -> Path:
    if repository_id not in {item["id"] for item in project.manifest["repositories"]}:
        raise AgentKitError(f"Repository ID не объявлен в manifest: {repository_id}")
    target = path.expanduser().resolve()
    if not target.is_dir():
        raise AgentKitError(f"Repository path не существует: {target}")
    register_memory(project, paths)
    data = _bindings(project, paths)
    data["repositories"] = sorted([entry for entry in data["repositories"] if entry["id"] != repository_id] + [{"id": repository_id, "path": str(target)}], key=lambda item: item["id"])
    return _save_bindings(project, paths, data)


def attach_project(root: Path, repository: Path, paths: KitPaths, *, identifier: str | None = None) -> LogicalProject:
    """Attach a repository without changing files inside it."""
    root = root.expanduser().resolve()
    if not root.is_dir():
        raise AgentKitError(f"Repository path не существует: {root}")
    project_id = slugify(identifier or root.name)
    path = _descriptor_path(paths, project_id)
    if path.is_file():
        existing = load_attached_project(project_id, paths)
        if existing and existing.root != root:
            raise AgentKitError(f"Collision project.id={project_id!r}: local descriptor уже принадлежит другому root")
        return existing  # type: ignore[return-value]
    manifest: dict[str, Any] = {
        "version": 1,
        "id": project_id,
        "name": root.name,
        "repositories": [{"id": "root", "path": ".", "required": True}],
        "components": [],
        "documentation": {"index": "docs/INDEX.md", "roots": ["docs"]},
        "memory": {"namespace": project_id},
    }
    check = validate_instance(manifest, repository / "schemas" / "project.schema.json", str(path))
    if not check.ok:
        raise AgentKitError("Некорректный local project descriptor")
    project = LogicalProject(root, path, manifest)
    register_memory(project, paths)
    atomic_write(path, "# Локальный descriptor логического проекта; исходный репозиторий не изменяется.\n" + yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False))
    bind_repository(project, paths, "root", root)
    return project


def _remote_matches(root: Path, expected: str) -> bool:
    parsed = urlsplit(expected)
    if parsed.username or parsed.password:
        return False
    result = subprocess.run(["git", "-C", str(root), "config", "--get", "remote.origin.url"], capture_output=True, text=True, check=False)
    actual = result.stdout.strip() if result.returncode == 0 else ""
    return actual == expected


def repository_paths(project: LogicalProject, paths: KitPaths) -> dict[str, Path]:
    bound = {entry["id"]: Path(entry["path"]).expanduser().resolve() for entry in _bindings(project, paths)["repositories"]}
    repositories: dict[str, Path] = {}
    local_descriptor = project.manifest_path == _descriptor_path(paths, project.identifier)
    for entry in project.manifest["repositories"]:
        if entry["id"] in bound:
            repositories[entry["id"]] = bound[entry["id"]]
        elif not local_descriptor:
            candidate = (project.root / entry["path"]).resolve()
            try:
                candidate.relative_to(project.root)
            except ValueError as error:
                raise AgentKitError(f"Repository выходит за logical project root: {entry['path']}") from error
            repositories[entry["id"]] = candidate
    return repositories


def project_readiness(project: LogicalProject, paths: KitPaths) -> dict[str, Any]:
    locations = repository_paths(project, paths)
    issues: list[dict[str, str]] = []
    for entry in project.manifest["repositories"]:
        identifier = entry["id"]
        path = locations.get(identifier)
        if path is None or not path.is_dir():
            issues.append({"repository": identifier, "reason": "missing", "severity": "required" if entry.get("required", True) else "optional"})
        elif entry.get("remote") and not _remote_matches(path, entry["remote"]):
            issues.append({"repository": identifier, "reason": "remote-mismatch", "severity": "required" if entry.get("required", True) else "optional"})
    if any(item["reason"] == "remote-mismatch" for item in issues):
        status = "MISMATCHED"
    elif any(item["severity"] == "required" for item in issues):
        status = "BLOCKED"
    elif issues:
        status = "DEGRADED"
    else:
        status = "READY"
    return {"status": status, "issues": issues, "repositories": {key: str(value) for key, value in sorted(locations.items())}}


def reconcile_project(project: LogicalProject, paths: KitPaths, *, apply: bool = False) -> dict[str, Any]:
    readiness = project_readiness(project, paths)
    locations = repository_paths(project, paths)
    available = {key: path for key, path in locations.items() if path.is_dir() and not any(issue["repository"] == key for issue in readiness["issues"])}
    inventory_path = paths.projects / project.identifier / "state" / "component-inventory.json"
    previous = json.loads(inventory_path.read_text(encoding="utf-8"))["components"] if inventory_path.is_file() else []
    settings = project.manifest.get("discovery", {})
    if settings.get("enabled", True):
        current = discover_components(available, exclude_paths=settings.get("exclude_paths", []))
        unavailable = {item["repository"] for item in readiness["issues"]}
        current.extend(item for item in previous if item["repository"] in unavailable and item["id"] not in {row["id"] for row in current})
    else:
        current = previous
    before = {item["id"]: item for item in previous}
    after = {item["id"]: item for item in current}
    diff = {
        "added": [after[key] for key in sorted(after.keys() - before.keys())],
        "removed": [before[key] for key in sorted(before.keys() - after.keys())],
        "changed": [{"before": before[key], "after": after[key]} for key in sorted(before.keys() & after.keys()) if before[key] != after[key]],
    }
    if apply:
        if readiness["status"] in {"BLOCKED", "MISMATCHED"}:
            raise AgentKitError(f"Inventory не обновлён: project status {readiness['status']}")
        register_memory(project, paths)
        inventory = {"version": 1, "project_id": project.identifier, "components": current}
        validation = validate_instance(inventory, paths.repository / "schemas" / "component-inventory.schema.json", str(inventory_path))
        if not validation.ok:
            raise AgentKitError("Некорректный component inventory")
        atomic_write(inventory_path, json.dumps(inventory, ensure_ascii=False, indent=2) + "\n")
    return {**readiness, "diff": diff, "workspace_structure_change": any(diff.values()), "applied": apply}
