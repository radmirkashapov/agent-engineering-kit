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
_MCP_SCHEMA = Path(__file__).resolve().parents[2] / "schemas" / "mcp.schema.json"
_OVERRIDE_SCHEMA = Path(__file__).resolve().parents[2] / "schemas" / "override.schema.json"
_SKILL_SCHEMA = Path(__file__).resolve().parents[2] / "schemas" / "skill.schema.json"
_IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")


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


def _validate_identifier(identifier: str) -> None:
    if _IDENTIFIER_PATTERN.fullmatch(identifier) is None:
        raise AgentKitError(
            "ID компонента должен начинаться со строчной латинской буквы "
            "и содержать только строчные латинские буквы, цифры и дефис"
        )


def _scope_path(scope: OverrideScope, *parts: str) -> Path:
    root = scope.root.expanduser().resolve()
    candidate = root.joinpath(*parts).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise AgentKitError(f"Путь компонента выходит за область переопределений: {candidate}") from error
    return candidate


def _default_backup_root(scope: OverrideScope) -> Path:
    root = scope.root.expanduser().resolve()
    if scope.kind == "global":
        return root.parent / "backups"
    if scope.kind == "project":
        return root.parent.parent / "backups"
    raise AgentKitError(f"Неизвестная область переопределений: {scope.kind!r}")


