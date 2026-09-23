from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_engineering_kit.errors import AgentKitError
from agent_engineering_kit.io import load_yaml
from agent_engineering_kit.override_service import (
    OverrideScope,
    install_mcp_override,
    install_skill_override,
    reset_component_override,
    resolve_scope,
    set_component_access,
)
from agent_engineering_kit.overrides import apply_local_overrides
from agent_engineering_kit.paths import KitPaths


def paths_fixture(tmp_path: Path) -> KitPaths:
    data = tmp_path / "data"
    return KitPaths(
        repository=tmp_path / "kit",
        data=data,
        runtime=data / "runtime",
        projects=data / "projects",
        overrides=data / "overrides",
    )


def write_yaml(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def test_disable_and_enable_edit_the_same_yaml_source(tmp_path: Path) -> None:
    scope = OverrideScope("global", tmp_path / "global", None)
    path = set_component_access(scope, "mcp", "context7", enabled=False)
    assert load_yaml(path)["mcp"]["block"] == ["context7"]

    set_component_access(scope, "mcp", "context7", enabled=True)

    assert load_yaml(path)["mcp"]["block"] == []


def test_access_edit_preserves_other_section_and_sorts_lists(tmp_path: Path) -> None:
    scope = OverrideScope("global", tmp_path / "global", None)
    write_yaml(
        scope.root / "access.yaml",
        {
            "version": 1,
            "mcp": {"allow": [], "block": ["zeta"]},
            "skills": {"allow": ["review"], "block": ["legacy"]},
        },
    )

    target = set_component_access(scope, "mcp", "alpha", enabled=False)

    document = load_yaml(target)
    assert document["mcp"]["block"] == ["alpha", "zeta"]
    assert document["skills"] == {"allow": ["review"], "block": ["legacy"]}


def test_invalid_access_document_is_not_replaced(tmp_path: Path) -> None:
    scope = OverrideScope("global", tmp_path / "global", None)
    target = write_yaml(scope.root / "access.yaml", {"version": 1, "mcp": "сломано"})
    original = target.read_bytes()

    with pytest.raises(AgentKitError, match="Некорректный раздел политики доступа"):
        set_component_access(scope, "mcp", "context7", enabled=False)

    assert target.read_bytes() == original


def test_malformed_access_list_reports_domain_error_without_replacing_file(tmp_path: Path) -> None:
    scope = OverrideScope("global", tmp_path / "global", None)
    target = write_yaml(
        scope.root / "access.yaml",
        {"version": 1, "mcp": {"allow": [], "block": [{"id": "context7"}]}},
    )
    original = target.read_bytes()

    with pytest.raises(AgentKitError, match="Список mcp.block"):
        set_component_access(scope, "mcp", "context7", enabled=False)

    assert target.read_bytes() == original


def test_project_scope_requires_logical_project(tmp_path: Path) -> None:
    with pytest.raises(AgentKitError, match="Логический проект не найден"):
        resolve_scope(paths_fixture(tmp_path), "project", tmp_path)


def test_project_scope_uses_discovered_project_identifier(tmp_path: Path) -> None:
    paths = paths_fixture(tmp_path)
    working_directory = tmp_path / "workspace/repository"
    write_yaml(
        tmp_path / "workspace/.ai-team/project.yaml",
        {"id": "demo-project"},
    )
    working_directory.mkdir(parents=True)

    scope = resolve_scope(paths, "project", working_directory)

    assert scope == OverrideScope(
        "project",
        paths.overrides / "projects/demo-project",
        "demo-project",
    )


def test_skill_override_is_copied_and_uses_relative_path(tmp_path: Path) -> None:
    source = tmp_path / "custom"
    source.mkdir()
    (source / "SKILL.md").write_text(
        "---\nversion: 1\nname: greeting\ndescription: Пример\n"
        "policy: configurable\nrequires:\n  model_capabilities: [reasoning]\n---\n# Приветствие\n",
        encoding="utf-8",
    )
    scope = OverrideScope("global", tmp_path / "global", None)

    target = install_skill_override(scope, "greeting", source)

    document = load_yaml(target)
    assert document["override"]["mode"] == "replace"
    relative = document["override"]["value"]["path"]
    assert not Path(relative).is_absolute()
    assert (target.parent / relative).resolve().is_dir()


def test_relative_override_path_is_resolved_from_declaring_yaml(tmp_path: Path) -> None:
    override_root = tmp_path / "overrides"
    definition = override_root / "global/skills/greeting.yaml"
    copied_source = override_root / "global/sources/skills/greeting"
    copied_source.mkdir(parents=True)
    definition.parent.mkdir(parents=True)
    definition.write_text(
        "target: greeting\noverride:\n  mode: replace\n  value:\n    path: ../sources/skills/greeting\n",
        encoding="utf-8",
    )

    effective = apply_local_overrides([{"id": "greeting", "path": "исходный"}], override_root, "skills")

    assert effective[0]["path"] == str(copied_source.resolve())


def test_mcp_override_rejects_literal_secret(tmp_path: Path) -> None:
    source = write_yaml(
        tmp_path / "mcp.yaml",
        {"mode": "extend", "value": {"environment": {"TOKEN": "literal-value"}}},
    )

    with pytest.raises(AgentKitError, match="env:VARIABLE"):
        install_mcp_override(OverrideScope("global", tmp_path / "global", None), "github", source)


def test_mcp_override_accepts_environment_reference(tmp_path: Path) -> None:
    source = write_yaml(
        tmp_path / "mcp.yaml",
        {"mode": "extend", "value": {"environment": {"TOKEN": "env:GITHUB_TOKEN"}}},
    )

    target = install_mcp_override(
        OverrideScope("global", tmp_path / "global", None),
        "github",
        source,
    )

    assert load_yaml(target) == {
        "target": "github",
        "override": {
            "mode": "extend",
            "value": {"environment": {"TOKEN": "env:GITHUB_TOKEN"}},
        },
    }


def test_reset_moves_definition_and_source_to_timestamped_backup(tmp_path: Path) -> None:
    scope = OverrideScope("global", tmp_path / "global", None)
    active = write_yaml(
        scope.root / "skills/greeting.yaml",
        {"target": "greeting", "override": {"mode": "disable"}},
    )
    local_source = scope.root / "sources/skills/greeting"
    local_source.mkdir(parents=True)
    (local_source / "SKILL.md").write_text("содержимое", encoding="utf-8")
    write_yaml(
        scope.root / "access.yaml",
        {
            "version": 1,
            "mcp": {"allow": [], "block": []},
            "skills": {"allow": ["greeting", "other"], "block": []},
        },
    )

    backup_root = tmp_path / "backups"
    moved = reset_component_override(scope, "skills", "greeting", backup_root)

    assert not active.exists()
    assert not local_source.exists()
    assert any(path.name == "greeting.yaml" and path.exists() for path in moved)
    assert any(path.name == "greeting" and path.is_dir() for path in moved)
    assert load_yaml(scope.root / "access.yaml")["skills"]["allow"] == ["other"]
    assert len({path.relative_to(backup_root).parts[0] for path in moved}) == 1
