"""Проверка документов по схемам JSON Schema."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .io import load_json
from .result import ValidationResult


SCHEMA_TARGETS = {
    "models/corporate.yaml": "models/schemas/models.schema.json",
    "templates/project/project.yaml": "schemas/project.schema.json",
    "mcp/registry.yaml": "schemas/mcp.schema.json",
    "mcp/docker-toolkit.yaml": "schemas/docker-toolkit.schema.json",
    "catalog/skills.yaml": "schemas/skill-source.schema.json",
    "catalog/security.yaml": "schemas/security-catalog.schema.json",
    "catalog/clients.yaml": "schemas/clients.schema.json",
    "locks/skills.lock.yaml": "schemas/lock.schema.json",
    "locks/mcp.lock.yaml": "schemas/lock.schema.json",
    "locks/security.lock.yaml": "schemas/lock.schema.json",
}


def validate_instance(instance: Any, schema_path: Path, label: str) -> ValidationResult:
    result = ValidationResult()
    schema = load_json(schema_path)
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(instance), key=lambda item: list(item.absolute_path))
    for error in errors:
        location = ".".join(map(str, error.absolute_path)) or "<root>"
        result.error("schemas", f"{label}:{location}: {error.message}")
    return result


def validate_repository_schemas(repository: Path) -> ValidationResult:
    from .io import load_yaml

    result = ValidationResult()
    for data_name, schema_name in SCHEMA_TARGETS.items():
        data_path = repository / data_name
        schema_path = repository / schema_name
        if not data_path.is_file() or not schema_path.is_file():
            result.error("schemas", f"Отсутствует обязательный файл: {data_path if not data_path.is_file() else schema_path}")
            continue
        result.extend(validate_instance(load_yaml(data_path), schema_path, data_name))

    for schema_path in sorted((repository / "schemas").glob("*.json")) + sorted((repository / "models" / "schemas").glob("*.json")):
        schema = load_json(schema_path)
        try:
            Draft202012Validator.check_schema(schema)
        except Exception as error:  # jsonschema предоставляет несколько типов SchemaError
            result.error("schemas", f"Некорректная схема {schema_path}: {error}")
    try:
        app_version = (repository / "app.version").read_text(encoding="utf-8").strip()
        package_version = (repository / "src" / "agent_engineering_kit" / "__init__.py").read_text(encoding="utf-8")
        if f'__version__ = "{app_version}"' not in package_version:
            result.error("schemas", "app.version не совпадает с package __version__")
    except OSError as error:
        result.error("schemas", f"Не удалось проверить app.version: {error}")
    if result.ok:
        result.info("schemas", "JSON Schema и эталонные manifests валидны")
    return result
