from __future__ import annotations

import json
import os
import stat
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from agent_engineering_kit.errors import AgentKitError
from agent_engineering_kit.paths import KitPaths
from agent_engineering_kit.process import CommandResult, run_command
from agent_engineering_kit.projects import LogicalProject
from agent_engineering_kit.project_skills import ProjectSkillRepositoryManager, redact_url
from agent_engineering_kit.clients import (
    effective_skill_inventory,
    effective_skill_sources,
    expose_native_skills,
    project_skill_status_report,
    sync_clients,
)
from agent_engineering_kit.cli import _effective_skill_roots
from agent_engineering_kit.component_state import Lifecycle, write_state
from agent_engineering_kit.validation import validate_effective_overrides
from conftest import write_yaml


def git(root: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
           "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.invalid"}
    return subprocess.run(["git", *args], cwd=root, env=env, text=True, capture_output=True, check=True).stdout.strip()


@dataclass
class RepositoryFixture:
    upstream: Path
    seed: Path
    project: LogicalProject
    paths: KitPaths

    def manager(self, *, second_root: bool = False, runner=run_command, validator=None):
        project = replace(self.project, root=self.project.root.parent / "other") if second_root else self.project
        return ProjectSkillRepositoryManager(self.paths.repository, self.paths, project, runner=runner, validator=validator)

    def commit_skill(self, content: str, *, name: str = "example") -> str:
        git(self.seed, "switch", "-q", "main")
        skill = self.seed / "skills" / name / "SKILL.md"
        skill.parent.mkdir(parents=True, exist_ok=True)
        skill.write_text(content, encoding="utf-8")
        git(self.seed, "add", ".")
        git(self.seed, "commit", "-qm", "update skill")
        git(self.seed, "push", "-q", str(self.upstream), "main")
        return self.remote_revision("main")

    def disable_remote(self) -> None:
        self.upstream.rename(self.upstream.with_name("offline.git"))

    def remote_revision(self, branch: str) -> str:
        return git(self.upstream, "rev-parse", f"refs/heads/{branch}")

    def product_state(self) -> tuple[str, ...]:
        return tuple(git(self.project.root, *args) for args in (
            ("rev-parse", "HEAD"), ("symbolic-ref", "HEAD"), ("status", "--porcelain"),
            ("diff", "--cached"), ("config", "--local", "--list"),
        ))

    def product_snapshot(self) -> tuple[tuple[str, ...], dict[str, bytes]]:
        state = self.product_state()
        files = {str(path.relative_to(self.project.root)): path.read_bytes()
                 for path in self.project.root.rglob("*") if path.is_file()}
        return state, files


@pytest.fixture
def fixture(tmp_path: Path) -> RepositoryFixture:
    seed = tmp_path / "seed"
    skill = seed / "skills/example/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("---\nname: example\ndescription: fixture\n---\n# Example\n", encoding="utf-8")
    git(seed, "init", "-qb", "main")
    git(seed, "add", ".")
    git(seed, "commit", "-qm", "initial")
    git(seed, "switch", "-qc", "feat/new-check")
    skill.write_text("# Branch example\n", encoding="utf-8")
    git(seed, "commit", "-qam", "branch skill")
    upstream = tmp_path / "upstream.git"
    git(tmp_path, "clone", "--bare", str(seed), str(upstream))
    git(upstream, "symbolic-ref", "HEAD", "refs/heads/main")
    product = tmp_path / "product"
    product.mkdir()
    git(product, "init", "-qb", "product")
    (product / "app.txt").write_text("product\n", encoding="utf-8")
    git(product, "add", ".")
    git(product, "commit", "-qm", "product")
    git(product, "remote", "add", "origin", str(upstream))
    git(product, "config", "branch.product.remote", "origin")
    git(product, "config", "branch.product.merge", "refs/heads/main")
    (product / "app.txt").write_text("staged\n", encoding="utf-8")
    git(product, "add", "app.txt")
    (product / "app.txt").write_text("unstaged\n", encoding="utf-8")
    data = tmp_path / "data"
    paths = KitPaths(tmp_path / "kit", data, data / "runtime", data / "projects", data / "overrides")
    (paths.repository / "schemas").mkdir(parents=True)
    shutil.copy2(Path(__file__).resolve().parents[1] / "schemas/project.schema.json",
                 paths.repository / "schemas/project.schema.json")
    project = LogicalProject(product, product / ".ai-team/project.yaml", {
        "version": 1, "id": "shared", "name": "Shared fixture",
        "repositories": [{"id": "product", "path": "."}],
        "documentation": {"index": "README.md", "roots": ["docs"]},
        "memory": {"namespace": "shared"},
        "skills": {"repository": {"url": str(upstream), "default_branch": "main"}},
    })
    return RepositoryFixture(upstream, seed, project, paths)


@pytest.fixture
def publication_fixture(fixture):
    real = Path(__file__).resolve().parents[1]
    for directory in ("clients", "catalog", "locks", "schemas"):
        shutil.copytree(real / directory, fixture.paths.repository / directory, dirs_exist_ok=True)
    return fixture


@pytest.mark.parametrize("local_override", [False, True])
def test_project_skills_are_published_with_provenance(publication_fixture, monkeypatch, local_override):
    fixture = publication_fixture
    manager = fixture.manager(validator=lambda _: (True, []))
    status = manager.resync()
    repository, paths = fixture.paths.repository, fixture.paths
    builtin = repository / "skills/first-party/example"
    builtin.mkdir(parents=True)
    (builtin / "SKILL.md").write_text("---\nname: example\n---\n", encoding="utf-8")
    (builtin / "builtin-only.txt").touch()
    external = paths.installations / "skills/superpowers/revisions" / ("b" * 40)
    (external / "skills/example").mkdir(parents=True)
    (external / "skills/example/SKILL.md").write_text("# External", encoding="utf-8")
    write_state(paths, "skills", "superpowers", Lifecycle.ACTIVE,
                installation_path=str(external), revision="b" * 40)
    local = paths.overrides / "projects/shared/skills/local-example"
    if local_override:
        local.mkdir(parents=True)
        (local / "SKILL.md").write_text(
            "---\nversion: 1\nname: example\ndescription: Use this skill for testing publication.\n"
            "requires:\n  model_capabilities: []\n---\n", encoding="utf-8",
        )
        write_yaml(local.parent / "example.yaml", {
            "target": "example", "override": {"mode": "replace", "value": {"path": "local-example"}},
        })

    def no_fetch(*args, **kwargs):
        raise AssertionError("client publication must never fetch project skills")

    monkeypatch.setattr(ProjectSkillRepositoryManager, "_fetch_candidate", no_fetch)
    fixture.disable_remote()
    sync_clients(repository, paths, project=fixture.project)

    shared = paths.installations / "clients/shared"
    assert (shared / "skills/example").resolve() == (local if local_override else manager.active_skills()["example"].resolve())
    assert not (shared / "skills/example/builtin-only.txt").exists()
    row = json.loads((shared / "skills-provenance.json").read_text())["skills"]["example"]
    assert row["source"] == ("local-override" if local_override else "project-skills")
    project_row = row["shadowed"][2] if local_override else row
    assert project_row["revision"] == status.active_revision
    assert project_row["source_url"] == str(fixture.upstream)
    assert [item["source"] for item in row["shadowed"]] == (
        ["built-in", "external-catalog", "project-skills"] if local_override else ["built-in", "external-catalog"]
    )


