from __future__ import annotations

from pathlib import Path

import json
import pytest
import shutil
import yaml

from agent_engineering_kit.clients import CLIENTS, expose_native_instructions, expose_native_skills, register_native_mcp, sync_clients, validate_clients
from agent_engineering_kit.paths import KitPaths
from agent_engineering_kit.errors import AgentKitError
from agent_engineering_kit.process import CommandResult
from agent_engineering_kit.explain import explain
from conftest import write_yaml


def test_client_adapters_validate() -> None:
    repository = Path(__file__).resolve().parents[1]
    assert validate_clients(repository).ok


def test_duplicate_client_contract_is_rejected(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    candidate = tmp_path / "kit"
    shutil.copytree(repository / "clients", candidate / "clients")
    shutil.copytree(repository / "catalog", candidate / "catalog")
    document = yaml.safe_load((candidate / "catalog/clients.yaml").read_text(encoding="utf-8"))
    document["clients"].append(dict(document["clients"][0]))
    write_yaml(candidate / "catalog/clients.yaml", document)

    result = validate_clients(candidate)

    assert not result.ok
    assert any("ровно один раз" in item.message for item in result.diagnostics)


def test_config_explain_names_control_plane_and_execution_harness(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")

    output = explain(repository, paths, tmp_path)

    assert "Harness:" in output
    assert "control plane: agent-engineering-kit" in output
    assert "execution owner: client" in output
    assert "selected client: codex" in output


def test_sync_generates_thin_runtime_adapters(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    generated = sync_clients(repository, paths)
    assert len(generated) == len(CLIENTS)
    content = (data / "runtime/clients/codex/adapter.yaml").read_text(encoding="utf-8")
    expected = (
        "# Сгенерировано agent-kit; локальный runtime, не Git.\n"
        f"kit_repository: {repository}\n"
        f"entrypoint: {repository / 'AI.md'}\n"
        f"effective_policy: {data / 'installations/clients/shared/effective-policy.json'}\n"
        f"skills: {data / 'installations/clients/shared/skills'}\n"
        f"mcp_registry: {repository / 'mcp' / 'registry.yaml'}\n"
    )
    assert content == expected
    assert str(tmp_path) not in "\n".join(path.read_text(encoding="utf-8") for path in repository.glob("clients/*/adapter.yaml"))


def test_core_mcp_registration_is_namespaced_and_oauth_safe(tmp_path: Path, monkeypatch) -> None:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    for identifier, command in (("codebase-memory", "codebase-memory-mcp"), ("serena", "serena")):
        binary = paths.installations / "mcp" / identifier / "bin" / command
        binary.parent.mkdir(parents=True)
        binary.write_text("fixture", encoding="utf-8")
    monkeypatch.setattr("agent_engineering_kit.clients.shutil.which", lambda name: f"/usr/bin/{name}" if name in {"codex", "claude"} else None)
    calls: list[list[str]] = []

    def runner(args, **kwargs):
        calls.append(args)
        return CommandResult(tuple(args), 1 if "get" in args else 0, "", "")

    state_path = register_native_mcp(repository, paths, runner=runner)
    additions = [args for args in calls if "add" in args]
    assert len(additions) == 6
    assert all(any(value.startswith("agent-kit-") for value in args) for args in additions)
    assert sum("https://mcp.context7.com/mcp/oauth" in args for args in additions) == 2
    registrations = json.loads(state_path.read_text(encoding="utf-8"))["registrations"]
    assert sum(item.get("mcp") == "context7" and item["status"] == "AUTH_REQUIRED" for item in registrations) == 2


def test_blocked_mcp_is_removed_from_previously_registered_native_clients(tmp_path: Path, monkeypatch) -> None:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    monkeypatch.setattr("agent_engineering_kit.clients.shutil.which", lambda name: f"/usr/bin/{name}" if name in {"codex", "claude"} else None)
    client_state = {
        "codex": {"user-owned"},
        "claude-code": {"user-owned"},
    }

    def runner(args, **kwargs):
        client = "codex" if Path(args[0]).name == "codex" else "claude-code"
        if args[2] == "get":
            name = args[3]
            if name not in client_state[client]:
                return CommandResult(tuple(args), 1, "", "не найден")
            output = (
                json.dumps({"transport": {"url": "https://mcp.context7.com/mcp/oauth"}})
                if client == "codex"
                else "https://mcp.context7.com/mcp/oauth"
            )
            return CommandResult(tuple(args), 0, output, "")
        if args[2] == "add":
            name = args[3] if client == "codex" else args[-2]
            client_state[client].add(name)
            return CommandResult(tuple(args), 0, "", "")
        if args[2] == "remove":
            client_state[client].discard(args[3])
            return CommandResult(tuple(args), 0, "", "")
        return CommandResult(tuple(args), 1, "", "неподдерживаемая команда")

    register_native_mcp(repository, paths, runner=runner)
    assert all("agent-kit-context7" in registrations for registrations in client_state.values())

    write_yaml(paths.overrides / "global/access.yaml", {"version": 1, "mcp": {"allow": [], "block": ["context7"]}})
    state_path = register_native_mcp(repository, paths, runner=runner)

    assert all("agent-kit-context7" not in registrations for registrations in client_state.values())
    assert all("user-owned" in registrations for registrations in client_state.values())
    rows = json.loads(state_path.read_text(encoding="utf-8"))["registrations"]
    disabled = [row for row in rows if row.get("mcp") == "context7" and row["status"] == "DISABLED"]
    assert {row["client"] for row in disabled} == {"codex", "claude-code"}


def test_missing_cli_preserves_managed_registration_for_later_cleanup(tmp_path: Path, monkeypatch) -> None:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    state_path = paths.state / "client-mcp-registrations.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps({"version": 1, "registrations": [{"client": "codex", "mcp": "context7", "status": "AUTH_REQUIRED"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr("agent_engineering_kit.clients.shutil.which", lambda _: None)

    register_native_mcp(repository, paths)

    rows = json.loads(state_path.read_text(encoding="utf-8"))["registrations"]
    preserved = next(row for row in rows if row.get("client") == "codex" and row.get("mcp") == "context7")
    assert preserved["status"] == "NOT_SUPPORTED"


def test_instruction_bridge_preserves_user_text_and_is_idempotent(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    paths = KitPaths(repository, tmp_path / "data", tmp_path / "runtime", tmp_path / "projects", tmp_path / "overrides")
    target = tmp_path / ".codex/AGENTS.md"
    target.parent.mkdir(parents=True)
    target.write_text("# Мои инструкции\n", encoding="utf-8")
    expose_native_instructions(repository, paths, home=tmp_path)
    first = target.read_text(encoding="utf-8")
    expose_native_instructions(repository, paths, home=tmp_path)
    assert target.read_text(encoding="utf-8") == first
    assert "# Мои инструкции" in first
    assert first.count("agent-engineering-kit:start") == 1


def test_stale_managed_skill_exposure_is_removed(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    root = tmp_path / "discovery"
    expose_native_skills(repository, paths, roots=(root,))
    stale = root / "obsolete"
    stale.symlink_to(paths.installations / "clients/shared/skills/change-impact", target_is_directory=True)
    state = paths.state / "managed-skill-exposures.json"
    document = json.loads(state.read_text(encoding="utf-8"))
    document["paths"].append(str(stale))
    state.write_text(json.dumps(document), encoding="utf-8")
    expose_native_skills(repository, paths, roots=(root,))
    assert not stale.exists() and not stale.is_symlink()


def test_stale_user_symlink_with_installations_prefix_is_preserved(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    root = tmp_path / "discovery"
    expose_native_skills(repository, paths, roots=(root,))
    user_skill = tmp_path / "data/installations-user/custom"
    user_skill.mkdir(parents=True)
    stale = root / "user-owned"
    stale.symlink_to(user_skill, target_is_directory=True)
    state = paths.state / "managed-skill-exposures.json"
    document = json.loads(state.read_text(encoding="utf-8"))
    document["paths"].append(str(stale))
    state.write_text(json.dumps(document), encoding="utf-8")

    expose_native_skills(repository, paths, roots=(root,))

    assert stale.resolve() == user_skill


def test_user_owned_skill_symlink_collision_is_preserved(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    root = tmp_path / "discovery"
    user_skill = tmp_path / "user-skill"
    user_skill.mkdir()
    root.mkdir()
    collision = root / "change-impact"
    collision.symlink_to(user_skill, target_is_directory=True)
    with pytest.raises(AgentKitError, match="пользовательским symlink"):
        expose_native_skills(repository, paths, roots=(root,))
    assert collision.resolve() == user_skill


def test_user_owned_symlink_inside_data_overrides_is_preserved(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    root = tmp_path / "discovery"
    user_skill = paths.overrides / "global/skills/change-impact"
    user_skill.mkdir(parents=True)
    root.mkdir()
    collision = root / "change-impact"
    collision.symlink_to(user_skill, target_is_directory=True)

    with pytest.raises(AgentKitError, match="пользовательским symlink"):
        expose_native_skills(repository, paths, roots=(root,))

    assert collision.resolve() == user_skill


def test_agent_and_rule_overrides_are_materialized_into_effective_policy(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    agent_override = paths.overrides / "global/agents/reviewer.yaml"
    agent_override.parent.mkdir(parents=True)
    agent_override.write_text("target: reviewer\noverride:\n  mode: extend\n  value:\n    local_note: strict\n", encoding="utf-8")
    rule_override = paths.overrides / "projects/demo/rules/review.yaml"
    rule_override.parent.mkdir(parents=True)
    rule_override.write_text("target: review\noverride:\n  mode: extend\n  value:\n    local_note: project\n", encoding="utf-8")

    sync_clients(repository, paths, project_id="demo")

    policy = json.loads((paths.installations / "clients/shared/effective-policy.json").read_text(encoding="utf-8"))
    assert next(item for item in policy["agents"] if item["id"] == "reviewer")["local_note"] == "strict"
    assert next(item for item in policy["rules"] if item["id"] == "review")["local_note"] == "project"


def test_disabled_skill_is_removed_from_shared_discovery(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    write_yaml(paths.overrides / "global/access.yaml", {"version": 1, "skills": {"allow": [], "block": ["verification"]}})

    sync_clients(repository, paths)

    shared = paths.installations / "clients/shared/skills"
    assert not (shared / "verification").exists()
    compatibility = (paths.runtime / "clients/codex/adapter.yaml").read_text(encoding="utf-8")
    assert f"skills: {shared}" in compatibility
    assert f"skills: {repository / 'skills'}" not in compatibility


def test_explain_reports_access_policy_layer_and_reason(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    write_yaml(paths.overrides / "global/access.yaml", {"version": 1, "mcp": {"allow": [], "block": ["context7"]}, "skills": {"allow": [], "block": ["verification"]}})

    output = explain(repository, paths, tmp_path)

    assert "verification: disabled; DISABLED; access: blocked:global" in output
    assert "context7: disabled; DISABLED; access: blocked:global" in output
