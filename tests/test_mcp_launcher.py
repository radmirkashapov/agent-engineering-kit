from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import agent_engineering_kit.mcp_launcher as launcher
from agent_engineering_kit.errors import AgentKitError
from agent_engineering_kit.mcp_launcher import registration_command, write_launch_contract
from agent_engineering_kit.paths import KitPaths


def make_paths(tmp_path: Path) -> KitPaths:
    data = tmp_path / "data"
    return KitPaths(tmp_path / "repository", data, data / "runtime", data / "projects", data / "overrides")


def sample_item():
    return {
        "id": "sample",
        "args": ["serve"],
        "environment": {"TARGET": "env:SOURCE"},
        "required_environment": ["SOURCE"],
    }


def test_contract_contains_references_but_never_secret_values(tmp_path, monkeypatch):
    paths = make_paths(tmp_path)
    monkeypatch.setenv("SOURCE", "private-inherited-value")
    contract = write_launch_contract(paths, sample_item(), Path("/opt/sample-mcp"))
    assert contract == paths.installations / "clients/shared/mcp-launchers/sample.json"
    assert json.loads(contract.read_text()) == {
        "version": 1,
        "mcp_id": "sample",
        "command": "/opt/sample-mcp",
        "args": ["serve"],
        "environment": {"TARGET": "SOURCE"},
        "required_environment": ["SOURCE"],
    }
    assert "private-inherited-value" not in contract.read_text()


def test_registration_command_uses_python_module_and_absolute_contract(tmp_path):
    command, args = registration_command(make_paths(tmp_path), sample_item(), Path("/opt/sample-mcp"))
    assert command == sys.executable
    assert args[:2] == ["-m", "agent_engineering_kit.mcp_launcher"]
    assert Path(args[2]).is_absolute()
    assert json.loads(Path(args[2]).read_text())["command"] == "/opt/sample-mcp"


@pytest.mark.parametrize("identifier", ["../escape", "/absolute", "a/b", "a\\b", "", ".", "..", "bad:drive", "CON", "trailing."])
def test_contract_rejects_unsafe_identifiers(tmp_path, identifier):
    item = sample_item() | {"id": identifier}
    with pytest.raises(AgentKitError):
        write_launch_contract(make_paths(tmp_path), item, Path("/opt/sample-mcp"))
    assert not list(tmp_path.rglob("*.json"))


@pytest.mark.parametrize("mapping", ["private-literal-value", "env:", "env:BAD-NAME", "env:SOURCE\x00", None])
def test_contract_rejects_literal_or_invalid_environment_sources(tmp_path, mapping):
    item = sample_item() | {"environment": {"TARGET": mapping}}
    with pytest.raises(AgentKitError) as raised:
        write_launch_contract(make_paths(tmp_path), item, Path("/opt/sample-mcp"))
    assert "private-literal-value" not in str(raised.value)
    assert not list(tmp_path.rglob("*.json"))


def test_contract_replacement_is_atomic(tmp_path, monkeypatch):
    import agent_engineering_kit.io as io_module

    paths = make_paths(tmp_path)
    contract = write_launch_contract(paths, sample_item(), Path("/opt/original"))
    previous = contract.read_bytes()

    def fail_replace(*args):
        raise OSError("private-error-value")

    monkeypatch.setattr(io_module.os, "replace", fail_replace)
    with pytest.raises(AgentKitError) as raised:
        write_launch_contract(paths, sample_item(), Path("/opt/replacement"))
    assert contract.read_bytes() == previous
    assert list(contract.parent.iterdir()) == [contract]
    assert "private-error-value" not in str(raised.value)


@pytest.mark.parametrize("changes", [
    {"args": "serve"}, {"args": [1]}, {"args": ["private\x00value"]},
    {"required_environment": "SOURCE"}, {"required_environment": ["BAD-NAME"]},
    {"environment": {"BAD=TARGET": "env:SOURCE"}},
])
def test_contract_rejects_malformed_launch_fields_before_writing(tmp_path, changes):
    with pytest.raises(AgentKitError):
        write_launch_contract(make_paths(tmp_path), sample_item() | changes, Path("/opt/sample-mcp"))
    assert not list(tmp_path.rglob("*.json"))


