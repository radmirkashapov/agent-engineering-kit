from __future__ import annotations

from pathlib import Path

import agent_engineering_kit.paths as paths_module
from agent_engineering_kit.paths import resolve_paths


def test_explicit_data_and_repository_paths_are_separated(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    data = tmp_path / "data"
    paths = resolve_paths({"AGENT_KIT_REPOSITORY": str(repository), "AGENT_KIT_DATA_HOME": str(data)})
    assert paths.repository == repository
    assert paths.runtime == data / "runtime"
    assert paths.projects == data / "projects"
    assert paths.repository != paths.runtime != paths.projects


def test_registered_checkout_is_used_after_package_install(
    tmp_path: Path,
    monkeypatch,
) -> None:
    data = tmp_path / "data"
    repository = tmp_path / "corporate-checkout"
    repository.mkdir()
    pointer = data / "state" / "repository-path"
    pointer.parent.mkdir(parents=True)
    pointer.write_text(f"{repository}\n", encoding="utf-8")
    monkeypatch.setattr(paths_module, "_source_repository", lambda: None)

    paths = resolve_paths({"AGENT_KIT_DATA_HOME": str(data)})

    assert paths.repository == repository


def test_registered_checkout_accepts_windows_utf8_bom(tmp_path: Path, monkeypatch) -> None:
    data = tmp_path / "data"
    repository = tmp_path / "corporate-checkout"
    repository.mkdir()
    pointer = data / "state" / "repository-path"
    pointer.parent.mkdir(parents=True)
    pointer.write_text(f"{repository}\n", encoding="utf-8-sig")
    monkeypatch.setattr(paths_module, "_source_repository", lambda: None)

    assert resolve_paths({"AGENT_KIT_DATA_HOME": str(data)}).repository == repository
