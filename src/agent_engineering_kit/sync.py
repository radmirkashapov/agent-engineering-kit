"""Безопасное обновление рабочей копии Kit и фиксация ревизии сеанса."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .clients import sync_clients
from .errors import AgentKitError
from .io import atomic_write
from .paths import KitPaths, ensure_runtime


def _git(repository: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repository, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def revision(repository: Path) -> str:
    completed = _git(repository, "rev-parse", "HEAD")
    return completed.stdout.strip() if completed.returncode == 0 else "uncommitted"


def update_repository(repository: Path) -> None:
    """Обновить только чистый deployment checkout без merge/reset."""
    status = _git(repository, "status", "--porcelain")
    if status.returncode != 0:
        raise AgentKitError("Repository kit не является рабочим Git checkout")
    if status.stdout.strip():
        raise AgentKitError("Sync остановлен: в deployment checkout есть незакоммиченные изменения")
    remote = _git(repository, "remote", "get-url", "origin")
    if remote.returncode == 0:
        fetched = _git(repository, "fetch", "origin")
        if fetched.returncode != 0:
            raise AgentKitError(f"git fetch origin завершился ошибкой: {fetched.stderr.strip()}")
        pulled = _git(repository, "pull", "--ff-only")
        if pulled.returncode != 0:
            raise AgentKitError(f"git pull --ff-only завершился ошибкой: {pulled.stderr.strip()}")


def record_sync(repository: Path, paths: KitPaths) -> tuple[str, list[Path]]:
    """Materialize adapters и зафиксировать immutable revision текущей session."""
    ensure_runtime(paths)
    current_revision = revision(repository)
    generated = sync_clients(repository, paths)
    atomic_write(
        paths.runtime / "session-revision.json",
        json.dumps(
            {"revision": current_revision, "recorded_at": datetime.now(timezone.utc).isoformat(), "immutable_for_session": True},
            ensure_ascii=False,
            indent=2,
        ) + "\n",
    )
    return current_revision, generated


def sync_repository(repository: Path, paths: KitPaths, *, update: bool = True) -> tuple[str, list[Path]]:
    """Совместимый API для callers, которым не нужна промежуточная validation."""
    if update:
        update_repository(repository)
    return record_sync(repository, paths)