def _new_backup_directory(backup_root: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    backup = backup_root.expanduser().resolve() / timestamp
    backup.mkdir(parents=True, exist_ok=False)
    return backup


def _backup_destination(scope: OverrideScope, backup: Path, source: Path) -> Path:
    root = scope.root.expanduser().resolve()
    source = source.resolve()
    try:
        relative = source.relative_to(root)
    except ValueError as error:
        raise AgentKitError(f"Резервируемый путь выходит за область переопределений: {source}") from error
    destination = (backup / relative).resolve()
    try:
        destination.relative_to(backup.resolve())
    except ValueError as error:
        raise AgentKitError(f"Путь резервной копии выходит за её каталог: {destination}") from error
    return destination


def _snapshot_existing(
    scope: OverrideScope,
    paths: list[Path],
    *,
    backup_root: Path | None = None,
) -> tuple[Path | None, list[Path]]:
    existing = [path for path in paths if path.exists()]
    if not existing:
        return None, []
    backup = _new_backup_directory(backup_root or _default_backup_root(scope))
    snapshots: list[Path] = []
    for source in existing:
        destination = _backup_destination(scope, backup, source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, destination)
        else:
            shutil.copy2(source, destination)
        snapshots.append(destination)
    return backup, snapshots


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
    target_moved = False
    try:
        shutil.copytree(source, staging, dirs_exist_ok=True)
        if target.exists():
            previous = Path(tempfile.mkdtemp(prefix=f".{target.name}.previous.", dir=target.parent))
            previous.rmdir()
            os.replace(target, previous)
            target_moved = True
        try:
            os.replace(staging, target)
        except Exception:
            if target_moved and previous is not None:
                os.replace(previous, target)
            raise
        try:
            atomic_write(definition, content)
        except Exception:
            if target.exists():
                shutil.rmtree(target)
            if target_moved and previous is not None:
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
    _validate_identifier(identifier)
    path = _scope_path(scope, "access.yaml")
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
    _snapshot_existing(scope, [path])
    _write_access(path, document)
    return path


def install_skill_override(scope: OverrideScope, identifier: str, source: Path) -> Path:
    """Скопировать локальный skill и записать переносимое переопределение."""
    _validate_identifier(identifier)
    source = source.expanduser().resolve()
    skill_file = source / "SKILL.md"
    if not source.is_dir() or not skill_file.is_file():
        raise AgentKitError(f"Источник skill должен быть каталогом с SKILL.md: {source}")
    metadata = markdown_frontmatter(skill_file)
    result = validate_instance(metadata, _SKILL_SCHEMA, str(skill_file))
    if not result.ok:
        message = next(item.message for item in result.diagnostics if item.severity == "ERROR")
        raise AgentKitError(f"Некорректный SKILL.md: {message}")

    definition = _scope_path(scope, "skills", f"{identifier}.yaml")
    copied_source = _scope_path(scope, "sources", "skills", identifier)
    relative_source = Path("..") / "sources" / "skills" / identifier
    document: dict[str, object] = {
        "target": identifier,
        "override": {
            "mode": "replace",
            "value": {"path": relative_source.as_posix()},
        },
    }
    content = _validated_yaml(document, _OVERRIDE_SCHEMA, str(definition))
    _snapshot_existing(scope, [definition, copied_source])
    _replace_directory(source, copied_source, definition, content)
    return definition


def install_mcp_override(scope: OverrideScope, identifier: str, source: Path) -> Path:
    """Проверить и атомарно установить локальное переопределение MCP."""
    _validate_identifier(identifier)
    source = source.expanduser().resolve()
    document = load_yaml(source)
    mode = document.get("mode")
    value = document.get("value", {})
    if not isinstance(value, dict):
        raise AgentKitError("Поле value переопределения MCP должно быть объектом")
    if "id" in value:
        raise AgentKitError("Поле value переопределения MCP не должно содержать id; используйте target команды")
    environment = value.get("environment", {})
    if not isinstance(environment, dict):
        raise AgentKitError("Поле environment переопределения MCP должно быть объектом")
    if any(
        not isinstance(reference, str)
        or re.fullmatch(r"env:[A-Z][A-Z0-9_]*", reference) is None
        for reference in environment.values()
    ):
        raise AgentKitError("Секреты MCP задаются только ссылками формата env:VARIABLE")

    if mode == "replace":
        effective = {**value, "id": identifier}
        result = validate_instance(
            {"version": 1, "servers": [effective]},
            _MCP_SCHEMA,
            f"итоговый MCP {identifier!r}",
        )
        if not result.ok:
            message = next(item.message for item in result.diagnostics if item.severity == "ERROR")
            raise AgentKitError(f"Некорректный итоговый MCP: {message}")

    target = _scope_path(scope, "mcp", f"{identifier}.yaml")
    override: dict[str, object] = {
        "target": identifier,
        "override": {"mode": mode, "value": value},
    }
    content = _validated_yaml(override, _OVERRIDE_SCHEMA, str(target))
    _snapshot_existing(scope, [target])
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
    _validate_identifier(identifier)

    access_path = _scope_path(scope, "access.yaml")
    access_document: dict[str, object] | None = None
    access_changed = False
    if access_path.is_file():
        access_document = load_yaml(access_path)
        section = access_document.get(kind, {})
        if not isinstance(section, dict):
            raise AgentKitError(f"Некорректный раздел политики доступа: {kind}")
        allow = _access_values(section, kind, "allow")
        block = _access_values(section, kind, "block")
        access_changed = identifier in allow or identifier in block
        allow.discard(identifier)
        block.discard(identifier)
        section["allow"] = sorted(allow)
        section["block"] = sorted(block)
        result = validate_instance(access_document, _ACCESS_SCHEMA, str(access_path))
        if not result.ok:
            message = next(item.message for item in result.diagnostics if item.severity == "ERROR")
            raise AgentKitError(f"Некорректная политика доступа: {message}")

    candidates = [_scope_path(scope, kind, f"{identifier}.yaml")]
    if kind == "skills":
        candidates.append(_scope_path(scope, "sources", "skills", identifier))
    existing = [candidate for candidate in candidates if candidate.exists()]
    if not existing and not access_changed:
        return []

    backup = _new_backup_directory(backup_root)
    moved: list[Path] = []
    moved_components: list[Path] = []
    origins: list[Path] = []
    try:
        if access_changed:
            access_backup = _backup_destination(scope, backup, access_path)
            access_backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(access_path, access_backup)
            moved.append(access_backup)

        for candidate in existing:
            destination = _backup_destination(scope, backup, candidate)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(candidate), str(destination))
            origins.append(candidate)
            moved.append(destination)
            moved_components.append(destination)

        if access_document is not None and access_changed:
            _write_access(access_path, access_document)
    except Exception:
        for origin, destination in reversed(list(zip(origins, moved_components, strict=True))):
            origin.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(destination), str(origin))
        raise
    return moved
