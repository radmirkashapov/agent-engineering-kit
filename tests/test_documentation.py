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
