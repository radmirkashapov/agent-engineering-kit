from __future__ import annotations

from pathlib import Path

from agent_engineering_kit.access import resolve_access, validate_access
from conftest import write_yaml


def test_empty_policy_allows_every_known_component(tmp_path: Path) -> None:
    write_yaml(tmp_path / "global/access.yaml", {"version": 1, "mcp": {"allow": [], "block": []}})

    decisions = resolve_access({"context7", "github"}, tmp_path, "mcp")

    assert {key for key, value in decisions.items() if value.enabled} == {"context7", "github"}


def test_block_wins_and_project_cannot_restore_global_block(tmp_path: Path) -> None:
    write_yaml(tmp_path / "global/access.yaml", {"version": 1, "mcp": {"allow": [], "block": ["context7"]}})
    write_yaml(tmp_path / "projects/demo/access.yaml", {"version": 1, "mcp": {"allow": ["context7"], "block": []}})

    decision = resolve_access({"context7"}, tmp_path, "mcp", "demo")["context7"]

    assert decision.enabled is False
    assert decision.reason == "blocked:global"


def test_non_empty_allowlists_are_intersected(tmp_path: Path) -> None:
    write_yaml(
        tmp_path / "global/access.yaml",
        {"version": 1, "skills": {"allow": ["greeting", "verification"], "block": []}},
    )
    write_yaml(
        tmp_path / "projects/demo/access.yaml",
        {"version": 1, "skills": {"allow": ["greeting"], "block": []}},
    )

    decisions = resolve_access({"greeting", "verification"}, tmp_path, "skills", "demo")

    assert decisions["greeting"].enabled is True
    assert decisions["verification"].reason == "not-allowed:project"


def test_unknown_and_conflicting_ids_fail_validation(tmp_path: Path) -> None:
    write_yaml(
        tmp_path / "global/access.yaml",
        {"version": 1, "mcp": {"allow": ["missing", "github"], "block": ["github"]}},
    )

    result = validate_access({"mcp": {"github"}, "skills": set()}, tmp_path)

    messages = "\n".join(item.message for item in result.diagnostics)
    assert not result.ok
    assert "неизвестные ID" in messages
    assert "одновременно" in messages
