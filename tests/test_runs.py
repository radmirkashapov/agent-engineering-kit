from __future__ import annotations

import json
from pathlib import Path

from agent_engineering_kit.paths import KitPaths
from agent_engineering_kit.runs import build_run_request, record_run_result, write_run_request


def test_run_request_separates_planned_state_and_redacts_secrets(tmp_path: Path) -> None:
    manifest = build_run_request(
        run_id="run-01",
        created_at="2026-10-12T10:00:00+00:00",
        kit_revision="abc123",
        project_id="commerce",
        policy={"model": "approved", "token": "must-not-leak"},
        conventions={"git": {"pull_request_required": True}},
        harness={"selected_client": "codex", "managed_capabilities": ["mcp"]},
        roles=[{"id": "developer"}],
        skills=[{"id": "verification", "revision": "1"}],
        mcp=[{"id": "jira", "authorization": "Bearer must-not-leak"}],
        requested_model="approved",
        permissions={"profile": "readonly", "api_key": "must-not-leak"},
        repositories=[{"id": "backend", "commit": "deadbeef", "branch": "feat/demo", "worktree": "/tmp/wt"}],
        verification_steps=["unit-tests"],
        bypasses=[{"target": "models", "reason": "local license"}],
    )

    serialized = json.dumps(manifest)
    assert manifest["schema"] == "agent-engineering-kit/run-manifest/v1"
    assert manifest["phase"] == "request"
    assert manifest["policy_sha256"]
    assert manifest["conventions_sha256"]
    assert manifest["repository_revision_vector"] == {"backend": "deadbeef"}
    assert "must-not-leak" not in serialized
    assert manifest["permissions"]["api_key"] == "[REDACTED]"


def test_request_and_result_are_written_as_separate_documents(tmp_path: Path) -> None:
    paths = KitPaths(tmp_path / "kit", tmp_path / "data", tmp_path / "runtime", tmp_path / "projects", tmp_path / "overrides")
    request = build_run_request(
        run_id="run-02",
        created_at="2026-10-12T10:00:00+00:00",
        kit_revision="abc123",
        project_id="commerce",
        policy={},
        conventions={},
        harness={"selected_client": "codex"},
        roles=[],
        skills=[],
        mcp=[],
        requested_model="approved",
        permissions={"profile": "readonly"},
        repositories=[],
        verification_steps=[],
        bypasses=[],
    )

    request_path = write_run_request(paths, request)
    result_path = record_run_result(
        paths,
        project_id="commerce",
        run_id="run-02",
        recorded_at="2026-10-12T10:01:00+00:00",
        status="passed",
        actual_model="approved",
        verification=[{"id": "unit-tests", "status": "passed"}],
        details={"password": "must-not-leak"},
    )

    assert request_path.name == "request.json"
    assert result_path.name == "result.json"
    assert json.loads(request_path.read_text())["phase"] == "request"
    result = json.loads(result_path.read_text())
    assert result["phase"] == "result"
    assert result["request"] == "request.json"
    assert result["details"]["password"] == "[REDACTED]"
