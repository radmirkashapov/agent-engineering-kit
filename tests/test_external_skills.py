from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

from agent_engineering_kit.component_state import Lifecycle
from agent_engineering_kit.clients import sync_clients
from agent_engineering_kit.external_skills import ExternalSkillManager
from agent_engineering_kit.override_service import OverrideScope, install_skill_override
from agent_engineering_kit.paths import KitPaths
from conftest import write_yaml


def _git(root: Path, *args: str) -> str:
    env = {"GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.invalid", "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.invalid"}
    completed = subprocess.run(["git", *args], cwd=root, env={**__import__("os").environ, **env}, text=True, capture_output=True, check=True)
    return completed.stdout.strip()


def _fixture(tmp_path: Path, validator) -> tuple[ExternalSkillManager, Path, str]:
    upstream = tmp_path / "upstream"
    skill = upstream / "skills" / "example"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: example\ndescription: test\n---\n# Test\n", encoding="utf-8")
    _git(upstream, "init", "-q")
    _git(upstream, "add", ".")
    _git(upstream, "commit", "-qm", "initial")
    revision = _git(upstream, "rev-parse", "HEAD")
    repository = tmp_path / "kit"
    (repository / "catalog").mkdir(parents=True)
    (repository / "locks").mkdir()
    (repository / "models").mkdir()
    (repository / "models/corporate.yaml").write_text(yaml.safe_dump({"version": 1, "providers": [], "models": []}), encoding="utf-8")
    (repository / "catalog/skills.yaml").write_text(yaml.safe_dump({"version": 1, "skills": [{"id": "fixture", "source": {"type": "git", "repository": str(upstream)}, "installation": {"mode": "external"}, "required": True, "capabilities": ["example"]}]}), encoding="utf-8")
    (repository / "locks/skills.lock.yaml").write_text(yaml.safe_dump({"version": 1, "components": [{"id": "fixture", "version": "1", "revision": revision}]}), encoding="utf-8")
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    return ExternalSkillManager(repository, paths, validator=validator), repository, revision


def test_clean_install_is_external_and_second_run_is_idempotent(tmp_path: Path) -> None:
    manager, repository, revision = _fixture(tmp_path, lambda _: (True, [{"check": "fixture", "status": "PASS"}]))
    first = manager.resync()[0]
    second = manager.resync()[0]
    assert first["status"] == Lifecycle.ACTIVE.value
    assert first["revision"] == revision
    assert Path(first["installation_path"]).is_relative_to(manager.paths.data)
    assert not Path(first["installation_path"]).is_relative_to(repository)
    assert second["changed"] is False
    assert not (repository / "vendor").exists()


def test_failed_candidate_never_becomes_active(tmp_path: Path) -> None:
    manager, _, _ = _fixture(tmp_path, lambda _: (False, [{"check": "fixture", "status": "FAIL"}]))
    state = manager.resync()[0]
    assert state["status"] == Lifecycle.BLOCKED.value
    assert manager.active_path("fixture") is None


def test_missing_required_skill_becomes_blocked_instead_of_crashing(tmp_path: Path) -> None:
    manager, _, _ = _fixture(tmp_path, lambda _: (True, []))
    upstream = Path(manager.desired()[0][0]["source"]["repository"])
    (upstream / "skills/example/SKILL.md").unlink()
    _git(upstream, "add", ".")
    _git(upstream, "commit", "-qm", "remove required skill")
    revision = _git(upstream, "rev-parse", "HEAD")
    (manager.repository / "locks/skills.lock.yaml").write_text(
        yaml.safe_dump({"version": 1, "components": [{"id": "fixture", "version": "2", "revision": revision}]}),
        encoding="utf-8",
    )

    state = manager.resync()[0]

    assert state["status"] == Lifecycle.BLOCKED.value
    assert "required capability отсутствует" in state["reason"]


def test_failed_update_preserves_previous_active_revision(tmp_path: Path) -> None:
    validation_passes = True

    def validator(_):
        return validation_passes, []

    manager, _, first_revision = _fixture(tmp_path, validator)
    first = manager.resync()[0]
    upstream = Path(manager.desired()[0][0]["source"]["repository"])
    (upstream / "skills/example/SKILL.md").write_text("---\nname: example\ndescription: rejected\n---\n", encoding="utf-8")
    _git(upstream, "add", ".")
    _git(upstream, "commit", "-qm", "rejected")
    rejected_revision = _git(upstream, "rev-parse", "HEAD")
    (manager.repository / "locks/skills.lock.yaml").write_text(yaml.safe_dump({"version": 1, "components": [{"id": "fixture", "version": "2", "revision": rejected_revision}]}), encoding="utf-8")
    validation_passes = False
    blocked = manager.resync()[0]
    assert blocked["status"] == Lifecycle.BLOCKED.value
    assert blocked["active_revision"] == first_revision
    assert manager.active_path("fixture") == Path(first["installation_path"])


