from __future__ import annotations

from pathlib import Path
import pytest

from agent_engineering_kit.mcp_manager import McpManager
from agent_engineering_kit.component_state import Lifecycle, read_state, write_state
from agent_engineering_kit.paths import KitPaths
from agent_engineering_kit.process import CommandResult
from agent_engineering_kit.projects import LogicalProject
from agent_engineering_kit.mcp_manager import select_capabilities
from agent_engineering_kit.errors import AgentKitError
from agent_engineering_kit.catalog import resolve_desired
from agent_engineering_kit.override_service import OverrideScope, set_component_access
from conftest import write_yaml


def test_managed_mcp_does_not_fall_back_to_unmanaged_path(tmp_path: Path, monkeypatch) -> None:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    manager = McpManager(repository, paths)
    item = next(item for item in manager.available() if item["id"] == "serena")
    monkeypatch.setattr("agent_engineering_kit.mcp_manager.shutil.which", lambda _: "/usr/local/bin/serena")

    assert manager.executable(item) is None


def test_serena_keeps_dashboard_available_without_opening_browser_tabs(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")

    serena = next(item for item in McpManager(repository, paths).available() if item["id"] == "serena")

    assert serena["args"][-2:] == ["--open-web-dashboard", "false"]


def test_sentry_is_optional_read_only_and_supports_custom_host(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")

    sentry = next(item for item in McpManager(repository, paths).available() if item["id"] == "sentry")

    assert sentry["required"] is False
    assert sentry["activation"] == "sentry"
    assert sentry["policy"] == "configurable"
    assert sentry["args"] == [
        "-y",
        "@sentry/mcp-server@0.42.0",
        "--skills=inspect",
        "--sentry-dsn=",
    ]
    assert sentry["environment"] == {
        "SENTRY_ACCESS_TOKEN": "env:SENTRY_ACCESS_TOKEN",
        "SENTRY_HOST": "env:SENTRY_HOST",
    }
    assert sentry["required_environment"] == ["SENTRY_ACCESS_TOKEN"]
    assert sentry["enabled_capabilities"] == ["observability.read"]


def test_sentry_without_token_is_inactive_and_does_not_fail_doctor(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    monkeypatch.delenv("SENTRY_ACCESS_TOKEN", raising=False)
    monkeypatch.setattr("agent_engineering_kit.mcp_manager.shutil.which", lambda command: f"/usr/bin/{command}")

    manager = McpManager(repository, paths)
    sentry = next(item for item in manager.list() if item["id"] == "sentry")
    result = manager.doctor()

    assert sentry["enabled"] is False
    assert sentry["status"] == "inactive"
    assert result.ok


def test_sentry_can_be_enabled_from_default_access_policy(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    write_yaml(paths.overrides / "global/access.yaml", {
        "version": 1,
        "mcp": {"allow": [], "block": ["sentry"]},
        "skills": {"allow": [], "block": []},
    })
    scope = OverrideScope("global", paths.overrides / "global", None)
    monkeypatch.setenv("SENTRY_ACCESS_TOKEN", "not-printed-token")

    assert next(item for item in McpManager(repository, paths).list() if item["id"] == "sentry")["status"] == "DISABLED"

    set_component_access(scope, "mcp", "sentry", enabled=True)
    sentry = next(item for item in McpManager(repository, paths).list() if item["id"] == "sentry")

    assert sentry["enabled"] is True


def test_sentry_doctor_rejects_protocol_in_custom_host(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    monkeypatch.setenv("SENTRY_ACCESS_TOKEN", "not-printed-token")
    monkeypatch.setenv("SENTRY_HOST", "https://sentry.company.example")
    monkeypatch.setattr("agent_engineering_kit.mcp_manager.shutil.which", lambda command: f"/usr/bin/{command}")

    result = McpManager(repository, paths).doctor()
    messages = "\n".join(item.message for item in result.diagnostics)

    assert not result.ok
    assert "SENTRY_HOST должен содержать hostname без протокола и пути" in messages
    assert "not-printed-token" not in messages


def test_default_profile_exposes_only_servers_with_enforceable_read_boundaries(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    root = tmp_path / "workspace"
    (root / "github/.git").mkdir(parents=True)
    (root / "gitlab/.git").mkdir(parents=True)
    manifest = {"id": "multi", "repositories": [{"id": "github", "path": "github"}, {"id": "gitlab", "path": "gitlab"}]}
    project = LogicalProject(root, root / ".ai-team/project.yaml", manifest)

    def runner(args, **kwargs):
        cwd = kwargs.get("cwd")
        host = "github.com" if cwd and cwd.name == "github" else "gitlab.com"
        return CommandResult(tuple(args), 0, f"origin https://{host}/owner/repo.git (fetch)\n", "")

    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    manager = McpManager(repository, paths, runner=runner)
    enabled = {row["id"]: row["enabled"] for row in manager.list(project)}
    assert enabled["context7"]
    assert not enabled["codebase-memory"] and not enabled["serena"]
    assert not enabled["github"] and not enabled["gitlab"]
    assert not enabled["sonarqube"] and not enabled["atlassian"]


def test_access_policy_can_disable_required_mcp(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    write_yaml(paths.overrides / "global/access.yaml", {"version": 1, "mcp": {"allow": [], "block": ["context7"]}})

    manager = McpManager(repository, paths)
    context7 = next(row for row in manager.available() if row["id"] == "context7")

    assert context7["enabled"] is False
    assert context7["access_reason"] == "blocked:global"
    assert "context7" not in {item["id"] for item, _ in manager.desired()}
    listed = next(row for row in manager.list() if row["id"] == "context7")
    assert listed["status"] == "DISABLED"


def test_legacy_override_can_disable_locked_mcp(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    write_yaml(paths.overrides / "global/mcp/context7.yaml", {"target": "context7", "override": {"mode": "disable"}})

    context7 = next(row for row in McpManager(repository, paths).available() if row["id"] == "context7")

    assert context7["enabled"] is False
    assert context7["access_reason"] == "disabled:override"


def test_unmatched_activation_signal_is_inactive_but_allowed(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")

    github = next(row for row in McpManager(repository, paths).list() if row["id"] == "github")

    assert github["enabled"] is False
    assert github["access_reason"] == "corporate:partial-capability-selection-unenforceable"
    assert github["status"] == "DISABLED"


def test_missing_pinned_container_image_is_pulled_before_fast_path(tmp_path: Path, monkeypatch) -> None:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    calls: list[list[str]] = []

    def runner(args, **kwargs):
        calls.append(list(args))
        if "inspect" in args:
            return CommandResult(tuple(args), 1, "", "missing")
        return CommandResult(tuple(args), 0, "", "")

    manager = McpManager(repository, paths, runner=runner)
    github = next(row for row in resolve_desired(repository, "mcp") if row[0]["id"] == "github")
    manager.desired = lambda project=None, **_kwargs: [github]  # type: ignore[method-assign]
    manager.is_enabled = lambda item, project=None: True  # type: ignore[method-assign]
    monkeypatch.setattr("agent_engineering_kit.mcp_manager.shutil.which", lambda command: "/usr/local/bin/docker")
    write_state(paths, "mcp", "github", Lifecycle.ACTIVE, revision=github[1].revision)

    manager.install()

    assert any(args[1] == "pull" and "@sha256:" in args[2] for args in calls)
    assert read_state(paths, "mcp", "github")["status"] == Lifecycle.ACTIVE.value


def test_corporate_capabilities_default_to_read_only(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")

    rows = {row["id"]: row for row in McpManager(repository, paths).available()}

    assert rows["context7"]["enabled_capabilities"] == ["documentation.read"]
    assert rows["atlassian"]["enabled_capabilities"] == []
    assert rows["atlassian"]["enabled"] is False
    assert rows["atlassian"]["access_reason"] == "corporate:partial-capability-selection-unenforceable"


def test_corporate_policy_metadata_is_visible_in_list(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")

    context7 = next(row for row in McpManager(repository, paths).list() if row["id"] == "context7")

    assert context7["owner"] == "engineering-platform"
    assert context7["trust"] == "trusted"
    assert context7["data_classes"] == ["public"]
    assert context7["enabled_capabilities"] == ["documentation.read"]
    assert context7["planned_capabilities"] == ["documentation.read"]
    assert context7["capability_enforcement"] == "whole-server"
    assert context7["boundaries"]["read_only"] is True
    assert context7["audit"]["arguments"] == "redacted"


def test_capability_selection_respects_conflicts_budget_and_modes() -> None:
    capabilities = [
        {"id": "docs.read", "mode": "read", "tool_cost": 2, "conflicts_with": ["wiki.read"]},
        {"id": "wiki.read", "mode": "read", "tool_cost": 1},
        {"id": "issues.read", "mode": "read", "tool_cost": 2},
        {"id": "issues.write", "mode": "write", "tool_cost": 1},
        {"id": "issues.admin", "mode": "admin", "tool_cost": 1},
    ]

    selected = select_capabilities(capabilities, tool_budget=3)

    assert selected == ["docs.read"]


def test_editor_profile_does_not_claim_partially_selected_server_is_enforced(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")

    atlassian = next(
        row for row in McpManager(repository, paths).available(access_profile="editor")
        if row["id"] == "atlassian"
    )

    assert "jira.issue.write" in atlassian["planned_capabilities"]
    assert atlassian["enabled_capabilities"] == []
    assert atlassian["enabled"] is False
    assert atlassian["access_reason"] == "corporate:partial-capability-selection-unenforceable"


def test_capability_selection_obeys_profile_without_boolean_enforcement_claim() -> None:
    capabilities = [{"id": "issues.write", "mode": "write", "tool_cost": 1}]

    assert select_capabilities(capabilities, tool_budget=2, allowed_modes={"read"}) == []
    assert select_capabilities(capabilities, tool_budget=2, allowed_modes={"read", "write"}) == ["issues.write"]


def test_effective_mcp_override_rejects_credentials_in_endpoint(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    write_yaml(paths.overrides / "global/mcp/context7.yaml", {
        "target": "context7",
        "override": {"mode": "extend", "value": {"installation": {"endpoint": "https://user:password@example.com/mcp"}}},
    })

    with pytest.raises(AgentKitError, match="credentials"):
        McpManager(repository, paths).available()


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://example.com/mcp?sig=secret",
        "https://example.com/mcp?code=oauth-code",
        "https://example.com/mcp#secret",
    ],
)
def test_effective_mcp_override_rejects_query_and_fragment_urls(
    tmp_path: Path,
    endpoint: str,
) -> None:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    write_yaml(paths.overrides / "global/mcp/context7.yaml", {
        "target": "context7",
        "override": {"mode": "extend", "value": {"installation": {"endpoint": endpoint}}},
    })

    with pytest.raises(AgentKitError, match="credentials"):
        McpManager(repository, paths).available()
