from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from agent_engineering_kit import skill_authoring
from agent_engineering_kit.errors import AgentKitError
from agent_engineering_kit.projects import LogicalProject
from agent_engineering_kit.skill_authoring import (
    add_bundled_skill,
    add_project_skill,
    checkout_project_skills,
    write_project_skill_index,
)


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
         "-c", "commit.gpgsign=false", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def write_skill(directory: Path, name: str, description: str = "Review API changes.") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_text(
        f"---\nversion: 1\nname: {name}\ndescription: {description}\n"
        "requires:\n  model_capabilities: []\n---\n# Skill\n",
        encoding="utf-8",
    )
    return directory


@pytest.fixture
def kit_repository(tmp_path: Path) -> Path:
    repository = tmp_path / "kit"
    (repository / "schemas").mkdir(parents=True)
    schema = Path(__file__).resolve().parents[1] / "schemas" / "skill.schema.json"
    shutil.copyfile(schema, repository / "schemas" / schema.name)
    git(repository, "init", "-qb", "main")
    git(repository, "add", ".")
    git(repository, "commit", "-qm", "add schema")
    return repository


@dataclass
class ProjectFixture:
    repository: Path
    project: LogicalProject
    source: Path
    remote: Path
    data: Path

    def clone_sibling(self) -> Path:
        checkout = self.project.root.parent / "authoring-checkout"
        git(self.remote, "clone", "-qb", "project-skills", str(self.remote), str(checkout))
        return checkout


@pytest.fixture
def fixture(tmp_path: Path, kit_repository: Path, monkeypatch: pytest.MonkeyPatch) -> ProjectFixture:
    data = tmp_path / "kit-data"
    monkeypatch.setenv("AGENT_KIT_DATA_HOME", str(data))
    remote = tmp_path / "skills-remote"
    write_skill(remote / "skills" / "zeta", "zeta", "Review database migrations.")
    git(remote, "init", "-qb", "project-skills")
    git(remote, "add", ".")
    git(remote, "commit", "-qm", "add project skill")
    product = tmp_path / "product"
    product.mkdir()
    git(product, "init", "-qb", "main")
    git(product, "remote", "add", "origin", str(remote))
    project = LogicalProject(product, product / ".ai-team/project.yaml", {
        "id": "delivery",
        "repositories": [{"id": "product", "path": "."}],
        "skills": {"repository": {"url": str(remote), "default_branch": "project-skills"}},
    })
    return ProjectFixture(kit_repository, project, write_skill(tmp_path / "source", "review-api"), remote, data)


def test_add_bundled_skill_copies_validated_directory(tmp_path: Path, kit_repository: Path):
    source = write_skill(tmp_path / "source", "review-api")
    (source / "references").mkdir()
    (source / "references" / "guide.md").write_text("# Guide\n", encoding="utf-8")
    original_head = git(kit_repository, "rev-parse", "HEAD")

    target = add_bundled_skill(kit_repository, source, identifier="review-api")

    assert target == kit_repository / "skills/first-party/review-api"
    assert (target / "SKILL.md").read_bytes() == (source / "SKILL.md").read_bytes()
    assert (target / "references" / "guide.md").read_text(encoding="utf-8") == "# Guide\n"
    assert git(kit_repository, "rev-parse", "HEAD") == original_head
    assert git(kit_repository, "diff", "--cached", "--name-only") == ""


@pytest.mark.parametrize("identifier", ["../review-api", "different-name", ""])
def test_add_bundled_skill_rejects_mismatched_or_invalid_identifier(
    tmp_path: Path, kit_repository: Path, identifier: str,
):
    source = write_skill(tmp_path / "source", "review-api")

    with pytest.raises(AgentKitError, match="skill"):
        add_bundled_skill(kit_repository, source, identifier=identifier)

    assert not (kit_repository / "skills").exists()


