"""Проверяемая матрица возможностей клиентских сред выполнения."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .io import load_yaml
from .result import ValidationResult


def build_conformance_matrix(repository: Path) -> list[dict[str, Any]]:
    """Развернуть компактные client contracts в единую capability matrix."""
    clients = load_yaml(repository / "catalog" / "clients.yaml").get("clients", [])
    matrix: list[dict[str, Any]] = []
    for client in clients:
        harness = client["harness"]
        capabilities: dict[str, str] = {}
        for capability in harness.get("managed_capabilities", []):
            capabilities[str(capability)] = "managed"
        for capability in harness.get("delegated_capabilities", []):
            capabilities[str(capability)] = "delegated"
        for capability in harness.get("experimental_capabilities", []):
            capabilities[str(capability)] = "experimental"
        matrix.append(
            {
                "id": client["id"],
                "adapter_version": harness.get("adapter_version"),
                "reference_runtime": bool(harness.get("reference_runtime", False)),
                "capabilities": capabilities,
            }
        )
    return matrix


def validate_conformance(repository: Path) -> ValidationResult:
    """Проверить полноту, уникальность и reference runtime."""
    result = ValidationResult()
    matrix = build_conformance_matrix(repository)
    references = [item["id"] for item in matrix if item["reference_runtime"]]
    if references != ["codex"]:
        result.error("conformance", f"Reference runtime должен быть только codex, получено: {references}")
    for item in matrix:
        if not isinstance(item.get("adapter_version"), int) or item["adapter_version"] < 1:
            result.error("conformance", f"Client {item['id']} не содержит adapter_version")
        if "agent-loop" not in item["capabilities"]:
            result.error("conformance", f"Client {item['id']} не объявляет владельца agent-loop")
        if not item["capabilities"]:
            result.error("conformance", f"Client {item['id']} не содержит capabilities")
    if result.ok:
        result.info("conformance", f"Проверено client harness: {len(matrix)}")
    return result
