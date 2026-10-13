"""Загрузка декларативных каталогов и неизменяемых lock-файлов."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import AgentKitError
from .io import load_yaml


REVISION = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class LockedComponent:
    identifier: str
    version: str
    revision: str
    metadata: dict[str, Any]


def load_catalog(repository: Path, name: str) -> dict[str, Any]:
    document = load_yaml(repository / "catalog" / f"{name}.yaml")
    if document.get("version") != 1:
        raise AgentKitError(f"catalog/{name}.yaml: поддерживается только version: 1")
    if registry := document.get("registry"):
        registry_path = (repository / registry).resolve()
        try:
            registry_path.relative_to(repository.resolve())
        except ValueError as error:
            raise AgentKitError(f"catalog/{name}.yaml: registry выходит за repository") from error
        document = load_yaml(registry_path)
    values = document.get(name)
    if name == "mcp" and values is None:
        values = document.get("servers")
        document = {**document, "mcp": values}
    if not isinstance(values, list):
        raise AgentKitError(f"catalog/{name}.yaml: key {name!r} должен быть массивом")
    identifiers = [item.get("id") for item in values if isinstance(item, dict)]
    if len(identifiers) != len(set(identifiers)):
        raise AgentKitError(f"catalog/{name}.yaml: повторяющиеся IDs")
    return document


def load_locks(repository: Path, name: str) -> dict[str, LockedComponent]:
    document = load_yaml(repository / "locks" / f"{name}.lock.yaml")
    if document.get("version") != 1:
        raise AgentKitError(f"locks/{name}.lock.yaml: поддерживается только version: 1")
    result: dict[str, LockedComponent] = {}
    for item in document.get("components", []):
        identifier = item.get("id")
        revision = item.get("revision")
        if not isinstance(identifier, str) or identifier in result:
            raise AgentKitError(f"locks/{name}.lock.yaml: некорректный или повторяющийся id")
        if not isinstance(revision, str) or not REVISION.fullmatch(revision):
            raise AgentKitError(f"locks/{name}.lock.yaml: {identifier} должен иметь полный 40-символьный revision")
        result[identifier] = LockedComponent(identifier, str(item.get("version", revision[:12])), revision, item)
    return result


def resolve_desired(repository: Path, name: str) -> list[tuple[dict[str, Any], LockedComponent]]:
    catalog = load_catalog(repository, name)
    locks = load_locks(repository, name)
    resolved: list[tuple[dict[str, Any], LockedComponent]] = []
    for item in catalog[name]:
        identifier = item["id"]
        if identifier not in locks:
            raise AgentKitError(f"Catalog {name}: для {identifier} отсутствует lock")
        resolved.append((item, locks[identifier]))
    stale = sorted(set(locks) - {item["id"] for item in catalog[name]})
    if stale:
        raise AgentKitError(f"locks/{name}.lock.yaml содержит stale entries: {', '.join(stale)}")
    return resolved
