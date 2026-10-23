"""Защита Git от локальных файлов и явных секретов."""

from __future__ import annotations

import fnmatch
import re
import subprocess
from pathlib import Path

from .result import ValidationResult
from .paths import KitPaths


LOCAL_ONLY_PATTERNS = (
    "models/user.local.yaml",
    "models/*.local.yaml",
    "overrides/*.local.*",
    "overrides/local/**",
    "overrides/**",
    ".local/**",
    ".runtime/**",
    "clients/**/generated/**",
    "installations/**",
    "state/**",
    "projects/**",
)
SECRET_PATTERNS = (".env", ".env.*", "secrets/**", "*.token", "*.secret", "*.pem", "*.key")
MCP_CREDENTIAL_PATTERNS = ("mcp-creds.env", "mcp-creds.*.env")
STAGED_SECRET = re.compile(r"(?i)^\+.*(token|secret|password|api[_-]?key)\s*[:=]\s*['\"]?[A-Za-z0-9_./+=-]{16,}")


def _git(repository: Path, *arguments: str) -> tuple[int, list[str]]:
    completed = subprocess.run(
        ["git", *arguments], cwd=repository, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False
    )
    return completed.returncode, [line for line in completed.stdout.splitlines() if line]


def _matches(path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def validate_git_hygiene(repository: Path, paths: KitPaths | None = None, *, require_gitleaks: bool = False) -> ValidationResult:
    result = ValidationResult()
    returncode, tracked = _git(repository, "ls-files")
    if returncode != 0:
        result.error("git-hygiene", "Не удалось выполнить git ls-files")
        return result
    _, staged = _git(repository, "diff", "--cached", "--name-only", "--diff-filter=ACMR")
    staged_patch = subprocess.run(["git", "diff", "--cached", "--no-ext-diff", "--unified=0"], cwd=repository, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False).stdout
    if any(STAGED_SECRET.search(line) for line in staged_patch.splitlines()):
        result.error("git-hygiene", "В staged patch обнаружен возможный literal secret")
    candidates = sorted(set(tracked + staged))
    forbidden_external_roots = ("vendor/", "upstream/superpowers/", "skills/external/")
    for path in candidates:
        if _matches(path, LOCAL_ONLY_PATTERNS):
            result.error("git-hygiene", f"Local-only файл tracked/staged: {path}")
        if _matches(path, MCP_CREDENTIAL_PATTERNS) and path != "mcp-creds.example.env":
            result.error("git-hygiene", f"Потенциальный secret tracked/staged: {path}")
        if _matches(path, SECRET_PATTERNS) and path != ".env.example":
            result.error("git-hygiene", f"Потенциальный secret tracked/staged: {path}")
        if path.startswith(forbidden_external_roots):
            result.error("git-hygiene", f"Запрещён vendored external source: {path}")

    checks = (
        "models/user.local.yaml",
        "overrides/local/probe.yaml",
        ".runtime/probe",
        "clients/codex/generated/probe",
        "mcp-creds.env",
        "mcp-creds.work.env",
    )
    for path in checks:
        code, _ = _git(repository, "check-ignore", "-q", path)
        if code != 0:
            result.error("git-hygiene", f"Defensive ignore не покрывает: {path}")
    gitleaks = paths.installations / "security" / "gitleaks" / "bin" / "gitleaks" if paths else None
    if gitleaks and gitleaks.is_file():
        scan = subprocess.run([str(gitleaks), "git", str(repository), "--redact", "--no-banner"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        if scan.returncode != 0:
            result.error("git-hygiene", "Managed Gitleaks обнаружил secret в Git history/current revision")
        staged_scan = subprocess.run([str(gitleaks), "stdin", "--redact", "--no-banner"], input=staged_patch, text=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        if staged_scan.returncode != 0:
            result.error("git-hygiene", "Managed Gitleaks обнаружил secret в staged patch")
    elif paths:
        message = "Managed Gitleaks не установлен; выполнены filename и staged regex checks"
        (result.error if require_gitleaks else result.warning)("git-hygiene", message)
    if result.ok:
        result.info("git-hygiene", "Tracked/staged файлы и defensive .gitignore безопасны")
    return result
