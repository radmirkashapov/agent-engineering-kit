from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_engineering_kit.errors import AgentKitError
from agent_engineering_kit.paths import KitPaths
from agent_engineering_kit.resync import resync
from agent_engineering_kit.resync import build_session_manifest
import agent_engineering_kit.resync as resync_module


def test_resync_initializes_overrides_before_local_validation(monkeypatch, tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    paths = KitPaths(repository, tmp_path / "data", tmp_path / "runtime", tmp_path / "projects", tmp_path / "overrides")
    calls: list[str] = []
    monkeypatch.setattr(resync_module, "ensure_runtime", lambda _paths: calls.append("runtime"))
    monkeypatch.setattr(
        resync_module,
        "initialize_override_workspace",
        lambda _repository, _paths: calls.append("initializer"),
    )
    monkeypatch.setattr(resync_module, "revision", lambda _repository: "revision")
    monkeypatch.setattr(resync_module, "validate", lambda *_args, **_kwargs: SimpleNamespace(ok=True))
    monkeypatch.setattr(
        resync_module,
        "validate_overrides",
        lambda *_args, **_kwargs: SimpleNamespace(ok=False, diagnostics=[SimpleNamespace(severity="ERROR", message="stop")]),
    )

    with pytest.raises(AgentKitError, match="local overrides validation"):
        resync(repository, paths, update_kit=False)

    assert calls == ["runtime", "initializer"]


def test_session_manifest_records_harness_and_effective_policy_digest(tmp_path: Path) -> None:
    policy = tmp_path / "effective-policy.json"
    policy.write_text('{"version":1}\n', encoding="utf-8")
    harness = {
        "control_plane": "agent-engineering-kit",
        "execution_owner": "client",
        "selected_client": "codex",
    }

    manifest = build_session_manifest(
        revision="abc123",
        project_id="demo",
        security=[],
        skills=[],
        mcp=[],
        clients=["codex"],
        harness=harness,
        effective_policy=policy,
        recorded_at="2026-10-09T00:00:00+00:00",
    )

    assert manifest["schema"] == "agent-engineering-kit/effective-environment/v2"
    assert manifest["harness"] == harness
    assert manifest["effective_policy_sha256"] == "50208d78350a7a160dec59a82df1499b6ca7da33e54c5eb11c97e342118e68bb"
