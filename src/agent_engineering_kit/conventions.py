"""Загрузка и проверка дополняющих соглашений Kit и логического проекта."""

from __future__ import annotations

from pathlib import Path, PureWindowsPath
from typing import Any

from .errors import AgentKitError
from .io import load_yaml
from .projects import LogicalProject
from .result import ValidationResult
from .schema import validate_instance


def _sources(repository: Path, project: LogicalProject | None, result: ValidationResult) -> list[tuple[str, Path]]:
    root = repository / "conventions"
    if not root.is_dir():
        result.error("conventions", f"Отсутствует каталог общих conventions: {root}")
        return []
    sources = [(f"kit:{path.relative_to(repository).as_posix()}", path) for path in sorted(root.glob("*.yaml"))]
    if not sources:
        result.error("conventions", f"В каталоге нет общих conventions: {root}")
    if project is None:
        return sources
    declared_paths = project.manifest.get("conventions", [])
    if not isinstance(declared_paths, list):
        result.error("conventions", "project.conventions должен быть массивом относительных YAML-путей")
        return sources
    project_root = project.root.resolve()
    for declared in declared_paths:
        if not isinstance(declared, str) or not declared.strip():
            result.error("conventions", "Путь project convention должен быть непустой строкой")
            continue
        relative = Path(declared)
        if relative.is_absolute() or PureWindowsPath(declared).drive:
            result.error("conventions", f"Абсолютный путь project convention запрещён: {declared}")
            continue
        if "\\" in declared:
            result.error("conventions", f"Project convention выходит за logical project root или содержит непереносимый разделитель: {declared}")
            continue
        path = (project_root / relative).resolve()
        if not path.is_relative_to(project_root):
            result.error("conventions", f"Project convention выходит за logical project root: {declared}")
            continue
        if path.suffix not in {".yaml", ".yml"}:
            result.error("conventions", f"Project convention должен быть YAML-файлом: {declared}")
            continue
        sources.append((f"project:{declared}", path))
    return sources


def _collect(repository: Path, project: LogicalProject | None) -> tuple[list[dict[str, Any]], ValidationResult]:
    result = ValidationResult()
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    schema = repository / "schemas" / "conventions.schema.json"
    for source, path in _sources(repository, project, result):
        if not path.is_file():
            result.error("conventions", f"Файл conventions не найден: {path}")
            continue
        try:
            document = load_yaml(path)
            schema_result = validate_instance(document, schema, str(path))
        except (AgentKitError, OSError) as error:
            result.error("conventions", str(error))
            continue
        result.extend(schema_result)
        if not schema_result.ok:
            continue
        for item in document["conventions"]:
            identifier = item["id"]
            if identifier in seen:
                result.error("conventions", f"Повторный convention ID {identifier!r} в {path}; разрешено только добавление")
                continue
            seen.add(identifier)
            items.append({**item, "source": source})
    return items, result


def validate_conventions(repository: Path, project: LogicalProject | None = None) -> ValidationResult:
    _, result = _collect(repository, project)
    if result.ok:
        result.info("conventions", "Общие и проектные conventions валидны")
    return result


def load_conventions(repository: Path, project: LogicalProject | None = None) -> list[dict[str, Any]]:
    items, result = _collect(repository, project)
    if not result.ok:
        failures = "; ".join(item.message for item in result.diagnostics if item.severity == "ERROR")
        raise AgentKitError(f"Невозможно активировать conventions: {failures}")
    return items