@pytest.mark.parametrize("mode", ["replace", "disable", "block", "invalid"])
def test_project_skills_obey_explicit_local_overrides(publication_fixture, mode):
    fixture = publication_fixture
    fixture.manager(validator=lambda _: (True, [])).resync()
    paths = fixture.paths
    local = paths.overrides / "projects/shared/skills/local-example"
    local.mkdir(parents=True)
    (local / "SKILL.md").write_text(
        "---\nversion: 1\nname: example\ndescription: Use this skill for testing publication.\n"
        "requires:\n  model_capabilities: []\n---\n" if mode != "invalid" else "# Invalid", encoding="utf-8",
    )
    write_yaml(paths.overrides / "projects/shared/skills/example.yaml", {
        "target": "example", "override": {"mode": "disable" if mode == "disable" else "replace",
        "value": {"path": "local-example"}},
    })
    if mode == "block":
        write_yaml(paths.overrides / "projects/shared/access.yaml", {
            "version": 1, "skills": {"allow": [], "block": ["example"]},
        })
    if mode == "invalid":
        with pytest.raises(AgentKitError, match="local skill override"):
            sync_clients(paths.repository, paths, project=fixture.project)
        return

    sync_clients(paths.repository, paths, project=fixture.project)

    shared = paths.installations / "clients/shared"
    rows = json.loads((shared / "skills-provenance.json").read_text())["skills"]
    if mode in {"disable", "block"}:
        assert not (shared / "skills/example").exists()
        assert "example" not in rows
    else:
        assert (shared / "skills/example").resolve() == local
        assert rows["example"]["source"] == "local-override"
        assert rows["example"]["shadowed"][0]["source"] == "project-skills"


def test_effective_skill_resolver_exposes_project_skill_and_applies_acl(publication_fixture):
    fixture = publication_fixture
    fixture.manager(validator=lambda _: (True, [])).resync()

    sources = effective_skill_sources(
        fixture.paths.repository, fixture.paths, fixture.project, include_disabled=True,
    )

    assert sources["example"].source == "project-skills"
    assert sources["example"].enabled is True
    write_yaml(fixture.paths.overrides / "projects/shared/access.yaml", {
        "version": 1, "skills": {"allow": [], "block": ["example"]},
    })
    blocked = effective_skill_sources(
        fixture.paths.repository, fixture.paths, fixture.project, include_disabled=True,
    )["example"]
    inventory = {row["id"]: row for row in effective_skill_inventory(
        fixture.paths.repository, fixture.paths, fixture.project,
    )}
    assert blocked.enabled is False
    assert blocked.access_reason == "blocked:project"
    assert inventory["example"]["status"] == "DISABLED"


def test_repository_validation_accepts_active_project_skill_override(publication_fixture, monkeypatch):
    fixture = publication_fixture
    fixture.manager(validator=lambda _: (True, [])).resync()
    write_yaml(fixture.project.manifest_path, fixture.project.manifest)
    write_yaml(fixture.paths.overrides / "projects/shared/skills/example.yaml", {
        "target": "example", "override": {"mode": "disable"},
    })
    monkeypatch.chdir(fixture.project.root)

    result = validate_effective_overrides(
        fixture.paths.repository, fixture.paths, include_local=True,
    )

    assert result.ok


def test_security_roots_follow_effective_project_skill_precedence(publication_fixture):
    fixture = publication_fixture
    manager = fixture.manager(validator=lambda _: (True, []))
    manager.resync()
    assert _effective_skill_roots(fixture.paths.repository, fixture.paths, fixture.project) == [
        manager.active_skills()["example"].resolve(),
    ]
    local = fixture.paths.overrides / "projects/shared/sources/skills/example"
    local.mkdir(parents=True)
    (local / "SKILL.md").write_text(
        "---\nversion: 1\nname: example\ndescription: Use the local test skill.\n"
        "requires:\n  model_capabilities: []\n---\n", encoding="utf-8",
    )
    write_yaml(fixture.paths.overrides / "projects/shared/skills/example.yaml", {
        "target": "example", "override": {"mode": "replace", "value": {"path": "../sources/skills/example"}},
    })

    assert _effective_skill_roots(fixture.paths.repository, fixture.paths, fixture.project) == [local.resolve()]


def test_project_skill_status_reports_branch_override_provenance_and_collisions(publication_fixture):
    fixture = publication_fixture
    manager = fixture.manager(validator=lambda _: (True, []))
    manager.resync()
    builtin = fixture.paths.repository / "skills/first-party/example"
    builtin.mkdir(parents=True)
    (builtin / "SKILL.md").write_text(
        "---\nversion: 1\nname: example\ndescription: Use the built-in test skill.\n"
        "requires:\n  model_capabilities: []\n---\n", encoding="utf-8",
    )
    manager.set_branch("feat/new-check")

    report = project_skill_status_report(fixture.paths.repository, fixture.paths, fixture.project)

    assert report["local_override_applied"] is True
    assert report["provenance"]["example"]["source"] == "project-skills"
    assert report["collisions"]["example"] == ["built-in", "project-skills"]


def test_project_skill_status_is_one_snapshot_during_concurrent_resync(publication_fixture, monkeypatch):
    fixture = publication_fixture
    manager = fixture.manager(validator=lambda _: (True, []))
    initial = manager.resync()
    updated_revision = fixture.commit_skill("---\nname: example\n---\n# Updated\n")
    status_read = threading.Event()
    release_status = threading.Event()
    resync_entered = threading.Event()
    original_status = ProjectSkillRepositoryManager.status
    original_fetch = manager._fetch_candidate

    def paused_status(self):
        status = original_status(self)
        status_read.set()
        assert release_status.wait(5)
        return status

    def observe_fetch(*, ci=False):
        resync_entered.set()
        return original_fetch(ci=ci)

    monkeypatch.setattr(ProjectSkillRepositoryManager, "status", paused_status)
    manager._fetch_candidate = observe_fetch
    with ThreadPoolExecutor(max_workers=2) as executor:
        report_future = executor.submit(
            project_skill_status_report, fixture.paths.repository, fixture.paths, fixture.project,
        )
        assert status_read.wait(5)
        resync_future = executor.submit(manager.resync)
        raced_with_snapshot = resync_entered.wait(1)
        release_status.set()
        report = report_future.result(timeout=5)
        updated = resync_future.result(timeout=5)

    assert not raced_with_snapshot
    assert report["active_revision"] == initial.active_revision
    assert report["provenance"]["example"]["revision"] == initial.active_revision
    assert updated.active_revision == updated_revision


@pytest.mark.parametrize("configured", [True, False])
@pytest.mark.parametrize("artifact", ["candidate", "revision"])
def test_client_sync_publishes_no_project_skills_without_active_pointer(publication_fixture, configured, artifact):
    fixture = publication_fixture
    manager = fixture.manager(validator=lambda _: (True, []))
    if artifact == "candidate":
        manager.fetch_candidate()
    else:
        manager.resync()
        (manager.root / "active.json").unlink()
    if not configured:
        fixture.project.manifest.pop("skills")

    sync_clients(fixture.paths.repository, fixture.paths, project=fixture.project)

    assert not (fixture.paths.installations / "clients/shared/skills/example").exists()


