from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from agent_engineering_kit.errors import AgentKitError
from agent_engineering_kit.paths import KitPaths
from agent_engineering_kit.projects import LogicalProject, find_project, init_project, register_memory, validate_project
import agent_engineering_kit.projects as projects_module
from agent_engineering_kit.bindings import attach_project, bind_repository, project_readiness, reconcile_project


@pytest.fixture
def kit_repository() -> Path:
    return Path(__file__).resolve().parents[1]


def paths(tmp_path: Path, repository: Path) -> KitPaths:
    data = tmp_path / "data"
    return KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")


def test_single_repo_project(tmp_path: Path, kit_repository: Path) -> None:
    root = tmp_path / "single-repository"
    (root / ".git").mkdir(parents=True)
    project = init_project(root, kit_repository, paths(tmp_path, kit_repository))
    assert project.manifest["repositories"] == [{"id": "root", "path": "."}]
    assert project.manifest["harness"] == {
        "preferred_client": "auto",
        "required_capabilities": ["instructions", "skills", "mcp"],
    }
    assert (root / "docs/INDEX.md").is_file()
    assert validate_project(project, kit_repository).ok


def test_project_init_indexes_memory_immediately(
    tmp_path: Path,
    kit_repository: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    indexed: list[tuple[str, str]] = []

    class FakeMemoryManager:
        def __init__(self, repository: Path, kit_paths: KitPaths) -> None:
            assert repository == kit_repository

        def index(self, project, *, mode: str):
            indexed.append((project.identifier, mode))
            return {"status": "PASS"}

    monkeypatch.setattr(projects_module, "ProjectMemoryManager", FakeMemoryManager)

    init_project(tmp_path / "indexed-project", kit_repository, paths(tmp_path, kit_repository))

    assert indexed == [("indexed-project", "full")]


def test_monorepo_detects_nested_components(tmp_path: Path, kit_repository: Path) -> None:
    root = tmp_path / "platform-monorepo"
    (root / ".git").mkdir(parents=True)
    (root / "backend").mkdir()
    (root / "backend/pyproject.toml").write_text("[project]\nname='backend'\n", encoding="utf-8")
    (root / "frontend").mkdir()
    (root / "frontend/package.json").write_text('{"name":"frontend"}', encoding="utf-8")
    (root / "backend/services/worker").mkdir(parents=True)
    (root / "backend/services/worker/pyproject.toml").write_text("[project]\nname='worker'\n", encoding="utf-8")
    project = init_project(root, kit_repository, paths(tmp_path, kit_repository))
    assert project.manifest["components"] == []
    added = reconcile_project(project, paths(tmp_path, kit_repository))["diff"]["added"]
    assert {item["path"] for item in added} == {"backend", "frontend", "backend/services/worker"}


def test_multi_repo_workspace(tmp_path: Path, kit_repository: Path) -> None:
    root = tmp_path / "platform-workspace"
    for name in ("backend", "frontend", "infrastructure"):
        (root / name / ".git").mkdir(parents=True)
    project = init_project(root, kit_repository, paths(tmp_path, kit_repository), identifier="platform-v2")
    assert {item["path"] for item in project.manifest["repositories"]} == {"backend", "frontend", "infrastructure"}
    nested = root / "backend/services/api"
    nested.mkdir(parents=True)
    assert find_project(nested).identifier == "platform-v2"


def test_stable_project_id_and_idempotent_init(tmp_path: Path, kit_repository: Path) -> None:
    root = tmp_path / "stable-project"
    first = init_project(root, kit_repository, paths(tmp_path, kit_repository), identifier="stable-id")
    second = init_project(root, kit_repository, paths(tmp_path, kit_repository), identifier="ignored-new-id")
    assert first.identifier == second.identifier == "stable-id"


def test_project_id_collision_fails(tmp_path: Path, kit_repository: Path) -> None:
    kit_paths = paths(tmp_path, kit_repository)
    first = init_project(tmp_path / "first-project", kit_repository, kit_paths, identifier="shared-id")
    register_memory(first, kit_paths)
    with pytest.raises(AgentKitError, match="Collision"):
        init_project(tmp_path / "second-project", kit_repository, kit_paths, identifier="shared-id")


def _skills_source(project, url="git@gitlab.example.com:team/project-skills.git"):
    project.manifest["skills"] = {"repository": {"url": url, "default_branch": "main"}}
    return project


def _shared_project(root: Path) -> LogicalProject:
    root.mkdir()
    return LogicalProject(root, root / ".ai-team/project.yaml", {
        "version": 1, "id": "shared", "name": root.name,
        "repositories": [{"id": "root", "path": "."}],
        "documentation": {"index": "docs/INDEX.md", "roots": ["docs"]},
        "memory": {"namespace": "shared"},
    })


@pytest.mark.parametrize("url", [
    "git@gitlab.example.com:team/project-skills.git",
    "https://example.com/team/project-skills.git",
])
def test_project_manifest_accepts_project_skills_repository(tmp_path, kit_repository, url):
    project = _skills_source(init_project(tmp_path / "first", kit_repository, paths(tmp_path, kit_repository)), url)
    assert validate_project(project, kit_repository).ok
    assert project.skills_repository == {"url": url, "default_branch": "main"}


def test_project_skills_absence_is_not_configured(tmp_path, kit_repository):
    project = init_project(tmp_path / "first", kit_repository, paths(tmp_path, kit_repository))
    assert "skills" not in project.manifest
    assert project.skills_repository is None


@pytest.mark.parametrize("url", [
    "https://user:secret@example.com/project-skills.git",
    "https://example.com/project-skills.git?token=secret",
    "https://example.com/project-skills.git#secret",
    "",
])
def test_project_skills_url_rejects_credentials(tmp_path, kit_repository, url):
    project = _skills_source(_shared_project(tmp_path / "unsafe"), url)
    assert not validate_project(project, kit_repository).ok


@pytest.mark.parametrize("prior_identity", [False, True])
@pytest.mark.parametrize("skills", [
    {"repository": {"url": "https://user:secret@example.com/project-skills.git", "default_branch": "main"}},
    {"repository": {"url": "https://example.com/project-skills.git?token=secret", "default_branch": "main"}},
    {"repository": {"url": "https://example.com/project-skills.git#secret", "default_branch": "main"}},
    None,
    "invalid",
    {"repository": "invalid"},
    {"repository": {"default_branch": "main"}},
])
def test_project_skills_unsafe_existing_manifest_preserves_identity(tmp_path, kit_repository, prior_identity, skills):
    kit_paths = paths(tmp_path, kit_repository)
    project = _shared_project(tmp_path / "existing")
    identity_path = kit_paths.projects / "shared/identity.json"
    if prior_identity:
        register_memory(project, kit_paths)
    before = identity_path.read_bytes() if identity_path.exists() else None
    project.manifest["skills"] = skills
    project.manifest_path.parent.mkdir()
    project.manifest_path.write_text(json.dumps(project.manifest), encoding="utf-8")

    with pytest.raises(AgentKitError) as error:
        init_project(project.root, kit_repository, kit_paths)

    assert "secret" not in str(error.value)
    assert (identity_path.read_bytes() if identity_path.exists() else None) == before


@pytest.mark.parametrize("branch", ["", "feature/../bad", "bad branch", "bad~ref", "bad^ref", "bad:ref", "bad?ref", "bad*ref", "bad\\ref", "bad[ref"])
def test_project_skills_rejects_invalid_branch(tmp_path, kit_repository, branch):
    project = _skills_source(_shared_project(tmp_path / "unsafe"))
    project.manifest["skills"]["repository"]["default_branch"] = branch
    assert not validate_project(project, kit_repository).ok


@pytest.mark.parametrize("skills", [{}, {"repository": {}}, {"repository": {"url": "safe"}}, {"repository": {"url": "safe", "default_branch": "main", "extra": True}}])
def test_project_skills_requires_complete_source(tmp_path, kit_repository, skills):
    project = _shared_project(tmp_path / "unsafe")
    project.manifest["skills"] = skills
    assert not validate_project(project, kit_repository).ok


def test_shared_project_id_requires_identical_skills_source(tmp_path, kit_repository):
    kit_paths = paths(tmp_path, kit_repository)
    first = _skills_source(_shared_project(tmp_path / "first"))
    second = _skills_source(_shared_project(tmp_path / "second"), " git@gitlab.example.com:team/project-skills.git/ ")
    register_memory(first, kit_paths)
    register_memory(second, kit_paths)
    register_memory(first, kit_paths)
    identity = json.loads((kit_paths.projects / "shared/identity.json").read_text())
    assert identity["project_id"] == "shared"
    assert identity["skills_repository_url"] == "git@gitlab.example.com:team/project-skills.git"
    assert identity["root_hashes"] == sorted([
        hashlib.sha256(str(first.root).encode()).hexdigest(),
        hashlib.sha256(str(second.root).encode()).hexdigest(),
    ])


@pytest.mark.parametrize("second_source", [None, "git@gitlab.example.com:other/project-skills.git", "https://gitlab.example.com/team/project-skills.git", "git@gitlab.example.com:team/project-skills"])
def test_shared_project_id_rejects_missing_or_different_source(tmp_path, kit_repository, second_source):
    kit_paths = paths(tmp_path, kit_repository)
    first = _skills_source(_shared_project(tmp_path / "first"))
    second = _shared_project(tmp_path / "second")
    if second_source:
        _skills_source(second, second_source)
    register_memory(first, kit_paths)
    identity_path = kit_paths.projects / "shared/identity.json"
    before = identity_path.read_text()
    with pytest.raises(AgentKitError, match="Collision"):
        register_memory(second, kit_paths)
    assert identity_path.read_text() == before


@pytest.mark.parametrize("legacy", [False, True])
def test_shared_project_id_adopts_source_only_from_existing_root(tmp_path, kit_repository, legacy):
    kit_paths = paths(tmp_path, kit_repository)
    first = _shared_project(tmp_path / "first")
    second = _skills_source(_shared_project(tmp_path / "second"))
    register_memory(first, kit_paths)
    identity_path = kit_paths.projects / "shared/identity.json"
    if legacy:
        identity_path.write_text(json.dumps({"project_id": "shared", "root_hash": hashlib.sha256(str(first.root).encode()).hexdigest()}))
    with pytest.raises(AgentKitError, match="Collision"):
        register_memory(second, kit_paths)
    register_memory(_skills_source(first), kit_paths)
    register_memory(second, kit_paths)
    assert len(json.loads(identity_path.read_text())["root_hashes"]) == 2


@pytest.mark.parametrize("replacement", [None, "https://example.com/different.git"])
def test_shared_project_id_rejects_source_change_for_registered_root(tmp_path, kit_repository, replacement):
    kit_paths = paths(tmp_path, kit_repository)
    first = _skills_source(_shared_project(tmp_path / "first"))
    second = _skills_source(_shared_project(tmp_path / "second"))
    register_memory(first, kit_paths)
    register_memory(second, kit_paths)
    if replacement:
        _skills_source(first, replacement)
    else:
        first.manifest.pop("skills")
    with pytest.raises(AgentKitError, match="Collision"):
        register_memory(first, kit_paths)


@pytest.mark.parametrize("replacement", [None, "https://example.com/different.git"])
def test_project_skills_single_root_can_replace_or_remove_source(tmp_path, kit_repository, replacement):
    kit_paths = paths(tmp_path, kit_repository)
    project = _skills_source(_shared_project(tmp_path / "first"))
    register_memory(project, kit_paths)
    if replacement:
        _skills_source(project, replacement)
    else:
        project.manifest.pop("skills")
    register_memory(project, kit_paths)
    identity = json.loads((kit_paths.projects / "shared/identity.json").read_text())
    assert identity["skills_repository_url"] == replacement


def test_memory_has_expected_isolated_shape(tmp_path: Path, kit_repository: Path) -> None:
    kit_paths = paths(tmp_path, kit_repository)
    project = init_project(tmp_path / "isolated-project", kit_repository, kit_paths)
    memory = kit_paths.projects / project.identifier
    assert {path.name for path in memory.iterdir()} == {
        "state", "sessions", "summaries", "checkpoints", "integrations", "identity.json"
    }
    assert json.loads((memory / "identity.json").read_text())["project_id"] == project.identifier


def test_attach_creates_only_machine_local_descriptor(tmp_path: Path, kit_repository: Path) -> None:
    root = tmp_path / "external"
    root.mkdir()
    kit_paths = paths(tmp_path, kit_repository)
    project = attach_project(root, kit_repository, kit_paths, identifier="external-project")
    assert project.identifier == "external-project"
    assert project.manifest_path == kit_paths.projects / "external-project" / "project.yaml"
    assert not (root / ".ai-team").exists()
    assert project_readiness(project, kit_paths)["status"] == "READY"


def test_bindings_keep_absolute_paths_out_of_committed_manifest(tmp_path: Path, kit_repository: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    backend = tmp_path / "backend"
    backend.mkdir()
    kit_paths = paths(tmp_path, kit_repository)
    project = init_project(root, kit_repository, kit_paths)
    project.manifest["repositories"].append({"id": "backend", "path": "backend", "required": True})
    bind_repository(project, kit_paths, "backend", backend)
    assert "backend" not in project.manifest_path.read_text(encoding="utf-8")
    bindings = (kit_paths.projects / project.identifier / "bindings.yaml").read_text(encoding="utf-8")
    assert str(backend) in bindings
    assert project_readiness(project, kit_paths)["status"] == "READY"


def test_readiness_distinguishes_missing_optional_required_and_remote_mismatch(tmp_path: Path, kit_repository: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    kit_paths = paths(tmp_path, kit_repository)
    project = init_project(root, kit_repository, kit_paths)
    project.manifest["repositories"].append({"id": "docs", "path": "docs-repo", "required": False})
    assert project_readiness(project, kit_paths)["status"] == "DEGRADED"
    project.manifest["repositories"].append({"id": "api", "path": "api-repo", "required": True})
    assert project_readiness(project, kit_paths)["status"] == "BLOCKED"
    project.manifest["repositories"] = [{"id": "root", "path": ".", "remote": "https://example.com/wrong.git"}]
    (root / ".git").mkdir()
    (root / ".git/config").write_text('[remote "origin"]\nurl = https://example.com/actual.git\n', encoding="utf-8")
    assert project_readiness(project, kit_paths)["status"] == "MISMATCHED"


def test_reconcile_preview_is_read_only_and_apply_is_machine_local(tmp_path: Path, kit_repository: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "pyproject.toml").write_text('[project]\nname = "service"\n', encoding="utf-8")
    kit_paths = paths(tmp_path, kit_repository)
    project = init_project(root, kit_repository, kit_paths)
    inventory_path = kit_paths.projects / project.identifier / "state" / "component-inventory.json"
    preview = reconcile_project(project, kit_paths)
    assert preview["diff"]["added"][0]["id"] == "python:service"
    assert preview["workspace_structure_change"] is True
    assert not inventory_path.exists()
    applied = reconcile_project(project, kit_paths, apply=True)
    assert applied["diff"] == preview["diff"]
    assert inventory_path.is_file()
    assert reconcile_project(project, kit_paths)["diff"] == {"added": [], "removed": [], "changed": []}
    assert not (root / ".ai-team/component-inventory.json").exists()


def test_reconcile_honors_project_discovery_exclusions(tmp_path: Path, kit_repository: Path) -> None:
    root = tmp_path / "workspace"
    (root / "app").mkdir(parents=True)
    (root / "generated").mkdir()
    (root / "app/pyproject.toml").write_text('[project]\nname = "app"\n', encoding="utf-8")
    (root / "generated/pyproject.toml").write_text('[project]\nname = "generated"\n', encoding="utf-8")
    kit_paths = paths(tmp_path, kit_repository)
    project = init_project(root, kit_repository, kit_paths)
    project.manifest["discovery"]["exclude_paths"] = ["generated"]
    assert [item["id"] for item in reconcile_project(project, kit_paths)["diff"]["added"]] == ["python:app"]


def test_missing_optional_repo_keeps_last_inventory(tmp_path: Path, kit_repository: Path) -> None:
    root = tmp_path / "workspace"
    docs = tmp_path / "docs-external"
    docs.mkdir(parents=True)
    (docs / "pyproject.toml").write_text('[project]\nname = "docs"\n', encoding="utf-8")
    kit_paths = paths(tmp_path, kit_repository)
    project = init_project(root, kit_repository, kit_paths)
    project.manifest["repositories"].append({"id": "docs", "path": "docs-repo", "required": False})
    bind_repository(project, kit_paths, "docs", docs)
    reconcile_project(project, kit_paths, apply=True)
    (docs / "pyproject.toml").unlink()
    docs.rmdir()
    preview = reconcile_project(project, kit_paths)
    assert preview["status"] == "DEGRADED"
    assert preview["diff"]["removed"] == []


@pytest.mark.parametrize(
    "remote",
    [
        "https://example.com/repository.git?access_token=secret",
        "https://example.com/repository.git#credential",
        "https://user:secret@example.com/repository.git",
    ],
)
def test_committed_remote_rejects_credential_bearing_urls(
    tmp_path: Path,
    kit_repository: Path,
    remote: str,
) -> None:
    project = init_project(tmp_path / "unsafe-remote", kit_repository, paths(tmp_path, kit_repository))
    project.manifest["repositories"][0]["remote"] = remote

    result = validate_project(project, kit_repository)

    assert not result.ok


def test_root_binding_cannot_be_reassigned_without_explicit_migration(
    tmp_path: Path,
    kit_repository: Path,
) -> None:
    kit_paths = paths(tmp_path, kit_repository)
    original = tmp_path / "original"
    replacement = tmp_path / "replacement"
    original.mkdir()
    replacement.mkdir()
    project = attach_project(original, kit_repository, kit_paths, identifier="stable-root")

    with pytest.raises(AgentKitError, match="root binding"):
        bind_repository(project, kit_paths, "root", replacement)

    assert project_readiness(project, kit_paths)["repositories"]["root"] == str(original)


def test_manifest_components_refine_and_extend_discovered_inventory(
    tmp_path: Path,
    kit_repository: Path,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "pyproject.toml").write_text('[project]\nname = "service"\n', encoding="utf-8")
    kit_paths = paths(tmp_path, kit_repository)
    project = init_project(root, kit_repository, kit_paths)
    project.manifest["components"] = [
        {
            "id": "python:service",
            "repository": "root",
            "path": ".",
            "owner": "platform-team",
            "criticality": "critical",
        },
        {
            "id": "business-boundary",
            "repository": "root",
            "path": ".",
            "owner": "product-team",
            "criticality": "high",
        },
    ]

    added = reconcile_project(project, kit_paths)["diff"]["added"]
    by_id = {row["id"]: row for row in added}

    assert by_id["python:service"]["owner"] == "platform-team"
    assert by_id["python:service"]["criticality"] == "critical"
    assert by_id["business-boundary"] == {
        "id": "business-boundary",
        "repository": "root",
        "path": ".",
        "type": "logical",
        "dependencies": [],
        "evidence": [".ai-team/project.yaml"],
        "confidence": "declared",
        "owner": "product-team",
        "criticality": "high",
    }


def test_manifest_component_refinement_rejects_conflicting_location(
    tmp_path: Path,
    kit_repository: Path,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "pyproject.toml").write_text('[project]\nname = "service"\n', encoding="utf-8")
    kit_paths = paths(tmp_path, kit_repository)
    project = init_project(root, kit_repository, kit_paths)
    project.manifest["components"] = [
        {"id": "python:service", "repository": "root", "path": "other"}
    ]

    with pytest.raises(AgentKitError, match="конфликтует"):
        reconcile_project(project, kit_paths)
