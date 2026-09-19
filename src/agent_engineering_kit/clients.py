"""Thin adapters: generation идёт только в local runtime."""

from __future__ import annotations

from pathlib import Path

from .io import atomic_write, load_yaml
from .paths import KitPaths, ensure_runtime
from .result import ValidationResult


CLIENTS = ("codex", "claude-code", "claude-desktop", "opencode", "cline")


def validate_clients(repository: Path) -> ValidationResult:
    result = ValidationResult()
    for client in CLIENTS:
        directory = repository / "clients" / client
        adapter = directory / "adapter.yaml"
        readme = directory / "README.md"
        if not adapter.is_file() or not readme.is_file():
            result.error("clients", f"Неполный adapter {client}: нужны adapter.yaml и README.md")
            continue
        document = load_yaml(adapter)
        if document.get("id") != client:
            result.error("clients", f"clients/{client}/adapter.yaml: id должен совпадать с именем каталога")
        if document.get("entrypoint") != "AI.md":
            result.error("clients", f"Adapter {client} должен ссылаться на AI.md, а не копировать rules")
    if result.ok:
        result.info("clients", f"Thin adapters валидны: {len(CLIENTS)}")
    return result


def sync_clients(repository: Path, paths: KitPaths) -> list[Path]:
    ensure_runtime(paths)
    generated: list[Path] = []
    for client in CLIENTS:
        adapter = load_yaml(repository / "clients" / client / "adapter.yaml")
        target = paths.runtime / "clients" / client / "adapter.yaml"
        content = (
            "# Сгенерировано agent-kit; локальный runtime, не Git.\n"
            f"kit_repository: {repository}\n"
            f"entrypoint: {repository / adapter['entrypoint']}\n"
            f"skills: {repository / 'skills'}\n"
            f"mcp_registry: {repository / 'mcp' / 'registry.yaml'}\n"
        )
        atomic_write(target, content)
        generated.append(target)
    return generated
