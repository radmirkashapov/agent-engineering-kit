"""Загрузка недоверенного контекста PR/MR через read-only MCP tools."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

import yaml

from .errors import AgentKitError
from .io import atomic_write
from .paths import KitPaths
from .process import run_command
from .projects import LogicalProject


class ToolClient(Protocol):
    def call(self, server_id: str, tool: str, arguments: dict[str, Any]) -> Any: ...


@dataclass(frozen=True)
class ScmReference:
    provider: str
    host: str
    project: str
    number: int | None = None
    url: str | None = None


def parse_scm_reference(value: str) -> ScmReference:
    """Разобрать URL PR/MR без сетевого запроса."""
    parsed = urlparse(value)
    parts = [part for part in parsed.path.split("/") if part]
    if parsed.netloc == "github.com" and len(parts) >= 4 and parts[-2] == "pull":
        return ScmReference("github", parsed.netloc, "/".join(parts[:2]), int(parts[-1]), value)
    if "-" in parts and len(parts) >= 3 and parts[-2] == "merge_requests":
        marker = parts.index("-")
        return ScmReference("gitlab", parsed.netloc, "/".join(parts[:marker]), int(parts[-1]), value)
    raise AgentKitError(f"Не удалось распознать URL PR/MR: {value}")


def _remote_reference(remote: str) -> ScmReference:
    value = remote.strip()
    if value.startswith("git@") and ":" in value:
        host, path = value[4:].split(":", 1)
    else:
        parsed = urlparse(value)
        host = parsed.hostname or ""
        path = parsed.path.lstrip("/")
    path = path.removesuffix(".git")
    provider = "github" if host == "github.com" else "gitlab"
    if not host or "/" not in path:
        raise AgentKitError(f"Не удалось распознать Git remote: {remote}")
    return ScmReference(provider, host, path)


def _git(repository: Path, *arguments: str) -> str:
    result = run_command(["git", "-C", str(repository), *arguments])
    if not result.ok:
        raise AgentKitError(result.stderr.strip() or "Git command завершилась с ошибкой")
    return result.stdout.strip()


def _rows(value: Any, *keys: str) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        for key in keys:
            nested = value.get(key)
            if isinstance(nested, list):
                return [item for item in nested if isinstance(item, dict)]
    return []


_SENSITIVE_KEYS = {"token", "authorization", "password", "secret", "access_token", "refresh_token"}


def _sanitize(value: Any, warnings: list[str], *, path: str = "$") -> Any:
    """Удалить секреты и ограничить объём недоверенного ответа."""
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in _SENSITIVE_KEYS:
                result[str(key)] = "<redacted>"
                warnings.append(f"redacted:{path}.{key}")
            else:
                result[str(key)] = _sanitize(item, warnings, path=f"{path}.{key}")
        return result
    if isinstance(value, list):
        if len(value) > 200:
            warnings.append(f"truncated-list:{path}:{len(value)}")
        return [_sanitize(item, warnings, path=f"{path}[]") for item in value[:200]]
    if isinstance(value, str) and len(value) > 100_000:
        warnings.append(f"truncated-string:{path}:{len(value)}")
        return value[:100_000]
    return value


class PullRequestService:
    """Найти PR/MR и атомарно обновить его machine-local snapshot."""

    def __init__(self, repository: Path, paths: KitPaths, client: ToolClient) -> None:
        self.repository = repository
        self.paths = paths
        self.client = client

    def _context(self, repository_path: Path) -> tuple[ScmReference, str]:
        remote = _remote_reference(_git(repository_path, "remote", "get-url", "origin"))
        branch = _git(repository_path, "branch", "--show-current")
        if not branch:
            raise AgentKitError("Detached HEAD: укажите URL или номер PR/MR явно")
        return remote, branch

    def _choose(self, rows: list[dict[str, Any]], *, interactive: bool) -> dict[str, Any]:
        if not rows:
            raise AgentKitError("Для текущей ветки не найден открытый PR/MR")
        if len(rows) == 1:
            return rows[0]
        if not interactive:
            choices = ", ".join(str(item.get("iid") or item.get("number")) for item in rows)
            raise AgentKitError(f"Найдено несколько открытых PR/MR: {choices}; укажите URL или номер")
        print("Найдено несколько PR/MR:")
        for index, item in enumerate(rows, start=1):
            print(f"  {index}. #{item.get('iid') or item.get('number')} {item.get('title', '')}")
        raw = input("Выберите номер: ").strip()
        try:
            return rows[int(raw) - 1]
        except (ValueError, IndexError) as error:
            raise AgentKitError(f"Некорректный выбор PR/MR: {raw}") from error

    def _resolve(
        self,
        reference: str | None,
        *,
        repository_path: Path,
        interactive: bool,
    ) -> ScmReference:
        if reference and reference.startswith(("http://", "https://")):
            return parse_scm_reference(reference)
        remote, branch = self._context(repository_path)
        if reference:
            try:
                number = int(reference)
            except ValueError as error:
                raise AgentKitError(f"Ожидается URL либо номер PR/MR: {reference}") from error
            return ScmReference(remote.provider, remote.host, remote.project, number)
        if remote.provider == "gitlab":
            branch_rows: list[dict[str, Any]] = []
            after: str | None = None
            for _page in range(100):
                arguments: dict[str, Any] = {
                    "project_id": remote.project,
                    "state": "opened",
                    "first": 100,
                }
                if after:
                    arguments["after"] = after
                response = self.client.call("gitlab", "list_merge_requests", arguments)
                branch_rows.extend(
                    item
                    for item in _rows(response, "merge_requests", "items", "nodes")
                    if item.get("source_branch") == branch
                )
                page_info = response.get("pageInfo", {}) if isinstance(response, dict) else {}
                if not isinstance(page_info, dict) or not page_info.get("hasNextPage"):
                    break
                after = str(page_info.get("endCursor") or "")
                if not after:
                    raise AgentKitError("GitLab MCP сообщил следующую страницу без endCursor")
            else:
                raise AgentKitError("GitLab MCP вернул слишком много страниц открытых MR")
            selected = self._choose(branch_rows, interactive=interactive)
            return ScmReference("gitlab", remote.host, remote.project, int(selected["iid"]), selected.get("web_url"))
        owner, repository = remote.project.split("/", 1)
        response = self.client.call(
            "github",
            "list_pull_requests",
            {
                "owner": owner,
                "repo": repository,
                "state": "open",
                "head": f"{owner}:{branch}",
                "perPage": 100,
                "fields": ["number", "title", "html_url", "head"],
            },
        )
        selected = self._choose(_rows(response, "pull_requests", "items"), interactive=interactive)
        return ScmReference("github", remote.host, remote.project, int(selected["number"]), selected.get("html_url"))

    def _fetch(self, reference: ScmReference) -> dict[str, Any]:
        if reference.number is None:
            raise AgentKitError("Номер PR/MR не определён")
        if reference.provider == "gitlab":
            arguments = {"project_id": reference.project, "merge_request_iid": reference.number}
            base = self.client.call("gitlab", "get_merge_request", arguments)
            facets: dict[str, Any] = {}
            for facet in ("diffs", "commits", "notes", "pipelines", "discussions", "approvals"):
                facet_arguments = {**arguments, "include": [facet]}
                if facet == "diffs":
                    facet_arguments["detail"] = "full_patch"
                facets[facet] = self.client.call("gitlab", "get_merge_request", facet_arguments)
            return {"base": base, "facets": facets}
        owner, repository = reference.project.split("/", 1)
        common = {"owner": owner, "repo": repository, "pullNumber": reference.number}
        methods = ("get", "get_files", "get_commits", "get_review_comments", "get_reviews", "get_comments", "get_check_runs")
        return {
            "base": self.client.call("github", "pull_request_read", {**common, "method": "get"}),
            "facets": {
                method: self.client.call(
                    "github",
                    "pull_request_read",
                    {**common, "method": method, "perPage": 100},
                )
                for method in methods
                if method != "get"
            },
        }

    def refresh(
        self,
        reference: str | None,
        *,
        project: LogicalProject,
        repository_path: Path,
        interactive: bool | None = None,
    ) -> Path:
        resolved = self._resolve(
            reference,
            repository_path=repository_path,
            interactive=sys.stdin.isatty() if interactive is None else interactive,
        )
        raw = self._fetch(resolved)
        base = raw.get("base", {}) if isinstance(raw.get("base"), dict) else {}
        warnings: list[str] = []
        snapshot = {
            "schema": "agent-engineering-kit/scm-context/v1",
            "provider": resolved.provider,
            "host": resolved.host,
            "project": resolved.project,
            "number": resolved.number,
            "url": resolved.url or base.get("web_url") or base.get("html_url"),
            "source_revision": base.get("diff_head_sha") or base.get("head", {}).get("sha"),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "provenance": {"transport": "mcp", "server": resolved.provider},
            "data": _sanitize(raw, warnings),
            "warnings": warnings,
        }
        safe_project = re.sub(r"[^a-zA-Z0-9._-]+", "-", resolved.project).strip("-")
        directory = (
            self.paths.projects
            / project.identifier
            / "integrations"
            / "scm"
            / resolved.provider
            / safe_project
            / str(resolved.number)
        )
        target = directory / "snapshot.json"
        atomic_write(target, json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n")
        metadata = {
            "version": 1,
            "provider": resolved.provider,
            "project": resolved.project,
            "number": resolved.number,
            "snapshot": "snapshot.json",
        }
        atomic_write(
            directory / "metadata.yaml",
            "# Machine-local указатель на последний снимок PR/MR; файл не предназначен для Git.\n"
            + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False),
        )
        return target
