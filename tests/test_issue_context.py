from __future__ import annotations

from agent_engineering_kit.issue_context import IssueContext, resolve_issue


class FakeMcpClient:
    def call(self, server_id: str, tool: str, arguments: dict) -> dict:
        assert server_id == "atlassian"
        assert tool == "getJiraIssue"
        assert arguments["issueIdOrKey"] == "TASK-123"
        return {
            "key": "TASK-123",
            "fields": {
                "summary": "Add order filter",
                "issuetype": {"name": "Bug"},
            },
        }


class FailingMcpClient:
    def call(self, server_id: str, tool: str, arguments: dict) -> dict:
        raise RuntimeError("Jira unavailable")


def test_jira_url_is_enriched_through_read_tool() -> None:
    issue = resolve_issue(
        "https://company.atlassian.net/browse/TASK-123",
        jira={"cloud_id": "cloud-1"},
        client=FakeMcpClient(),
    )

    assert issue == IssueContext("TASK-123", "Add order filter", "fix", True)


def test_plain_id_survives_missing_jira_without_summary() -> None:
    issue = resolve_issue("SOME-ID", jira=None, client=FailingMcpClient())

    assert issue == IssueContext("SOME-ID", None, None, False)
