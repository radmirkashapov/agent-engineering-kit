"""Неблокирующее обогащение задачи данными Jira."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlparse


class ToolClient(Protocol):
    def call(self, server_id: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class IssueContext:
    task_id: str
    summary: str | None
    branch_type: str | None
    enriched: bool


def _task_id(reference: str) -> str:
    parsed = urlparse(reference)
    value = parsed.path.rstrip("/").split("/")[-1] if parsed.scheme else reference
    return value.strip().upper()


def _branch_type(issue_type: str | None) -> str | None:
    normalized = (issue_type or "").strip().lower()
    if normalized in {"bug", "defect", "ошибка"}:
        return "fix"
    if normalized in {"story", "feature", "epic", "история", "функциональность"}:
        return "feat"
    if normalized in {"documentation", "docs", "документация"}:
        return "docs"
    if normalized in {"test", "testing", "тест"}:
        return "test"
    return None


def resolve_issue(
    reference: str,
    *,
    jira: dict[str, Any] | None,
    client: ToolClient,
) -> IssueContext:
    """Прочитать Jira issue или вернуть исходный ID без summary."""
    task_id = _task_id(reference)
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*-\d+|[A-Z0-9][A-Z0-9._-]*", task_id):
        return IssueContext(task_id, None, None, False)
    if not jira:
        return IssueContext(task_id, None, None, False)
    arguments: dict[str, Any] = {"issueIdOrKey": task_id}
    if jira.get("cloud_id"):
        arguments["cloudId"] = jira["cloud_id"]
    try:
        response = client.call("atlassian", "getJiraIssue", arguments)
    except Exception:
        return IssueContext(task_id, None, None, False)
    issue = response.get("issue", response)
    fields = issue.get("fields", {}) if isinstance(issue, dict) else {}
    summary = fields.get("summary") or issue.get("summary")
    issue_type = fields.get("issuetype") or issue.get("issueType")
    if isinstance(issue_type, dict):
        issue_type = issue_type.get("name")
    key = str(issue.get("key") or task_id)
    return IssueContext(key, str(summary) if summary else None, _branch_type(str(issue_type) if issue_type else None), True)
