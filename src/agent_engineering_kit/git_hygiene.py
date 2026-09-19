"""Защита Git от local-only файлов и очевидных secrets."""

from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path

from .result import ValidationResult


LOCAL_ONLY_PATTERNS = (
    "models/user.local.yaml",
    "models/*.local.yaml",
    "overrides/*.local.*",
    "overrides/local/**",
    ".local/**",
    ".runtime/**",
    "clients/**/generated/**",
)
SECRET_PATTERNS = (".env", ".env.*", "secrets/**", "*.token", "*.secret", "*.pem", "*.key")


def _git(repository: Path, *arguments: str) -> tuple[int, list[str]]:
    completed = subprocess.run(
        ["git", *arguments], cwd=repository, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False
    )
    return completed.returncode, [line for line in completed.stdout.splitlines() if line]


def _matches(path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def validate_git_hygiene(repository: Path) -> ValidationResult:
    result = ValidationResult()
    returncode, tracked = _git(repository, "ls-files")
    if returncode != 0:
        result.error("git-hygiene", "Не удалось выполнить git ls-files")
        return result
    _, staged = _git(repository, "diff", "--cached", "--name-only", "--diff-filter=ACMR")
    candidates = sorted(set(tracked + staged))
    for path in candidates:
        if _matches(path, LOCAL_ONLY_PATTERNS):
            result.error("git-hygiene", f"Local-only файл tracked/staged: {path}")
        if _matches(path, SECRET_PATTERNS) and path != ".env.example":
            result.error("git-hygiene", f"Потенциальный secret tracked/staged: {path}")

    checks = ("models/user.local.yaml", "overrides/local/probe.yaml", ".runtime/probe", "clients/codex/generated/probe")
    for path in checks:
        code, _ = _git(repository, "check-ignore", "-q", path)
        if code != 0:
            result.error("git-hygiene", f"Defensive ignore не покрывает: {path}")
    if result.ok:
        result.info("git-hygiene", "Tracked/staged файлы и defensive .gitignore безопасны")
    return result