@pytest.mark.parametrize("linked_path", ["source", "parent", "SKILL.md", "nested", "destination-parent", "target"])
def test_add_bundled_skill_rejects_symlinks(tmp_path: Path, kit_repository: Path, linked_path: str):
    source = write_skill(tmp_path / "source", "review-api")
    if linked_path == "source":
        alias = tmp_path / "alias"
        alias.symlink_to(source, target_is_directory=True)
        source = alias
    elif linked_path == "parent":
        alias = tmp_path / "alias"
        alias.symlink_to(tmp_path, target_is_directory=True)
        source = alias / "source"
    elif linked_path == "SKILL.md":
        (source / "SKILL.md").rename(tmp_path / "external.md")
        (source / "SKILL.md").symlink_to(tmp_path / "external.md")
    elif linked_path == "nested":
        (source / "references").mkdir()
        (source / "references" / "broken").symlink_to(tmp_path / "missing.md")
    elif linked_path == "destination-parent":
        (kit_repository / "skills").symlink_to(tmp_path, target_is_directory=True)
    else:
        target = kit_repository / "skills/first-party/review-api"
        target.parent.mkdir(parents=True)
        target.symlink_to(tmp_path / "missing", target_is_directory=True)

    with pytest.raises(AgentKitError, match="symlink"):
        add_bundled_skill(kit_repository, source)

    assert not (kit_repository / "skills/first-party/review-api/SKILL.md").exists()
    assert not (tmp_path / "first-party").exists()


def test_add_bundled_skill_rejects_invalid_frontmatter(tmp_path: Path, kit_repository: Path):
    source = write_skill(tmp_path / "source", "review-api")
    (source / "SKILL.md").write_text("---\nname: review-api\n---\n", encoding="utf-8")

    with pytest.raises(AgentKitError, match="description"):
        add_bundled_skill(kit_repository, source)

    assert not (kit_repository / "skills").exists()


def test_add_bundled_skill_rejects_nested_git_repository(tmp_path: Path, kit_repository: Path):
    source = write_skill(tmp_path / "source", "review-api")
    nested = source / "references"
    nested.mkdir()
    git(nested, "init", "-qb", "main")

    with pytest.raises(AgentKitError, match=r"\.git"):
        add_bundled_skill(kit_repository, source)

    assert not (kit_repository / "skills").exists()


def test_add_bundled_skill_requires_explicit_replace(tmp_path: Path, kit_repository: Path):
    source = write_skill(tmp_path / "source", "review-api")
    target = add_bundled_skill(kit_repository, source)
    original = (target / "SKILL.md").read_bytes()
    write_skill(source, "review-api", "Use a different description.")

    with pytest.raises(AgentKitError, match="replace"):
        add_bundled_skill(kit_repository, source)

    assert (target / "SKILL.md").read_bytes() == original


@pytest.mark.parametrize("dirty", ["unrelated", "ignored-target", "staged-target"])
def test_replace_bundled_skill_preserves_dirty_worktree(
    tmp_path: Path, kit_repository: Path, dirty: str,
):
    source = write_skill(tmp_path / "source", "review-api")
    target = add_bundled_skill(kit_repository, source)
    (kit_repository / ".gitignore").write_text("*.local\n", encoding="utf-8")
    git(kit_repository, "add", ".")
    git(kit_repository, "commit", "-qm", "track bundled skill")
    if dirty == "unrelated":
        (kit_repository / "local.md").touch()
    elif dirty == "ignored-target":
        (target / "notes.local").touch()
    else:
        write_skill(target, "review-api", "Keep staged edits.")
        git(kit_repository, "add", ".")
    original = (target / "SKILL.md").read_bytes()
    write_skill(source, "review-api", "Use a different description.")

    with pytest.raises(AgentKitError, match="clean|tracked"):
        add_bundled_skill(kit_repository, source, replace=True)

    assert (target / "SKILL.md").read_bytes() == original


def test_replace_bundled_skill_replaces_entire_clean_tracked_tree(tmp_path: Path, kit_repository: Path):
    source = write_skill(tmp_path / "source", "review-api")
    target = add_bundled_skill(kit_repository, source)
    (target / "old.md").touch()
    git(kit_repository, "add", ".")
    git(kit_repository, "commit", "-qm", "track bundled skill")
    write_skill(source, "review-api", "Use a different description.")

    assert add_bundled_skill(kit_repository, source, replace=True) == target
    assert not (target / "old.md").exists()
    assert (target / "SKILL.md").read_bytes() == (source / "SKILL.md").read_bytes()
    assert git(kit_repository, "diff", "--cached", "--name-only") == ""