def test_missing_installation_is_detected_and_restored(tmp_path: Path) -> None:
    manager, _, _ = _fixture(tmp_path, lambda _: (True, []))
    installed = manager.resync()[0]
    installation = Path(installed["installation_path"])
    installation.rename(installation.with_name("externally-removed"))
    assert manager.list()[-1]["status"] == Lifecycle.NOT_INSTALLED.value
    restored = manager.resync()[0]
    assert restored["status"] == Lifecycle.ACTIVE.value
    assert Path(restored["installation_path"]).is_dir()


def test_changed_lock_marks_active_dependency_outdated(tmp_path: Path) -> None:
    manager, _, _ = _fixture(tmp_path, lambda _: (True, []))
    manager.resync()
    upstream = Path(manager.desired()[0][0]["source"]["repository"])
    (upstream / "skills/example/SKILL.md").write_text("---\nname: example\ndescription: newer\n---\n", encoding="utf-8")
    _git(upstream, "add", ".")
    _git(upstream, "commit", "-qm", "new lock")
    revision = _git(upstream, "rev-parse", "HEAD")
    lock = {"version": 1, "components": [{"id": "fixture", "version": "2", "revision": revision}]}
    (manager.repository / "locks/skills.lock.yaml").write_text(yaml.safe_dump(lock), encoding="utf-8")
    assert manager.list()[-1]["status"] == Lifecycle.OUTDATED.value


def test_project_skill_override_changes_effective_status_list(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    override = paths.overrides / "projects/demo/skills/change-impact.yaml"
    override.parent.mkdir(parents=True)
    override.write_text("target: change-impact\noverride:\n  mode: disable\n", encoding="utf-8")

    rows = ExternalSkillManager(repository, paths, project_id="demo").list()

    change_impact = next(item for item in rows if item["id"] == "change-impact")
    assert change_impact["enabled"] is False
    assert change_impact["access_reason"] == "disabled:override"
    assert change_impact["status"] == "DISABLED"


def test_access_policy_can_disable_enforced_skill(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    write_yaml(paths.overrides / "global/access.yaml", {"version": 1, "skills": {"allow": [], "block": ["verification"]}})

    manager = ExternalSkillManager(repository, paths)
    verification = next(row for row in manager.available() if row["id"] == "verification")

    assert verification["enabled"] is False
    assert verification["access_reason"] == "blocked:global"
    listed = next(row for row in manager.list() if row["id"] == "verification")
    assert listed["status"] == "DISABLED"


def test_access_policy_filters_required_external_skill_from_desired(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    write_yaml(paths.overrides / "global/access.yaml", {"version": 1, "skills": {"allow": [], "block": ["superpowers"]}})

    manager = ExternalSkillManager(repository, paths)

    assert "superpowers" not in {item["id"] for item, _ in manager.desired()}
    superpowers = next(row for row in manager.list() if row["id"] == "superpowers")
    assert superpowers["status"] == "DISABLED"


def test_external_skill_can_be_replaced_by_valid_local_skill(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    source = tmp_path / "local-superpowers"
    source.mkdir()
    (source / "SKILL.md").write_text(
        "---\nversion: 1\nname: superpowers\n"
        "description: Provide a user-owned replacement for the external skill bundle\n"
        "policy: configurable\nrequires:\n  model_capabilities: [reasoning]\n"
        "---\n# Local replacement\n",
        encoding="utf-8",
    )
    install_skill_override(
        OverrideScope("global", paths.overrides / "global", None),
        "superpowers",
        source,
    )

    manager = ExternalSkillManager(repository, paths)
    row = next(item for item in manager.list() if item["id"] == "superpowers")
    generated = sync_clients(repository, paths)

    assert row["source"] == "local-override"
    assert row["status"] == Lifecycle.ACTIVE.value
    assert all(item[0]["id"] != "superpowers" for item in manager.desired())
    assert (paths.installations / "clients/shared/skills/superpowers").resolve() == (
        paths.overrides / "global/sources/skills/superpowers"
    ).resolve()
    assert generated


def test_rollback_restores_previous_locked_revision(tmp_path: Path) -> None:
    manager, _, first_revision = _fixture(tmp_path, lambda _: (True, []))
    first = manager.resync()[0]
    upstream = Path(manager.desired()[0][0]["source"]["repository"])
    (upstream / "skills/example/SKILL.md").write_text("---\nname: example\ndescription: changed\n---\n", encoding="utf-8")
    _git(upstream, "add", ".")
    _git(upstream, "commit", "-qm", "second")
    second_revision = _git(upstream, "rev-parse", "HEAD")
    lock = {"version": 1, "components": [{"id": "fixture", "version": "2", "revision": second_revision}]}
    (manager.repository / "locks/skills.lock.yaml").write_text(yaml.safe_dump(lock), encoding="utf-8")
    second = manager.resync()[0]
    restored = manager.rollback("fixture")
    assert first["revision"] == first_revision
    assert second["revision"] == second_revision
    assert restored["revision"] == first_revision
