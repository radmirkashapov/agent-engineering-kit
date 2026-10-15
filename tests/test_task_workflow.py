from __future__ import annotations

import json
import subprocess
from datetime import date
from pathlib import Path

from agent_engineering_kit.paths import KitPaths
from agent_engineering_kit.task_workflow import (
    build_branch_name,
    create_task_lane,
    complete_task_lane,
    create_task_workflow,
    integration_plan,
    retry_task_workflow,
    task_workflow_status,
)


def _paths(tmp_path: Path, repository: Path) -> KitPaths:
    data = tmp_path / "data"
    return KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")


def _repository(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "repository"
    root.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "tests@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Tests"], cwd=root, check=True)
    (root / "README.md").write_text("# Project\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-m", "docs(readme): add project"], cwd=root, check=True, capture_output=True)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()
    return root, commit


def test_branch_name_omits_summary_when_issue_lookup_has_no_result() -> None:
    assert build_branch_name("SOME-ID", None, "feat", date(2026, 10, 14)) == "feat/14-10-2026-some-id"


def test_branch_name_uses_explicit_type_and_normalized_summary() -> None:
    assert build_branch_name(
        "TASK-123", "Add orders filter", "fix", date(2026, 10, 14)
    ) == "fix/14-10-2026-task-123-add-orders-filter"


def test_task_workflow_creates_copy_branch_when_requested_branch_exists(tmp_path: Path) -> None:
    kit_repository = Path(__file__).resolve().parents[1]
    repository, commit = _repository(tmp_path)
    subprocess.run(
        ["git", "branch", "feat/14-10-2026-task-123-orders", commit],
        cwd=repository,
        check=True,
    )

    result = create_task_workflow(
        _paths(tmp_path, kit_repository),
        project_id="orders",
        task_id="TASK-123",
        repositories=[{"id": "root", "path": str(repository), "commit": commit}],
        write_set=["services/orders/**"],
        policy_digest="policy",
        conventions_digest="conventions",
        branch_type="feat",
        summary="orders",
        today=date(2026, 10, 14),
    )

    assert result["status"] == "active"
    assert result["worktrees"][0]["branch"] == "feat/14-10-2026-task-123-orders-copy-2"
    assert Path(result["worktrees"][0]["target"]).is_dir()


def test_overlapping_task_waits_and_names_blocker(tmp_path: Path) -> None:
    kit_repository = Path(__file__).resolve().parents[1]
    repository, commit = _repository(tmp_path)
    kit_paths = _paths(tmp_path, kit_repository)
    first = create_task_workflow(
        kit_paths,
        project_id="orders",
        task_id="TASK-1",
        repositories=[{"id": "root", "path": str(repository), "commit": commit}],
        write_set=["services/orders/**"],
        policy_digest="policy",
        conventions_digest="conventions",
        branch_type="feat",
        summary=None,
        today=date(2026, 10, 14),
    )
    second = create_task_workflow(
        kit_paths,
        project_id="orders",
        task_id="TASK-2",
        repositories=[{"id": "root", "path": str(repository), "commit": commit}],
        write_set=["services/orders/api/**"],
        policy_digest="policy",
        conventions_digest="conventions",
        branch_type="fix",
        summary=None,
        today=date(2026, 10, 14),
    )

    assert first["status"] == "active"
    assert second["status"] == "waiting"
    assert second["blocked_by"] == [
        {"task_id": "TASK-1", "overlap": ["services/orders/**", "services/orders/api/**"]}
    ]
    state = json.loads(Path(second["task_path"]).read_text(encoding="utf-8"))
    assert state["status"] == "waiting"
    assert state["blocked_by"] == second["blocked_by"]

    first_state = json.loads(Path(first["task_path"]).read_text(encoding="utf-8"))
    first_state["status"] = "completed"
    Path(first["task_path"]).write_text(json.dumps(first_state), encoding="utf-8")
    (kit_paths.projects / "orders" / "leases" / "TASK-1.json").unlink()

    assert task_workflow_status(kit_paths, project_id="orders", task_id="TASK-2")["ready_to_retry"] is True
    retried = retry_task_workflow(kit_paths, project_id="orders", task_id="TASK-2")
    assert retried["status"] == "active"
    assert (kit_paths.projects / "orders" / "leases" / "TASK-2.json").is_file()


