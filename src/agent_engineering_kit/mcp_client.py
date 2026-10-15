"""Узкий MCP-клиент для детерминированного чтения интеграционного контекста."""

from __future__ import annotations

import asyncio
import json
import os
import webbrowser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from pydantic import AnyUrl

from mcp import ClientSession, StdioServerParameters
from mcp.client.auth import OAuthClientProvider
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

from .errors import AgentKitError
from .io import atomic_write, load_yaml
from .mcp_manager import McpManager
from .paths import KitPaths
from .projects import LogicalProject


class FileTokenStorage:
    """Хранить OAuth-сессию вне Git с правами только для владельца."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _read(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, document: dict[str, Any]) -> None:
        atomic_write(self.path, json.dumps(document, ensure_ascii=False, indent=2) + "\n")
        os.chmod(self.path, 0o600)

    async def get_tokens(self) -> OAuthToken | None:
        value = self._read().get("tokens")
        return OAuthToken.model_validate(value) if value else None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        document = self._read()
        document["tokens"] = tokens.model_dump(mode="json", exclude_none=True)
        self._write(document)

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        value = self._read().get("client_info")
        return OAuthClientInformationFull.model_validate(value) if value else None

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        document = self._read()
        document["client_info"] = client_info.model_dump(mode="json", exclude_none=True)
        self._write(document)


class McpToolClient:
    """Вызывать только явно выбранный MCP tool без участия модели."""

    def __init__(self, repository: Path, paths: KitPaths, *, project: LogicalProject | None = None) -> None:
        self.repository = repository
        self.paths = paths
        self.project = project

    def connection_plan(self, server_id: str) -> dict[str, Any]:
        effective = next(
            (item for item in McpManager(self.repository, self.paths).available(self.project) if item["id"] == server_id),
            None,
        )
        if effective is None:
            raise AgentKitError(f"MCP server не найден: {server_id}")
        if effective.get("access_reason", "").startswith(("blocked:", "disabled:")):
            raise AgentKitError(f"MCP {server_id} явно отключён локальным override")
        registry = load_yaml(self.repository / "mcp" / "registry.yaml")
        server = next((item for item in registry.get("servers", []) if item.get("id") == server_id), None)
        if server is None:
            raise AgentKitError(f"MCP server не найден: {server_id}")
        if server.get("transport") == "stdio":
            arguments = [str(item) for item in server.get("args", [])]
            environment = {
                key: os.environ.get(str(reference).removeprefix("env:"), "")
                for key, reference in dict(server.get("environment", {})).items()
            }
            if server_id == "github":
                environment.update(
                    {
                        "GITHUB_READ_ONLY": "1",
                        "GITHUB_LOCKDOWN_MODE": "1",
                        "GITHUB_TOOLSETS": "pull_requests",
                    }
                )
                image = arguments.pop()
                arguments.extend(
                    [
                        "-e",
                        "GITHUB_READ_ONLY=1",
                        "-e",
                        "GITHUB_LOCKDOWN_MODE=1",
                        "-e",
                        "GITHUB_TOOLSETS=pull_requests",
                        image,
                    ]
                )
            return {
                "id": server_id,
                "transport": "stdio",
                "command": str(server["command"]),
                "args": arguments,
                "environment": environment,
            }
        installation = dict(server.get("installation", {}))
        endpoint = str(installation.get("endpoint", ""))
        if server_id == "gitlab":
            endpoint = os.environ.get("GITLAB_MCP_URL", endpoint)
        headers: dict[str, str] = {}
        if server_id == "gitlab":
            headers["X-Gitlab-Enabled-Mcp-Server-Toolsets"] = "merge_requests"
        return {
            "id": server_id,
            "transport": "http",
            "endpoint": endpoint,
            "authentication": installation.get("authentication"),
            "headers": headers,
            "oauth_storage": str(self.paths.data / "auth" / "mcp" / f"{server_id}.json"),
        }

    async def _oauth_redirect(self, url: str) -> None:
        print(f"Откройте OAuth URL и подтвердите доступ:\n{url}")
        webbrowser.open(url)

    async def _oauth_callback(self) -> tuple[str, str | None]:
        callback = await asyncio.to_thread(input, "Вставьте полный callback URL: ")
        values = parse_qs(urlparse(callback).query)
        if not values.get("code"):
            raise AgentKitError("OAuth callback не содержит code")
        return values["code"][0], values.get("state", [None])[0]

    async def _call_async(self, server_id: str, tool: str, arguments: dict[str, Any]) -> Any:
        plan = self.connection_plan(server_id)
        if plan["transport"] == "stdio":
            environment = {**os.environ, **plan["environment"]}
            missing = [key for key, value in plan["environment"].items() if key.endswith("TOKEN") and not value]
            if missing:
                raise AgentKitError(f"Не заданы переменные окружения: {', '.join(missing)}")
            parameters = StdioServerParameters(
                command=plan["command"],
                args=plan["args"],
                env=environment,
            )
            async with stdio_client(parameters) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(tool, arguments)
        else:
            scope = "mcp" if server_id == "gitlab" else "read:jira:agent-interface"
            auth = OAuthClientProvider(
                server_url=plan["endpoint"],
                client_metadata=OAuthClientMetadata(
                    client_name="Agent Engineering Kit",
                    redirect_uris=[AnyUrl("http://localhost:8765/callback")],
                    scope=scope,
                ),
                storage=FileTokenStorage(Path(plan["oauth_storage"])),
                redirect_handler=self._oauth_redirect,
                callback_handler=self._oauth_callback,
            )
            async with streamablehttp_client(
                plan["endpoint"],
                headers=plan["headers"],
                auth=auth,
            ) as (read, write, _session_id):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(tool, arguments)
        if result.isError:
            messages = [str(getattr(item, "text", "MCP tool error")) for item in result.content]
            raise AgentKitError("; ".join(messages))
        if result.structuredContent is not None:
            return result.structuredContent
        for item in result.content:
            text = getattr(item, "text", None)
            if isinstance(text, str):
                try:
                    value = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, (dict, list)):
                    return value
        raise AgentKitError(f"MCP tool {server_id}/{tool} не вернул структурированные данные")

    def call(self, server_id: str, tool: str, arguments: dict[str, Any]) -> Any:
        """Синхронно вызвать MCP tool из CLI."""
        return asyncio.run(self._call_async(server_id, tool, arguments))
