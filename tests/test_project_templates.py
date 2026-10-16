from __future__ import annotations

from pathlib import Path

import pytest

from agent_engineering_kit.errors import AgentKitError
from agent_engineering_kit.paths import KitPaths
from agent_engineering_kit.project_templates import load_project_templates, resolve_project_template
from agent_engineering_kit.projects import init_project


def _paths(tmp_path: Path, repository: Path) -> KitPaths:
    data = tmp_path / "data"
    return KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")


def test_catalog_resolves_template_by_id_and_language_stack() -> None:
    repository = Path(__file__).resolve().parents[1]

    templates = load_project_templates(repository)

    by_id = resolve_project_template(templates, template_id="python-fastapi")
    by_stack = resolve_project_template(templates, language="python", stack="fastapi")
    assert by_id == by_stack
    assert by_id["files"]["src/app/main.py"].startswith('"""')


def test_unknown_template_is_rejected() -> None:
    repository = Path(__file__).resolve().parents[1]

    with pytest.raises(AgentKitError, match="Шаблон проекта не найден"):
        resolve_project_template(load_project_templates(repository), template_id="unknown")


def test_project_init_applies_template_and_initializes_git(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    root = tmp_path / "orders"

    project = init_project(
        root,
        repository,
        _paths(tmp_path, repository),
        template_id="python-fastapi",
        initialize_git=True,
        default_branch="develop",
    )

    assert project.identifier == "orders"
    assert (root / "src/app/main.py").is_file()
    assert (root / "tests/test_health.py").is_file()
    assert (root / ".env.example").is_file()
    assert (root / ".git").is_dir()
    head = (root / ".git/HEAD").read_text(encoding="utf-8").strip()
    assert head == "ref: refs/heads/develop"


def test_project_init_refuses_to_overwrite_template_conflict(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    root = tmp_path / "orders"
    target = root / "src/app/main.py"
    target.parent.mkdir(parents=True)
    target.write_text("user content\n", encoding="utf-8")

    with pytest.raises(AgentKitError, match="не перезаписывает"):
        init_project(
            root,
            repository,
            _paths(tmp_path, repository),
            template_id="python-fastapi",
        )

    assert target.read_text(encoding="utf-8") == "user content\n"
    assert not (root / ".ai-team/project.yaml").exists()
