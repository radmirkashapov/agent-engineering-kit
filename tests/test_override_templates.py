from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import shutil

import pytest

import agent_engineering_kit.override_service as override_service
from agent_engineering_kit.errors import AgentKitError
from agent_engineering_kit.override_service import initialize_override_workspace
from agent_engineering_kit.overrides import validate_overrides
from agent_engineering_kit.paths import KitPaths


def _paths(repository: Path, tmp_path: Path) -> KitPaths:
    return KitPaths(
        repository,
        tmp_path / "data",
        tmp_path / "runtime",
        tmp_path / "projects",
        tmp_path / "overrides",
    )


def test_initializer_creates_neutral_policy_and_examples(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    paths = _paths(repository, tmp_path)

    created = initialize_override_workspace(repository, paths)

    assert paths.overrides / "global/access.yaml" in created
    assert (paths.overrides / "examples/greeting/SKILL.md").is_file()
    assert validate_overrides(repository, paths.overrides).ok


def test_initializer_never_overwrites_user_policy(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    paths = _paths(repository, tmp_path)
    target = paths.overrides / "global/access.yaml"
    target.parent.mkdir(parents=True)
    target.write_text("user-owned\n", encoding="utf-8")

    initialize_override_workspace(repository, paths)

    assert target.read_text(encoding="utf-8") == "user-owned\n"


def test_initializer_is_idempotent(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    paths = _paths(repository, tmp_path)

    initialize_override_workspace(repository, paths)

    assert initialize_override_workspace(repository, paths) == []


def test_initializer_ignores_python_bytecode_in_template_tree(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    template_repository = tmp_path / "repository"
    shutil.copytree(repository / "templates", template_repository / "templates")
    bytecode = template_repository / "templates/overrides/examples/greeting/scripts/__pycache__/greet.pyc"
    bytecode.parent.mkdir()
    bytecode.write_bytes(b"not a UTF-8 template")

    initialize_override_workspace(template_repository, _paths(template_repository, tmp_path))

    assert not (tmp_path / "overrides/examples/greeting/scripts/__pycache__/greet.pyc").exists()


def test_initializer_skips_symlinked_template_file(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    template_repository = tmp_path / "repository"
    shutil.copytree(repository / "templates", template_repository / "templates")
    outside = tmp_path / "outside.yaml"
    outside.write_text("outside\n", encoding="utf-8")
    source_link = template_repository / "templates/overrides/global/outside.yaml"
    try:
        source_link.symlink_to(outside)
    except OSError:
        pytest.skip("Создание symlink недоступно в текущей среде")

    initialize_override_workspace(template_repository, _paths(template_repository, tmp_path))

    assert not (tmp_path / "overrides/global/outside.yaml").exists()


def test_initializer_rejects_symlinked_destination_parent(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    paths = _paths(repository, tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    linked_parent = paths.overrides / "global"
    linked_parent.parent.mkdir(parents=True)
    try:
        linked_parent.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Создание symlink недоступно в текущей среде")

    with pytest.raises(AgentKitError):
        initialize_override_workspace(repository, paths)

    assert not (outside / "README.md").exists()
    assert not (outside / "access.yaml").exists()


def test_initializer_preserves_file_created_during_copy(monkeypatch, tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    paths = _paths(repository, tmp_path)
    target = paths.overrides / "README.md"
    original_open = os.open
    original_atomic_write = override_service.atomic_write

    def write_user_file() -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor = original_open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write("user-owned\n")

    def create_user_file(path: str | bytes | os.PathLike[str] | os.PathLike[bytes], flags: int, mode: int = 0o777) -> int:
        if Path(path) == target and not target.exists():
            write_user_file()
        return original_open(path, flags, mode)

    def create_collision_before_legacy_replace(path: Path, content: str) -> None:
        if path == target and not target.exists():
            write_user_file()
        original_atomic_write(path, content)

    monkeypatch.setattr(override_service.os, "open", create_user_file)
    monkeypatch.setattr(override_service, "atomic_write", create_collision_before_legacy_replace)

    created = initialize_override_workspace(repository, paths)

    assert target.read_text(encoding="utf-8") == "user-owned\n"
    assert target not in created


def test_greeting_example_prints_current_user(monkeypatch, capsys, tmp_path: Path) -> None:
    script = Path(__file__).resolve().parents[1] / "templates/overrides/examples/greeting/scripts/greet.py"
    copied_script = tmp_path / "greet.py"
    shutil.copy2(script, copied_script)
    specification = importlib.util.spec_from_file_location("greeting_example", copied_script)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    monkeypatch.setattr(module.getpass, "getuser", lambda: "developer")

    module.main()

    assert capsys.readouterr().out == "Привет, developer!\n"
