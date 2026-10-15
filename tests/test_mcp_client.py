from __future__ import annotations

from pathlib import Path

from agent_engineering_kit.mcp_client import McpToolClient
from agent_engineering_kit.errors import AgentKitError
from agent_engineering_kit.paths import KitPaths
from conftest import write_yaml
import pytest


def _client(tmp_path: Path) -> McpToolClient:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    return McpToolClient(repository, paths)


def test_github_connection_plan_enforces_read_only_and_lockdown(tmp_path: Path) -> None:
    plan = _client(tmp_path).connection_plan("github")

    assert plan["transport"] == "stdio"
    assert plan["environment"]["GITHUB_READ_ONLY"] == "1"
    assert plan["environment"]["GITHUB_LOCKDOWN_MODE"] == "1"
    assert plan["environment"]["GITHUB_TOOLSETS"] == "pull_requests"
    assert plan["args"].count("-e") == 4
    assert "GITHUB_READ_ONLY=1" in plan["args"]
    assert "GITHUB_LOCKDOWN_MODE=1" in plan["args"]
    assert "GITHUB_TOOLSETS=pull_requests" in plan["args"]


def test_gitlab_connection_plan_limits_toolsets_and_uses_oauth_storage(tmp_path: Path) -> None:
    client = _client(tmp_path)

    plan = client.connection_plan("gitlab")

    assert plan["transport"] == "http"
    assert plan["headers"] == {
        "X-Gitlab-Enabled-Mcp-Server-Toolsets": "merge_requests"
    }
    assert plan["authentication"] == "oauth"
    assert plan["oauth_storage"] == str(client.paths.data / "auth/mcp/gitlab.json")


def test_dedicated_reader_respects_explicit_local_mcp_block(tmp_path: Path) -> None:
    client = _client(tmp_path)
    write_yaml(
        client.paths.overrides / "global/access.yaml",
        {"version": 1, "mcp": {"allow": [], "block": ["gitlab"]}},
    )

    with pytest.raises(AgentKitError, match="явно отключён"):
        client.connection_plan("gitlab")
