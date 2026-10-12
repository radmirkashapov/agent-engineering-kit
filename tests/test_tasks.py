from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_engineering_kit.errors import AgentKitError
from agent_engineering_kit.paths import KitPaths
from agent_engineering_kit.tasks import acquire_lease, create_task_workspace, release_leases, write_sets_overlap


def _paths(tmp_path: Path) -> KitPaths:
    return KitPaths(tmp_path / "kit", tmp_path / "data", tmp_path / "runtime", tmp_path / "projects", tmp_path / "overrides")


def test_write_set_overlap_is_conservative() -> None:
    assert write_sets_overlap(["src/payments/**"], ["src/payments/api.py"])
    assert write_sets_overlap(["docs/INDEX.md"], ["docs/INDEX.md"])
    assert not write_sets_overlap(["src/payments/**"], ["src/orders/**"])


def test_task_workspace_records_revision_vector_without_mutating_repositories(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    repository = tmp_path / "backend"
    repository.mkdir()

    target = create_task_workspace(
        paths,
        project_id="commerce",
        task_id="task-01",
        repositories=[{"id": "backend", "path": str(repository), "commit": "abc123"}],
        write_set=["src/**"],
        policy_digest="policy",
        conventions_digest="conventions",
    )

    document = json.loads(target.read_text())
    assert document["repository_revision_vector"] == {"backend": "abc123"}
    assert document["status"] == "planned"
    assert list(repository.iterdir()) == []


def test_overlapping_leases_are_rejected_and_release_is_scoped(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    first = acquire_lease(paths, project_id="commerce", task_id="task-01", write_set=["src/payments/**"])

    with pytest.raises(AgentKitError, match="пересекается"):
        acquire_lease(paths, project_id="commerce", task_id="task-02", write_set=["src/payments/api.py"])

    assert release_leases(paths, project_id="commerce", task_id="task-02") == []
    assert first.exists()
    assert release_leases(paths, project_id="commerce", task_id="task-01") == [first]
    assert not first.exists()
