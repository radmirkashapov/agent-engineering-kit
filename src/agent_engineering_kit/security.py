"""Неблокирующие и блокирующие security checks repository."""

from __future__ import annotations

import re
from pathlib import Path

from .io import markdown_frontmatter
from .result import ValidationResult
from .schema import validate_instance


SECRET_ASSIGNMENT = re.compile(r"(?i)(token|secret|password|api[_-]?key)\s*[:=]\s*['\"]?[A-Za-z0-9_./+=-]{16,}")
TEXT_SUFFIXES = {".md", ".yaml", ".yml", ".json", ".toml", ".sh", ".ps1", ".py"}


def validate_security(repository: Path) -> ValidationResult:
    result = ValidationResult()
    excluded = {".git", ".venv", "__pycache__", ".pytest_cache"}
    for path in repository.rglob("*"):
        if not path.is_file() or path.suffix not in TEXT_SUFFIXES or any(part in excluded for part in path.parts):
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
            if "env:" in line or "from_env" in line or "SECRET_ASSIGNMENT" in line:
                continue
            if SECRET_ASSIGNMENT.search(line):
                result.error("security", f"Возможный literal secret: {path.relative_to(repository)}:{number}")
    expected = {"skill-evaluator", "skillspector", "semgrep", "gitleaks", "bumblebee"}
    contracts = repository / "security" / "catalog"
    found: set[str] = set()
    for path in sorted(contracts.glob("*.md")):
        metadata = markdown_frontmatter(path)
        result.extend(validate_instance(metadata, repository / "schemas" / "security-tool.schema.json", str(path.relative_to(repository))))
        found.add(str(metadata.get("id")))
        body = path.read_text(encoding="utf-8")
        for heading in (
            "Назначение",
            "Почему используется",
            "Модель угроз",
            "Источник",
            "Поддерживаемые платформы",
            "Установка",
            "Проверка",
            "Обновление",
            "Откат",
            "Удаление",
            "Разрешения",
            "Доступ к сети",
            "Интеграция с agent-kit",
            "Ограничения",
        ):
            if f"# {heading}" not in body:
                result.error("security", f"{path.relative_to(repository)}: отсутствует раздел {heading}")
    if found != expected:
        result.error("security", f"Неполный набор security contracts: {sorted(expected - found)}")
    if result.ok:
        result.info("security", "Literal secrets не обнаружены")
    return result
