"""Версионируемые шаблоны и безопасное создание каркаса проекта."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import AgentKitError
from .io import atomic_write, load_yaml


def load_project_templates(repository: Path) -> list[dict[str, Any]]:
    """Загрузить каталог шаблонов из репозитория Kit."""
    document = load_yaml(repository / "catalog" / "project-templates.yaml")
    templates = document.get("templates", [])
    if not isinstance(templates, list):
        raise AgentKitError("catalog/project-templates.yaml: templates должен быть списком")
    identifiers: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in templates:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise AgentKitError("catalog/project-templates.yaml содержит шаблон без строкового id")
        identifier = str(item["id"])
        if identifier in identifiers:
            raise AgentKitError(f"Повторяющийся шаблон проекта: {identifier}")
        identifiers.add(identifier)
        if not isinstance(item.get("files", {}), dict):
            raise AgentKitError(f"Шаблон {identifier}: files должен быть объектом")
        result.append(dict(item))
    return result


def resolve_project_template(
    templates: list[dict[str, Any]],
    *,
    template_id: str | None = None,
    language: str | None = None,
    stack: str | None = None,
) -> dict[str, Any]:
    """Выбрать ровно один шаблон по ID либо паре язык/стек."""
    candidates = templates
    if template_id is not None:
        candidates = [item for item in candidates if item["id"] == template_id]
    else:
        if language is not None:
            candidates = [item for item in candidates if item.get("language") == language]
        if stack is not None:
            candidates = [item for item in candidates if item.get("stack") == stack]
    if not candidates:
        details = template_id or "/".join(part for part in (language, stack) if part) or "без критериев"
        raise AgentKitError(f"Шаблон проекта не найден: {details}")
    if len(candidates) > 1:
        identifiers = ", ".join(str(item["id"]) for item in candidates)
        raise AgentKitError(f"Найдено несколько шаблонов ({identifiers}); укажите --template")
    return candidates[0]


def apply_project_template(root: Path, template: dict[str, Any], *, project_name: str) -> list[Path]:
    """Создать файлы шаблона после общей проверки конфликтов."""
    rendered: list[tuple[Path, str]] = []
    for relative, content in dict(template.get("files", {})).items():
        target = (root / str(relative)).resolve()
        try:
            target.relative_to(root.resolve())
        except ValueError as error:
            raise AgentKitError(f"Шаблон выходит за корень проекта: {relative}") from error
        if not isinstance(content, str):
            raise AgentKitError(f"Шаблон {template['id']}: содержимое {relative} должно быть строкой")
        value = content.replace("${PROJECT_NAME}", project_name)
        if target.exists() and target.read_text(encoding="utf-8") != value:
            raise AgentKitError(f"project init не перезаписывает существующий файл: {target}")
        rendered.append((target, value))
    changed: list[Path] = []
    for target, value in rendered:
        if not target.exists():
            atomic_write(target, value)
            changed.append(target)
    return changed
