"""Безопасный процесс ведения канонической документации и фрагментов изменений."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Any

from .errors import AgentKitError
from .io import atomic_write


_TASK_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$")


def _matches(path: str, pattern: str) -> bool:
    candidate = PurePosixPath(path)
    return candidate.match(pattern) or (pattern.endswith("/**") and path.startswith(pattern[:-3].rstrip("/") + "/"))


def owner_for_path(path: str, ownership: list[dict[str, Any]]) -> str | None:
    """Вернуть роль-владельца первого подходящего правила."""
    normalized = path.replace("\\", "/").lstrip("./")
    for rule in ownership:
        for pattern in rule.get("paths", []):
            if _matches(normalized, str(pattern)):
                return str(rule["owner_role"])
    return None


def validate_write_set(role: str, paths: list[str], ownership: list[dict[str, Any]]) -> None:
    """Отклонить изменение защищённого документа не владельцем."""
    for path in paths:
        owner = owner_for_path(path, ownership)
        if owner and owner != role:
            raise AgentKitError(f"Путь {path} принадлежит роли {owner}, а не {role}")


def create_change_fragment(repository: Path, task_id: str, content: str) -> Path:
    """Создать уникальный additive fragment без изменения горячих документов."""
    if not _TASK_ID.fullmatch(task_id):
        raise AgentKitError(f"Некорректный task ID: {task_id!r}")
    target = repository / "docs" / "changes" / f"{task_id}.md"
    if target.exists():
        raise AgentKitError(f"Change fragment уже существует: {target}")
    atomic_write(target, f"# Изменения задачи {task_id}\n\n{content.rstrip()}\n")
    return target


def _title(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem.replace("-", " ").title()


def render_docs_index(docs_root: Path, *, title: str = "Индекс документации") -> str:
    """Детерминированно сформировать индекс из самостоятельных Markdown-файлов."""
    rows: list[str] = []
    for path in sorted(docs_root.rglob("*.md"), key=lambda item: item.relative_to(docs_root).as_posix()):
        relative = path.relative_to(docs_root)
        if relative == Path("INDEX.md") or relative.parts[:1] == ("changes",):
            continue
        rows.append(f"- [{_title(path)}]({relative.as_posix()})")
    return f"# {title}\n\n" + ("\n".join(rows) if rows else "Документы пока не добавлены.") + "\n"
