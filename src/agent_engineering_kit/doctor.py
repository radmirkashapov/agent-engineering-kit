"""Диагностика installation и runtime."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from .models import load_policy
from .io import load_yaml
from .paths import KitPaths, ensure_runtime
from .result import ValidationResult


def doctor(repository: Path, paths: KitPaths) -> ValidationResult:
    result = ValidationResult()
    if sys.version_info < (3, 10):
        result.error("doctor", "Нужен Python 3.10 или новее")
    else:
        result.info("doctor", f"Python: {sys.version.split()[0]}")
    for required in ("AI.md", "README.md", "app.version", "models/corporate.yaml", "mcp/registry.yaml"):
        if not (repository / required).is_file():
            result.error("doctor", f"Отсутствует {required}")
    if shutil.which("git") is None:
        result.error("doctor", "git не найден в PATH")
    try:
        ensure_runtime(paths)
        probe = paths.runtime / ".doctor-write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        result.info("doctor", f"Runtime доступен для записи: {paths.runtime}")
    except OSError as error:
        result.error("doctor", f"Runtime недоступен для записи: {error}")
    policy = load_policy(repository)
    result.info("doctor", f"Corporate models: {len(policy.corporate)}; user-local models: {len(policy.local)}")
    for server in load_yaml(repository / "mcp" / "registry.yaml").get("servers", []):
        if not server.get("enabled", True) or server.get("transport") != "stdio":
            continue
        available = shutil.which(server.get("command", "")) is not None
        message = f"MCP {server['id']}: {'доступен' if available else 'command не найден'}"
        if not available and server.get("required"):
            result.error("doctor", message)
        elif not available:
            result.warning("doctor", message)
        else:
            result.info("doctor", message)
    return result
