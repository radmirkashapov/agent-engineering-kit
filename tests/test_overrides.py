from __future__ import annotations

from pathlib import Path
import shutil

import pytest

from agent_engineering_kit.overrides import validate_overrides
from conftest import write_yaml


@pytest.fixture
def kit(tmp_path: Path) -> tuple[Path, Path]:
    repository = tmp_path / "kit"
    overrides = tmp_path / "data/overrides"
    (repository / "schemas").mkdir(parents=True)
    shutil.copy(Path(__file__).resolve().parents[1] / "schemas/override.schema.json", repository / "schemas/override.schema.json")
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
