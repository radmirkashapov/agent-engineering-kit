"""Диагностика локальной установки и среды выполнения."""

from __future__ import annotations

import shutil
import sys
import json
from pathlib import Path

from .models import load_policy
from .mcp_manager import McpManager
from .paths import KitPaths, ensure_runtime
from .policy import effective_policy
from .result import ValidationResult
from .security_tools import SecurityToolManager


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
    policy = load_policy(repository, local_path=paths.overrides / "models.yaml")
    result.info("doctor", f"Corporate models: {len(policy.corporate)}; user-local models: {len(policy.local)}")
    access_profile = str(effective_policy(repository, paths, None).values["mcp.access_profile"])
    result.extend(McpManager(repository, paths).doctor(access_profile=access_profile))
    registrations = paths.state / "client-mcp-registrations.json"
    if registrations.is_file():
        try:
            rows = json.loads(registrations.read_text(encoding="utf-8")).get("registrations", [])
            for row in rows:
                status = row.get("status")
                label = f"{row.get('client')}/{row.get('mcp', 'adapter')}: {status}"
                if status == "ERROR":
                    result.error("client-mcp-doctor", label)
                elif status in {"AUTH_REQUIRED", "CONFIG_REQUIRED", "NOT_SUPPORTED"}:
                    result.warning("client-mcp-doctor", label)
        except (OSError, json.JSONDecodeError) as error:
            result.error("client-mcp-doctor", f"State client registrations повреждён: {error}")
    else:
        result.warning("client-mcp-doctor", "Client MCP registrations ещё не созданы; выполните agent-kit resync")
    result.extend(SecurityToolManager(repository, paths).doctor())
    return result