def test_contract_rejects_invalid_executable_without_echoing_value(tmp_path):
    with pytest.raises(AgentKitError) as raised:
        write_launch_contract(make_paths(tmp_path), sample_item(), Path("private\x00value"))
    assert "private" not in str(raised.value)
    assert not list(tmp_path.rglob("*.json"))


def prepared_contract(tmp_path: Path, **overrides):
    paths = make_paths(tmp_path)
    return paths, write_launch_contract(paths, sample_item() | overrides, Path("/opt/sample-mcp"))


def write_private_vault(paths: KitPaths, content: str) -> None:
    paths.secrets.mkdir(parents=True, mode=0o700)
    paths.secrets.chmod(0o700)
    vault = paths.secrets / "mcp-creds.env"
    vault.write_text(content, encoding="utf-8")
    vault.chmod(0o600)


def test_launch_overlays_only_declared_vault_values(tmp_path):
    paths, contract = prepared_contract(tmp_path)
    write_private_vault(paths, "SOURCE=vault-value\nUNUSED=hidden\n")
    parent = {"SOURCE": "inherited", "KEEP": "yes", "UNUSED": "parent"}
    calls = []
    launcher.launch(contract, paths=paths, environ=parent, exec_process=lambda *args: calls.append(args))
    assert calls == [("/opt/sample-mcp", ["/opt/sample-mcp", "serve"], {
        "TARGET": "vault-value", "KEEP": "yes", "UNUSED": "parent",
    })]
    assert parent == {"SOURCE": "inherited", "KEEP": "yes", "UNUSED": "parent"}


@pytest.mark.parametrize("vault", [None, "SOURCE=\n"])
def test_launch_falls_back_to_inherited_source(tmp_path, vault):
    paths, contract = prepared_contract(tmp_path)
    if vault is not None:
        write_private_vault(paths, vault)
    calls = []
    launcher.launch(contract, paths=paths, environ={"SOURCE": "inherited"}, exec_process=lambda *args: calls.append(args))
    assert calls[0][2] == {"TARGET": "inherited"}


@pytest.mark.parametrize("parent", [{}, {"SOURCE": ""}])
def test_launch_fails_before_exec_when_required_source_is_missing(tmp_path, parent):
    paths, contract = prepared_contract(tmp_path)
    write_private_vault(paths, "SOURCE=\nUNUSED=private-value\n")
    calls = []
    with pytest.raises(AgentKitError, match="SOURCE") as raised:
        launcher.launch(contract, paths=paths, environ=parent, exec_process=lambda *args: calls.append(args))
    assert calls == []
    assert "private-value" not in str(raised.value)


def test_launch_resolves_required_only_and_same_name_sources(tmp_path):
    paths, contract = prepared_contract(tmp_path, environment={"SOURCE": "env:SOURCE"}, required_environment=["SOURCE", "OTHER"])
    write_private_vault(paths, "SOURCE=vault-value\nOTHER=required-only\n")
    calls = []
    launcher.launch(contract, paths=paths, environ={}, exec_process=lambda *args: calls.append(args))
    assert calls[0][2] == {"SOURCE": "vault-value", "OTHER": "required-only"}


def test_launch_keeps_unset_optional_target_and_removes_only_renamed_sources(tmp_path):
    paths, contract = prepared_contract(tmp_path, required_environment=[])
    calls = []
    launcher.launch(contract, paths=paths, environ={"TARGET": "existing", "KEEP": "yes"}, exec_process=lambda *args: calls.append(args))
    assert calls[0][2] == {"TARGET": "existing", "KEEP": "yes"}


