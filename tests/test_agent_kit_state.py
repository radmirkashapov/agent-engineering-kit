from pathlib import Path

import pytest

from agent_engineering_kit.agent_kit_state import read_status, set_enabled
from agent_engineering_kit.clients import expose_native_instructions
from agent_engineering_kit.errors import AgentKitError
from agent_engineering_kit.paths import KitPaths


def make_paths(tmp_path: Path) -> KitPaths:
    repository = tmp_path / "kit"
    repository.mkdir()
    return KitPaths(repository, tmp_path / "data", tmp_path / "runtime", tmp_path / "projects", tmp_path / "overrides")


def test_toggle_defaults_to_enabled_and_is_idempotent(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)

    assert read_status(paths).enabled is True
    first = set_enabled(paths, False)
    second = set_enabled(paths, False)
    assert first.enabled is False
    assert second.enabled is False
    assert read_status(paths).enabled is False
    assert set_enabled(paths, True).enabled is True


def test_corrupted_status_reports_machine_local_path(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    paths.state.mkdir(parents=True)
    status_path = paths.state / "agent-kit-status.json"
    status_path.write_text("{broken", encoding="utf-8")

    with pytest.raises(AgentKitError, match=str(status_path)):
        read_status(paths)


def test_instruction_bridge_publishes_disabled_state_immediately(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    repository = paths.repository
    (repository / "AI.md").write_text("# Kit\n", encoding="utf-8")
    home = tmp_path / "home"
    user_file = home / ".codex/AGENTS.md"
    user_file.parent.mkdir(parents=True)
    user_file.write_text("# Мои правила\n", encoding="utf-8")

    expose_native_instructions(repository, paths, home=home, agent_kit_enabled=False)
    disabled = user_file.read_text(encoding="utf-8")
    assert "глобально отключён" in disabled
    assert "agent-kit enable" in disabled
    assert "# Мои правила" in disabled

    expose_native_instructions(repository, paths, home=home, agent_kit_enabled=True)
    enabled = user_file.read_text(encoding="utf-8")
    assert "Используй canonical instructions" in enabled
    assert "Kit отключён" not in enabled
    assert enabled.count("agent-engineering-kit:start") == 1
