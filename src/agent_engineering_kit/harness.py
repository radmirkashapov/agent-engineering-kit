"""Контракт между control plane набора и внешними execution harness."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import AgentKitError
from .io import load_yaml


DEFAULT_REQUIRED_CAPABILITIES = ("instructions", "skills", "mcp")


def load_harness_clients(repository: Path) -> list[dict[str, Any]]:
    """Загрузить упорядоченный каталог поддерживаемых клиентских harness."""
    document = load_yaml(repository / "catalog" / "clients.yaml")
    clients = document.get("clients", [])
    if not isinstance(clients, list):
        raise AgentKitError("catalog/clients.yaml: clients должен быть массивом")
    return clients


def resolve_harness(repository: Path, project_manifest: dict[str, Any] | None = None) -> dict[str, object]:
    """Выбрать client adapter и вернуть явную границу ответственности harness."""
    manifest = project_manifest or {}
    settings = manifest.get("harness") or {}
    preferred = settings.get("preferred_client", "auto")
    required = list(settings.get("required_capabilities", DEFAULT_REQUIRED_CAPABILITIES))
    clients = load_harness_clients(repository)
    by_id = {item["id"]: item for item in clients}

    if preferred == "auto":
        selected = next(
            (
                item
                for item in clients
                if set(required) <= set(item["harness"]["managed_capabilities"])
            ),
            None,
        )
        if selected is None:
            raise AgentKitError(
                "Ни один client harness не поддерживает обязательные возможности: "
                + ", ".join(required)
            )
    else:
        selected = by_id.get(preferred)
        if selected is None:
            raise AgentKitError(f"Неизвестный preferred client harness: {preferred}")
        missing = sorted(set(required) - set(selected["harness"]["managed_capabilities"]))
        if missing:
            raise AgentKitError(
                f"Client harness {preferred} не поддерживает обязательные возможности: {', '.join(missing)}"
            )

    harness = selected["harness"]
    return {
        "control_plane": "agent-engineering-kit",
        "execution_owner": harness["execution_owner"],
        "preferred_client": preferred,
        "selected_client": selected["id"],
        "required_capabilities": required,
        "managed_capabilities": list(harness["managed_capabilities"]),
        "delegated_capabilities": list(harness["delegated_capabilities"]),
    }