def test_checkout_project_skills_uses_configured_branch(fixture: ProjectFixture):
    checkout = fixture.project.root.parent / "sibling"
    checkout.mkdir()
    git(fixture.remote, "branch", "main")
    git(fixture.remote, "symbolic-ref", "HEAD", "refs/heads/main")

    assert checkout_project_skills(fixture.project, checkout) == checkout
    assert (checkout / ".git").is_dir()
    assert git(checkout, "branch", "--show-current") == "project-skills"
    assert git(checkout, "remote", "get-url", "origin") == str(fixture.remote)


def test_checkout_project_skills_rejects_nonempty_directory(fixture: ProjectFixture):
    checkout = fixture.project.root.parent / "sibling"
    checkout.mkdir()
    sentinel = checkout / "keep.md"
    sentinel.touch()

    with pytest.raises(AgentKitError, match="empty"):
        checkout_project_skills(fixture.project, checkout)

    assert list(checkout.iterdir()) == [sentinel]


@pytest.mark.parametrize("location", ["product", "product-child", "managed"])
def test_checkout_and_add_reject_protected_locations(fixture: ProjectFixture, location: str):
    checkout, reason = {
        "product": (fixture.project.root, "product repository"),
        "product-child": (fixture.project.root / "authoring", "product repository"),
        "managed": (fixture.data / "projects/delivery/skills-repository/checkout", "managed"),
    }[location]
    with pytest.raises(AgentKitError, match=reason):
        checkout_project_skills(fixture.project, checkout)

    if location != "product":
        checkout.parent.mkdir(parents=True, exist_ok=True)
        git(fixture.remote, "clone", "-q", str(fixture.remote), str(checkout))

    with pytest.raises(AgentKitError, match=reason):
        add_project_skill(fixture.repository, fixture.project, fixture.source, checkout)

    assert not (checkout / "skills/review-api").exists()


def test_checkout_rejects_actual_product_repo_when_logical_root_is_nested(fixture: ProjectFixture):
    product = fixture.project.root
    logical_root = product / "nested"
    logical_root.mkdir()
    project = replace(fixture.project, root=logical_root)
    checkout = product / "skills-sibling"

    with pytest.raises(AgentKitError, match="product repository"):
        checkout_project_skills(project, checkout)

    assert not checkout.exists()


def test_authoring_checkout_can_be_sibling_inside_multi_repository_workspace(fixture: ProjectFixture):
    workspace = fixture.project.root.parent
    backend = workspace / "backend"
    backend.mkdir()
    git(backend, "init", "-qb", "main")
    project = replace(
        fixture.project,
        root=workspace,
        manifest_path=workspace / ".ai-team/project.yaml",
        manifest={
            **fixture.project.manifest,
            "repositories": [
                {"id": "product", "path": fixture.project.root.name},
                {"id": "backend", "path": backend.name},
            ],
        },
    )
    checkout = workspace / "authoring-checkout"

    assert checkout_project_skills(project, checkout) == checkout
    assert add_project_skill(fixture.repository, project, fixture.source, checkout).is_dir()


@pytest.mark.parametrize("checkout_kind", ["mismatched-origin", "bare", "git-subdirectory", "worktree"])
def test_add_project_skill_requires_matching_normal_checkout(fixture: ProjectFixture, checkout_kind: str):
    checkout = fixture.clone_sibling()
    if checkout_kind == "mismatched-origin":
        git(checkout, "remote", "set-url", "origin", str(fixture.project.root))
    elif checkout_kind == "bare":
        checkout = checkout.with_name("bare")
        git(fixture.remote, "clone", "-q", "--bare", str(fixture.remote), str(checkout))
    elif checkout_kind == "git-subdirectory":
        checkout = checkout / "skills"
    else:
        worktree = checkout.with_name("worktree")
        git(checkout, "worktree", "add", "-q", "--detach", str(worktree))
        checkout = worktree

    with pytest.raises(AgentKitError, match="checkout|origin"):
        add_project_skill(fixture.repository, fixture.project, fixture.source, checkout)

    assert not (checkout / "skills/review-api").exists()


def test_checkout_project_skills_explains_missing_configuration(fixture: ProjectFixture):
    project = replace(fixture.project, manifest={"id": "delivery"})
    checkout = fixture.project.root.parent / "sibling"
    with pytest.raises(AgentKitError, match="skills.repository.*project init"):
        checkout_project_skills(project, checkout)
    assert not checkout.exists()