def test_native_project_skills_follow_new_active_revision_and_preserve_user_paths(publication_fixture):
    fixture = publication_fixture
    manager = fixture.manager(validator=lambda _: (True, []))
    manager.resync()
    native = fixture.project.root.parent / "native-skills"
    expose_native_skills(fixture.paths.repository, fixture.paths, project=fixture.project, roots=(native,))
    revision = fixture.commit_skill("---\nname: example\n---\n# Updated\n")
    manager.resync()

    expose_native_skills(fixture.paths.repository, fixture.paths, project=fixture.project, roots=(native,))

    assert revision in str((native / "example").resolve())
    assert "Updated" in (native / "example/SKILL.md").read_text()
    (native / "example").unlink()
    user = native.parent / "user-skill"
    user.mkdir()
    (native / "example").symlink_to(user, target_is_directory=True)
    with pytest.raises(AgentKitError, match="пользовательским symlink"):
        expose_native_skills(fixture.paths.repository, fixture.paths, project=fixture.project, roots=(native,))
    assert (native / "example").resolve() == user


def test_client_sync_rejects_project_pointer_changed_during_resolution(publication_fixture, monkeypatch):
    fixture = publication_fixture
    manager = fixture.manager(validator=lambda _: (True, []))
    manager.resync()
    old_skills = manager.active_skills()
    fixture.commit_skill("---\nname: example\n---\n# New revision\n")
    manager.resync()
    # Моделируем смену atomic pointer между двумя read-only вызовами manager.
    monkeypatch.setattr(ProjectSkillRepositoryManager, "active_skills", lambda _: old_skills)

    with pytest.raises(AgentKitError, match="active pointer.*изменился"):
        sync_clients(fixture.paths.repository, fixture.paths, project=fixture.project)

    assert not (fixture.paths.installations / "clients/shared/skills/example").exists()


def test_client_provenance_uses_active_source_after_failed_source_change(publication_fixture):
    fixture = publication_fixture
    manager = fixture.manager(validator=lambda _: (True, []))
    active = manager.resync()
    missing_source = str(fixture.upstream.with_name("missing.git"))
    fixture.project.manifest["skills"]["repository"]["url"] = missing_source
    assert manager.resync().state == "STALE"
    assert manager.status().source_url == missing_source

    sync_clients(fixture.paths.repository, fixture.paths, project=fixture.project)

    provenance = fixture.paths.installations / "clients/shared/skills-provenance.json"
    row = json.loads(provenance.read_text())["skills"]["example"]
    assert row["source_url"] == str(fixture.upstream)
    assert row["revision"] == active.active_revision


def test_branch_override_is_machine_local_and_shared_by_project_id(fixture):
    manager = fixture.manager()
    assert manager.requested_branch() == "main"
    selection = manager.set_branch("feat/new-check")
    assert selection == {"project_id": "shared", "source_url": str(fixture.upstream),
                         "default_branch": "main", "requested_branch": "feat/new-check",
                         "local_override_applied": True}
    assert fixture.manager(second_root=True).requested_branch() == "feat/new-check"
    assert manager.requested_branch(ci=True) == "main"
    assert not (fixture.project.root / ".ai-team/project-skills-branch").exists()
    override = manager.root / "branch-override.json"
    assert stat.S_IMODE(override.stat().st_mode) == 0o600
    assert manager.use_main()["local_override_applied"] is False
    assert manager.requested_branch() == "main"
    assert not override.exists()


def test_branch_override_ci_ignores_malformed_local_file(fixture):
    manager = fixture.manager()
    manager.set_branch("feat/new-check")
    (manager.root / "branch-override.json").write_text("broken", encoding="utf-8")
    assert manager.requested_branch(ci=True) == "main"
    with pytest.raises(AgentKitError):
        manager.requested_branch()


@pytest.mark.parametrize("activated", [False, True])
def test_ci_validation_ignores_machine_branch_override_without_writes(fixture, monkeypatch, activated):
    manager = fixture.manager(validator=lambda _: (True, []))
    active = manager.resync() if activated else None
    manager.set_branch("feat/new-check")
    manager.override_path.write_text("malformed machine-local input")
    before = {str(path): path.read_bytes() for path in manager.root.rglob("*") if path.is_file()}
    product_before = fixture.product_snapshot()
    original_read = Path.read_text

    def guarded_read(path, *args, **kwargs):
        if path == manager.override_path:
            raise AssertionError("CI must not read the machine-local branch override")
        return original_read(path, *args, **kwargs)

    def read_only_git(args, **kwargs):
        if "rev-parse" not in args and not ("status" in args and "--no-optional-locks" in args):
            raise AssertionError(f"CI attempted Git mutation or network: {args}")
        return run_command(args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read)
    manager.runner = read_only_git
    observed = manager.inspect(ci=True)

    assert observed["requested_branch"] == "main"
    assert observed["local_override_applied"] is False
    assert observed["active_revision"] == (active.active_revision if active else None)
    assert observed["resolved_revision"] is None
    assert {str(path): path.read_bytes() for path in manager.root.rglob("*") if path.is_file()} == before
    assert fixture.product_snapshot() == product_before


def test_inspection_preserves_explicit_local_branch_selection(fixture):
    manager = fixture.manager()
    manager.set_branch("feat/new-check")
    observed = manager.inspect()
    assert observed["requested_branch"] == "feat/new-check"
    assert observed["local_override_applied"] is True


def test_status_masks_credential_bearing_runtime_remote(fixture):
    manager = fixture.manager(validator=lambda _: (True, []))
    active = manager.resync()
    secret_url = "https://runtime-user:runtime-password@example.invalid/skills.git?token=runtime-token#runtime-fragment"
    git(manager.checkout, "remote", "set-url", "origin", secret_url)
    diagnostic = manager.root / "status.json"
    diagnostic.write_text(json.dumps({**active.as_dict(), "reason": secret_url, "state": "STALE",
                                     "default_branch": secret_url}))
    rendered = json.dumps(manager.status().as_dict())
    assert "<redacted-url>" in rendered
    assert all(secret not in rendered for secret in ("runtime-user", "runtime-password", "runtime-token", "runtime-fragment"))


@pytest.mark.parametrize("branch", ["bad branch", "--help", "../main", "main:other", "@{-1}", ""])
def test_branch_override_rejects_invalid_refs_without_changing_selection(fixture, branch):
    manager = fixture.manager()
    manager.set_branch("feat/new-check")
    with pytest.raises(AgentKitError):
        manager.set_branch(branch)
    assert manager.requested_branch() == "feat/new-check"


def test_fetch_candidate_resolves_remote_commit_without_touching_product_tree(fixture):
    before = fixture.product_state()
    manager = fixture.manager()
    candidate, revision = manager.fetch_candidate()
    assert revision == fixture.remote_revision("main")
    assert candidate.parent == manager.root / "candidates"
    assert (candidate / "skills/example/SKILL.md").is_file()
    assert git(candidate, "rev-parse", "HEAD") == revision
    assert subprocess.run(["git", "-C", str(candidate), "symbolic-ref", "-q", "HEAD"], capture_output=True).returncode == 1
    assert fixture.product_state() == before


