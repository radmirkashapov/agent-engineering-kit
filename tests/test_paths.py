from __future__ import annotations

from pathlib import Path

from agent_engineering_kit.paths import resolve_paths


def test_explicit_data_and_repository_paths_are_separated(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    data = tmp_path / "data"
    paths = resolve_paths({"AGENT_KIT_REPOSITORY": str(repository), "AGENT_KIT_DATA_HOME": str(data)})
    assert paths.repository == repository
    assert paths.runtime == data / "runtime"
    assert paths.projects == data / "projects"
    assert paths.repository != paths.runtime != paths.projects
