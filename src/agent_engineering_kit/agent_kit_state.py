"""Machine-local состояние глобального переключателя Agent Engineering Kit."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .errors import AgentKitError
from .io import atomic_write
from .paths import KitPaths


@dataclass(frozen=True)
class AgentKitStatus:
    enabled: bool
    updated_at: str | None = None
    source: str = "default"

    def as_dict(self) -> dict[str, object]:
        return {
            "version": 1,
            "enabled": self.enabled,
            "updated_at": self.updated_at,
            "source": self.source,
        }


def status_path(paths: KitPaths) -> Path:
    return paths.state / "agent-kit-status.json"


def read_status(paths: KitPaths) -> AgentKitStatus:
    path = status_path(paths)
    if not path.is_file():
        return AgentKitStatus(enabled=True)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AgentKitError(f"Некорректное состояние Agent Kit {path}: {error}; выполните `agent-kit enable --reset`") from error
    if not isinstance(document, dict) or not isinstance(document.get("enabled"), bool):
        raise AgentKitError(f"Некорректное состояние Agent Kit {path}: поле enabled должно быть boolean; выполните `agent-kit enable --reset`")
    updated_at = document.get("updated_at")
    source = document.get("source", "machine-local")
    if updated_at is not None and not isinstance(updated_at, str):
        raise AgentKitError(f"Некорректное состояние Agent Kit {path}: updated_at должен быть строкой")
    if not isinstance(source, str):
        raise AgentKitError(f"Некорректное состояние Agent Kit {path}: source должен быть строкой")
    return AgentKitStatus(enabled=document["enabled"], updated_at=updated_at, source=source)


def set_enabled(paths: KitPaths, enabled: bool, *, source: str = "cli") -> AgentKitStatus:
    result = AgentKitStatus(
        enabled=enabled,
        updated_at=datetime.now(timezone.utc).isoformat(),
        source=source,
    )
    atomic_write(status_path(paths), json.dumps(result.as_dict(), ensure_ascii=False, indent=2) + "\n")
    return result


def reset(paths: KitPaths) -> None:
    path = status_path(paths)
    if path.is_file():
        path.unlink()
