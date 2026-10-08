from __future__ import annotations

from pathlib import Path

import pytest

from agent_engineering_kit.errors import AgentKitError
from agent_engineering_kit.harness import resolve_harness


def test_auto_selects_first_client_covering_required_capabilities() -> None:
    repository = Path(__file__).resolve().parents[1]
    manifest = {
        "harness": {
            "preferred_client": "auto",
            "required_capabilities": ["instructions", "skills", "mcp"],
        }
    }

    contract = resolve_harness(repository, manifest)

    assert contract["control_plane"] == "agent-engineering-kit"
    assert contract["execution_owner"] == "client"
    assert contract["preferred_client"] == "auto"
    assert contract["selected_client"] == "codex"
    assert contract["required_capabilities"] == ["instructions", "skills", "mcp"]
    assert "agent-loop" in contract["delegated_capabilities"]
    assert "sandbox" in contract["delegated_capabilities"]
    assert "approvals" in contract["delegated_capabilities"]


def test_explicit_client_is_selected_when_it_satisfies_requirements() -> None:
    repository = Path(__file__).resolve().parents[1]
    manifest = {
        "harness": {
            "preferred_client": "cline",
            "required_capabilities": ["instructions", "mcp"],
        }
    }

    assert resolve_harness(repository, manifest)["selected_client"] == "cline"


def test_explicit_client_rejects_unsupported_managed_capability() -> None:
    repository = Path(__file__).resolve().parents[1]
    manifest = {
        "harness": {
            "preferred_client": "cline",
            "required_capabilities": ["skills"],
        }
    }

    with pytest.raises(AgentKitError, match="не поддерживает обязательные возможности"):
        resolve_harness(repository, manifest)
