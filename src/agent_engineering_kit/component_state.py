"""Локальное состояние жизненного цикла внешних компонентов."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from .io import atomic_write
from .paths import KitPaths, ensure_runtime


class Lifecycle(str, Enum):
    NOT_INSTALLED = "NOT_INSTALLED"
    INSTALLED = "INSTALLED"
    VALIDATING = "VALIDATING"
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"
    OUTDATED = "OUTDATED"
    ERROR = "ERROR"
    NOT_SUPPORTED = "NOT_SUPPORTED"


def state_path(paths: KitPaths, kind: str, identifier: str) -> Path:
    return paths.state / "components" / kind / f"{identifier}.json"


def read_state(paths: KitPaths, kind: str, identifier: str) -> dict[str, Any]:
    path = state_path(paths, kind, identifier)
    if not path.is_file():
        return {"id": identifier, "kind": kind, "status": Lifecycle.NOT_INSTALLED.value}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"id": identifier, "kind": kind, "status": Lifecycle.ERROR.value, "reason": "state повреждён"}


def write_state(paths: KitPaths, kind: str, identifier: str, status: Lifecycle, **values: Any) -> dict[str, Any]:
    ensure_runtime(paths)
    document = {
        "id": identifier,
        "kind": kind,
        "status": status.value,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        **values,
    }
    atomic_write(state_path(paths, kind, identifier), json.dumps(document, ensure_ascii=False, indent=2) + "\n")
    return document
