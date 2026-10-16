from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from agent_engineering_kit.errors import AgentKitError
from agent_engineering_kit.paths import KitPaths
from agent_engineering_kit.projects import init_project
from agent_engineering_kit.pull_requests import PullRequestService, parse_scm_reference


class FakeGitLabClient:
    def __init__(self, *, multiple: bool = False) -> None:
        self.calls: list[tuple[str, str, dict]] = []
        self.multiple = multiple

    def call(self, server_id: str, tool: str, arguments: dict) -> dict:
        self.calls.append((server_id, tool, arguments))
        if tool == "list_merge_requests":
            rows = [
                {
                    "iid": 16,
                    "title": "Another branch",
                    "source_branch": "feature/other",
                    "web_url": "https://gitlab.example.com/team/orders/-/merge_requests/16",
                },
                {
                    "iid": 17,
                    "title": "Add order filter",
                    "source_branch": "feature/orders",
                    "web_url": "https://gitlab.example.com/team/orders/-/merge_requests/17",
                }
            ]
            if self.multiple:
                rows.append({**rows[1], "iid": 18, "web_url": rows[1]["web_url"].replace("17", "18")})
            return {"merge_requests": rows}
        include = arguments.get("include")
        if include:
            return {include[0]: [{"name": include[0], "token": "must-not-be-saved"}]}
        return {
            "iid": 17,
            "title": "Add order filter",
            "state": "opened",
            "source_branch": "feature/orders",
            "target_branch": "main",
            "diff_head_sha": "abc123",
            "web_url": "https://gitlab.example.com/team/orders/-/merge_requests/17",
        }


class PaginatedGitLabClient(FakeGitLabClient):
    def call(self, server_id: str, tool: str, arguments: dict) -> dict:
        if tool != "list_merge_requests":
            return super().call(server_id, tool, arguments)
        self.calls.append((server_id, tool, arguments))
        if "after" not in arguments:
            return {
                "merge_requests": [{"iid": 16, "source_branch": "feature/other"}],
                "pageInfo": {"hasNextPage": True, "endCursor": "next-page"},
            }
        return {
            "merge_requests": [{"iid": 17, "source_branch": "feature/orders"}],
            "pageInfo": {"hasNextPage": False, "endCursor": None},
        }


def _project(tmp_path: Path):
    kit_repository = Path(__file__).resolve().parents[1]
    root = tmp_path / "orders"
    root.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "tests@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Tests"], cwd=root, check=True)
    (root / "README.md").write_text("# Orders\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-m", "docs(readme): add project"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", "git@gitlab.example.com:team/orders.git"], cwd=root, check=True)
    subprocess.run(["git", "switch", "-c", "feature/orders"], cwd=root, check=True, capture_output=True)
    data = tmp_path / "data"
    paths = KitPaths(kit_repository, data, data / "runtime", data / "projects", data / "overrides")
    project = init_project(root, kit_repository, paths, identifier="orders")
    return project, paths, root


def test_parse_reference_distinguishes_github_and_gitlab() -> None:
    github = parse_scm_reference("https://github.com/acme/orders/pull/42")
    gitlab = parse_scm_reference("https://gitlab.example.com/team/orders/-/merge_requests/17")

    assert (github.provider, github.project, github.number) == ("github", "acme/orders", 42)
    assert (gitlab.provider, gitlab.project, gitlab.number) == ("gitlab", "team/orders", 17)


def test_refresh_without_reference_selects_single_open_mr_for_current_branch(tmp_path: Path) -> None:
    project, paths, root = _project(tmp_path)
    client = FakeGitLabClient()

    snapshot_path = PullRequestService(paths.repository, paths, client).refresh(
        None,
        project=project,
        repository_path=root,
    )

    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["provider"] == "gitlab"
    assert snapshot["number"] == 17
    assert snapshot["source_revision"] == "abc123"
    assert snapshot["provenance"]["transport"] == "mcp"
    assert "must-not-be-saved" not in snapshot_path.read_text(encoding="utf-8")
    assert client.calls[0] == (
        "gitlab",
        "list_merge_requests",
        {"project_id": "team/orders", "state": "opened", "first": 100},
    )
    assert {tool for _server, tool, _arguments in client.calls} == {"list_merge_requests", "get_merge_request"}


def test_refresh_without_reference_rejects_multiple_open_mrs(tmp_path: Path) -> None:
    project, paths, root = _project(tmp_path)

    with pytest.raises(AgentKitError, match="Найдено несколько"):
        PullRequestService(paths.repository, paths, FakeGitLabClient(multiple=True)).refresh(
            None,
            project=project,
            repository_path=root,
            interactive=False,
        )


def test_gitlab_branch_lookup_reads_following_pages(tmp_path: Path) -> None:
    project, paths, root = _project(tmp_path)
    client = PaginatedGitLabClient()

    snapshot_path = PullRequestService(paths.repository, paths, client).refresh(
        None,
        project=project,
        repository_path=root,
        interactive=False,
    )

    assert json.loads(snapshot_path.read_text(encoding="utf-8"))["number"] == 17
    assert client.calls[1][2]["after"] == "next-page"


def test_explicit_url_does_not_require_origin_remote(tmp_path: Path) -> None:
    project, paths, root = _project(tmp_path)
    subprocess.run(["git", "remote", "remove", "origin"], cwd=root, check=True)

    snapshot = PullRequestService(paths.repository, paths, FakeGitLabClient()).refresh(
        "https://gitlab.example.com/team/orders/-/merge_requests/17",
        project=project,
        repository_path=root,
        interactive=False,
    )

    assert json.loads(snapshot.read_text(encoding="utf-8"))["number"] == 17