def test_launch_mapping_resolution_is_independent_of_target_order(tmp_path):
    paths, contract = prepared_contract(tmp_path, environment={"A": "env:B", "C": "env:A"}, required_environment=["A", "B"])
    calls = []
    launcher.launch(contract, paths=paths, environ={"A": "first", "B": "second"}, exec_process=lambda *args: calls.append(args))
    assert calls[0][2] == {"A": "second", "C": "first"}


def test_launch_uses_process_environment_by_default(tmp_path, monkeypatch):
    paths, contract = prepared_contract(tmp_path)
    monkeypatch.setenv("SOURCE", "inherited-default")
    calls = []
    launcher.launch(contract, paths=paths, exec_process=lambda *args: calls.append(args))
    assert calls[0][2]["TARGET"] == "inherited-default"
    assert "SOURCE" not in calls[0][2]


@pytest.mark.parametrize("changes", [
    {"version": 2}, {"version": True}, {"version": "1"},
    {"mcp_id": "../escape"}, {"command": "relative-command"}, {"command": "bad\x00command"},
    {"args": "serve"}, {"args": ["bad\x00argument"]}, {"args": [1]},
    {"environment": {"TARGET": "private-value"}}, {"environment": {"BAD=NAME": "SOURCE"}},
    {"required_environment": "SOURCE"}, {"required_environment": ["BAD-NAME"]},
    {"unknown": "private-value"},
])
def test_launch_rejects_invalid_contract_before_exec(tmp_path, changes):
    paths, contract = prepared_contract(tmp_path)
    document = json.loads(contract.read_text()) | changes
    contract.write_text(json.dumps(document))
    calls = []
    with pytest.raises(AgentKitError) as raised:
        launcher.launch(contract, paths=paths, environ={"SOURCE": "private-value"}, exec_process=lambda *args: calls.append(args))
    assert calls == []
    assert "private-value" not in str(raised.value)


@pytest.mark.parametrize("content", ["not-json-private-value", "[]", "null", "{}"])
def test_launch_rejects_unreadable_or_malformed_contract_safely(tmp_path, content):
    paths, contract = prepared_contract(tmp_path)
    contract.write_text(content)
    with pytest.raises(AgentKitError) as raised:
        launcher.launch(contract, paths=paths, environ={}, exec_process=lambda *args: pytest.fail("exec called"))
    assert "private-value" not in str(raised.value)


def test_launch_missing_contract_is_a_user_error(tmp_path):
    with pytest.raises(AgentKitError):
        launcher.launch(tmp_path / "missing.json", paths=make_paths(tmp_path), environ={}, exec_process=lambda *args: pytest.fail("exec called"))


def test_launch_sanitizes_exec_error(tmp_path):
    paths, contract = prepared_contract(tmp_path)

    def fail_exec(*args):
        raise OSError("private-child-environment")

    with pytest.raises(AgentKitError) as raised:
        launcher.launch(contract, paths=paths, environ={"SOURCE": "private-value"}, exec_process=fail_exec)
    assert "sample" in str(raised.value)
    assert "private" not in str(raised.value)


def test_module_entry_point_launches_real_process_with_resolved_credentials(tmp_path):
    paths = make_paths(tmp_path)
    item = sample_item() | {"args": ["-c", "import os; print(os.environ['TARGET']); assert 'SOURCE' not in os.environ"]}
    command, args = registration_command(paths, item, Path(sys.executable))
    write_private_vault(paths, "SOURCE=fixture-token\n")
    completed = subprocess.run([command, *args], env={**os.environ, "AGENT_KIT_DATA_HOME": str(paths.data)}, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == "fixture-token\n"
    assert completed.stderr == ""


def test_module_entry_point_reports_user_error_without_traceback(tmp_path):
    paths, contract = prepared_contract(tmp_path)
    completed = subprocess.run([sys.executable, "-m", "agent_engineering_kit.mcp_launcher", str(contract)],
        env={"AGENT_KIT_DATA_HOME": str(paths.data)}, capture_output=True, text=True)
    assert completed.returncode == 1
    assert "SOURCE" in completed.stderr
    assert "Traceback" not in completed.stderr
    assert completed.stdout == ""
