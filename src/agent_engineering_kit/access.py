"""Разрешение и проверка локальных политик доступа к компонентам."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .errors import AgentKitError
from .io import load_yaml
from .result import ValidationResult
from .schema import repository_schema_path, validate_instance


ACCESS_KINDS = frozenset({"mcp", "skills"})


@dataclass(frozen=True)
class AccessDecision:
    """Решение о доступности компонента после применения политик."""

    identifier: str
    enabled: bool
    reason: str


def _validate_kind(kind: str) -> None:
    if kind not in ACCESS_KINDS:
        raise AgentKitError(f"Неподдерживаемый тип политики доступа: {kind!r}")


def _layers(override_root: Path, project_id: str | None) -> list[tuple[str, Path]]:
    layers = [("global", override_root / "global" / "access.yaml")]
    if project_id:
        layers.append(("project", override_root / "projects" / project_id / "access.yaml"))
    return layers


def _access_lists(document: dict[object, object], kind: str) -> tuple[set[str], set[str]]:
    """Вернуть списки доступа только из структурно корректного раздела."""
    section = document.get(kind, {})
    if not isinstance(section, dict):
        return set(), set()
    allow = section.get("allow", [])
    block = section.get("block", [])
    return (
        set(allow) if isinstance(allow, list) and all(isinstance(item, str) for item in allow) else set(),
        set(block) if isinstance(block, list) and all(isinstance(item, str) for item in block) else set(),
    )


def resolve_access(
    identifiers: set[str],
    override_root: Path,
    kind: str,
    project_id: str | None = None,
) -> dict[str, AccessDecision]:
    """Определить доступность известных идентификаторов по слоям политик."""
    _validate_kind(kind)
    decisions = {
        identifier: AccessDecision(identifier, True, "allowed:catalog")
        for identifier in identifiers
    }
    for layer, path in _layers(override_root, project_id):
        if not path.is_file():
            continue
        allow, block = _access_lists(load_yaml(path), kind)
        for identifier, current in list(decisions.items()):
            if not current.enabled:
                continue
            if identifier in block:
                decisions[identifier] = AccessDecision(identifier, False, f"blocked:{layer}")
            elif allow and identifier not in allow:
                decisions[identifier] = AccessDecision(identifier, False, f"not-allowed:{layer}")
    return decisions


def validate_access(
    identifiers_by_kind: dict[str, set[str]],
    override_root: Path,
    project_id: str | None = None,
) -> ValidationResult:
    """Проверить схемы политик, неизвестные идентификаторы и конфликты списков."""
    result = ValidationResult()
    unknown_kinds = set(identifiers_by_kind) - ACCESS_KINDS
    if unknown_kinds:
        raise AgentKitError(f"Неподдерживаемые типы политик доступа: {sorted(unknown_kinds)}")
    for layer, path in _layers(override_root, project_id):
        if not path.is_file():
            continue
        document = load_yaml(path)
        result.extend(validate_instance(document, repository_schema_path("access.schema.json"), str(path)))
        for kind in ACCESS_KINDS:
            allow, block = _access_lists(document, kind)
            known = identifiers_by_kind.get(kind, set())
            unknown = sorted((allow | block) - known)
            if unknown:
                result.error("access", f"{path}: {kind} содержит неизвестные ID: {unknown}")
            conflicts = sorted(allow & block)
            if conflicts:
                result.error("access", f"{path}: {kind} содержит ID одновременно в allow и block: {conflicts}")
    return result
