from __future__ import annotations

from pathlib import Path

from agent_engineering_kit.clients import CLIENTS, sync_clients, validate_clients
from agent_engineering_kit.paths import KitPaths


def test_client_adapters_validate() -> None:
    repository = Path(__file__).resolve().parents[1]
    assert validate_clients(repository).ok


def test_sync_generates_thin_runtime_adapters(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    generated = sync_clients(repository, paths)
    assert len(generated) == len(CLIENTS)
    content = (data / "runtime/clients/codex/adapter.yaml").read_text(encoding="utf-8")
    expected = (
        "# Сгенерировано agent-kit; локальный runtime, не Git.\n"
        f"kit_repository: {repository}\n"
        f"entrypoint: {repository / 'AI.md'}\n"
        f"skills: {repository / 'skills'}\n"
        f"mcp_registry: {repository / 'mcp' / 'registry.yaml'}\n"
    )
    assert content == expected
    assert str(tmp_path) not in "\n".join(path.read_text(encoding="utf-8") for path in repository.glob("clients/*/adapter.yaml"))
