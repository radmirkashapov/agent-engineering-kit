"""Платформенные пути без смешивания репозитория, среды выполнения и памяти проекта."""

from __future__ import annotations

import os
import platform
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class KitPaths:
    repository: Path
    data: Path
    runtime: Path
    projects: Path
    overrides: Path
    installations: Path | None = None
    state: Path | None = None
    locks: Path | None = None
    logs: Path | None = None
    secrets: Path | None = None

    def __post_init__(self) -> None:
        defaults = {
            "installations": self.data / "installations",
            "state": self.data / "state",
            "locks": self.data / "locks",
            "logs": self.data / "logs",
            "secrets": self.data / "secrets",
        }
        for name, value in defaults.items():
            if getattr(self, name) is None:
                object.__setattr__(self, name, value)


def _data_home(environ: dict[str, str]) -> Path:
    if value := environ.get("AGENT_KIT_DATA_HOME"):
        return Path(value).expanduser()
    if platform.system() == "Windows":
        base = environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "agent-engineering-kit"
    base = environ.get("XDG_DATA_HOME")
    return (Path(base).expanduser() if base else Path.home() / ".local" / "share") / "agent-engineering-kit"


def _source_repository() -> Path | None:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "AI.md").is_file() and (candidate / "app.version").is_file():
            return candidate
    return None


def _registered_repository(data: Path) -> Path | None:
    """Прочитать checkout, зарегистрированный bootstrap-установщиком."""
    pointer = data / "state" / "repository-path"
    if not pointer.is_file():
        return None
    # utf-8-sig также читает pointer от старого Windows PowerShell, который добавлял BOM.
    value = pointer.read_text(encoding="utf-8-sig").strip()
    return Path(value).expanduser().resolve() if value else None


def resolve_paths(environ: dict[str, str] | None = None) -> KitPaths:
    env = dict(os.environ if environ is None else environ)
    data = _data_home(env).resolve()
    repository = (
        Path(env["AGENT_KIT_REPOSITORY"]).expanduser().resolve()
        if env.get("AGENT_KIT_REPOSITORY")
        else (_source_repository() or _registered_repository(data) or data / "repository")
    )
    return KitPaths(
        repository=repository,
        data=data,
        runtime=data / "runtime",
        projects=data / "projects",
        overrides=data / "overrides",
        installations=data / "installations",
        state=data / "state",
        locks=data / "locks",
        logs=data / "logs",
    )


def ensure_runtime(paths: KitPaths) -> None:
    directories = (
        paths.runtime,
        paths.projects,
        paths.overrides / "global",
        paths.overrides / "projects",
        paths.installations / "skills",
        paths.installations / "mcp",
        paths.installations / "security",
        paths.installations / "clients",
        paths.state / "components",
        paths.state / "candidates",
        paths.locks,
        paths.logs,
    )
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)
    paths.secrets.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name == "posix":
        paths.secrets.chmod(0o700)