def test_fetch_candidate_uses_override_but_ci_uses_default(fixture):
    manager = fixture.manager()
    manager.set_branch("feat/new-check")
    branch_candidate, branch_revision = manager.fetch_candidate()
    ci_candidate, ci_revision = manager.fetch_candidate(ci=True)
    assert branch_revision == fixture.remote_revision("feat/new-check")
    assert ci_revision == fixture.remote_revision("main")
    assert ci_candidate != branch_candidate


def test_fetch_candidate_refreshes_remote_after_branch_rewind(fixture):
    manager = fixture.manager()
    manager.set_branch("feat/new-check")
    _, original = manager.fetch_candidate()
    git(fixture.upstream, "update-ref", "refs/heads/feat/new-check", fixture.remote_revision("main"))
    _, rewound = manager.fetch_candidate()
    assert rewound == fixture.remote_revision("main")
    assert rewound != original


def test_fetch_candidate_missing_branch_keeps_existing_candidate_and_active_state(fixture):
    manager = fixture.manager()
    candidate, revision = manager.fetch_candidate()
    active = manager.root / "active.json"
    active.write_text(json.dumps({"revision": revision}), encoding="utf-8")
    manager.set_branch("missing/branch")
    with pytest.raises(AgentKitError):
        manager.fetch_candidate()
    assert list((manager.root / "candidates").iterdir()) == [candidate]
    assert json.loads(active.read_text())["revision"] == revision
    assert git(candidate, "rev-parse", "HEAD") == revision


@pytest.mark.parametrize("operation", ["clone", "worktree"])
def test_fetch_candidate_cleans_partial_failed_git_commands(fixture, operation):
    def fail(args, **kwargs):
        if operation == "clone" and args[1] == "clone":
            Path(args[-1]).mkdir(parents=True)
            return CommandResult(tuple(args), 1, "", "clone failed")
        if operation == "worktree" and "worktree" in args and "add" in args:
            result = run_command(args, **kwargs)
            assert result.ok
            return CommandResult(tuple(args), 1, "", "worktree failed after creation")
        return run_command(args, **kwargs)

    manager = fixture.manager(runner=fail)
    with pytest.raises(AgentKitError):
        manager.fetch_candidate()
    assert not list((manager.root / "candidates").glob("*"))
    checkout = manager.root / "checkout"
    if operation == "clone":
        assert not checkout.exists()
    else:
        assert "candidates" not in git(checkout, "worktree", "list", "--porcelain")
    # A failed attempt must allow a normal retry.
    assert fixture.manager().fetch_candidate()[1] == fixture.remote_revision("main")


def test_fetch_candidate_errors_and_selection_redact_url_credentials(fixture):
    secret_url = "https://alice:password@example.invalid/repo.git?token=secret#private"
    fixture.project.manifest["skills"]["repository"]["url"] = secret_url

    def fail(args, **kwargs):
        if args[1] == "check-ref-format":
            return run_command(args, **kwargs)
        return CommandResult(tuple(args), 1, "", f"cannot access '{secret_url}'")

    manager = fixture.manager(runner=fail)
    status = manager.set_branch("main")
    with pytest.raises(AgentKitError) as caught:
        manager.fetch_candidate()
    for output in (str(caught.value), json.dumps(status), redact_url(secret_url)):
        for secret in ("alice", "password", "secret", "private"):
            assert secret not in output
        assert "<redacted-url>" in output


@pytest.mark.parametrize("unsafe", [
    "https://alice:secret'part@example.invalid/repo",
    'https://alice:secret"part@example.invalid/repo',
    "https://example.invalid/repo?token='secret part'",
    'https://example.invalid/repo#"secret part"',
    "https://example.invalid/repo?token='https://alice:secret@private.invalid/part'",
    "https://alice:secret' part@example.invalid/repo",
    "https://alice:secret'part",
    "https://alice:secret'part' private@example.invalid/repo",
    "https://alice:1234'secret/private@example.invalid/repo",
    "https://example.invalid/repo?token='secret' private",
    'https://example.invalid/repo#"secret" private',
    "https://alice:secret'part@[malformed/repo?token=private",
])
@pytest.mark.parametrize("wrapper", ["{}", "cannot access '{}'", '{{"url":"{}"}}'])
def test_redact_url_masks_quoted_and_malformed_secret_text(unsafe, wrapper):
    rendered = redact_url(wrapper.format(unsafe))
    assert all(secret not in rendered for secret in ("alice", "secret", "part", "private"))
    assert "<redacted-url>" in rendered


@pytest.mark.parametrize("text", [
    "https://example.invalid/repo",
    "cannot access 'https://example.invalid/repo' (offline)",
    '{"url":"https://example.invalid/repo"}',
    '{"one":"https://one.example.invalid","two":"https://two.example.invalid"}',
    "https://[2001:db8::1]/repo",
])
def test_redact_url_preserves_safe_url_and_surrounding_text(text):
    assert redact_url(text) == text


@pytest.mark.parametrize("unsafe", [
    "https://alice: secret'part@example.invalid/repo",
    "https://alice:secret 'part@example.invalid/repo",
    'https://alice: secret"part@example.invalid/repo',
    'https://alice:secret "part@example.invalid/repo',
    "https://example.invalid/repo token ? 'secret part'",
    'https://example.invalid/repo token # "secret part"',
])
def test_redact_url_applies_fail_closed_line_rule(unsafe):
    text = "before " + unsafe + " diagnostic tail\r\nafter https://safe.example.invalid/repo\n"
    assert redact_url(text) == "before <redacted-url>\r\nafter https://safe.example.invalid/repo\n"


@pytest.mark.parametrize("prefix", ["label_", "Ошибка", "value="])
def test_redact_url_line_rule_detects_scheme_after_diagnostic_prefix(prefix):
    assert redact_url(prefix + "https://alice: secret'part@example.invalid/repo") == prefix + "<redacted-url>"


@pytest.mark.parametrize("separator", ["\v", "\f", "\x1c", "\u0085"])
def test_redact_url_keeps_non_diagnostic_separators_inside_sensitive_line(separator):
    unsafe = "https://alice:" + separator + "secret@example.invalid/repo"
    text = "before " + unsafe + " diagnostic tail\r\nafter https://safe.example.invalid/repo\rfinal\n"
    assert redact_url(text) == "before <redacted-url>\r\nafter https://safe.example.invalid/repo\rfinal\n"


@pytest.mark.parametrize("separator", ["\v", "\f", "\x1c", "\u0085"])
def test_public_outputs_mask_non_diagnostic_separators(fixture, separator):
    from agent_engineering_kit.project_skills import ProjectSkillsStatus

    unsafe = "https://alice:" + separator + "secret@example.invalid/repo"
    text = "before " + unsafe + " diagnostic tail\r\nafter https://safe.example.invalid/repo\rfinal\n"
    status = ProjectSkillsStatus("shared", unsafe, "main", "main", None, None, "STALE", text, None, ())
    rendered = status.as_dict()
    assert rendered["source_url"] == "<redacted-url>"
    assert rendered["reason"] == "before <redacted-url>\r\nafter https://safe.example.invalid/repo\rfinal\n"
    fixture.project.manifest["skills"]["repository"]["url"] = unsafe
    assert fixture.manager().inspect(ci=True)["source_url"] == "<redacted-url>"


