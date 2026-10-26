from __future__ import annotations

import json
import os
import stat
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from agent_engineering_kit.errors import AgentKitError
from agent_engineering_kit.paths import KitPaths
from agent_engineering_kit.process import CommandResult, run_command
from agent_engineering_kit.projects import LogicalProject
from agent_engineering_kit.project_skills import ProjectSkillRepositoryManager, redact_url


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

    def manager(self, *, second_root: bool = False, runner=run_command):
        project = replace(self.project, root=self.project.root.parent / "other") if second_root else self.project
        return ProjectSkillRepositoryManager(self.paths.repository, self.paths, project, runner=runner)

    def remote_revision(self, branch: str) -> str:
        return git(self.upstream, "rev-parse", f"refs/heads/{branch}")

    def product_state(self) -> tuple[str, ...]:
        return tuple(git(self.project.root, *args) for args in (
            ("rev-parse", "HEAD"), ("symbolic-ref", "HEAD"), ("status", "--porcelain"),
            ("diff", "--cached"), ("config", "--local", "--list"),
        ))


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
    project = LogicalProject(product, product / ".ai-team/project.yaml", {
        "id": "shared", "skills": {"repository": {"url": str(upstream), "default_branch": "main"}},
    })
    return RepositoryFixture(upstream, seed, project, paths)


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
        assert "example.invalid/repo.git" in output


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
