"""Неизменяемый журнал событий с обязательным сокрытием чувствительных данных."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .errors import AgentKitError
from .redaction import redact


REQUIRED_FIELDS = frozenset({"event_id", "run_id", "recorded_at", "type", "payload"})
_SCHEMA = "agent-engineering-kit/run-event/v1"


def _validate_event(event: dict[str, Any], *, require_schema: bool) -> None:
    missing = sorted(REQUIRED_FIELDS - set(event))
    if missing:
        raise AgentKitError(f"Run event не содержит обязательные поля: {', '.join(missing)}")
    if require_schema and event.get("schema") != _SCHEMA:
        raise AgentKitError(f"Run event содержит неизвестную schema: {event.get('schema')!r}")
    for field in ("event_id", "run_id", "recorded_at", "type"):
        if not isinstance(event.get(field), str) or not event[field]:
            raise AgentKitError(f"Run event: поле {field} должно быть непустой строкой")
    if not isinstance(event.get("payload"), dict):
        raise AgentKitError("Run event: поле payload должно быть объектом")


def append_event(path: Path, event: dict[str, Any], *, redact_tool_results: bool = False) -> None:
    """Добавить одно валидное событие одной атомарной записью."""
    _validate_event(event, require_schema=False)
    document = redact(event, redact_result_fields=redact_tool_results)
    document["schema"] = _SCHEMA
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
        _validate_event(value, require_schema=True)
        events.append(value)
    return events
