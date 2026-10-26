"""Обнаружение, инициализация и состояние логического проекта."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .errors import AgentKitError
from .harness import resolve_harness
from .io import atomic_write, load_yaml
from .paths import KitPaths, ensure_runtime
from .process import run_command
from .project_memory import ProjectMemoryManager
from .project_templates import apply_project_template, load_project_templates, resolve_project_template
from .result import ValidationResult
from .schema import validate_instance


@dataclass(frozen=True)
class LogicalProject:
    root: Path
    manifest_path: Path
    manifest: dict[str, Any]

    @property
    def identifier(self) -> str:
        return str(self.manifest["id"])

    @property
    def skills_repository(self) -> dict[str, str] | None:
        value = self.manifest.get("skills", {}).get("repository")
        return dict(value) if isinstance(value, dict) else None


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "project"


def find_project(start: Path) -> LogicalProject | None:
    current = start.expanduser().resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        manifest = candidate / ".ai-team" / "project.yaml"
        if manifest.is_file():
            return LogicalProject(candidate, manifest, load_yaml(manifest))
    return None


def validate_project_definition(project: LogicalProject, repository: Path) -> ValidationResult:
    """Проверить переносимый manifest без требований к локальной полноте workspace."""
    result = validate_instance(project.manifest, repository / "schemas" / "project.schema.json", str(project.manifest_path))
    if project.manifest.get("memory", {}).get("namespace") != project.manifest.get("id"):
        result.error("projects", "memory.namespace должен совпадать со stable project.id")
    seen_repositories: set[str] = set()
    for entry in project.manifest.get("repositories", []):
        if entry["id"] in seen_repositories:
            result.error("projects", f"Повторяющийся repository ID: {entry['id']}")
        seen_repositories.add(entry["id"])
        path = (project.root / entry["path"]).resolve()
        try:
            path.relative_to(project.root)
        except ValueError:
            result.error("projects", f"Repository выходит за logical project root: {entry['path']}")
    repositories = {item["id"]: (project.root / item["path"]).resolve() for item in project.manifest.get("repositories", [])}
    seen_components: set[str] = set()
    for component in project.manifest.get("components", []):
        if component["id"] in seen_components:
            result.error("projects", f"Повторяющийся component ID: {component['id']}")
        seen_components.add(component["id"])
        if component["repository"] not in repositories:
            result.error("projects", f"Component {component['id']} ссылается на неизвестный repository {component['repository']}")
            continue
        component_path = (repositories[component["repository"]] / component["path"]).resolve()
        try:
            component_path.relative_to(repositories[component["repository"]])
        except ValueError:
            result.error("projects", f"Component {component['id']} выходит за repository root")
    try:
        resolve_harness(repository, project.manifest)
    except AgentKitError as error:
        result.error("projects", str(error))
    if result.ok:
        result.info("projects", f"Logical project {project.identifier} валиден")
    return result


def validate_project(project: LogicalProject, repository: Path) -> ValidationResult:
    """Проверить manifest и наличие репозиториев в обычном committed workspace."""
    result = validate_project_definition(project, repository)
    for entry in project.manifest.get("repositories", []):
        if not (project.root / entry["path"]).resolve().is_dir():
            result.error("projects", f"Repository path не существует: {entry['path']}")
    return result


def _find_repositories(root: Path) -> list[dict[str, str]]:
    found: list[Path] = []
    if (root / ".git").exists():
        found.append(root)
    for marker in root.glob("*/.git"):
        found.append(marker.parent)
    if not found:
        found.append(root)
    entries: list[dict[str, str]] = []
    used: set[str] = set()
    for path in sorted(set(found)):
        relative = path.relative_to(root)
        identifier = "root" if relative == Path(".") else slugify(path.name)
        base = identifier
        counter = 2
        while identifier in used:
            identifier = f"{base}-{counter}"
            counter += 1
        used.add(identifier)
        entries.append({"id": identifier, "path": "." if relative == Path(".") else relative.as_posix()})
    return entries


def _probable_components(root: Path, repositories: list[dict[str, str]]) -> list[dict[str, str]]:
    markers = ("pyproject.toml", "package.json", "go.mod", "Cargo.toml")
    components: list[dict[str, str]] = []
    used: set[str] = set()
    for repository in repositories:
        repository_root = (root / repository["path"]).resolve()
        parents = {
            path.parent
            for marker in markers
            for path in repository_root.rglob(marker)
            if not any(part.startswith(".") or part in {"node_modules", "vendor", "build", "dist"} for part in path.relative_to(repository_root).parts)
        }
        for parent in sorted(parents):
            relative = parent.relative_to(repository_root)
            identifier = slugify(parent.name)
            if identifier in used:
                identifier = slugify(f"{repository['id']}-{relative.as_posix()}")
            counter = 2
            base = identifier
            while identifier in used:
                identifier = f"{base}-{counter}"
                counter += 1
            used.add(identifier)
            components.append({
                "id": identifier,
                "repository": repository["id"],
                "path": relative.as_posix(),
            })
    return components


def detect_project(root: Path) -> dict[str, Any]:
    """Read-only preview logical topology."""
    root = root.expanduser().resolve()
    existing = find_project(root)
    if existing:
        return {"root": str(existing.root), "manifest": str(existing.manifest_path), "id": existing.identifier, "repositories": existing.manifest.get("repositories", []), "components": existing.manifest.get("components", [])}
    repositories = _find_repositories(root)
    return {"root": str(root), "manifest": None, "id": slugify(root.name), "repositories": repositories, "components": _probable_components(root, repositories)}


def register_memory(project: LogicalProject, paths: KitPaths) -> Path:
    validation = validate_instance(project.manifest, paths.repository / "schemas" / "project.schema.json", "project")
    if not validation.ok:
        raise AgentKitError("Некорректный project manifest: регистрация namespace отклонена")
    ensure_runtime(paths)
    memory = paths.projects / project.identifier
    identity_path = memory / "identity.json"
    root_hash = hashlib.sha256(str(project.root).encode("utf-8")).hexdigest()
    source = project.skills_repository
    source_url = source["url"].strip().rstrip("/") or None if source else None
    root_hashes: set[str] = set()
    if identity_path.exists():
        identity = json.loads(identity_path.read_text(encoding="utf-8"))
        root_hashes.update(identity.get("root_hashes", []))
        if identity.get("root_hash"):
            root_hashes.add(identity["root_hash"])
        existing_url = (identity.get("skills_repository_url") or "").strip().rstrip("/") or None
        same_single_root = root_hashes == {root_hash}
        matching_shared_source = bool(source_url) and source_url == existing_url
        if not same_single_root and not matching_shared_source:
            raise AgentKitError(
                f"Collision project.id={project.identifier!r}: namespace уже принадлежит другому root. Измените id в project.yaml."
            )
    root_hashes.add(root_hash)
    for child in ("state", "sessions", "summaries", "checkpoints", "integrations"):
        (memory / child).mkdir(parents=True, exist_ok=True)
    atomic_write(identity_path, json.dumps({
        "project_id": project.identifier,
        "skills_repository_url": source_url,
        "root_hashes": sorted(root_hashes),
    }, ensure_ascii=False, indent=2) + "\n")
    return memory


def register_integrations(project: LogicalProject, repository: Path, paths: KitPaths) -> Path:
    """Зафиксировать local mapping, не забирая native state у MCP."""
    from .mcp_manager import McpManager
    from .policy import effective_policy

    memory = register_memory(project, paths)
    integrations = []
    access_profile = str(effective_policy(repository, paths, project).values["mcp.access_profile"])
    for server in McpManager(repository, paths).list(project, access_profile=access_profile):
        integrations.append(
            {
                "id": server["id"],
                "enabled": server["enabled"],
                "available": server["available"],
                "status": server["status"],
                "state_owner": "mcp-native",
            }
        )
    target = memory / "integrations" / "registry.yaml"
    atomic_write(
        target,
        yaml.safe_dump({"version": 1, "project_id": project.identifier, "integrations": integrations}, allow_unicode=True, sort_keys=False),
    )
    return target


def init_project(
    root: Path,
    repository: Path,
    paths: KitPaths,
    *,
    identifier: str | None = None,
    template_id: str | None = None,
    language: str | None = None,
    stack: str | None = None,
    initialize_git: bool = False,
    default_branch: str = "main",
) -> LogicalProject:
    root = root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / ".ai-team" / "project.yaml"
    if manifest_path.exists():
        project = LogicalProject(root, manifest_path, load_yaml(manifest_path))
        register_integrations(project, repository, paths)
        memory_report = ProjectMemoryManager(repository, paths).index(project, mode="full")
        if memory_report["status"] == "FAIL":
            raise AgentKitError("Индексация памяти проекта завершилась ошибкой")
        return project

    project_id = slugify(identifier or root.name)
    if template_id is not None or language is not None or stack is not None:
        template = resolve_project_template(
            load_project_templates(repository),
            template_id=template_id,
            language=language,
            stack=stack,
        )
        apply_project_template(root, template, project_name=project_id)
    if initialize_git and not (root / ".git").exists():
        initialized = run_command(["git", "-C", str(root), "init", "-b", default_branch])
        if not initialized.ok:
            raise AgentKitError(initialized.stderr.strip() or "Не удалось инициализировать Git repository")
    repositories = _find_repositories(root)
    manifest: dict[str, Any] = {
        "version": 1,
        "id": project_id,
        "name": root.name,
        "repositories": repositories,
        "components": [],
        "discovery": {"enabled": True, "exclude_paths": []},
        "documentation": {"index": "docs/INDEX.md", "roots": ["docs"]},
        "memory": {"namespace": project_id},
        "integrations": {},
        "harness": {
            "preferred_client": "auto",
            "required_capabilities": ["instructions", "skills", "mcp"],
        },
    }
    schema_result = validate_instance(manifest, repository / "schemas" / "project.schema.json", str(manifest_path))
    if not schema_result.ok:
        raise AgentKitError("Не удалось создать валидный project manifest")
    atomic_write(manifest_path, "# Логический проект: компоненты обнаруживаются и сохраняются локально.\n" + yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False))
    docs_index = root / "docs" / "INDEX.md"
    if not docs_index.exists():
        atomic_write(
            docs_index,
            f"# Индекс документации {root.name}\n\n"
            "Этот файл — каноническая точка входа в durable project knowledge.\n\n"
            "## Разделы\n\n- Архитектура: `architecture/`\n- ADR: `adr/`\n- Runbooks: `runbooks/`\n",
        )
    project = LogicalProject(root, manifest_path, manifest)
    register_integrations(project, repository, paths)
    memory_report = ProjectMemoryManager(repository, paths).index(project, mode="full")
    if memory_report["status"] == "FAIL":
        raise AgentKitError("Индексация памяти проекта завершилась ошибкой")
    return project
