from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import agent_engineering_kit.cli as cli_module
from agent_engineering_kit.cli import _parser, run
from agent_engineering_kit.io import load_yaml


REPOSITORY = Path(__file__).resolve().parents[1]


@pytest.fixture
def isolated_data(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("AGENT_KIT_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("AGENT_KIT_REPOSITORY", str(REPOSITORY))
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _write_skill_source(path: Path) -> Path:
    path.mkdir(parents=True)
    (path / "SKILL.md").write_text(
        """---
version: 1
name: verification
description: Локальная проверка результата.
requires:
  model_capabilities: [reasoning]
---

# Локальная проверка
""",
        encoding="utf-8",
    )
    return path


def _write_mcp_source(path: Path) -> Path:
    path.write_text("mode: extend\nvalue:\n  transport: sse\n", encoding="utf-8")
    return path


@pytest.mark.parametrize("resource", ["skills", "mcp"])
@pytest.mark.parametrize("action", ["enable", "disable", "reset"])
def test_mutating_commands_require_explicit_scope(resource: str, action: str) -> None:
    with pytest.raises(SystemExit):
        _parser().parse_args([resource, action, "greeting"])


def test_available_does_not_require_scope() -> None:
    args = _parser().parse_args(["skills", "available"])

    assert args.skills_command == "available"


@pytest.mark.parametrize("resource", ["skills", "mcp"])
def test_override_requires_source_and_scope(resource: str) -> None:
    with pytest.raises(SystemExit):
        _parser().parse_args([resource, "override", "greeting", "--scope", "global"])
    with pytest.raises(SystemExit):
        _parser().parse_args([resource, "override", "greeting", "--from", "source"])


@pytest.mark.parametrize("resource", ["skills", "mcp"])
def test_override_exposes_source(resource: str) -> None:
    args = _parser().parse_args(
        [resource, "override", "greeting", "--from", "source", "--scope", "global"]
    )

    assert args.source == "source"


@pytest.mark.parametrize(
    ("resource", "identifier"),
    [("skills", "verification"), ("mcp", "context7")],
)
def test_cli_disable_then_enable_round_trip(
    resource: str,
    identifier: str,
    isolated_data: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    access_path = isolated_data / "overrides" / "global" / "access.yaml"

    assert run([resource, "disable", identifier, "--scope", "global"]) == 0
    assert identifier in load_yaml(access_path)[resource]["block"]
    disabled_output = capsys.readouterr().out
    assert str(access_path) in disabled_output
    assert '"enabled": false' in disabled_output

    assert run([resource, "enable", identifier, "--scope", "global"]) == 0
    assert identifier not in load_yaml(access_path)[resource]["block"]
    enabled_output = capsys.readouterr().out
    assert str(access_path) in enabled_output
    assert '"enabled": true' in enabled_output


@pytest.mark.parametrize(
    ("resource", "identifier"),
    [("skills", "verification"), ("mcp", "context7")],
)
def test_available_prints_effective_catalog(
    resource: str,
    identifier: str,
    isolated_data: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert run([resource, "available"]) == 0

    output = capsys.readouterr().out
    assert f'"id": "{identifier}"' in output
    assert '"enabled": true' in output
    assert not (isolated_data / "overrides").exists()


def test_cli_skill_override_and_reset(
    isolated_data: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _write_skill_source(isolated_data / "local-skill")
    definition = isolated_data / "overrides" / "global" / "skills" / "verification.yaml"
    copied_source = isolated_data / "overrides" / "global" / "sources" / "skills" / "verification"

    assert run(
        ["skills", "override", "verification", "--from", str(source), "--scope", "global"]
    ) == 0
    assert definition.is_file()
    assert (copied_source / "SKILL.md").is_file()
    override_output = capsys.readouterr().out
    assert str(definition) in override_output
    assert '"enabled": true' in override_output

    assert run(["skills", "reset", "verification", "--scope", "global"]) == 0
    assert not definition.exists()
    assert not copied_source.exists()
    assert list((isolated_data / "overrides" / "backups").glob("*/skills/verification.yaml"))
    assert list((isolated_data / "overrides" / "backups").glob("*/sources/skills/verification/SKILL.md"))
    reset_output = capsys.readouterr().out
    assert str(isolated_data / "overrides" / "backups") in reset_output
    assert '"enabled": true' in reset_output


def test_cli_mcp_override_and_reset(
    isolated_data: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _write_mcp_source(isolated_data / "context7.yaml")
    definition = isolated_data / "overrides" / "global" / "mcp" / "context7.yaml"

    assert run(
        ["mcp", "override", "context7", "--from", str(source), "--scope", "global"]
    ) == 0
    assert definition.is_file()
    assert load_yaml(definition)["override"]["value"]["transport"] == "sse"
    override_output = capsys.readouterr().out
    assert str(definition) in override_output
    assert '"transport": "sse"' in override_output

    assert run(["mcp", "reset", "context7", "--scope", "global"]) == 0
    assert not definition.exists()
    assert list((isolated_data / "overrides" / "backups").glob("*/mcp/context7.yaml"))
    reset_output = capsys.readouterr().out
    assert str(isolated_data / "overrides" / "backups") in reset_output
    assert '"transport": "http"' in reset_output


@pytest.mark.parametrize("resource", ["skills", "mcp"])
def test_unknown_id_fails_without_side_effects(
    resource: str,
    isolated_data: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert run([resource, "disable", "unknown-component", "--scope", "global"]) == 1

    assert "не найден" in capsys.readouterr().err.lower()
    assert not (isolated_data / "overrides").exists()


@pytest.mark.parametrize("resource", ["skills", "mcp"])
def test_project_scope_without_manifest_fails_without_side_effects(
    resource: str,
    isolated_data: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    identifier = "verification" if resource == "skills" else "context7"

    assert run([resource, "disable", identifier, "--scope", "project"]) == 1

    assert ".ai-team/project.yaml" in capsys.readouterr().err
    assert not (isolated_data / "overrides").exists()


def test_resync_runs_only_after_successful_atomic_mutation(
    monkeypatch: pytest.MonkeyPatch,
    isolated_data: Path,
) -> None:
    calls: list[bool] = []
    access_path = isolated_data / "overrides" / "global" / "access.yaml"

    def fake_resync(*args: object, **kwargs: object) -> SimpleNamespace:
        calls.append(access_path.is_file())
        return SimpleNamespace(incomplete=[], revision="test", changed=True, skills=[], mcp=[], clients=[])

    monkeypatch.setattr(cli_module, "resync", fake_resync)

    assert run(["mcp", "disable", "unknown-component", "--scope", "global", "--resync"]) == 1
    assert calls == []
    assert run(["mcp", "disable", "context7", "--scope", "global", "--resync"]) == 0
    assert calls == [True]
    assert run(["mcp", "enable", "context7", "--scope", "global", "--resync"]) == 0
    assert calls == [True, True]

    source = _write_mcp_source(isolated_data / "context7.yaml")
    assert run(
        ["mcp", "override", "context7", "--from", str(source), "--scope", "global", "--resync"]
    ) == 0
    assert calls == [True, True, True]
    assert run(["mcp", "reset", "context7", "--scope", "global", "--resync"]) == 0
    assert calls == [True, True, True, True]


def test_reset_without_changes_does_not_run_resync(
    monkeypatch: pytest.MonkeyPatch,
    isolated_data: Path,
) -> None:
    calls: list[object] = []

    def fake_resync(*args: object, **kwargs: object) -> SimpleNamespace:
        calls.append((args, kwargs))
        return SimpleNamespace(incomplete=[], revision="test", changed=True, skills=[], mcp=[], clients=[])

    monkeypatch.setattr(cli_module, "resync", fake_resync)

    assert run(["mcp", "reset", "context7", "--scope", "global", "--resync"]) == 0
    assert calls == []


def test_generic_override_requires_reason_and_explicit_scope() -> None:
    with pytest.raises(SystemExit):
        _parser().parse_args([
            "override", "set", "approvals", "profile", "--mode", "replace", "--from", "value.yaml", "--scope", "global"
        ])


def test_generic_override_cli_round_trip(
    isolated_data: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = isolated_data / "approval.yaml"
    source.write_text("# Локальный профиль подтверждений.\nvalue: autonomous\n", encoding="utf-8")

    assert run([
        "override", "set", "approvals", "profile",
        "--mode", "replace", "--from", str(source),
        "--reason", "Use isolated local execution", "--scope", "global",
    ]) == 0
    target = isolated_data / "overrides/global/policy/approvals-profile.yaml"
    assert target.is_file()
    capsys.readouterr()

    assert run(["override", "list", "--scope", "global"]) == 0
    assert "approvals.profile" in capsys.readouterr().out

    assert run(["override", "reset", "approvals", "profile", "--scope", "global"]) == 0
    assert not target.exists()


def test_local_mcp_access_profile_enables_complete_server_surface(
    isolated_data: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = isolated_data / "mcp-profile.yaml"
    source.write_text("# Локальный профиль MCP.\nvalue: administrator\n", encoding="utf-8")

    assert run([
        "override", "set", "mcp", "access-profile",
        "--mode", "replace", "--from", str(source),
        "--reason", "Use complete local MCP tools", "--scope", "global",
    ]) == 0
    capsys.readouterr()
    assert run(["override", "explain", "mcp", "access-profile", "--scope", "global"]) == 0
    assert "mcp.access_profile" in capsys.readouterr().out

    assert run(["mcp", "available"]) == 0
    rows = {row["id"]: row for row in json.loads(capsys.readouterr().out)}
    assert rows["codebase-memory"]["enabled"] is True
    assert rows["serena"]["enabled"] is True


def test_config_explain_supports_json(isolated_data: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["config", "explain", "--format", "json"]) == 0
    document = __import__("json").loads(capsys.readouterr().out)
    assert "policy" in document


def test_project_attach_status_and_reconcile_preview(
    isolated_data: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = isolated_data / "external"
    root.mkdir()
    (root / "pyproject.toml").write_text('[project]\nname = "external-app"\n', encoding="utf-8")
    assert run(["project", "attach", str(root), "--id", "external-project"]) == 0
    assert not (root / ".ai-team").exists()
    capsys.readouterr()
    assert run(["project", "status", "external-project"]) == 0
    assert "READY" in capsys.readouterr().out
    assert run(["project", "reconcile", "external-project"]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["diff"]["added"][0]["id"] == "python:external-app"
    inventory = isolated_data / "projects/external-project/state/component-inventory.json"
    assert not inventory.exists()
    assert run(["project", "reconcile", "external-project", "--apply"]) == 0
    assert inventory.exists()


def test_project_bind_declared_repo_only(
    isolated_data: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = isolated_data / "existing"
    root.mkdir()
    extra = isolated_data / "extra"
    extra.mkdir()
    assert run(["project", "attach", str(root), "--id", "existing-project"]) == 0
    capsys.readouterr()
    assert run(["project", "bind", "existing-project", "unknown", str(extra)]) == 1
    assert "не объявлен" in capsys.readouterr().err
    assert run(["project", "bind", "existing-project", "root", str(root)]) == 0
    assert (isolated_data / "projects/existing-project/bindings.yaml").exists()


def test_project_id_resolution_does_not_fall_back_to_ambient_manifest(
    isolated_data: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    external = isolated_data / "external"
    external.mkdir()
    assert run(["project", "attach", str(external), "--id", "external-project"]) == 0
    capsys.readouterr()
    ambient = isolated_data / "ambient"
    assert run(["project", "init", str(ambient), "--id", "ambient-project"]) == 0
    capsys.readouterr()
    monkeypatch.chdir(ambient)

    assert run(["project", "status", "external-project"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["project_id"] == "external-project"


def test_project_status_rejects_invalid_manifest(
    isolated_data: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = isolated_data / "invalid-project"
    assert run(["project", "init", str(root), "--id", "invalid-project"]) == 0
    capsys.readouterr()
    manifest = root / ".ai-team/project.yaml"
    document = load_yaml(manifest)
    document["memory"]["namespace"] = "different-project"
    manifest.write_text(__import__("yaml").safe_dump(document, allow_unicode=True), encoding="utf-8")

    assert run(["project", "status", str(root)]) == 1

    assert "memory.namespace" in capsys.readouterr().err


def test_run_cli_prepares_request_and_records_result(
    isolated_data: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = isolated_data / "run-project"
    assert run(["project", "init", str(root), "--id", "run-project"]) == 0
    capsys.readouterr()

    assert run([
        "run", "prepare", str(root), "--run-id", "cli-run", "--profile", "developer",
        "--verify", "pytest",
    ]) == 0
    request_path = Path(capsys.readouterr().out.strip())
    request = json.loads(request_path.read_text(encoding="utf-8"))
    assert request["project_id"] == "run-project"
    assert request["permissions"]["profile"] == "developer"
    assert request["verification_steps"] == ["pytest"]

    assert run([
        "run", "record-result", "cli-run", "--project-id", "run-project",
        "--status", "passed", "--details-json", '{"summary":"ok"}',
    ]) == 0
    result_path = Path(capsys.readouterr().out.strip())
    assert json.loads(result_path.read_text(encoding="utf-8"))["status"] == "passed"

    assert run(["run", "events", "cli-run", "--project-id", "run-project"]) == 0
    assert json.loads(capsys.readouterr().out) == []

    assert run(["run", "events", "../escape", "--project-id", "run-project"]) == 1
    assert "Некорректный run_id" in capsys.readouterr().err


def test_run_prepare_rejects_unknown_explicit_project(
    isolated_data: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert run(["run", "prepare", "missing-project", "--run-id", "run-1"]) == 1
    assert "не найден" in capsys.readouterr().err


def test_task_cli_creates_workspace_and_controls_lease(
    isolated_data: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = isolated_data / "task-project"
    root.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "tests@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Tests"], cwd=root, check=True)
    (root / "README.md").write_text("# Проект\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-m", "docs(readme): add project"], cwd=root, check=True, capture_output=True)
    assert run(["project", "attach", str(root), "--id", "task-project"]) == 0
    capsys.readouterr()

    assert run([
        "task", "create", "task-project", "task-01", "--write", "src/**",
    ]) == 0
    task_path = Path(capsys.readouterr().out.strip())
    assert json.loads(task_path.read_text(encoding="utf-8"))["status"] == "planned"

    assert run(["task", "lease", "task-project", "task-01"]) == 0
    lease_path = Path(capsys.readouterr().out.strip())
    assert lease_path.exists()
    assert run(["task", "worktree-plan", "task-project", "task-01", "--branch-prefix", "feat/13-10-2026-task-01"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["branch"].startswith("feat/13-10-2026-task-01")
    assert run(["task", "complete", "task-project", "task-01"]) == 0
    capsys.readouterr()
    assert run(["task", "release", "task-project", "task-01"]) == 0
    assert not lease_path.exists()
    capsys.readouterr()
    assert run(["task", "gc", "task-project", "task-01"]) == 0
    assert not task_path.exists()
