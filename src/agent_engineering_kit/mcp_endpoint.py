"""Разрешение endpoint MCP без публикации корпоративных URL в Git."""

from __future__ import annotations

import os
from typing import Any, Mapping


def resolved_endpoint(item: Mapping[str, Any], environ: Mapping[str, str] | None = None) -> str:
    """Вернуть локальный endpoint, предпочитая заданную в профиле переменную."""
    installation = item.get("installation", {})
    endpoint = str(installation.get("endpoint", "")) if isinstance(installation, Mapping) else ""
    name = item.get("endpoint_environment")
    values = os.environ if environ is None else environ
    return str(values.get(str(name)) or endpoint) if isinstance(name, str) else endpoint
