"""Repository-owned policy for explicit MCP activation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .errors import AgentKitError
from .io import atomic_write, load_yaml
from .schema import validate_instance


ACTIVATION_PATH = Path("mcp/activation.yaml")


def activation_path(repository: Path) -> Path:
    return repository / ACTIVATION_PATH


def load_activation(repository: Path) -> dict[str, set[str]]:
    """Load the committed activation policy and reject invalid or unknown IDs."""
    path = activation_path(repository)
    document = load_yaml(path)
    validation = validate_instance(document, repository / "schemas/mcp-activation.schema.json", str(ACTIVATION_PATH))
    if not validation.ok:
        errors = "; ".join(item.message for item in validation.diagnostics)
        raise AgentKitError(f"Некорректная repository MCP activation policy: {errors}")
    registry = load_yaml(repository / "mcp/registry.yaml")
    known = {item["id"] for item in registry.get("servers", [])}
    enabled = set(document["enabled"])
    disabled = set(document["disabled"])
    unknown = sorted((enabled | disabled) - known)
    if unknown:
        raise AgentKitError(f"mcp/activation.yaml содержит неизвестные MCP ID: {unknown}")
    overlap = sorted(enabled & disabled)
    if overlap:
        raise AgentKitError(f"mcp/activation.yaml содержит ID одновременно в enabled и disabled: {overlap}")
    return {"enabled": enabled, "disabled": disabled}


def set_activation(repository: Path, identifier: str, *, enabled: bool | None) -> Path:
    """Set or reset a repository activation decision without touching local overrides."""
    policy = load_activation(repository)
    active, disabled = policy["enabled"], policy["disabled"]
    active.discard(identifier)
    disabled.discard(identifier)
    if enabled is True:
        active.add(identifier)
    elif enabled is False:
        disabled.add(identifier)
    document: dict[str, Any] = {
        "version": 1,
        "enabled": sorted(active),
        "disabled": sorted(disabled),
    }
    rendered = (
        "# Политика repository-level activation: включает MCP независимо от project signals, но не обходит access profile, boundaries и credentials.\n"
        "# Изменяется командой agent-kit mcp enable|disable|reset <id> --scope repository; изменения следует закоммитить обычным Git workflow.\n"
        + yaml.safe_dump(document, allow_unicode=True, sort_keys=False)
    )
    path = activation_path(repository)
    atomic_write(path, rendered)
    return path
