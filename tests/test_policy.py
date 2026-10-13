from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_engineering_kit.errors import AgentKitError
from agent_engineering_kit.explain import explain
from agent_engineering_kit.paths import KitPaths
from agent_engineering_kit.policy import load_policy_overrides, resolve_policy
from conftest import write_yaml


REPOSITORY = Path(__file__).resolve().parents[1]


def test_restriction_override_is_effective_with_warning_and_provenance() -> None:
    layers = [{"source": "corporate", "entries": [{"key": "network.enabled", "value": False, "classification": "restriction"}]}]
    overrides = [{"key": "network.enabled", "value": True, "reason": "Local development", "source": "user-global"}]

    result = resolve_policy(layers, overrides)

    assert result.values["network.enabled"] is True
    assert result.classifications["network.enabled"] == "restriction"
    assert result.warnings
    assert result.provenance["network.enabled"][-1] == {
        "source": "user-global", "classification": "restriction", "value": True,
        "reason": "Local development", "decision": "override-restriction",
    }


def test_preference_override_does_not_warn() -> None:
    layers = [{"source": "kit", "entries": [{"key": "client.preferred", "value": "codex", "classification": "preference"}]}]

    result = resolve_policy(layers, [{"key": "client.preferred", "value": "cline", "reason": "Local choice", "source": "user-global"}])

    assert result.values["client.preferred"] == "cline"
    assert result.warnings == []


def test_invariant_override_blocks_activation() -> None:
    layers = [{"source": "technical-invariants", "entries": [{"key": "secrets.in_git", "value": False, "classification": "invariant"}]}]

    with pytest.raises(AgentKitError, match="инвариант"):
        resolve_policy(layers, [{"key": "secrets.in_git", "value": True, "reason": "Test", "source": "user-global"}])


def test_later_layer_cannot_downgrade_an_invariant_even_when_value_matches() -> None:
    layers = [
        {"source": "technical-invariants", "entries": [{"key": "secrets.in_git", "value": False, "classification": "invariant"}]},
        {"source": "project", "entries": [{"key": "secrets.in_git", "value": False, "classification": "preference"}]},
    ]

    with pytest.raises(AgentKitError, match="инвариант"):
        resolve_policy(layers)


def test_final_invariant_layer_applies_after_local_overrides() -> None:
    layers = [{"source": "kit", "entries": [{"key": "network.enabled", "value": False, "classification": "restriction"}]}]
    final_layers = [{"source": "technical-invariants", "entries": [{"key": "secrets.in_git", "value": False, "classification": "invariant"}]}]

    result = resolve_policy(
        layers,
        [{"key": "network.enabled", "value": True, "reason": "Local work", "source": "user-global"}],
        final_layers=final_layers,
    )

    assert result.values == {"network.enabled": True, "secrets.in_git": False}
    assert list(result.provenance) == ["network.enabled", "secrets.in_git"]
    with pytest.raises(AgentKitError, match="инвариант"):
        resolve_policy(layers, [{"key": "secrets.in_git", "value": True, "reason": "Test"}], final_layers=final_layers)


def test_convention_override_blocks_activation() -> None:
    layers = [{"source": "kit-conventions", "entries": [{"key": "conventions.documentation-ownership", "value": True, "classification": "invariant"}]}]

    with pytest.raises(AgentKitError, match="инвариант"):
        resolve_policy(layers, [{"key": "conventions.documentation-ownership", "value": False, "reason": "Test", "source": "user-global"}])


def test_override_reason_is_required_and_validated(tmp_path: Path) -> None:
    paths = KitPaths(REPOSITORY, tmp_path, tmp_path / "runtime", tmp_path / "projects", tmp_path / "overrides")
    write_yaml(paths.overrides / "global" / "policy" / "network.yaml", {
        "version": 1, "overrides": [{"key": "network.enabled", "value": True}],
    })

    with pytest.raises(AgentKitError, match="reason"):
        load_policy_overrides(REPOSITORY, paths)


def test_project_policy_override_wins_over_global(tmp_path: Path) -> None:
    paths = KitPaths(REPOSITORY, tmp_path, tmp_path / "runtime", tmp_path / "projects", tmp_path / "overrides")
    write_yaml(paths.overrides / "global" / "policy" / "network.yaml", {
        "version": 1, "overrides": [{"key": "network.enabled", "value": True, "reason": "Global"}],
    })
    write_yaml(paths.overrides / "projects" / "sample" / "policy" / "network.yaml", {
        "version": 1, "overrides": [{"key": "network.enabled", "value": False, "reason": "Project"}],
    })

    overrides = load_policy_overrides(REPOSITORY, paths, "sample")

    assert [entry["source"] for entry in overrides] == ["user-global", "user-project"]
    assert [entry["reason"] for entry in overrides] == ["Global", "Project"]


def test_project_id_cannot_escape_local_override_root(tmp_path: Path) -> None:
    paths = KitPaths(REPOSITORY, tmp_path, tmp_path / "runtime", tmp_path / "projects", tmp_path / "overrides")

    with pytest.raises(AgentKitError, match="project ID"):
        load_policy_overrides(REPOSITORY, paths, "../outside")


def test_explain_json_contains_effective_policy_and_provenance(tmp_path: Path) -> None:
    paths = KitPaths(REPOSITORY, tmp_path, tmp_path / "runtime", tmp_path / "projects", tmp_path / "overrides")

    payload = json.loads(explain(REPOSITORY, paths, tmp_path, output_format="json"))

    assert payload["policy"]["values"]["secrets.in_git"] is False
    assert payload["policy"]["classifications"]["secrets.in_git"] == "invariant"
    assert payload["policy"]["provenance"]["secrets.in_git"][0]["source"] == "technical-invariants"
    assert "documentation-ownership" in {entry["id"] for entry in payload["conventions"]}
    assert payload["policy"]["provenance"]["conventions.documentation-ownership"][0]["source"] == "kit:conventions/documentation.yaml"


def test_explain_json_shows_local_override_reason(tmp_path: Path) -> None:
    paths = KitPaths(REPOSITORY, tmp_path, tmp_path / "runtime", tmp_path / "projects", tmp_path / "overrides")
    write_yaml(paths.overrides / "global" / "policy" / "client.yaml", {
        "version": 1, "overrides": [{"key": "client.preferred", "value": "cline", "reason": "Local trial"}],
    })

    payload = json.loads(explain(REPOSITORY, paths, tmp_path, output_format="json"))

    assert payload["policy"]["values"]["client.preferred"] == "cline"
    assert payload["policy"]["provenance"]["client.preferred"][-1]["reason"] == "Local trial"


def test_policy_rejects_value_outside_target_domain() -> None:
    with pytest.raises(AgentKitError, match="approvals.profile"):
        resolve_policy(
            [{"source": "kit", "entries": [{"key": "approvals.profile", "value": "readonly", "classification": "restriction"}]}],
            [{"key": "approvals.profile", "value": "unsafe-magic", "reason": "test"}],
        )

    with pytest.raises(AgentKitError, match="mcp.access_profile"):
        resolve_policy(
            [{"source": "kit", "entries": [{"key": "mcp.access_profile", "value": "readonly", "classification": "restriction"}]}],
            [{"key": "mcp.access_profile", "value": "superuser", "reason": "test"}],
        )
