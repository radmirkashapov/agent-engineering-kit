from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from agent_engineering_kit.docker_mcp import DockerMcpToolkit, confirmed_docker_routes
from agent_engineering_kit.errors import AgentKitError
from agent_engineering_kit.paths import KitPaths
from agent_engineering_kit.process import CommandResult


REPOSITORY = Path(__file__).resolve().parents[1]


def _paths(tmp_path: Path) -> KitPaths:
    data = tmp_path / "data"
    return KitPaths(REPOSITORY, data, data / "runtime", data / "projects", data / "overrides")


def test_effective_config_merges_global_and_project_overrides(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    global_override = paths.overrides / "global/docker-toolkit.yaml"
    global_override.parent.mkdir(parents=True)
    global_override.write_text(
        "# Локальное включение Docker Toolkit.\nenabled: true\nprofile: team-profile\n",
        encoding="utf-8",
    )
    project_override = paths.overrides / "projects/shop/docker-toolkit.yaml"
    project_override.parent.mkdir(parents=True)
    project_override.write_text(
        "# Project mapping имеет высший приоритет.\nmappings:\n  github: catalog://custom-github\n",
        encoding="utf-8",
    )

    config = DockerMcpToolkit(REPOSITORY, paths, docker_executable="docker").effective_config("shop")

    assert config["enabled"] is True
    assert config["profile"] == "team-profile"
    assert config["mappings"]["github"] == "catalog://custom-github"
    assert config["mappings"]["playwright"] == "catalog://playwright"


def test_mapping_uri_with_credentials_is_rejected(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    override = paths.overrides / "global/docker-toolkit.yaml"
    override.parent.mkdir(parents=True)
    override.write_text(
        "# Credentials запрещены.\nmappings:\n  github: https://user:secret@example.com/server\n",
        encoding="utf-8",
    )

    with pytest.raises(AgentKitError, match="credentials"):
        DockerMcpToolkit(REPOSITORY, paths, docker_executable="docker").effective_config(None)


def test_plan_keeps_native_routes_until_toolkit_is_ready(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    override = paths.overrides / "global/docker-toolkit.yaml"
    override.parent.mkdir(parents=True)
    override.write_text("# Включить Docker runtime.\nenabled: true\n", encoding="utf-8")

    def runner(args, **kwargs):
        return CommandResult(tuple(args), 1, "", "docker: 'mcp' is not a docker command")

    plan = DockerMcpToolkit(REPOSITORY, paths, runner=runner, docker_executable="docker").plan(
        desired_ids={"github", "context7"}
    )

    assert plan["status"] == "CONFIG_REQUIRED"
    assert plan["routes"] == {"context7": "native", "github": "unavailable"}
    assert plan["operations"] == []


def test_disable_invalidates_confirmed_routes_before_client_resync(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    paths.state.mkdir(parents=True)
    (paths.state / "docker-mcp-toolkit.json").write_text(
        json.dumps({
            "status": "SYNCED",
            "project_id": None,
            "routes": {"github": "docker"},
            "managed_servers": {"github": "catalog://github-official"},
        }),
        encoding="utf-8",
    )

    DockerMcpToolkit(REPOSITORY, paths, docker_executable="docker").set_enabled(
        scope="global", project_id=None, enabled=False
    )

    routes, state = confirmed_docker_routes(paths, None)
    assert routes == set()
    assert state["status"] == "PENDING"
    assert state["managed_servers"] == {"github": "catalog://github-official"}


def test_sync_manages_only_owned_servers_and_is_idempotent(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    override = paths.overrides / "global/docker-toolkit.yaml"
    override.parent.mkdir(parents=True)
    override.write_text("# Включить Docker runtime.\nenabled: true\n", encoding="utf-8")
    servers = {"user-owned": "catalog://user-owned"}
    profile_exists = False
    calls: list[list[str]] = []

    def runner(args, **kwargs):
        nonlocal profile_exists
        command = list(args)
        calls.append(command)
        if command[1:3] == ["mcp", "--help"]:
            return CommandResult(tuple(args), 0, "MCP Toolkit", "")
        if command[1:5] == ["mcp", "profile", "show", "agent-engineering-kit"]:
            if not profile_exists:
                return CommandResult(tuple(args), 1, "", "not found")
            payload = {"name": "agent-engineering-kit", "servers": [{"name": key, "uri": value} for key, value in sorted(servers.items())]}
            return CommandResult(tuple(args), 0, json.dumps(payload), "")
        if command[1:5] == ["mcp", "profile", "create", "--name"]:
            profile_exists = True
            return CommandResult(tuple(args), 0, "", "")
        if command[1:6] == ["mcp", "profile", "server", "add", "agent-engineering-kit"]:
            uri = command[command.index("--server") + 1]
            servers[uri.rsplit("/", 1)[-1]] = uri
            return CommandResult(tuple(args), 0, "", "")
        if command[1:6] == ["mcp", "profile", "server", "remove", "agent-engineering-kit"]:
            servers.pop(command[command.index("--name") + 1], None)
            return CommandResult(tuple(args), 0, "", "")
        return CommandResult(tuple(args), 1, "", "unexpected")

    manager = DockerMcpToolkit(REPOSITORY, paths, runner=runner, docker_executable="docker")
    first = manager.sync(desired_ids={"github"})
    first_call_count = len(calls)
    second = manager.sync(desired_ids={"github"})

    assert first["status"] == second["status"] == "SYNCED"
    assert servers == {"github-official": "catalog://github-official", "user-owned": "catalog://user-owned"}
    assert len(calls) == first_call_count + 3  # probe, inspect, verification; mutating commands отсутствуют
    state = json.loads((paths.state / "docker-mcp-toolkit.json").read_text(encoding="utf-8"))
    assert state["routes"] == {"github": "docker"}
    assert state["managed_servers"] == {"github": "catalog://github-official"}