@pytest.mark.parametrize("first_path", ["/one", ""])
@pytest.mark.parametrize("second_path", ["/two", ""])
def test_redact_url_masks_multiple_compact_json_urls(first_path, second_path):
    text = ('{"one":"https://alice:secret\'part@one.example.invalid' + first_path
            + '","two":"https://bob:private\"part@two.example.invalid' + second_path + '"}')
    rendered = redact_url(text)
    assert all(secret not in rendered for secret in ("alice", "secret", "bob", "private", "part"))
    assert rendered == '{"one":"<redacted-url>'


@pytest.mark.parametrize("unsafe", [
    "https://alice:secret'part@example.invalid/repo",
    'https://alice:secret"part@example.invalid/repo',
    "https://example.invalid/repo?token='secret part'",
    'https://example.invalid/repo#"secret part"',
    "https://alice: secret'part@example.invalid/repo",
    "https://alice:secret 'part@example.invalid/repo",
])
def test_public_inspection_and_git_errors_mask_quoted_url_secrets(fixture, unsafe):
    fixture.project.manifest["skills"]["repository"]["url"] = unsafe

    def fail(args, **kwargs):
        if args[1] == "check-ref-format":
            return run_command(args, **kwargs)
        return CommandResult(tuple(args), 1, "", f"cannot access '{unsafe}'")

    manager = fixture.manager(runner=fail)
    inspected = json.dumps(manager.inspect(ci=True))
    with pytest.raises(AgentKitError) as caught:
        manager.fetch_candidate()
    for rendered in (inspected, str(caught.value)):
        assert all(secret not in rendered for secret in ("alice", "secret", "part"))


def test_unconfigured_source_does_not_create_managed_state(fixture):
    fixture.project.manifest.pop("skills")
    manager = fixture.manager()
    with pytest.raises(AgentKitError):
        manager.fetch_candidate()
    assert not manager.root.exists()


@pytest.mark.parametrize("target", ["root", "checkout", "candidates"])
def test_fetch_candidate_rejects_storage_links_into_product_tree(fixture, target):
    manager = fixture.manager()
    link = manager.root if target == "root" else manager.root / target
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(fixture.project.root, target_is_directory=True)
    before = fixture.product_state()
    with pytest.raises(AgentKitError):
        manager.fetch_candidate()
    assert fixture.product_state() == before
    assert not (fixture.project.root / "candidates").exists()


def test_fetch_candidate_does_not_reuse_ref_after_remote_branch_deleted(fixture):
    manager = fixture.manager()
    manager.set_branch("feat/new-check")
    candidate, _ = manager.fetch_candidate()
    git(fixture.upstream, "update-ref", "-d", "refs/heads/feat/new-check")
    with pytest.raises(AgentKitError):
        manager.fetch_candidate()
    assert list((manager.root / "candidates").iterdir()) == [candidate]


def test_use_main_restores_configured_default_branch(fixture):
    fixture.project.manifest["skills"]["repository"]["default_branch"] = "feat/new-check"
    manager = fixture.manager()
    manager.set_branch("main")
    assert manager.use_main()["requested_branch"] == "feat/new-check"
    assert manager.fetch_candidate()[1] == fixture.remote_revision("feat/new-check")


@pytest.mark.skipif(os.name == "nt", reason="POSIX advisory-lock probe")
def test_fetch_candidate_holds_project_lock_during_git_operations(fixture):
    import fcntl

    lock = fixture.paths.locks / "project-skills-shared.lock"

    def probe(args, **kwargs):
        with lock.open("rb") as stream:
            with pytest.raises(BlockingIOError):
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return run_command(args, **kwargs)

    assert fixture.manager(runner=probe).fetch_candidate()[1] == fixture.remote_revision("main")


def test_fetch_candidate_hostile_git_environment_preserves_complete_product_state(fixture, monkeypatch):
    manager = fixture.manager()
    manager.fetch_candidate()
    before = fixture.product_snapshot()
    with monkeypatch.context() as hostile:
        hostile.setenv("GIT_DIR", str(fixture.project.root / ".git"))
        hostile.setenv("GIT_WORK_TREE", str(fixture.project.root))
        hostile.setenv("GIT_INDEX_FILE", str(fixture.project.root / ".git/index"))
        hostile.setenv("GIT_OBJECT_DIRECTORY", str(fixture.project.root / ".git/objects"))
        try:
            manager.fetch_candidate()
        except AgentKitError:
            pass  # Отказ безопасен, если никакое product state не изменилось.
    assert fixture.product_snapshot() == before


def test_first_activation_is_last_known_good_git_worktree_and_idempotent(fixture):
    before = fixture.product_snapshot()
    manager = fixture.manager(validator=lambda _: (True, [{"check": "fixture", "status": "PASS"}]))
    active = manager.resync()
    assert active.state == "ACTIVE"
    assert active.active_revision == fixture.remote_revision("main") == active.resolved_revision
    assert active.skills == ("example",)
    path = manager.active_skills()["example"]
    assert path == manager.root / "revisions" / active.active_revision / "skills/example"
    assert git(path, "rev-parse", "HEAD") == active.active_revision
    assert str(path.parent.parent) in git(manager.checkout, "worktree", "list", "--porcelain")
    pointer = (manager.root / "active.json").read_bytes()
    assert manager.resync() == active
    assert (manager.root / "active.json").read_bytes() == pointer
    assert manager.status() == active
    assert not list((manager.root / "candidates").iterdir())
    assert fixture.product_snapshot() == before


def test_rejected_update_keeps_last_known_good(fixture):
    manager = fixture.manager(validator=lambda _: (True, []))
    active = manager.resync()
    pointer = (manager.root / "active.json").read_bytes()
    old_path = manager.active_skills()["example"]
    revision = fixture.commit_skill("---\nname: example\ndescription: rejected\n---\n# Rejected\n")
    manager.validator = lambda _: (False, [{"check": "fixture", "status": "FAIL"}])
    rejected = manager.resync()
    assert rejected.state == "UPDATE_REJECTED"
    assert rejected.resolved_revision == revision
    assert rejected.active_revision == active.active_revision
    assert rejected.reason
    assert manager.active_skills()["example"] == old_path
    assert (manager.root / "active.json").read_bytes() == pointer
    assert manager.status() == rejected
    assert not list((manager.root / "candidates").iterdir())
    assert "FAIL" in (manager.root / "status.json").read_text()


def test_offline_refresh_reports_stale_and_keeps_active_revision(fixture):
    manager = fixture.manager(validator=lambda _: (True, []))
    active = manager.resync()
    pointer = (manager.root / "active.json").read_bytes()
    fixture.disable_remote()
    stale = manager.resync()
    assert stale.state == "STALE"
    assert stale.active_revision == active.active_revision
    assert stale.resolved_revision is None
    assert manager.status() == stale
    assert manager.active_skills()["example"].joinpath("SKILL.md").is_file()
    assert (manager.root / "active.json").read_bytes() == pointer


