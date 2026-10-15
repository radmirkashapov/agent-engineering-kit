"""Редактирование чувствительных значений перед записью локальной телеметрии."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlsplit, urlunsplit


REDACTED = "[REDACTED]"
_SENSITIVE_PARTS = (
    "authorization",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "password",
    "passwd",
    "secret",
    "token",
    "cookie",
    "credential",
)


def _sensitive_key(key: object) -> bool:
    normalized = str(key).lower().replace("-", "_")
    return any(part in normalized for part in _SENSITIVE_PARTS)


def _redact_url(value: str) -> str:
    """Удалить credentials из URL, не изменяя обычную строку."""
    try:
        parsed = urlsplit(value)
    except ValueError:
        return value
    if not parsed.scheme or not parsed.netloc or (parsed.username is None and parsed.password is None):
        return value
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, f"{REDACTED}@{host}", parsed.path, parsed.query, parsed.fragment))


def redact(value: Any, *, redact_result_fields: bool = False) -> Any:
    """Вернуть JSON-совместимую копию без literal secrets и сырых результатов."""
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            string_key = str(key)
            if _sensitive_key(key) or (redact_result_fields and string_key.lower() in {"result", "output", "content", "rows"}):
                redacted[string_key] = REDACTED
            else:
                redacted[string_key] = redact(item, redact_result_fields=redact_result_fields)
        return redacted
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [redact(item, redact_result_fields=redact_result_fields) for item in value]
    if isinstance(value, str):
        return _redact_url(value)
    return value
