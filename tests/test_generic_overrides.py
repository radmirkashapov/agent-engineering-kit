from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_engineering_kit.errors import AgentKitError
from agent_engineering_kit.io import load_yaml
from agent_engineering_kit.override_service import OverrideScope, install_generic_override, list_overrides, reset_generic_override
from agent_engineering_kit.paths import KitPaths
from agent_engineering_kit.policy import effective_policy


REPOSITORY = Path(__file__).resolve().parents[1]


def _write(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
    return path


def test_generic_policy_override_bypasses_restriction_with_reason(tmp_path: Path) -> None:
    paths = KitPaths(REPOSITORY, tmp_path / "data", tmp_path / "runtime", tmp_path / "projects", tmp_path / "overrides")
    scope = OverrideScope("global", paths.overrides / "global", None)
    source = _write(tmp_path / "value.yaml", {"value": "autonomous"})

    target = install_generic_override(
        scope,
        "approvals",
        "profile",
        mode="replace",
        source=source,
        reason="Use an isolated local workstation",
    )
    policy = effective_policy(REPOSITORY, paths)

    assert target == scope.root / "policy" / "approvals-profile.yaml"
    assert policy.values["approvals.profile"] == "autonomous"
    assert policy.warnings
    assert policy.provenance["approvals.profile"][-1]["reason"] == "Use an isolated local workstation"


def test_generic_component_override_requires_reason_and_can_reset(tmp_path: Path) -> None:
    scope = OverrideScope("global", tmp_path / "overrides/global", None)
    source = _write(tmp_path / "value.yaml", {"value": {"role": "Custom developer"}})

    with pytest.raises(AgentKitError, match="причина"):
        install_generic_override(scope, "agents", "developer", mode="extend", source=source, reason="")

    target = install_generic_override(
        scope,
        "agents",
        "developer",
        mode="extend",
        source=source,
        reason="Use local team terminology",
    )
    assert load_yaml(target)["override"]["reason"] == "Use local team terminology"
    assert list_overrides(scope)[0]["kind"] == "agents"
    moved = reset_generic_override(scope, "agents", "developer", tmp_path / "backups")
    assert moved
    assert not target.exists()


def test_mcp_access_profile_is_a_policy_override_not_a_server_override(tmp_path: Path) -> None:
    paths = KitPaths(REPOSITORY, tmp_path / "data", tmp_path / "runtime", tmp_path / "projects", tmp_path / "overrides")
    scope = OverrideScope("global", paths.overrides / "global", None)
    source = _write(tmp_path / "value.yaml", {"value": "administrator"})

    target = install_generic_override(
        scope,
        "mcp",
        "access-profile",
        mode="replace",
        source=source,
        reason="Allow the complete local MCP surface",
    )

    assert target == scope.root / "policy/mcp-access-profile.yaml"
    assert effective_policy(REPOSITORY, paths).values["mcp.access_profile"] == "administrator"


def test_generic_override_rejects_unknown_kind_and_path_escape(tmp_path: Path) -> None:
    scope = OverrideScope("global", tmp_path / "overrides/global", None)
    source = _write(tmp_path / "value.yaml", {"value": {}})

    with pytest.raises(AgentKitError, match="тип"):
        install_generic_override(scope, "unknown", "item", mode="extend", source=source, reason="test")
    with pytest.raises(AgentKitError, match="ID"):
        install_generic_override(scope, "agents", "../../item", mode="extend", source=source, reason="test")
    with pytest.raises(AgentKitError, match="replace"):
        install_generic_override(scope, "network", "mode", mode="disable", source=source, reason="test")
