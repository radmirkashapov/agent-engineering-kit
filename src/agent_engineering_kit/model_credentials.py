"""Machine-local credentials моделей без публикации значений в client config."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from .errors import AgentKitError
from .mcp_credentials import McpCredentialStore
from .managed_paths import managed_directory
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
        target = super().import_file(source, self._providers(providers))
        # OpenCode умеет читать ключ из отдельного файла, а Codex — получать его
        # через auth.command. Файлы значений нужны только OpenCode и остаются
        # внутри приватного runtime-каталога.
        values = self.load()
        try:
            with managed_directory(self.paths.data, self.value_directory, create=True, private=True) as directory:
                for name, value in values.items():
                    self._atomic_write(self.value_directory / name, value, directory)
        except OSError:
            raise AgentKitError("Не удалось подготовить защищённые файлы credentials моделей") from None
        return target

    def status(self, providers: Iterable[dict[str, Any]]) -> list[dict[str, object]]:
        return super().status(self._providers(providers))

    @property
    def value_directory(self) -> Path:
        return self.paths.secrets / "model-values"

    def value_file(self, name: str) -> Path | None:
        """Вернуть private файл ключа, не раскрывая его содержимое."""
        candidate = self.value_directory / name
        return candidate if candidate.is_file() else None

    def read_value(self, name: str, providers: Iterable[dict[str, Any]]) -> str:
        """Напечатать ключ только дочернему auth.command клиента."""
        allowed = {str(item["api_key_env"]) for item in providers if item.get("api_key_env")}
        if name not in allowed:
            raise AgentKitError("Неизвестная переменная credentials модели")
        value = self.load().get(name)
        if not value:
            raise AgentKitError(f"Credentials модели {name} не заданы")
        return value
