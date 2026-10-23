"""Строгий разбор и machine-local хранилище credentials для MCP."""

from __future__ import annotations

import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .errors import AgentKitError
from .paths import KitPaths


@dataclass(frozen=True)
class CredentialRequirement:
    name: str
    required_by: tuple[str, ...]
    optional_for: tuple[str, ...]


def credential_requirements(servers: Iterable[dict[str, Any]]) -> dict[str, CredentialRequirement]:
    owners: dict[str, dict[str, set[str]]] = {}
    for server in servers:
        identifier = str(server["id"])
        required = {str(name) for name in server.get("required_environment", [])}
        referenced = {
            str(value)[4:]
            for value in server.get("environment", {}).values()
            if str(value).startswith("env:")
        } | required
        for name in referenced:
            bucket = owners.setdefault(name, {"required": set(), "optional": set()})
            bucket["required" if name in required else "optional"].add(identifier)
    return {
        name: CredentialRequirement(
            name=name,
            required_by=tuple(sorted(bucket["required"])),
            optional_for=tuple(sorted(bucket["optional"])),
        )
        for name, bucket in sorted(owners.items())
    }


def parse_credentials(text: str, *, allowed: set[str] | None) -> dict[str, str]:
    values: dict[str, str] = {}
    for number, line in enumerate(text.split("\n"), start=1):
        line = line.removesuffix("\r")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        name, separator, value = line.partition("=")
        if not separator or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) is None:
            raise AgentKitError(f"Строка {number}: некорректное присваивание credentials")
        if name in values:
            raise AgentKitError(f"Строка {number}: повторная переменная {name}")
        if allowed is not None and name not in allowed:
            raise AgentKitError(f"Строка {number}: неизвестная переменная {name}")
        if any(marker in value for marker in ("`", "$(", "${", "\x00", "\r")):
            raise AgentKitError(f"Строка {number}: небезопасный синтаксис переменной {name}")
        values[name] = value
    return values


class McpCredentialStore:
    def __init__(self, paths: KitPaths):
        self.paths = paths

    @property
    def vault_path(self) -> Path:
        return self.paths.secrets / "mcp-creds.env"

    @property
    def metadata_path(self) -> Path:
        return self.paths.state / "mcp-credentials.json"

    def import_file(self, source: Path, servers: Iterable[dict[str, Any]]) -> Path:
        requirements = credential_requirements(servers)
        try:
            text = source.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            raise AgentKitError("Не удалось прочитать файл credentials MCP") from None
        values = parse_credentials(text, allowed=set(requirements))
        self._write_private(values)
        self._write_metadata(names=sorted(name for name, value in values.items() if value))
        return self.vault_path

    def load(self) -> dict[str, str]:
        try:
            if not self.vault_path.is_file():
                return {}
            self._validate_permissions()
            text = self.vault_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            raise AgentKitError("Не удалось прочитать хранилище credentials MCP") from None
        return parse_credentials(text, allowed=None)

    def status(self, servers: Iterable[dict[str, Any]]) -> list[dict[str, object]]:
        requirements = credential_requirements(servers)
        values = self.load()
        return [
            {
                "name": name,
                "status": "SET" if values.get(name) else ("MISSING" if requirement.required_by else "OPTIONAL"),
                "required_by": list(requirement.required_by),
                "optional_for": list(requirement.optional_for),
            }
            for name, requirement in requirements.items()
        ]

    def clear(self) -> bool:
        try:
            existed = self.vault_path.exists() or self.metadata_path.exists()
            self.vault_path.unlink(missing_ok=True)
            self.metadata_path.unlink(missing_ok=True)
        except OSError:
            raise AgentKitError("Не удалось удалить хранилище credentials MCP") from None
        return existed

    def _write_private(self, values: dict[str, str]) -> None:
        try:
            self.paths.secrets.mkdir(mode=0o700, parents=True, exist_ok=True)
            if os.name == "posix":
                self.paths.secrets.chmod(0o700)
            self._atomic_write(self.vault_path, "".join(f"{name}={value}\n" for name, value in sorted(values.items())))
        except (OSError, UnicodeError):
            raise AgentKitError("Не удалось сохранить хранилище credentials MCP") from None

    def _write_metadata(self, *, names: list[str]) -> None:
        metadata = {
            "version": 1,
            "imported_at": datetime.now(timezone.utc).isoformat(),
            "names": names,
        }
        try:
            self.metadata_path.parent.mkdir(parents=True, exist_ok=True)
            self._atomic_write(self.metadata_path, json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
        except (OSError, UnicodeError):
            raise AgentKitError("Не удалось сохранить метаданные credentials MCP") from None

    def _validate_permissions(self) -> None:
        if os.name == "posix" and stat.S_IMODE(self.vault_path.stat().st_mode) & 0o077:
            raise AgentKitError("Небезопасные права хранилища credentials MCP: требуется 0600")

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                if os.name == "posix":
                    os.fchmod(stream.fileno(), 0o600)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