@pytest.mark.parametrize("kind", ["offline", "security"])
def test_first_failure_without_last_known_good_raises(fixture, kind):
    manager = fixture.manager(validator=lambda _: (False, [{"check": "fixture", "status": "FAIL"}]))
    if kind == "offline":
        fixture.disable_remote()
    with pytest.raises(AgentKitError):
        manager.resync()
    assert not (manager.root / "active.json").exists()
    assert manager.active_skills() == {}


@pytest.mark.parametrize("content", [
    "# Missing frontmatter\n", "---\nname: example\n", "---\nname: [broken\n---\n",
    "---\n- example\n---\n", "---\nname: other\n---\n", "---\nname: 123\n---\n",
])
def test_malformed_candidate_never_activates(fixture, content):
    fixture.commit_skill(content)
    manager = fixture.manager(validator=lambda _: (True, []))
    with pytest.raises(AgentKitError):
        manager.resync()
    assert not (manager.root / "active.json").exists()
    assert not list((manager.root / "candidates").iterdir())
    assert "FAIL" in (manager.root / "status.json").read_text()


@pytest.mark.parametrize("kind", ["missing-skills", "empty-skills", "missing-file", "outside-link", "duplicate-id"])
def test_malformed_repository_structure_keeps_last_known_good(fixture, kind):
    manager = fixture.manager(validator=lambda _: (True, []))
    active = manager.resync()
    git(fixture.seed, "switch", "-q", "main")
    skill = fixture.seed / "skills/example/SKILL.md"
    if kind in {"missing-skills", "empty-skills", "missing-file"}:
        skill.unlink()
        if kind == "missing-skills":
            (fixture.seed / "skills/example").rmdir()
            (fixture.seed / "skills").rmdir()
        else:
            marker = fixture.seed / ("skills/.keep" if kind == "empty-skills" else "skills/example/.keep")
            marker.write_text("keep\n")
    elif kind == "outside-link":
        (skill.parent / "secret").symlink_to(fixture.project.root / "app.txt")
    else:
        duplicate = fixture.seed / "skills/duplicate/SKILL.md"
        duplicate.parent.mkdir()
        duplicate.write_text("---\nname: example\n---\n")
    git(fixture.seed, "add", "-A")
    git(fixture.seed, "commit", "-qm", "malformed structure")
    git(fixture.seed, "push", "-q", str(fixture.upstream), "main")
    rejected = manager.resync()
    assert rejected.state == "UPDATE_REJECTED"
    assert rejected.active_revision == active.active_revision
    assert manager.active_skills()["example"].joinpath("SKILL.md").is_file()


def test_concurrent_resync_serializes_validation_and_activation(fixture):
    manager = fixture.manager(validator=lambda _: (True, []))
    with ThreadPoolExecutor(max_workers=4) as executor:
        statuses = list(executor.map(lambda _: manager.resync(), range(4)))
    assert all(status == statuses[0] for status in statuses)
    assert statuses[0].state == "ACTIVE"
    assert len(list((manager.root / "revisions").iterdir())) == 1
    assert not list((manager.root / "candidates").iterdir())
    assert git(manager.active_skills()["example"], "rev-parse", "HEAD") == statuses[0].active_revision


def test_resync_rejects_incompatible_source_registered_by_another_project_root(publication_fixture):
    fixture = publication_fixture
    first = fixture.manager(validator=lambda _: (True, []))
    first.resync()
    other_upstream = fixture.upstream.with_name("other-upstream.git")
    git(fixture.seed.parent, "clone", "--bare", str(fixture.seed), str(other_upstream))
    other_root = fixture.project.root.parent / "other-product"
    other_root.mkdir()
    other_project = LogicalProject(other_root, other_root / ".ai-team/project.yaml", {
        "version": 1, "id": fixture.project.identifier, "name": "Other fixture",
        "repositories": [{"id": "product", "path": "."}],
        "documentation": {"index": "README.md", "roots": ["docs"]},
        "memory": {"namespace": fixture.project.identifier},
        "skills": {"repository": {"url": str(other_upstream), "default_branch": "main"}},
    })
    second = ProjectSkillRepositoryManager(
        fixture.paths.repository, fixture.paths, other_project, validator=lambda _: (True, []),
    )
    origin_before = git(first.checkout, "remote", "get-url", "origin")

    with pytest.raises(AgentKitError, match="Collision project.id"):
        second.resync()

    assert git(first.checkout, "remote", "get-url", "origin") == origin_before == str(fixture.upstream)
    identity = json.loads((fixture.paths.projects / fixture.project.identifier / "identity.json").read_text())
    assert identity["skills_repository_url"] == str(fixture.upstream)


def test_concurrent_resync_allows_only_one_incompatible_namespace_source(publication_fixture):
    fixture = publication_fixture
    other_upstream = fixture.upstream.with_name("racing-upstream.git")
    git(fixture.seed.parent, "clone", "--bare", str(fixture.seed), str(other_upstream))
    other_root = fixture.project.root.parent / "racing-product"
    other_root.mkdir()
    other_project = LogicalProject(other_root, other_root / ".ai-team/project.yaml", {
        **fixture.project.manifest,
        "skills": {"repository": {"url": str(other_upstream), "default_branch": "main"}},
    })
    managers = (
        fixture.manager(validator=lambda _: (True, [])),
        ProjectSkillRepositoryManager(
            fixture.paths.repository, fixture.paths, other_project, validator=lambda _: (True, []),
        ),
    )

    def synchronize(manager):
        try:
            return manager.resync().state
        except AgentKitError as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(synchronize, managers))

    assert sum(result == "ACTIVE" for result in results) == 1
    assert sum("Collision project.id" in result for result in results) == 1
    identity = json.loads((fixture.paths.projects / fixture.project.identifier / "identity.json").read_text())
    assert git(managers[0].checkout, "remote", "get-url", "origin") == identity["skills_repository_url"]


def test_validator_mutation_after_structure_check_keeps_last_known_good(fixture):
    manager = fixture.manager(validator=lambda _: (True, []))
    active = manager.resync()
    pointer = (manager.root / "active.json").read_bytes()
    fixture.commit_skill("---\nname: example\n---\n# Candidate\n")

    def mutate(skill_root: Path):
        (skill_root / "SKILL.md").write_text("---\nname: example\n---\n# Mutated after validation\n")
        return True, [{"check": "fixture", "status": "PASS"}]

    manager.validator = mutate
    rejected = manager.resync()

    assert rejected.state == "UPDATE_REJECTED"
    assert rejected.active_revision == active.active_revision
    assert (manager.root / "active.json").read_bytes() == pointer
    assert "Mutated" not in manager.active_skills()["example"].joinpath("SKILL.md").read_text()


