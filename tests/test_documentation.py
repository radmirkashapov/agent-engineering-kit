from __future__ import annotations

from pathlib import Path

import pytest

from agent_engineering_kit.documentation import create_change_fragment, owner_for_path, render_docs_index, validate_write_set
from agent_engineering_kit.errors import AgentKitError


OWNERSHIP = [
    {"paths": ["docs/adr/**"], "owner_role": "architect"},
    {"paths": ["README.md", "docs/INDEX.md"], "owner_role": "documentation-integrator"},
]


def test_documentation_ownership_blocks_wrong_role() -> None:
    assert owner_for_path("docs/adr/20261012-task-demo.md", OWNERSHIP) == "architect"
    with pytest.raises(AgentKitError, match="documentation-integrator"):
        validate_write_set("developer", ["README.md"], OWNERSHIP)


def test_change_fragments_are_unique_and_path_safe(tmp_path: Path) -> None:
    first = create_change_fragment(tmp_path, "task-01", "Добавлена проверка.\n")
    assert first == tmp_path / "docs" / "changes" / "task-01.md"
    with pytest.raises(AgentKitError, match="уже существует"):
        create_change_fragment(tmp_path, "task-01", "Повтор.\n")
    with pytest.raises(AgentKitError, match="task ID"):
        create_change_fragment(tmp_path, "../escape", "Нет.\n")


def test_docs_index_is_deterministic(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    (docs / "adr").mkdir(parents=True)
    (docs / "guide.md").write_text("# Руководство\n", encoding="utf-8")
    (docs / "adr" / "20261012-task-decision.md").write_text("# ADR: Решение\n", encoding="utf-8")

    rendered = render_docs_index(docs, title="Документация Demo")

    assert rendered.startswith("# Документация Demo\n")
    assert rendered.index("ADR: Решение") < rendered.index("Руководство")
    assert "INDEX.md" not in rendered


def test_readme_documents_project_skills_workflow() -> None:
    repository = Path(__file__).resolve().parents[1]
    readme = (repository / "README.md").read_text(encoding="utf-8")
    required_commands = (
        "agent-kit project skills use-branch",
        "agent-kit project skills use-main",
        "agent-kit project skills status",
        "agent-kit resync",
    )
    required_states = ("ACTIVE", "STALE", "UPDATE_REJECTED", "NOT_CONFIGURED")

    assert all(command in readme for command in required_commands)
    assert all(state in readme for state in required_states)
    assert "skills/<id>/SKILL.md" in readme


def test_release_version_is_synchronized() -> None:
    repository = Path(__file__).resolve().parents[1]
    package = (repository / "src/agent_engineering_kit/__init__.py").read_text(encoding="utf-8")

    assert (repository / "app.version").read_text(encoding="utf-8").strip() == "0.12.0"
    assert '__version__ = "0.12.0"' in package
