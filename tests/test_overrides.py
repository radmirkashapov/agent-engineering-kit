from __future__ import annotations

from pathlib import Path
import shutil

import pytest

from agent_engineering_kit.overrides import apply_local_overrides, validate_overrides
from agent_engineering_kit.errors import AgentKitError
from agent_engineering_kit.mcp_manager import McpManager
from agent_engineering_kit.paths import KitPaths
from conftest import write_yaml


@pytest.fixture
def kit(tmp_path: Path) -> tuple[Path, Path]:
    repository = tmp_path / "kit"
    overrides = tmp_path / "data/overrides"
    (repository / "schemas").mkdir(parents=True)
    shutil.copy(Path(__file__).resolve().parents[1] / "schemas/override.schema.json", repository / "schemas/override.schema.json")
    shutil.copy(Path(__file__).resolve().parents[1] / "schemas/mcp.schema.json", repository / "schemas/mcp.schema.json")
    skill = repository / "skills/code-review/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "---\nid: code-review\npolicy: configurable\n---\n# Skill\n", encoding="utf-8"
    )
    enforced = repository / "skills/verification/SKILL.md"
    enforced.parent.mkdir(parents=True)
    enforced.write_text(
        "---\nid: verification\npolicy: enforced\n---\n# Skill\n", encoding="utf-8"
    )
    write_yaml(repository / "mcp/registry.yaml", {"servers": []})
    return repository, overrides


@pytest.mark.parametrize("mode", ["extend", "replace"])
def test_existing_skill_override_passes(kit: tuple[Path, Path], mode: str) -> None:
    repository, overrides = kit
    write_yaml(overrides / "global/skills/code-review.yaml", {"target": "code-review", "override": {"mode": mode}})
    assert validate_overrides(repository, overrides).ok


def test_unknown_target_fails(kit: tuple[Path, Path]) -> None:
    repository, overrides = kit
    write_yaml(overrides / "global/skills/missing.yaml", {"target": "missing", "override": {"mode": "extend"}})
    assert not validate_overrides(repository, overrides).ok


def test_disable_enforced_skill_fails(kit: tuple[Path, Path]) -> None:
    repository, overrides = kit
    write_yaml(overrides / "global/skills/verification.yaml", {"target": "verification", "override": {"mode": "disable"}})
    assert not validate_overrides(repository, overrides).ok


def test_required_external_skill_cannot_be_disabled(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    overrides = tmp_path / "overrides"
    write_yaml(overrides / "global/skills/superpowers.yaml", {"target": "superpowers", "override": {"mode": "disable"}})
    assert not validate_overrides(repository, overrides).ok


def test_project_override_wins_over_global_override(tmp_path: Path) -> None:
    overrides = tmp_path / "overrides"
    write_yaml(overrides / "global/mcp/optional.yaml", {"target": "optional", "override": {"mode": "extend", "value": {"installation": {"endpoint": "https://global.invalid/mcp"}}}})
    write_yaml(overrides / "projects/demo/mcp/optional.yaml", {"target": "optional", "override": {"mode": "extend", "value": {"installation": {"endpoint": "https://project.invalid/mcp"}}}})
    items = [{"id": "optional", "installation": {"type": "remote", "endpoint": "https://base.invalid/mcp"}}]
    effective = apply_local_overrides(items, overrides, "mcp", "demo")
    assert effective[0]["installation"]["endpoint"] == "https://project.invalid/mcp"


def test_disable_removes_optional_effective_component(tmp_path: Path) -> None:
    overrides = tmp_path / "overrides"
    write_yaml(overrides / "global/mcp/optional.yaml", {"target": "optional", "override": {"mode": "disable"}})
    assert apply_local_overrides([{"id": "optional"}], overrides, "mcp") == []


def test_incomplete_mcp_replace_is_rejected_as_configuration_error(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    write_yaml(
        paths.overrides / "global/mcp/github.yaml",
        {"target": "github", "override": {"mode": "replace", "value": {"installation": {"type": "remote", "endpoint": "https://example.invalid/mcp"}}}},
    )

    with pytest.raises(AgentKitError, match="Некорректный effective MCP override"):
        McpManager(repository, paths).list()
    assert not validate_overrides(repository, paths.overrides).ok