def test_validator_cannot_hide_mutation_with_assume_unchanged(fixture):
    manager = fixture.manager(validator=lambda _: (True, []))
    active = manager.resync()
    pointer = (manager.root / "active.json").read_bytes()
    fixture.commit_skill("---\nname: example\n---\n# Candidate\n")

    def mutate_and_hide(skill_root: Path):
        (skill_root / "SKILL.md").write_text(
            "---\nname: example\n---\n# Hidden mutation\n", encoding="utf-8",
        )
        git(skill_root, "update-index", "--assume-unchanged", "SKILL.md")
        assert git(skill_root, "status", "--porcelain") == ""
        return True, [{"check": "fixture", "status": "PASS"}]

    manager.validator = mutate_and_hide
    rejected = manager.resync()

    assert rejected.state == "UPDATE_REJECTED"
    assert rejected.active_revision == active.active_revision
    assert (manager.root / "active.json").read_bytes() == pointer
    assert "Hidden mutation" not in manager.active_skills()["example"].joinpath("SKILL.md").read_text()


def test_unconfigured_lifecycle_has_no_source_revision_or_state_writes(fixture):
    fixture.project.manifest.pop("skills")
    manager = fixture.manager()
    status = manager.resync()
    assert status.state == "NOT_CONFIGURED"
    assert status.source_url is status.active_revision is status.resolved_revision is None
    assert status.skills == ()
    assert manager.status() == status
    assert manager.active_skills() == {}
    assert not manager.root.exists()


@pytest.mark.parametrize("corruption", ["invalid-json", "missing-revision", "traversal", "missing-skill", "modified-file"])
def test_corrupt_active_pointer_fails_closed(fixture, corruption):
    manager = fixture.manager(validator=lambda _: (True, []))
    manager.resync()
    pointer = manager.root / "active.json"
    value = json.loads(pointer.read_text())
    if corruption == "invalid-json":
        pointer.write_text("broken")
    elif corruption == "modified-file":
        manager.active_skills()["example"].joinpath("SKILL.md").write_text(
            "---\nname: example\n---\n# Unvalidated modification\n")
    else:
        if corruption == "missing-revision":
            value["active_revision"] = "0" * 40
        elif corruption == "traversal":
            value["skills"] = ["../../product"]
        else:
            value["skills"] = ["missing"]
        pointer.write_text(json.dumps(value))
    with pytest.raises(AgentKitError):
        manager.active_skills()
    with pytest.raises(AgentKitError):
        manager.resync()


def test_status_diagnostics_cannot_claim_activation_or_replace_pointer(fixture):
    manager = fixture.manager(validator=lambda _: (True, []))
    with pytest.raises(AgentKitError, match="синхронизированы"):
        manager.status()
    active = manager.resync()
    pointer = manager.root / "active.json"
    diagnostic = manager.root / "status.json"
    diagnostic.write_text("broken")
    assert manager.status() == active
    diagnostic.write_text(json.dumps({**active.as_dict(), "skills": ["other"], "state": "STALE"}))
    assert manager.status() == active
    diagnostic.write_text(json.dumps(active.as_dict()))
    pointer.unlink()
    assert manager.active_skills() == {}
    with pytest.raises(AgentKitError):
        manager.status()


@pytest.mark.parametrize("operation", ["move", "pointer"])
def test_failed_activation_keeps_exact_last_known_good_pointer(fixture, monkeypatch, operation):
    manager = fixture.manager(validator=lambda _: (True, []))
    active = manager.resync()
    pointer = (manager.root / "active.json").read_bytes()
    fixture.commit_skill("---\nname: example\n---\n# Next revision\n")
    if operation == "move":
        def fail(args, **kwargs):
            if "worktree" in args and "move" in args:
                return CommandResult(tuple(args), 1, "", "move failed")
            return run_command(args, **kwargs)
        manager.runner = fail
    else:
        from agent_engineering_kit import project_skills
        original = project_skills.atomic_write

        def fail(path, content):
            if path.name == "active.json":
                raise OSError("pointer replacement failed")
            original(path, content)
        monkeypatch.setattr(project_skills, "atomic_write", fail)
    rejected = manager.resync()
    assert rejected.state == "UPDATE_REJECTED"
    assert rejected.active_revision == active.active_revision
    assert (manager.root / "active.json").read_bytes() == pointer
    assert manager.active_skills()["example"].joinpath("SKILL.md").is_file()
    assert not list((manager.root / "candidates").iterdir())


@pytest.mark.parametrize("secret_url", [
    "https://alice:password@example.invalid/repo.git?token=secret#private",
    "https://alice:secret'part@example.invalid/repo.git",
    'https://alice:secret"part@example.invalid/repo.git',
    "https://example.invalid/repo.git?token='secret part'",
    'https://example.invalid/repo.git#"secret part"',
    "https://alice: secret'part@example.invalid/repo.git",
    "https://alice:secret 'part@example.invalid/repo.git",
])
def test_status_and_evidence_redact_source_and_validator_errors(fixture, secret_url):
    manager = fixture.manager(validator=lambda _: (False, [{"check": "fixture", "status": "FAIL", "url": secret_url}]))
    with pytest.raises(AgentKitError):
        manager.resync()
    assert "<redacted-url>" in (manager.root / "status.json").read_text()
    status = replace(manager.status(), source_url=secret_url, reason=secret_url)
    for text in ((manager.root / "status.json").read_text(), json.dumps(status.as_dict())):
        assert "<redacted-url>" in text
        assert all(secret not in text for secret in ("alice", "password", "secret", "#private", "part"))


def test_rejected_evidence_masks_urls_in_diagnostic_keys(fixture):
    secret_url = "https://evidence-user:evidence-password@example.invalid/check?token=evidence-token#evidence-fragment"
    manager = fixture.manager(validator=lambda _: (False, [{secret_url: "rejected"}]))
    with pytest.raises(AgentKitError):
        manager.resync()
    rendered = (manager.root / "status.json").read_text()
    assert "<redacted-url>" in rendered
    assert all(secret not in rendered for secret in ("evidence-user", "evidence-password", "evidence-token", "evidence-fragment"))


@pytest.mark.parametrize("has_active", [False, True])
def test_validator_failure_is_rejection_with_candidate_cleanup(fixture, has_active):
    manager = fixture.manager(validator=lambda _: (True, []))
    active = manager.resync() if has_active else None
    fixture.commit_skill("---\nname: example\n---\n# Security checker crashes\n")

    def crash(_):
        raise RuntimeError("security evaluator failed")

    manager.validator = crash
    if active:
        rejected = manager.resync()
        assert rejected.state == "UPDATE_REJECTED"
        assert rejected.active_revision == active.active_revision
    else:
        with pytest.raises(AgentKitError):
            manager.resync()
    assert not list((manager.root / "candidates").iterdir())


def test_successful_update_keeps_old_revision_and_can_return_to_it(fixture):
    manager = fixture.manager(validator=lambda _: (True, []))
    active = manager.resync()
    old_path = manager.active_skills()["example"]
    revision = fixture.commit_skill("---\nname: example\n---\n# Updated\n")
    updated = manager.resync()
    assert updated.active_revision == revision != active.active_revision
    assert old_path.joinpath("SKILL.md").is_file()
    assert manager.active_skills()["example"] != old_path
    git(fixture.upstream, "update-ref", "refs/heads/main", active.active_revision)
    restored = manager.resync()
    assert restored.state == "ACTIVE"
    assert restored.active_revision == active.active_revision
    assert manager.active_skills()["example"] == old_path