def test_lanes_queue_overlapping_writes_and_only_prepare_git_integration(tmp_path: Path) -> None:
    kit_repository = Path(__file__).resolve().parents[1]
    repository, commit = _repository(tmp_path)
    kit_paths = _paths(tmp_path, kit_repository)
    task = create_task_workflow(
        kit_paths,
        project_id="orders",
        task_id="TASK-3",
        repositories=[{"id": "root", "path": str(repository), "commit": commit}],
        write_set=["services/**"],
        policy_digest="policy",
        conventions_digest="conventions",
        branch_type="feat",
        summary="orders",
        today=date(2026, 10, 14),
    )

    api = create_task_lane(
        kit_paths,
        project_id="orders",
        task_id=task["task_id"],
        lane_id="api",
        write_set=["services/orders/**"],
        today=date(2026, 10, 14),
    )
    tests = create_task_lane(
        kit_paths,
        project_id="orders",
        task_id=task["task_id"],
        lane_id="tests",
        write_set=["services/orders/tests/**"],
        today=date(2026, 10, 14),
    )

    assert api["status"] == "active"
    assert api["worktrees"][0]["branch"] == "agent/14-10-2026-task-3-api"
    assert tests["status"] == "waiting"
    assert tests["blocked_by"] == ["api"]
    plan = integration_plan(kit_paths, project_id="orders", task_id=task["task_id"], lane_id="api")
    assert plan["performs_merge"] is False
    assert plan["commands"][0].startswith(f"git -C {task['worktrees'][0]['target']} ")
    assert " merge --no-ff agent/14-10-2026-task-3-api" in plan["commands"][0]

    completed = complete_task_lane(
        kit_paths,
        project_id="orders",
        task_id=task["task_id"],
        lane_id="api",
    )
    assert completed["status"] == "completed"
    status = task_workflow_status(kit_paths, project_id="orders", task_id=task["task_id"])
    assert next(lane for lane in status["lanes"] if lane["id"] == "tests")["status"] == "active"


def test_lane_waits_while_parent_task_is_blocked_and_activates_after_retry(tmp_path: Path) -> None:
    kit_repository = Path(__file__).resolve().parents[1]
    repository, commit = _repository(tmp_path)
    kit_paths = _paths(tmp_path, kit_repository)
    first = create_task_workflow(
        kit_paths,
        project_id="orders",
        task_id="TASK-10",
        repositories=[{"id": "root", "path": str(repository), "commit": commit}],
        write_set=["services/orders/**"],
        policy_digest="policy",
        conventions_digest="conventions",
        branch_type="feat",
        summary=None,
        today=date(2026, 10, 14),
    )
    second = create_task_workflow(
        kit_paths,
        project_id="orders",
        task_id="TASK-11",
        repositories=[{"id": "root", "path": str(repository), "commit": commit}],
        write_set=["services/orders/api/**"],
        policy_digest="policy",
        conventions_digest="conventions",
        branch_type="fix",
        summary=None,
        today=date(2026, 10, 14),
    )

    lane = create_task_lane(
        kit_paths,
        project_id="orders",
        task_id=second["task_id"],
        lane_id="api",
        write_set=["services/orders/api/**"],
        today=date(2026, 10, 14),
    )

    assert second["status"] == "waiting"
    assert lane["status"] == "waiting"
    assert lane["blocked_by"] == ["task:TASK-10"]

    Path(first["task_path"]).write_text(
        json.dumps({**json.loads(Path(first["task_path"]).read_text(encoding="utf-8")), "status": "completed"}),
        encoding="utf-8",
    )
    (kit_paths.projects / "orders" / "leases" / "TASK-10.json").unlink()

    retried = retry_task_workflow(kit_paths, project_id="orders", task_id=second["task_id"])
    assert retried["status"] == "active"
    assert retried["lanes"][0]["status"] == "active"
    assert retried["lanes"][0]["blocked_by"] == []
