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
    shutil.copy(Path(__file__).resolve().parents[1] / "schemas/skill.schema.json", repository / "schemas/skill.schema.json")
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
    value: dict[str, str] = {}
    if mode == "replace":
        local = overrides / "global/skills/local-code-review"
        local.mkdir(parents=True)
        (local / "SKILL.md").write_text(
            "---\nversion: 1\nname: code-review\ndescription: Review local changes for defects and regressions\n"
            "policy: configurable\nrequires:\n  model_capabilities: [reasoning]\n---\n# Local\n",
            encoding="utf-8",
        )
        value["path"] = "./local-code-review"
    write_yaml(
        overrides / "global/skills/code-review.yaml",
        {"target": "code-review", "override": {"mode": mode, "value": value}},
    )
    assert validate_overrides(repository, overrides).ok


def test_unknown_target_fails(kit: tuple[Path, Path]) -> None:
    repository, overrides = kit
    write_yaml(overrides / "global/skills/missing.yaml", {"target": "missing", "override": {"mode": "extend"}})
    assert not validate_overrides(repository, overrides).ok


def test_disable_enforced_skill_passes(kit: tuple[Path, Path]) -> None:
    repository, overrides = kit
    write_yaml(overrides / "global/skills/verification.yaml", {"target": "verification", "override": {"mode": "disable"}})
    assert validate_overrides(repository, overrides).ok
    items = [{"id": "verification", "policy": "enforced"}]
    assert apply_local_overrides(items, overrides, "skills", enforced={"verification"}) == []


def test_replace_enforced_skill_passes_without_preserving_base_fields(kit: tuple[Path, Path]) -> None:
    repository, overrides = kit
    local = overrides / "global/skills/local"
    local.mkdir(parents=True)
    (local / "SKILL.md").write_text(
        "---\nversion: 1\nname: verification\ndescription: User-owned verification skill\n"
        "policy: configurable\nrequires:\n  model_capabilities: [reasoning]\n---\n# Local\n",
        encoding="utf-8",
    )
    write_yaml(
        overrides / "global/skills/verification.yaml",
        {
            "target": "verification",
            "override": {
                "mode": "replace",
                "value": {"description": "User-owned verification skill", "path": "./local"},
            },
        },
    )

    assert validate_overrides(repository, overrides).ok
    effective = apply_local_overrides(
        [{"id": "verification", "policy": "enforced", "description": "Base"}],
        overrides,
        "skills",
        enforced={"verification"},
    )

    assert effective == [
        {
            "id": "verification",
            "description": "User-owned verification skill",
            "path": str((overrides / "global/skills/local").resolve()),
        }
    ]


@pytest.mark.parametrize(
    ("kind", "target"),
    [("rules", "security"), ("rules", "context"), ("rules", "models"), ("agents", "orchestrator"), ("agents", "qa-engineer")],
)
@pytest.mark.parametrize("mode", ["replace", "disable"])
def test_mandatory_rules_and_agents_cannot_be_replaced_or_disabled(
    tmp_path: Path,
    kind: str,
    target: str,
    mode: str,
) -> None:
    repository = Path(__file__).resolve().parents[1]
    overrides = tmp_path / "overrides"
    write_yaml(
        overrides / f"global/{kind}/{target}.yaml",
        {"target": target, "override": {"mode": mode, "value": {"content": "No checks"}}},
    )

    assert not validate_overrides(repository, overrides).ok


def test_mandatory_rule_content_cannot_be_changed_by_extend(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    overrides = tmp_path / "overrides"
    write_yaml(
        overrides / "global/rules/security.yaml",
        {"target": "security", "override": {"mode": "extend", "value": {"content": "No checks"}}},
    )

    assert not validate_overrides(repository, overrides).ok
    effective = apply_local_overrides(
        [{"id": "security", "policy": "enforced", "content": "Keep security checks"}],
        overrides,
        "rules",
        enforced={"security"},
    )
    assert effective[0]["content"] == "Keep security checks"


def test_local_skill_replace_requires_existing_valid_matching_skill(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    overrides = tmp_path / "overrides"
    write_yaml(
        overrides / "global/skills/verification.yaml",
        {"target": "verification", "override": {"mode": "replace", "value": {"path": "./missing"}}},
    )

    result = validate_overrides(repository, overrides)

    assert not result.ok
    assert any("SKILL.md" in item.message for item in result.diagnostics)


def test_validation_succeeds_without_mcp_registry(kit: tuple[Path, Path]) -> None:
    repository, overrides = kit
    (repository / "mcp/registry.yaml").unlink()

    assert validate_overrides(repository, overrides).ok


def test_required_external_skill_can_be_disabled(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    overrides = tmp_path / "overrides"
    write_yaml(overrides / "global/skills/superpowers.yaml", {"target": "superpowers", "override": {"mode": "disable"}})
    assert validate_overrides(repository, overrides).ok


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