def test_resync_uses_configured_default_in_ci_without_changing_override(fixture):
    manager = fixture.manager(validator=lambda _: (True, []))
    fixture.commit_skill("---\nname: example\n---\n# Branch skill\n")
    git(fixture.upstream, "update-ref", "refs/heads/feat/new-check", fixture.remote_revision("main"))
    manager.set_branch("feat/new-check")
    active = manager.resync()
    assert active.requested_branch == "feat/new-check"
    ci = manager.resync(ci=True)
    assert ci.state == "ACTIVE"
    assert ci.requested_branch == "main"
    assert manager.requested_branch() == "feat/new-check"
    assert manager.active_skills()["example"].joinpath("SKILL.md").is_file()


def test_default_security_validator_is_required_for_activation(fixture, monkeypatch):
    from agent_engineering_kit.security_tools import SecurityToolManager

    def reject(self, skill):
        return False, [{"check": "default-validator", "status": "FAIL"}]

    monkeypatch.setattr(SecurityToolManager, "validate_skill", reject)
    manager = fixture.manager()
    with pytest.raises(AgentKitError):
        manager.resync()
    assert not (manager.root / "active.json").exists()
    assert "default-validator" in (manager.root / "status.json").read_text()


def test_changed_default_branch_updates_status_even_with_same_override_revision(fixture):
    manager = fixture.manager(validator=lambda _: (True, []))
    manager.set_branch("main")
    manager.resync()
    fixture.project.manifest["skills"]["repository"]["default_branch"] = "feat/new-check"
    updated = manager.resync()
    assert updated.default_branch == "feat/new-check"
    assert updated.requested_branch == "main"


def test_active_pointer_cannot_use_another_worktree_git_metadata(fixture):
    manager = fixture.manager(validator=lambda _: (True, []))
    active = manager.resync()
    root = manager.active_skills()["example"].parent.parent
    other = manager.root / "other"
    git(manager.checkout, "worktree", "add", "--detach", str(other), active.active_revision)
    (root / ".git").write_text((other / ".git").read_text())
    with pytest.raises(AgentKitError):
        manager.active_skills()


@pytest.mark.parametrize("has_active", [False, True])
@pytest.mark.parametrize("failure", ["fetch", "security"])
def test_diagnostic_write_failure_preserves_authoritative_update_outcome(fixture, monkeypatch, has_active, failure):
    from agent_engineering_kit import project_skills

    secret_url = "https://alice:password@example.invalid/repo.git?token=secret#private"
    manager = fixture.manager(validator=lambda _: (True, []))
    active = manager.resync() if has_active else None
    pointer = manager.root / "active.json"
    pointer_bytes = pointer.read_bytes() if active else None
    if failure == "fetch":
        def fail_fetch(args, **kwargs):
            if "fetch" in args:
                return CommandResult(tuple(args), 1, "", f"cannot fetch {secret_url}")
            return run_command(args, **kwargs)
        manager.runner = fail_fetch
    else:
        manager.validator = lambda _: (False, [{"check": "fixture", "status": "FAIL", "url": secret_url}])
    original_write = project_skills.atomic_write

    def fail_diagnostic(path, content):
        if path.name == "status.json":
            raise OSError(f"cannot write diagnostic {secret_url}")
        original_write(path, content)

    monkeypatch.setattr(project_skills, "atomic_write", fail_diagnostic)
    if active:
        result = manager.resync()
        assert result.state == ("STALE" if failure == "fetch" else "UPDATE_REJECTED")
        assert result.active_revision == active.active_revision
        assert pointer.read_bytes() == pointer_bytes
        assert manager.active_skills()["example"].joinpath("SKILL.md").is_file()
        diagnostic = result.reason
    else:
        with pytest.raises(AgentKitError) as caught:
            manager.resync()
        diagnostic = str(caught.value)
        assert not pointer.exists()
        assert manager.active_skills() == {}
    assert diagnostic
    assert "cannot write diagnostic" not in diagnostic
    assert all(secret not in diagnostic for secret in ("alice", "password", "token=secret", "#private"))
    assert not list((manager.root / "candidates").glob("*"))


def test_non_utf8_diagnostics_reconstruct_status_from_active_pointer(fixture):
    manager = fixture.manager(validator=lambda _: (True, []))
    active = manager.resync()
    pointer = (manager.root / "active.json").read_bytes()
    (manager.root / "status.json").write_bytes(b"\xff\xfe\x80")
    assert manager.status() == active
    assert (manager.root / "active.json").read_bytes() == pointer
    assert manager.active_skills()["example"].joinpath("SKILL.md").is_file()


@pytest.mark.parametrize("variable,value", [
    ("GIT_DIR", "product/.git"),
    ("GIT_WORK_TREE", "product"),
    ("GIT_COMMON_DIR", "product/.git"),
    ("GIT_INDEX_FILE", "product/.git/index"),
    ("GIT_OBJECT_DIRECTORY", "product/.git/objects"),
    ("GIT_ALTERNATE_OBJECT_DIRECTORIES", "product/.git/objects"),
    ("GIT_GRAFT_FILE", "product/.git/info/grafts"),
    ("GIT_SHALLOW_FILE", "product/.git/shallow"),
    ("GIT_REPLACE_REF_BASE", "refs/product/"),
    ("GIT_NAMESPACE", "product"),
    ("GIT_IMPLICIT_WORK_TREE", "0"),
    ("GIT_PREFIX", "product/"),
    ("GIT_INTERNAL_SUPER_PREFIX", "product/"),
    ("GIT_NO_REPLACE_OBJECTS", "1"),
    ("GIT_CONFIG", "product/.git/config"),
    ("GIT_CONFIG_SYSTEM", "product/.git/config"),
    ("GIT_CONFIG_GLOBAL", "product/.git/config"),
    ("GIT_CONFIG_PARAMETERS", "'core.bare=true'"),
    ("GIT_CONFIG_COUNT", "0"),
    ("GIT_CONFIG_KEY_0", "core.worktree"),
    ("GIT_CONFIG_VALUE_0", "product"),
])
def test_git_state_selectors_are_rejected_before_managed_mutation(fixture, monkeypatch, variable, value):
    manager = fixture.manager()
    before = fixture.product_snapshot()
    with monkeypatch.context() as hostile:
        hostile.setenv(variable, value)
        with pytest.raises(AgentKitError):
            manager.fetch_candidate()
    assert fixture.product_snapshot() == before
    assert not manager.checkout.exists()


def test_candidate_discard_rejects_hostile_repository_environment(fixture, monkeypatch):
    manager = fixture.manager()
    candidate, _ = manager.fetch_candidate()
    before = fixture.product_snapshot()
    with monkeypatch.context() as hostile:
        hostile.setenv("GIT_DIR", str(fixture.project.root / ".git"))
        with pytest.raises(AgentKitError):
            manager._discard_candidate(candidate)
    assert fixture.product_snapshot() == before
    assert (candidate / "skills/example/SKILL.md").is_file()
    manager._discard_candidate(candidate)
    assert not candidate.exists()
