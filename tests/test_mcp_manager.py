from __future__ import annotations

from pathlib import Path

from agent_engineering_kit.mcp_manager import McpManager
from agent_engineering_kit.component_state import Lifecycle, write_state
from agent_engineering_kit.paths import KitPaths
from agent_engineering_kit.process import CommandResult
from agent_engineering_kit.projects import LogicalProject


def test_managed_mcp_does_not_fall_back_to_unmanaged_path(tmp_path: Path, monkeypatch) -> None:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    manager = McpManager(repository, paths)
    item = next(item for item, _ in manager.desired() if item["id"] == "serena")
    monkeypatch.setattr("agent_engineering_kit.mcp_manager.shutil.which", lambda _: "/usr/local/bin/serena")

    assert manager.executable(item) is None


def test_core_and_conditional_multi_provider_activation(tmp_path: Path) -> None:
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
    assert enabled["codebase-memory"] and enabled["serena"] and enabled["context7"]
    assert enabled["github"] and enabled["gitlab"]
    assert not enabled["sonarqube"] and not enabled["atlassian"]


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
    github = next(row for row in manager.desired() if row[0]["id"] == "github")
    manager.desired = lambda project=None: [github]  # type: ignore[method-assign]
    manager.is_enabled = lambda item, project=None: True  # type: ignore[method-assign]
    monkeypatch.setattr("agent_engineering_kit.mcp_manager.shutil.which", lambda command: "/usr/local/bin/docker")
    write_state(paths, "mcp", "github", Lifecycle.ACTIVE, revision=github[1].revision)

    manager.install()

    assert any(args[1] == "pull" and "@sha256:" in args[2] for args in calls)
    assert manager.list()[0]["status"] == Lifecycle.NOT_INSTALLED.value