def test_add_project_skill_writes_deterministic_index(fixture: ProjectFixture):
    checkout = fixture.clone_sibling()
    project = replace(fixture.project, manifest={
        **fixture.project.manifest,
        "skills": {"repository": {"url": f" {fixture.remote.as_uri()}/ ", "default_branch": "project-skills"}},
    })
    write_skill(checkout / "skills" / "support" / "nested", "nested")
    write_skill(fixture.source, "review-api", "'Review | API changes.'")

    target = add_project_skill(fixture.repository, project, fixture.source, checkout)
    index = checkout / "skills" / "INDEX.md"
    initial_content = index.read_text(encoding="utf-8")

    assert target == checkout / "skills/review-api"
    assert initial_content == (
        "# Project skills\n\n| ID | Назначение | Определение |\n|---|---|---|\n"
        "| `review-api` | Review \\| API changes. | `review-api/SKILL.md` |\n"
        "| `zeta` | Review database migrations. | `zeta/SKILL.md` |\n"
    )
    assert write_project_skill_index(fixture.repository, checkout) == index
    assert index.read_text(encoding="utf-8") == initial_content
    assert git(checkout, "diff", "--cached", "--name-only") == ""


def test_contextual_index_rejects_checkout_for_a_different_origin(fixture: ProjectFixture):
    checkout = fixture.clone_sibling()
    git(checkout, "remote", "set-url", "origin", str(fixture.project.root))

    with pytest.raises(AgentKitError, match="origin"):
        write_project_skill_index(fixture.repository, checkout, project=fixture.project)

    assert not (checkout / "skills/INDEX.md").exists()


@pytest.mark.parametrize("replace_existing", [False, True])
def test_add_project_skill_rolls_back_copy_when_index_write_fails(
    fixture: ProjectFixture, monkeypatch: pytest.MonkeyPatch, replace_existing: bool,
):
    checkout = fixture.clone_sibling()
    index = write_project_skill_index(fixture.repository, checkout)
    target = checkout / "skills/zeta"
    if not replace_existing:
        target = checkout / "skills/review-api"
    original = (target / "SKILL.md").read_bytes() if replace_existing else None
    if replace_existing:
        (target / "previous.md").touch()
        write_skill(fixture.source, "zeta", "Use a different description.")
    git(checkout, "add", ".")
    git(checkout, "commit", "-qm", "track index")
    initial_index = index.read_bytes()

    def fail_write(path: Path, content: str) -> None:
        raise OSError("index write failed")

    monkeypatch.setattr(skill_authoring, "atomic_write", fail_write)
    with pytest.raises(AgentKitError, match="index write failed"):
        add_project_skill(fixture.repository, fixture.project, fixture.source, checkout, replace=replace_existing)

    if replace_existing:
        assert (target / "SKILL.md").read_bytes() == original
        assert (target / "previous.md").is_file()
    else:
        assert not target.exists()
    assert index.read_bytes() == initial_index
    assert git(checkout, "status", "--porcelain") == ""


def test_add_project_skill_preserves_index_when_existing_skill_is_invalid(fixture: ProjectFixture):
    checkout = fixture.clone_sibling()
    index = write_project_skill_index(fixture.repository, checkout)
    initial_index = index.read_bytes()
    write_skill(checkout / "skills/wrong-name", "different-name")

    with pytest.raises(AgentKitError, match="wrong-name"):
        add_project_skill(fixture.repository, fixture.project, fixture.source, checkout)

    assert index.read_bytes() == initial_index
    assert not (checkout / "skills/review-api").exists()


@pytest.mark.parametrize("path", ["skills", "skills/INDEX.md", "skills/linked", "skills/zeta/SKILL.md"])
def test_index_rejects_symlinks(fixture: ProjectFixture, tmp_path: Path, path: str):
    checkout = fixture.clone_sibling()
    link = checkout / path
    if link.is_dir():
        link.rename(tmp_path / "external")
    elif link.is_file():
        link.rename(tmp_path / "external")
    link.symlink_to(tmp_path / "external")

    with pytest.raises(AgentKitError, match="symlink"):
        write_project_skill_index(fixture.repository, checkout)

    assert link.is_symlink()
