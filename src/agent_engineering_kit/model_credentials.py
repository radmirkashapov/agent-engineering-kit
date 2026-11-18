"""Machine-local credentials моделей без публикации значений в client config."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from .mcp_credentials import McpCredentialStore
from .paths import KitPaths


class ModelCredentialStore(McpCredentialStore):
    """Использовать проверенный private vault MCP с отдельными именами файлов."""

    def __init__(self, paths: KitPaths):
        super().__init__(paths)

    @property
    def vault_path(self) -> Path:
        return self.paths.secrets / "model-creds.env"

    @property
    def metadata_path(self) -> Path:
        return self.paths.state / "model-credentials.json"

    @staticmethod
    def _providers(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {"id": item["id"], "environment": {str(item["api_key_env"]): f"env:{item['api_key_env']}"}}
            for item in items if isinstance(item.get("api_key_env"), str)
        ]

    def import_file(self, source: Path, providers: Iterable[dict[str, Any]]) -> Path:
        return super().import_file(source, self._providers(providers))

    def status(self, providers: Iterable[dict[str, Any]]) -> list[dict[str, object]]:
        return super().status(self._providers(providers))
