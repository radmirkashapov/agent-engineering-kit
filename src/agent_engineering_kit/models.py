"""Корпоративная и локальная пользовательская политика моделей."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .io import load_yaml, markdown_frontmatter
from .result import ValidationResult
from .schema import validate_instance


COMMITTED_DEFINITION_DIRS = ("agents", "skills", "rules", "clients", "mcp", "templates")
MODEL_KEYS = {"preferred", "allowed", "model", "default_model", "defaultModel"}


@dataclass(frozen=True)
class ModelPolicy:
    corporate: dict[str, dict[str, Any]]
    local: dict[str, dict[str, Any]]
    providers: set[str]

    @property
    def corporate_active(self) -> bool:
        return bool(self.corporate)

    @property
    def committed_allowed_ids(self) -> set[str]:
        return set(self.corporate)

    @property
    def runtime_allowed_ids(self) -> set[str]:
        return set(self.corporate) | set(self.local)


def _model_map(document: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    mapping: dict[str, dict[str, Any]] = {}
    duplicates: list[str] = []
    for item in document.get("models", []) or []:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            continue
        identifier = item["id"]
        if identifier in mapping:
            duplicates.append(identifier)
        mapping[identifier] = item
    return mapping, duplicates


def _local_model_document(repository: Path, include_local: bool, local_path: Path | None) -> dict[str, Any]:
    if not include_local:
        return {}
    candidates = [local_path] if local_path else []
    candidates.append(repository / "models" / "user.local.yaml")
    for candidate in candidates:
        if candidate and candidate.is_file():
            return load_yaml(candidate)
    return {}


def load_policy(repository: Path, *, include_local: bool = True, local_path: Path | None = None) -> ModelPolicy:
    corporate_document = load_yaml(repository / "models" / "corporate.yaml")
    local_document = _local_model_document(repository, include_local, local_path)
    corporate, _ = _model_map(corporate_document)
    local, _ = _model_map(local_document)
    providers = {
        item["id"]
        for document in (corporate_document, local_document)
        for item in document.get("providers", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    return ModelPolicy(corporate, local, providers)


def _aliases(models: dict[str, dict[str, Any]]) -> tuple[dict[str, str], list[str]]:
    mapping: dict[str, str] = {}
    duplicates: list[str] = []
    for identifier, model in models.items():
        for alias in model.get("aliases", []) or []:
            if alias in mapping or alias in models:
                duplicates.append(alias)
            mapping[alias] = identifier
    return mapping, duplicates


def _collect_model_references(value: Any, *, parent_key: str = "") -> Iterable[str]:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in MODEL_KEYS:
                if isinstance(nested, str):
                    yield nested
                elif isinstance(nested, list):
                    yield from (item for item in nested if isinstance(item, str))
                elif isinstance(nested, dict):
                    yield from _collect_model_references(nested, parent_key=key)
            else:
                yield from _collect_model_references(nested, parent_key=key)
    elif isinstance(value, list):
        for nested in value:
            yield from _collect_model_references(nested, parent_key=parent_key)


def model_references(value: Any) -> set[str]:
    return set(_collect_model_references(value))


def allowed_model_references(policy: ModelPolicy) -> set[str]:
    corporate_aliases, _ = _aliases(policy.corporate)
    local_aliases, _ = _aliases(policy.local)
    return set(policy.corporate) | set(policy.local) | set(corporate_aliases) | set(local_aliases)


def _definition_documents(repository: Path) -> Iterable[tuple[Path, dict[str, Any]]]:
    for dirname in COMMITTED_DEFINITION_DIRS:
        root = repository / dirname
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix in {".yaml", ".yml"}:
                yield path, load_yaml(path)
            elif path.suffix == ".md":
                metadata = markdown_frontmatter(path)
                if metadata:
                    yield path, metadata


def validate_models(repository: Path, *, include_local: bool = True, local_path: Path | None = None) -> ValidationResult:
    result = ValidationResult()
    corporate_path = repository / "models" / "corporate.yaml"
    effective_local_path = local_path or repository / "models" / "user.local.yaml"
    corporate_document = load_yaml(corporate_path)
    schema_path = repository / "models" / "schemas" / "models.schema.json"
    result.extend(validate_instance(corporate_document, schema_path, str(corporate_path)))

    local_document = _local_model_document(repository, include_local, local_path)
    if local_document:
        result.extend(validate_instance(local_document, schema_path, str(effective_local_path)))

    corporate, corporate_duplicates = _model_map(corporate_document)
    local, local_duplicates = _model_map(local_document)
    corporate_aliases, duplicate_corporate_aliases = _aliases(corporate)
    local_aliases, duplicate_local_aliases = _aliases(local)
    for identifier in corporate_duplicates:
        result.error("models", f"Повторяющийся corporate model ID: {identifier}")
    for identifier in local_duplicates:
        result.error("models", f"Повторяющийся user-local model ID: {identifier}")
    for alias in duplicate_corporate_aliases:
        result.error("models", f"Повторяющийся corporate model alias: {alias}")
    for alias in duplicate_local_aliases:
        result.error("models", f"Повторяющийся user-local model alias: {alias}")
    for identifier in sorted(set(corporate) & set(local)):
        result.error("models", f"User-local model конфликтует с corporate model ID: {identifier}")

    providers = {
        item["id"]
        for document in (corporate_document, local_document)
        for item in document.get("providers", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    for source, models in (("corporate", corporate), ("user-local", local)):
        for identifier, model in models.items():
            if providers and model.get("provider") not in providers:
                result.error("models", f"Модель {identifier} ({source}) использует неизвестного provider: {model.get('provider')}")

    allowed = (set(corporate) | set(corporate_aliases)) if corporate else (set(local) | set(local_aliases))
    for path, document in _definition_documents(repository):
        for reference in sorted(set(_collect_model_references(document))):
            if reference not in allowed:
                policy = "corporate allowlist" if corporate else "effective local policy"
                result.error("models", f"{path.relative_to(repository)} ссылается на модель {reference!r}, отсутствующую в {policy}")
            elif corporate and reference in local and reference not in corporate:
                result.error("models", f"Committed definition {path.relative_to(repository)} зависит от user-local модели {reference!r}")

    if result.ok:
        mode = "corporate" if corporate else "local runtime"
        result.info("models", f"Model policy валидна; режим: {mode}, разрешено моделей: {len(allowed)}")
    return result
