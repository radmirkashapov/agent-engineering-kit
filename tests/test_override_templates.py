from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil

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
