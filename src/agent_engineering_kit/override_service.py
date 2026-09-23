"""Безопасное изменение пользовательских локальных переопределений."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Literal

import yaml

from .access import ACCESS_KINDS
from .errors import AgentKitError
from .io import atomic_write, load_yaml, markdown_frontmatter
from .paths import KitPaths
from .projects import find_project
from .schema import validate_instance


_ACCESS_SCHEMA = Path(__file__).resolve().parents[2] / "schemas" / "access.schema.json"
_OVERRIDE_SCHEMA = Path(__file__).resolve().parents[2] / "schemas" / "override.schema.json"
_SKILL_SCHEMA = Path(__file__).resolve().parents[2] / "schemas" / "skill.schema.json"


@dataclass(frozen=True)
class OverrideScope:
    """Каталог локальных переопределений выбранного уровня."""

    kind: Literal["global", "project"]
    root: Path
    project_id: str | None


def resolve_scope(paths: KitPaths, scope: str, cwd: Path) -> OverrideScope:
    """Разрешить явно выбранный уровень локальных переопределений."""
    if scope == "global":
        return OverrideScope("global", paths.overrides / "global", None)
    if scope != "project":
        raise AgentKitError(f"Неизвестная область переопределений: {scope!r}")
    project = find_project(cwd)
    if project is None:
        raise AgentKitError("Логический проект не найден: ожидается .ai-team/project.yaml")
    return OverrideScope(
        "project",
        paths.overrides / "projects" / project.identifier,
        project.identifier,
    )


def _write_access(path: Path, document: dict[str, object]) -> None:
    result = validate_instance(document, _ACCESS_SCHEMA, str(path))
    if not result.ok:
        message = next(item.message for item in result.diagnostics if item.severity == "ERROR")
        raise AgentKitError(f"Некорректная политика доступа: {message}")
    atomic_write(path, yaml.safe_dump(document, allow_unicode=True, sort_keys=False))


def _access_values(section: dict[object, object], kind: str, name: str) -> set[str]:
    values = section.get(name, [])
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise AgentKitError(f"Список {kind}.{name} должен содержать только строковые ID")
    return set(values)


def _validated_yaml(document: dict[str, object], schema: Path, label: str) -> str:
    result = validate_instance(document, schema, label)
    if not result.ok:
        message = next(item.message for item in result.diagnostics if item.severity == "ERROR")
        raise AgentKitError(f"Некорректное переопределение: {message}")
    return yaml.safe_dump(document, allow_unicode=True, sort_keys=False)


def _replace_directory(source: Path, target: Path, definition: Path, content: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    previous: Path | None = None
    try:
        shutil.copytree(source, staging, dirs_exist_ok=True)
        if target.exists():
            previous = Path(tempfile.mkdtemp(prefix=f".{target.name}.previous.", dir=target.parent))
            previous.rmdir()
            os.replace(target, previous)
        os.replace(staging, target)
        try:
            atomic_write(definition, content)
        except Exception:
            shutil.rmtree(target)
            if previous is not None:
                os.replace(previous, target)
            raise
        if previous is not None:
            shutil.rmtree(previous)
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def set_component_access(
    scope: OverrideScope,
    kind: str,
    identifier: str,
    *,
    enabled: bool,
) -> Path:
    """Изменить доступ к произвольному ID, сохранив остальные разделы YAML."""
    if kind not in ACCESS_KINDS:
        raise AgentKitError(f"Неподдерживаемый тип политики доступа: {kind!r}")
    path = scope.root / "access.yaml"
    document: dict[str, object] = load_yaml(path) if path.is_file() else {
        "version": 1,
        "mcp": {"allow": [], "block": []},
        "skills": {"allow": [], "block": []},
    }
    section = document.setdefault(kind, {"allow": [], "block": []})
    if not isinstance(section, dict):
        raise AgentKitError(f"Некорректный раздел политики доступа: {kind}")
    allow = _access_values(section, kind, "allow")
    block = _access_values(section, kind, "block")
    if enabled:
        block.discard(identifier)
        if allow:
            allow.add(identifier)
    else:
        allow.discard(identifier)
        block.add(identifier)
    section["allow"] = sorted(allow)
    section["block"] = sorted(block)
    _write_access(path, document)
    return path


def install_skill_override(scope: OverrideScope, identifier: str, source: Path) -> Path:
    """Скопировать локальный skill и записать переносимое переопределение."""
    source = source.expanduser().resolve()
    skill_file = source / "SKILL.md"
    if not source.is_dir() or not skill_file.is_file():
        raise AgentKitError(f"Источник skill должен быть каталогом с SKILL.md: {source}")
    metadata = markdown_frontmatter(skill_file)
    result = validate_instance(metadata, _SKILL_SCHEMA, str(skill_file))
    if not result.ok:
        message = next(item.message for item in result.diagnostics if item.severity == "ERROR")
        raise AgentKitError(f"Некорректный SKILL.md: {message}")

    definition = scope.root / "skills" / f"{identifier}.yaml"
    copied_source = scope.root / "sources" / "skills" / identifier
    relative_source = Path("..") / "sources" / "skills" / identifier
    document: dict[str, object] = {
        "target": identifier,
        "override": {
            "mode": "replace",
            "value": {"path": relative_source.as_posix()},
        },
    }
    content = _validated_yaml(document, _OVERRIDE_SCHEMA, str(definition))
    _replace_directory(source, copied_source, definition, content)
    return definition


def install_mcp_override(scope: OverrideScope, identifier: str, source: Path) -> Path:
    """Проверить и атомарно установить локальное переопределение MCP."""
    source = source.expanduser().resolve()
    document = load_yaml(source)
    mode = document.get("mode")
    value = document.get("value", {})
    if not isinstance(value, dict):
        raise AgentKitError("Поле value переопределения MCP должно быть объектом")
    environment = value.get("environment", {})
    if not isinstance(environment, dict):
        raise AgentKitError("Поле environment переопределения MCP должно быть объектом")
    if any(
        not isinstance(reference, str)
        or re.fullmatch(r"env:[A-Z][A-Z0-9_]*", reference) is None
        for reference in environment.values()
    ):
        raise AgentKitError("Секреты MCP задаются только ссылками формата env:VARIABLE")

    target = scope.root / "mcp" / f"{identifier}.yaml"
    override: dict[str, object] = {
        "target": identifier,
        "override": {"mode": mode, "value": value},
    }
    content = _validated_yaml(override, _OVERRIDE_SCHEMA, str(target))
    atomic_write(target, content)
    return target


def reset_component_override(
    scope: OverrideScope,
    kind: str,
    identifier: str,
    backup_root: Path,
) -> list[Path]:
    """Сбросить локальные настройки и перенести данные в резервную копию."""
    if kind not in ACCESS_KINDS:
        raise AgentKitError(f"Неподдерживаемый тип переопределения: {kind!r}")

    access_path = scope.root / "access.yaml"
    access_document: dict[str, object] | None = None
    if access_path.is_file():
        access_document = load_yaml(access_path)
        section = access_document.get(kind, {})
        if not isinstance(section, dict):
            raise AgentKitError(f"Некорректный раздел политики доступа: {kind}")
        allow = _access_values(section, kind, "allow")
        block = _access_values(section, kind, "block")
        allow.discard(identifier)
        block.discard(identifier)
        section["allow"] = sorted(allow)
        section["block"] = sorted(block)
        result = validate_instance(access_document, _ACCESS_SCHEMA, str(access_path))
        if not result.ok:
            message = next(item.message for item in result.diagnostics if item.severity == "ERROR")
            raise AgentKitError(f"Некорректная политика доступа: {message}")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    backup = backup_root / timestamp
    candidates = [scope.root / kind / f"{identifier}.yaml"]
    if kind == "skills":
        candidates.append(scope.root / "sources" / "skills" / identifier)
    moved: list[Path] = []
    origins: list[Path] = []
    try:
        for candidate in candidates:
            if not candidate.exists():
                continue
            relative = candidate.relative_to(scope.root)
            destination = backup / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(candidate), str(destination))
            origins.append(candidate)
            moved.append(destination)

        if access_document is not None:
            _write_access(access_path, access_document)
    except Exception:
        for origin, destination in reversed(list(zip(origins, moved, strict=True))):
            origin.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(destination), str(origin))
        raise
    return moved
