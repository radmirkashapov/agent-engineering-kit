from __future__ import annotations

from pathlib import Path

import json
import pytest
import shutil
import sys
import yaml

from agent_engineering_kit.clients import CLIENTS, expose_native_instructions, expose_native_skills, register_native_mcp, sync_clients, validate_clients
from agent_engineering_kit.paths import KitPaths
from agent_engineering_kit.component_state import Lifecycle, write_state
from agent_engineering_kit.mcp_credentials import McpCredentialStore
from agent_engineering_kit.mcp_manager import McpManager
from agent_engineering_kit.projects import LogicalProject
from agent_engineering_kit.errors import AgentKitError
from agent_engineering_kit.process import CommandResult
from agent_engineering_kit.explain import explain
from conftest import write_yaml


def write_publication_skill(path: Path, identifier: str, marker: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text(
        f"---\nversion: 1\nname: {identifier}\ndescription: Use this skill for testing publication.\n"
        "requires:\n  model_capabilities: []\n---\n", encoding="utf-8",
    )
    (path / f"{marker}.txt").write_text(marker, encoding="utf-8")


@pytest.mark.parametrize("layer", ["built-in", "external-catalog", "local-override", "local-package-override"])
def test_skill_precedence_selects_one_directory_with_shadowed_provenance(tmp_path: Path, layer: str) -> None:
    real = Path(__file__).resolve().parents[1]
    repository = tmp_path / "kit"
    for directory in ("clients", "schemas"):
        shutil.copytree(real / directory, repository / directory)
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    builtin = repository / "skills/first-party/example"
    write_publication_skill(builtin, "example", "builtin-only")
    external = paths.installations / "skills/bundle/revisions" / ("a" * 40)
    write_publication_skill(external / "skills/example", "example", "external-only")
    package = "example" if layer == "local-package-override" else "bundle"
    write_yaml(repository / "catalog/skills.yaml", {"version": 1, "skills": [{
        "id": package, "source": {"repository": "https://user:password@example.invalid/skills.git?token=private#secret"},
        "capabilities": ["example"],
    }]})
    write_yaml(repository / "locks/skills.lock.yaml", {"version": 1, "components": [{
        "id": package, "version": "1", "revision": "a" * 40,
    }]})
    if layer != "built-in":
        write_state(paths, "skills", package, Lifecycle.ACTIVE,
                    installation_path=str(external), revision="a" * 40)
    local = tmp_path / "local/example"
    if layer.startswith("local-"):
        write_publication_skill(local, "example", "local-only")
        write_yaml(paths.overrides / "global/skills/example.yaml", {
            "target": "example", "override": {"mode": "replace", "value": {"path": str(local)}},
        })

    sync_clients(repository, paths)

    shared = paths.installations / "clients/shared"
    selected = {"built-in": builtin, "external-catalog": external / "skills/example",
                "local-override": local, "local-package-override": local}[layer]
    assert (shared / "skills/example").resolve() == selected
    assert sorted(path.name for path in (shared / "skills/example").iterdir()) == sorted(path.name for path in selected.iterdir())
    text = (shared / "skills-provenance.json").read_text(encoding="utf-8")
    row = json.loads(text)["skills"]["example"]
    assert row["source"] == ("local-override" if layer.startswith("local-") else layer)
    expected_shadowed = {"built-in": [], "external-catalog": ["built-in"],
                         "local-override": ["built-in", "external-catalog"],
                         "local-package-override": ["built-in", "external-catalog"]}[layer]
    assert [item["source"] for item in row["shadowed"]] == expected_shadowed
    if layer != "built-in":
        external_row = row if layer == "external-catalog" else row["shadowed"][1]
        assert external_row["source_url"] == "<redacted-url>"
        assert external_row["revision"] == "a" * 40
    assert all(secret not in text for secret in ("password", "token=private", "#secret", "user:"))


def test_sync_preserves_builtin_skill_validation(tmp_path: Path) -> None:
    repository = tmp_path / "kit"
    real = Path(__file__).resolve().parents[1]
    for directory in ("clients", "catalog", "locks", "schemas"):
        shutil.copytree(real / directory, repository / directory)
    skill = repository / "skills/first-party/example"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: example\n---\n# Invalid", encoding="utf-8")
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")

    with pytest.raises(AgentKitError, match="local skill override"):
        sync_clients(repository, paths)


def test_external_package_allowlist_keeps_publishing_its_capabilities(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    external = paths.installations / "skills/superpowers/revisions" / ("a" * 40)
    write_publication_skill(external / "skills/brainstorming", "brainstorming", "external-only")
    write_state(paths, "skills", "superpowers", Lifecycle.ACTIVE,
                installation_path=str(external), revision="a" * 40)
    write_yaml(paths.overrides / "global/access.yaml", {
        "version": 1, "skills": {"allow": ["superpowers"], "block": []},
    })

    sync_clients(repository, paths)

    shared = paths.installations / "clients/shared/skills"
    assert (shared / "brainstorming").resolve() == external / "skills/brainstorming"
    assert not (shared / "verification").exists()


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
    assert len(additions) == 2
    assert all(any(value.startswith("agent-kit-") for value in args) for args in additions)
    assert sum("https://mcp.context7.com/mcp/oauth" in args for args in additions) == 2
    registrations = json.loads(state_path.read_text(encoding="utf-8"))["registrations"]
    assert sum(item.get("mcp") == "context7" and item["status"] == "AUTH_REQUIRED" for item in registrations) == 2


@pytest.mark.parametrize("credential_source", ["missing", "vault", "shell"])
@pytest.mark.parametrize("server,variable", [("github", "GITHUB_PERSONAL_ACCESS_TOKEN"), ("sonarqube", "SONARQUBE_TOKEN")])
@pytest.mark.parametrize("required_only", [False, True])
def test_stdio_mcp_with_environment_is_registered_through_launcher(
    tmp_path: Path, monkeypatch, credential_source: str, server: str, variable: str, required_only: bool,
) -> None:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    (root / "sonar-project.properties").write_text("sonar.projectKey=fixture\n", encoding="utf-8")
    project = LogicalProject(root, root / ".ai-team/project.yaml", {
        "id": "project", "repositories": [{"id": "root", "path": "."}],
    })
    write_yaml(paths.overrides / "global/access.yaml", {
        "version": 1, "mcp": {"allow": [server, "context7"], "block": []},
    })
    if required_only:
        registry = yaml.safe_load((repository / "mcp/registry.yaml").read_text(encoding="utf-8"))
        definition = next(item for item in registry["servers"] if item["id"] == server)
        definition.pop("environment")
        write_yaml(paths.overrides / f"global/mcp/{server}.yaml", {"target": server, "override": {"mode": "replace", "value": definition}})
    monkeypatch.delenv(variable, raising=False)
    monkeypatch.setattr("agent_engineering_kit.clients.shutil.which", lambda name: f"/usr/bin/{name}" if name in {"codex", "claude", "docker"} else None)
    if credential_source == "vault":
        source = tmp_path / "credentials.env"
        source.write_text(f"{variable}=fixture-secret\n", encoding="utf-8")
        McpCredentialStore(paths).import_file(source, McpManager(repository, paths).available())
    elif credential_source == "shell":
        monkeypatch.setenv(variable, "fixture-secret")
    calls: list[list[str]] = []
    client_commands: dict[str, list[str]] = {
        "/usr/bin/codex": ["/usr/bin/docker", "run"],
        "/usr/bin/claude": ["/usr/bin/docker", "run"],
    }

    def runner(args, **kwargs):
        calls.append(list(args))
        if list(args[:3]) == ["git", "remote", "-v"]:
            return CommandResult(tuple(args), 0, "origin https://github.com/acme/repo.git (fetch)\n", "")
        if "add" in args and f"agent-kit-{server}" in args:
            client_commands[args[0]] = list(args[args.index("--") + 1:])
        if "get" in args and f"agent-kit-{server}" in args and args[0] in client_commands:
            command = client_commands[args[0]]
            output = json.dumps({"transport": {"type": "stdio", "command": command[0], "args": command[1:]}}) if Path(args[0]).name == "codex" else " ".join(command)
            return CommandResult(tuple(args), 0, output, "")
        return CommandResult(tuple(args), 1 if "get" in args else 0, "", "")

    state_path = register_native_mcp(repository, paths, project=project, access_profile="administrator", runner=runner)

    additions = [call for call in calls if "add" in call and f"agent-kit-{server}" in call]
    contract_path = paths.installations / "clients/shared/mcp-launchers" / f"{server}.json"
    assert len(additions) == 2
    assert sum("remove" in call and f"agent-kit-{server}" in call for call in calls) == 2
    assert all(call[call.index("--") + 1:] == [sys.executable, "-m", "agent_engineering_kit.mcp_launcher", str(contract_path.resolve())] for call in additions)
    assert variable not in json.dumps(additions)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    assert contract["required_environment"] == [variable]
    assert contract["command"] == str(Path("/usr/bin/docker").resolve())
    state_text = state_path.read_text(encoding="utf-8")
    assert "fixture-secret" not in json.dumps(calls) + state_text + contract_path.read_text(encoding="utf-8")
    server_rows = [row for row in json.loads(state_text)["registrations"] if row.get("mcp") == server and row["client"] in {"codex", "claude-code"}]
    assert len(server_rows) == 2
    assert all(row["desired_verified"] for row in server_rows)
    assert all(row["status"] == ("CONFIG_REQUIRED" if credential_source == "missing" else "ACTIVE") for row in server_rows)
    if credential_source == "missing":
        assert all(row["missing_environment"] == [variable] for row in server_rows)

    calls.clear()
    register_native_mcp(repository, paths, project=project, access_profile="administrator", runner=runner)
    assert not any(("add" in call or "remove" in call) and f"agent-kit-{server}" in call for call in calls)
    server_rows = [row for row in json.loads(state_path.read_text(encoding="utf-8"))["registrations"] if row.get("mcp") == server and row["client"] in {"codex", "claude-code"}]
    assert all(row["changed"] is False and row["desired_verified"] for row in server_rows)
    assert all(row["status"] == ("CONFIG_REQUIRED" if credential_source == "missing" else "ACTIVE") for row in server_rows)
    if credential_source == "missing":
        assert all(row["missing_environment"] == [variable] for row in server_rows)


def test_stale_launcher_cleanup_is_limited_to_managed_directory(tmp_path: Path, monkeypatch) -> None:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    launcher_root = paths.installations / "clients/shared/mcp-launchers"
    launcher_root.mkdir(parents=True)
    stale = [launcher_root / f"{name}.json" for name in ("removed-server", "context7", "sentry")]
    for path in stale:
        path.write_text("{}", encoding="utf-8")
    outside = paths.state / "outside.json"
    outside.parent.mkdir(parents=True)
    outside.write_text("preserve", encoding="utf-8")
    (launcher_root / "external.json").symlink_to(outside)
    notes = launcher_root / "notes.txt"
    notes.write_text("preserve", encoding="utf-8")
    nested = launcher_root / "nested/server.json"
    nested.parent.mkdir()
    nested.write_text("preserve", encoding="utf-8")
    monkeypatch.delenv("SENTRY_ACCESS_TOKEN", raising=False)
    monkeypatch.setattr("agent_engineering_kit.clients.shutil.which", lambda _: None)

    register_native_mcp(repository, paths)

    assert all(not path.exists() for path in stale)
    assert not (launcher_root / "external.json").is_symlink()
    assert outside.read_text(encoding="utf-8") == "preserve"
    assert notes.read_text(encoding="utf-8") == "preserve"
    assert nested.read_text(encoding="utf-8") == "preserve"


def test_launcher_cleanup_does_not_follow_symlinked_directory(tmp_path: Path, monkeypatch) -> None:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    outside = tmp_path / "outside"
    outside.mkdir()
    contract = outside / "user-owned.json"
    contract.write_text("preserve", encoding="utf-8")
    launcher_root = paths.installations / "clients/shared/mcp-launchers"
    launcher_root.parent.mkdir(parents=True)
    launcher_root.symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr("agent_engineering_kit.clients.shutil.which", lambda _: None)

    register_native_mcp(repository, paths)

    assert contract.read_text(encoding="utf-8") == "preserve"


@pytest.mark.parametrize("linked_parent", ["clients", "shared"])
def test_launcher_cleanup_does_not_follow_symlinked_parent(tmp_path: Path, monkeypatch, linked_parent: str) -> None:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    outside = tmp_path / "outside"
    external_launchers = outside / ("shared/mcp-launchers" if linked_parent == "clients" else "mcp-launchers")
    external_launchers.mkdir(parents=True)
    foreign = external_launchers / "foreign.json"
    foreign.write_text("preserve", encoding="utf-8")
    link = paths.installations / "clients"
    if linked_parent == "shared":
        link /= "shared"
    link.parent.mkdir(parents=True)
    link.symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr("agent_engineering_kit.clients.shutil.which", lambda _: None)

    register_native_mcp(repository, paths)

    assert foreign.read_text(encoding="utf-8") == "preserve"
    assert link.is_symlink()


@pytest.mark.parametrize("route", ["disabled", "direct", "docker"])
def test_launcher_contract_is_removed_when_server_no_longer_needs_it(tmp_path: Path, monkeypatch, route: str) -> None:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    monkeypatch.setenv("SENTRY_ACCESS_TOKEN", "fixture-secret")
    monkeypatch.setattr("agent_engineering_kit.clients.shutil.which", lambda name: f"/usr/bin/{name}" if name in {"codex", "claude", "npx", "docker"} else None)
    calls: list[list[str]] = []

    def runner(args, **kwargs):
        calls.append(list(args))
        return CommandResult(tuple(args), 1 if "get" in args else 0, "", "")

    state_path = register_native_mcp(repository, paths, runner=runner)
    contract = paths.installations / "clients/shared/mcp-launchers/sentry.json"
    assert contract.is_file()
    if route == "disabled":
        write_yaml(paths.overrides / "global/access.yaml", {"version": 1, "mcp": {"allow": [], "block": ["sentry"]}})
    elif route == "direct":
        registry = yaml.safe_load((repository / "mcp/registry.yaml").read_text(encoding="utf-8"))
        sentry = next(item for item in registry["servers"] if item["id"] == "sentry")
        sentry.pop("environment")
        sentry.pop("required_environment")
        write_yaml(paths.overrides / "global/mcp/sentry.yaml", {"target": "sentry", "override": {"mode": "replace", "value": sentry}})
    else:
        (paths.state / "docker-mcp-toolkit.json").write_text(json.dumps({
            "version": 1, "status": "SYNCED", "project_id": None,
            "profile": "agent-engineering-kit", "gateway_registration": "agent-kit-docker",
            "routes": {"sentry": "docker"}, "managed_servers": {"sentry": "catalog://sentry"},
        }), encoding="utf-8")

    calls.clear()
    register_native_mcp(repository, paths, runner=runner)

    assert not contract.exists()
    additions = [call for call in calls if "add" in call]
    if route == "direct":
        sentry = [call for call in additions if "agent-kit-sentry" in call]
        assert len(sentry) == 2
        assert all(call[call.index("--") + 1:] == ["/usr/bin/npx", "-y", "@sentry/mcp-server@0.42.0", "--skills=inspect", "--sentry-dsn="] for call in sentry)
    else:
        assert not any("agent-kit-sentry" in call for call in additions)
    if route == "docker":
        gateway = [call for call in additions if "agent-kit-docker" in call]
        assert len(gateway) == 2
        assert all(call[call.index("--") + 1:] == ["/usr/bin/docker", "mcp", "gateway", "run", "--profile", "agent-engineering-kit"] for call in gateway)
        rows = json.loads(state_path.read_text(encoding="utf-8"))["registrations"]
        assert sum(row.get("mcp") == "sentry" and row["status"] == "DOCKER_ROUTED" for row in rows) == 2


def test_registration_failure_does_not_persist_client_output_with_credentials(tmp_path: Path, monkeypatch) -> None:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    monkeypatch.setenv("SENTRY_ACCESS_TOKEN", "fixture-private-value")
    monkeypatch.setattr("agent_engineering_kit.clients.shutil.which", lambda name: f"/usr/bin/{name}" if name in {"codex", "claude", "npx"} else None)

    def runner(args, **kwargs):
        return CommandResult(tuple(args), 1, "client echo fixture-private-value", "failure fixture-private-value")

    state_path = register_native_mcp(repository, paths, runner=runner)

    text = state_path.read_text(encoding="utf-8")
    assert "fixture-private-value" not in text
    rows = [row for row in json.loads(text)["registrations"] if row.get("mcp") == "sentry" and row["client"] in {"codex", "claude-code"}]
    assert len(rows) == 2
    assert all(row["status"] == "ERROR" and row["desired_verified"] is False for row in rows)


def test_confirmed_docker_route_replaces_native_server_with_one_gateway(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    root = tmp_path / "web-project"
    root.mkdir()
    (root / "package.json").write_text('{"name":"web-project"}', encoding="utf-8")
    project = __import__("agent_engineering_kit.projects", fromlist=["LogicalProject"]).LogicalProject(
        root,
        root / ".ai-team/project.yaml",
        {"id": "web-project", "repositories": [{"id": "root", "path": "."}]},
    )
    for identifier, command in (("codebase-memory", "codebase-memory-mcp"), ("serena", "serena")):
        binary = paths.installations / "mcp" / identifier / "bin" / command
        binary.parent.mkdir(parents=True, exist_ok=True)
        binary.write_text("fixture", encoding="utf-8")
    paths.state.mkdir(parents=True)
    (paths.state / "docker-mcp-toolkit.json").write_text(
        json.dumps({
            "version": 1,
            "status": "SYNCED",
            "project_id": "web-project",
            "profile": "agent-engineering-kit",
            "gateway_registration": "agent-kit-docker",
            "routes": {"context7": "docker"},
            "managed_servers": {"context7": "catalog://context7"},
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "agent_engineering_kit.clients.shutil.which",
        lambda name: f"/usr/bin/{name}" if name in {"codex", "claude", "npx", "docker"} else None,
    )
    calls: list[list[str]] = []

    def runner(args, **kwargs):
        calls.append(list(args))
        return CommandResult(tuple(args), 1 if "get" in args else 0, "", "")

    register_native_mcp(repository, paths, project=project, access_profile="administrator", runner=runner)

    additions = [args for args in calls if "add" in args]
    assert not any("agent-kit-context7" in args for args in additions)
    gateway = [args for args in additions if "agent-kit-docker" in args]
    assert len(gateway) == 2
    assert all(Path(args[-6]).name == "docker" for args in gateway)
    assert all(args[-5:] == ["mcp", "gateway", "run", "--profile", "agent-engineering-kit"] for args in gateway)


def test_write_capable_scm_server_is_not_registered_under_readonly_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    project = __import__("agent_engineering_kit.projects", fromlist=["LogicalProject"]).LogicalProject(
        root,
        root / ".ai-team/project.yaml",
        {"id": "project", "repositories": [{"id": "root", "path": "."}]},
    )
    monkeypatch.setattr("agent_engineering_kit.clients.shutil.which", lambda name: f"/usr/bin/{name}" if name in {"codex", "claude"} else None)
    calls: list[list[str]] = []

    def runner(args, **kwargs):
        calls.append(list(args))
        if list(args[:3]) == ["git", "remote", "-v"]:
            return CommandResult(tuple(args), 0, "origin https://github.com/acme/repo.git (fetch)\n", "")
        return CommandResult(tuple(args), 1 if "get" in args else 0, "", "")

    state_path = register_native_mcp(repository, paths, project=project, runner=runner)

    additions = [args for args in calls if "mcp" in args and "add" in args]
    assert not any("agent-kit-github" in args for args in additions)
    github_rows = [
        row for row in json.loads(state_path.read_text(encoding="utf-8"))["registrations"]
        if row.get("mcp") == "github"
    ]
    assert github_rows
    assert all(row["status"] == "DISABLED" for row in github_rows)


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

    (paths.state / "docker-mcp-toolkit.json").write_text(
        json.dumps({
            "status": "SYNCED",
            "project_id": None,
            "profile": "agent-engineering-kit",
            "gateway_registration": "agent-kit-docker",
            "routes": {"context7": "docker"},
            "managed_servers": {"context7": "catalog://context7"},
        }),
        encoding="utf-8",
    )
    write_yaml(paths.overrides / "global/access.yaml", {"version": 1, "mcp": {"allow": [], "block": ["context7"]}})
    state_path = register_native_mcp(repository, paths, runner=runner)

    assert all("agent-kit-context7" not in registrations for registrations in client_state.values())
    assert all("agent-kit-docker" not in registrations for registrations in client_state.values())
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


def test_capability_policy_is_materialized_for_client_harness(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")

    sync_clients(
        repository,
        paths,
        capability_policy={"values": {"approvals.profile": "autonomous"}, "provenance": {}, "warnings": []},
    )

    policy = json.loads((paths.installations / "clients/shared/effective-policy.json").read_text(encoding="utf-8"))
    assert policy["capability_policy"]["values"]["approvals.profile"] == "autonomous"
