from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_engineering_kit.errors import AgentKitError
from agent_engineering_kit.paths import KitPaths
from agent_engineering_kit.project_skills import ProjectSkillsStatus
from agent_engineering_kit.projects import LogicalProject
from agent_engineering_kit.resync import resync
from agent_engineering_kit.resync import build_session_manifest
import agent_engineering_kit.resync as resync_module


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
