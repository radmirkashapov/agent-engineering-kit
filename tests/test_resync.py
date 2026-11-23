from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_engineering_kit.errors import AgentKitError
from agent_engineering_kit.cli import _print_resync_report
from agent_engineering_kit.component_state import Lifecycle, write_state
from agent_engineering_kit.paths import KitPaths
from agent_engineering_kit.project_skills import ProjectSkillsStatus
from agent_engineering_kit.projects import LogicalProject
from agent_engineering_kit.result import ValidationResult
from agent_engineering_kit.resync import resync
from agent_engineering_kit.resync import build_session_manifest
import agent_engineering_kit.resync as resync_module
from conftest import write_yaml


@pytest.fixture
def native_mcp_environment(monkeypatch, tmp_path: Path):
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    home = tmp_path / "home"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("CODEX_HOME", str(home / ".codex"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setattr(resync_module, "validate", lambda *_args, **_kwargs: ValidationResult())
    monkeypatch.setattr(resync_module.ExternalSkillManager, "resync", lambda *_args, **_kwargs: [])
    for item, lock in resync_module.McpManager(repository, paths).desired():
        if item["required"]:
            binary = paths.installations / "mcp" / item["id"] / "bin" / item["command"]
            binary.parent.mkdir(parents=True)
            binary.touch()
            write_state(paths, "mcp", item["id"], Lifecycle.ACTIVE, revision=lock.revision)
    write_yaml(paths.overrides / "global/docker-toolkit.yaml", {"version": 1, "enabled": True})
    return repository, paths, home


@pytest.mark.parametrize("docker_executable", [None, sys.executable])
@pytest.mark.parametrize("malformed_routes", [False, True])
def test_resync_keeps_native_mcp_when_docker_is_unavailable(
    confirmed_docker_mcp, monkeypatch, capsys, docker_executable, malformed_routes,
):
    repository, paths, config = confirmed_docker_mcp
    if malformed_routes:
        state_path = paths.state / "docker-mcp-toolkit.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state_path.write_text(json.dumps({**state, "routes": None}), encoding="utf-8")
    find_executable = shutil.which

    def which(name):
        if name == "docker":
            return docker_executable
        if name == "claude":
            return None
        return find_executable(name)

    monkeypatch.setattr(shutil, "which", which)
    report = resync(repository, paths, update_kit=False, install_security=False)

    assert any(item["id"] == "context7" and item["status"] == "ACTIVE" for item in report.mcp)
    config_content = config.read_text(encoding="utf-8")
    assert "[mcp_servers.agent-kit-context7]" in config_content
    assert "[mcp_servers.agent-kit-docker]" not in config_content
    _print_resync_report(report)
    assert "SKIPPED: Docker MCP Toolkit" in capsys.readouterr().out


@pytest.fixture
def confirmed_docker_mcp(native_mcp_environment):
    repository, paths, home = native_mcp_environment
    (paths.state / "docker-mcp-toolkit.json").write_text(json.dumps({
        "version": 1, "status": "SYNCED", "project_id": None,
        "profile": "agent-engineering-kit", "gateway_registration": "agent-kit-docker",
        "routes": {"context7": "docker"},
        "managed_servers": {"context7": "catalog://context7"},
    }), encoding="utf-8")
    config = home / ".codex/config.toml"
    config.parent.mkdir(parents=True)
    config.write_text('[mcp_servers.agent-kit-docker]\ncommand = "docker"\n', encoding="utf-8")
    return repository, paths, config


@pytest.mark.parametrize(("exit_code", "profile_output", "snapshot_override", "uses_docker"), [
    (1, "", {}, False),
    (0, '{"servers": []}', {}, False),
    (0, '{"servers": null}', {}, False),
    (0, '{"servers": ["catalog://["]}', {}, False),
    (0, '{"servers": ["catalog://context7"]}', {"profile": "agent-engineering-kit\0extra"}, False),
    (0, '{"servers": ["catalog://context7"]}', {"profile": "agent-engineering-kit\ud800"}, False),
    (0, '{"servers": ["catalog://context7"]}', {"managed_servers": None}, False),
    (0, '{"servers": ["catalog://context7"]}', {"routes": {"context7": "docker", "playwright": None}}, False),
    (0, '{"servers": ["catalog://context7", "catalog://other"]}', {}, True),
])
def test_resync_uses_confirmed_docker_routes_only_when_profile_is_usable(
    confirmed_docker_mcp, monkeypatch, exit_code, profile_output, snapshot_override, uses_docker,
):
    repository, paths, config = confirmed_docker_mcp
    if snapshot_override:
        state_path = paths.state / "docker-mcp-toolkit.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state_path.write_text(json.dumps({**state, **snapshot_override}), encoding="utf-8")
    # Use the Python executable as a fake Docker CLI. Its script is the
    # first argument, which DockerMcpToolkit supplies as "mcp".
    (Path.cwd() / "mcp").write_text(
        "import sys\n"
        "if sys.argv[1:] == ['--help']:\n"
        "    raise SystemExit(0)\n"
        "assert sys.argv[1:] == ['profile', 'show', 'agent-engineering-kit', '--format', 'json']\n"
        f"print({profile_output!r})\n"
        f"raise SystemExit({exit_code})\n",
        encoding="utf-8",
    )
    find_executable = shutil.which

    def which(name):
        if name == "docker":
            return sys.executable
        if name == "claude":
            return None
        return find_executable(name)

    monkeypatch.setattr(shutil, "which", which)

    report = resync(repository, paths, update_kit=False, install_security=False)

    config_content = config.read_text(encoding="utf-8")
    assert ("[mcp_servers.agent-kit-context7]" in config_content) is not uses_docker
    assert ("[mcp_servers.agent-kit-docker]" in config_content) is uses_docker
    assert (report.docker_mcp_skipped is None) is uses_docker


def test_resync_fails_if_required_native_mcp_installation_fails_without_docker(
    native_mcp_environment, monkeypatch,
):
    repository, paths, _ = native_mcp_environment
    (paths.installations / "mcp/context7/bin/npx").unlink()
    find_executable = shutil.which
    monkeypatch.setattr(shutil, "which", lambda name: None if name in {"npx", "docker"} else find_executable(name))

    with pytest.raises(AgentKitError, match="MCP installation: context7"):
        resync(repository, paths, update_kit=False, install_security=False)


def test_resync_initializes_overrides_before_local_validation(monkeypatch, tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    paths = KitPaths(repository, tmp_path / "data", tmp_path / "runtime", tmp_path / "projects", tmp_path / "overrides")
    calls: list[str] = []
    monkeypatch.setattr(resync_module, "ensure_runtime", lambda _paths: calls.append("runtime"))
    monkeypatch.setattr(
        resync_module,
        "initialize_override_workspace",
        lambda _repository, _paths: calls.append("initializer"),
    )
    monkeypatch.setattr(resync_module, "revision", lambda _repository: "revision")
    monkeypatch.setattr(resync_module, "validate", lambda *_args, **_kwargs: SimpleNamespace(ok=True))
    monkeypatch.setattr(
        resync_module,
        "validate_overrides",
        lambda *_args, **_kwargs: SimpleNamespace(ok=False, diagnostics=[SimpleNamespace(severity="ERROR", message="stop")]),
    )

    with pytest.raises(AgentKitError, match="local overrides validation"):
        resync(repository, paths, update_kit=False, install_security=False)

    assert calls == ["runtime", "initializer"]


def test_resync_rejects_corrupted_toggle_before_mutating_runtime(monkeypatch, tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    paths = KitPaths(repository, tmp_path / "data", tmp_path / "runtime", tmp_path / "projects", tmp_path / "overrides")
    paths.state.mkdir(parents=True)
    status_path = paths.state / "agent-kit-status.json"
    status_path.write_text("{broken", encoding="utf-8")
    calls: list[str] = []
    monkeypatch.setattr(resync_module, "ensure_runtime", lambda _paths: calls.append("runtime"))
    monkeypatch.setattr(resync_module, "initialize_override_workspace", lambda *_args: calls.append("initializer"))

    with pytest.raises(AgentKitError, match=str(status_path)):
        resync(repository, paths, update_kit=False, install_security=False)

    assert calls == ["runtime"]


def test_session_manifest_records_harness_and_effective_policy_digest(tmp_path: Path) -> None:
    policy = tmp_path / "effective-policy.json"
    policy.write_text('{"version":1}\n', encoding="utf-8")
    harness = {
        "control_plane": "agent-engineering-kit",
        "execution_owner": "client",
        "selected_client": "codex",
    }

    manifest = build_session_manifest(
        revision="abc123",
        project_id="demo",
        security=[],
        skills=[],
        mcp=[],
        clients=["codex"],
        harness=harness,
        effective_policy=policy,
        recorded_at="2026-10-09T00:00:00+00:00",
    )

    assert manifest["schema"] == "agent-engineering-kit/effective-environment/v2"
    assert manifest["harness"] == harness
    assert manifest["effective_policy_sha256"] == "50208d78350a7a160dec59a82df1499b6ca7da33e54c5eb11c97e342118e68bb"


@pytest.fixture
def resync_environment(monkeypatch, tmp_path: Path):
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    project = LogicalProject(tmp_path, tmp_path / ".ai-team/project.yaml", {"id": "demo"})
    calls: list[str] = []
    published_projects: list[LogicalProject | None] = []

    monkeypatch.setattr(resync_module, "revision", lambda *_args: "kit123")
    monkeypatch.setattr(resync_module, "validate", lambda *_args, **_kwargs: SimpleNamespace(ok=True))
    monkeypatch.setattr(resync_module, "validate_overrides", lambda *_args, **_kwargs: SimpleNamespace(ok=True))
    monkeypatch.setattr(resync_module, "effective_skill_sources", lambda *_args, **_kwargs: {"example": object()})
    monkeypatch.setattr(resync_module, "initialize_override_workspace", lambda *_args: None)
    monkeypatch.setattr(resync_module.SecurityToolManager, "install",
                        lambda *_args, **_kwargs: calls.append("security-install") or SimpleNamespace(ok=True))
    monkeypatch.setattr(resync_module.SecurityToolManager, "status",
                        lambda *_args: calls.append("security-status") or [])
    monkeypatch.setattr(resync_module.ExternalSkillManager, "resync",
                        lambda *_args, **_kwargs: calls.append("external-skills") or [])
    monkeypatch.setattr(resync_module.ExternalSkillManager, "list", lambda *_args: [])
    monkeypatch.setattr(resync_module, "resolve_effective_policy", lambda *_args: SimpleNamespace(
        values={"mcp.access_profile": "readonly"}, as_dict=lambda: {},
    ))
    monkeypatch.setattr(resync_module.McpManager, "install",
                        lambda *_args, **_kwargs: calls.append("mcp") or SimpleNamespace(ok=True))
    monkeypatch.setattr(resync_module.McpManager, "list", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(resync_module.McpManager, "desired", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(resync_module, "resolve_harness", lambda *_args, **_kwargs: {})

    def sync(_repository, _paths, **kwargs):
        calls.append("clients")
        published_projects.append(kwargs.get("project"))
        policy = paths.installations / "clients/shared/effective-policy.json"
        policy.parent.mkdir(parents=True, exist_ok=True)
        policy.write_text("{}\n", encoding="utf-8")
        return []

    def expose(_repository, _paths, **kwargs):
        calls.append("native-skills")
        published_projects.append(kwargs.get("project"))
        return []

    def register(*_args, **_kwargs):
        registration = data / "registrations.json"
        registration.write_text('{"registrations": []}\n', encoding="utf-8")
        return registration

    monkeypatch.setattr(resync_module, "sync_clients", sync)
    monkeypatch.setattr(resync_module, "expose_native_skills", expose)
    monkeypatch.setattr(resync_module, "expose_native_instructions", lambda *_args: [])
    monkeypatch.setattr(resync_module, "register_native_mcp", register)
    return SimpleNamespace(repository=repository, paths=paths, project=project,
                           calls=calls, published_projects=published_projects)


@pytest.mark.parametrize("state", ["ACTIVE", "STALE", "UPDATE_REJECTED", "NOT_CONFIGURED"])
def test_resync_updates_project_skills_before_client_sync(monkeypatch, resync_environment, state: str) -> None:
    env = resync_environment
    validated_skill_ids: list[set[str] | None] = []
    monkeypatch.setattr(
        resync_module,
        "validate_overrides",
        lambda *_args, **kwargs: validated_skill_ids.append(kwargs.get("additional_skill_ids"))
        or SimpleNamespace(ok=True),
    )
    status = ProjectSkillsStatus(
        project_id="demo", source_url="https://user:password@example.invalid/skills.git?token=private",
        default_branch="main", requested_branch="feature", resolved_revision="abc123",
        active_revision="abc123" if state != "NOT_CONFIGURED" else None, state=state,
        reason="fetch https://user:password@example.invalid/skills.git?token=private failed" if state == "STALE" else None,
        updated_at="2026-10-26T00:00:00+03:00", skills=("example",),
    )

    class FakeProjectSkills:
        def __init__(self, repository, paths, project):
            assert (repository, paths, project) == (env.repository, env.paths, env.project)
            env.calls.append("project-skills-manager")

        def resync(self):
            env.calls.append("project-skills")
            return status

    monkeypatch.setattr(resync_module, "ProjectSkillRepositoryManager", FakeProjectSkills, raising=False)

    report = resync(env.repository, env.paths, project=env.project, update_kit=False)

    assert env.calls == ["security-install", "security-status", "project-skills-manager", "project-skills",
                         "external-skills", "mcp", "clients", "native-skills"]
    assert validated_skill_ids == [{"example"}]
    assert env.published_projects == [env.project, env.project]
    assert report.project_skills == status.as_dict()
    manifest_text = (env.paths.state / "effective-environment.json").read_text(encoding="utf-8")
    assert json.loads(manifest_text)["project_skills"] == status.as_dict()
    assert all(value not in json.dumps(report.project_skills) + manifest_text
               for value in ("password", "token=private", "user:"))


def test_resync_propagates_initial_project_skills_failure(monkeypatch, resync_environment) -> None:
    env = resync_environment

    class FailedProjectSkills:
        def resync(self):
            raise AgentKitError("initial fetch failed")

    monkeypatch.setattr(resync_module, "ProjectSkillRepositoryManager",
                        lambda *_args: FailedProjectSkills(), raising=False)

    with pytest.raises(AgentKitError, match="initial fetch failed"):
        resync(env.repository, env.paths, project=env.project, update_kit=False)

    assert env.published_projects == []
    assert not (env.paths.state / "effective-environment.json").exists()


def test_resync_without_project_skips_project_skills(monkeypatch, resync_environment) -> None:
    env = resync_environment

    def unexpected_manager(*_args):
        pytest.fail("Project skills manager требует LogicalProject")

    monkeypatch.setattr(resync_module, "ProjectSkillRepositoryManager", unexpected_manager, raising=False)

    report = resync(env.repository, env.paths, update_kit=False, install_security=False, expose_native=False)

    assert report.project_skills is None
    assert env.published_projects == [None]
    assert json.loads((env.paths.state / "effective-environment.json").read_text())["project_skills"] is None


def test_resync_registers_client_models_after_client_adapters(monkeypatch, resync_environment) -> None:
    env = resync_environment
    monkeypatch.setattr(
        resync_module,
        "sync_client_models",
        lambda *_args, **_kwargs: env.calls.append("models") or {"codex": {"status": "SYNCED"}},
    )

    resync(env.repository, env.paths, update_kit=False, install_security=False, expose_native=False)

    assert env.calls[-2:] == ["clients", "models"]


def test_session_manifest_records_project_skills(tmp_path: Path) -> None:
    policy = tmp_path / "policy.json"
    policy.write_text("{}\n", encoding="utf-8")
    project_skills = {
        "state": "ACTIVE", "requested_branch": "main",
        "resolved_revision": "abc123", "active_revision": "abc123",
    }

    manifest = build_session_manifest(
        revision="kit123", project_id="demo", security=[], skills=[], mcp=[], clients=[],
        harness={}, effective_policy=policy, recorded_at="2026-10-26T00:00:00+03:00",
        project_skills=project_skills,
    )

    assert manifest["project_skills"] == project_skills
