from __future__ import annotations

from pathlib import Path

from agent_engineering_kit.conformance import build_conformance_matrix, validate_conformance


REPOSITORY = Path(__file__).resolve().parents[1]


def test_client_conformance_matrix_has_reference_runtime_and_support_levels() -> None:
    matrix = build_conformance_matrix(REPOSITORY)

    codex = next(item for item in matrix if item["id"] == "codex")
    assert codex["reference_runtime"] is True
    assert codex["adapter_version"] == 1
    assert codex["capabilities"]["instructions"] == "managed"
    assert codex["capabilities"]["agent-loop"] == "delegated"
    assert codex["capabilities"]["context-optimization"] == "experimental"


def test_client_conformance_contract_is_valid() -> None:
    result = validate_conformance(REPOSITORY)

    assert result.ok, [diagnostic.render() for diagnostic in result.diagnostics]
