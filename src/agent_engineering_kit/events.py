"""Append-only события выполнения с обязательным редактированием данных."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .errors import AgentKitError
from .redaction import redact


REQUIRED_FIELDS = frozenset({"event_id", "run_id", "recorded_at", "type", "payload"})


def append_event(path: Path, event: dict[str, Any], *, redact_tool_results: bool = False) -> None:
    """Добавить одно валидное событие одной атомарной записью."""
    missing = sorted(REQUIRED_FIELDS - set(event))
    if missing:
        raise AgentKitError(f"Run event не содержит обязательные поля: {', '.join(missing)}")
    document = redact(event, redact_result_fields=redact_tool_results)
    document["schema"] = "agent-engineering-kit/run-event/v1"
    serialized = (json.dumps(document, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(descriptor, serialized)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def read_events(path: Path) -> list[dict[str, Any]]:
    """Прочитать журнал и отклонить повреждённую строку."""
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise AgentKitError(f"Некорректное событие {path}:{number}: {error}") from error
        if not isinstance(value, dict):
            raise AgentKitError(f"Событие {path}:{number} должно быть объектом")
        events.append(value)
    return events
