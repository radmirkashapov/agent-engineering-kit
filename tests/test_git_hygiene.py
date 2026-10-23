from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_engineering_kit.git_hygiene import validate_git_hygiene


IGNORE = """models/user.local.yaml
models/*.local.yaml
overrides/local/
.local/
.runtime/
clients/**/generated/
.env
.env.*
!.env.example
mcp-creds.env
mcp-creds.*.env
!mcp-creds.example.env
secrets/
*.token
*.secret
*.pem
*.key
"""


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", tmp_path], check=True)
    (tmp_path / ".gitignore").write_text(IGNORE, encoding="utf-8")
    subprocess.run(["git", "-C", tmp_path, "add", ".gitignore"], check=True)
    return tmp_path


@pytest.mark.parametrize(
    "name",
    ["models/user.local.yaml", "overrides/local/skill.yaml", ".runtime/state", "clients/codex/generated/state.json"],
)
def test_local_only_tracked_fails(repository: Path, name: str) -> None:
    path = repository / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("local", encoding="utf-8")
    subprocess.run(["git", "-C", repository, "add", "-f", name], check=True)
    assert not validate_git_hygiene(repository).ok


def test_secret_tracked_fails(repository: Path) -> None:
    (repository / "credentials.token").write_text("not-a-real-secret", encoding="utf-8")
    subprocess.run(["git", "-C", repository, "add", "-f", "credentials.token"], check=True)
    assert not validate_git_hygiene(repository).ok


@pytest.mark.parametrize("name", ["mcp-creds.env", "mcp-creds.work.env"])
def test_git_hygiene_rejects_tracked_mcp_credentials(repository: Path, name: str) -> None:
    path = repository / name
    path.write_text("TOKEN=fixture-value\n", encoding="utf-8")
    subprocess.run(["git", "-C", repository, "add", "-f", name], check=True)
    result = validate_git_hygiene(repository)
    assert any(f"Потенциальный secret tracked/staged: {name}" in diagnostic.message for diagnostic in result.diagnostics)


def test_git_hygiene_rejects_deleted_staged_mcp_credentials(repository: Path) -> None:
    path = repository / "mcp-creds.env"
    path.write_text("TOKEN=fixture-value\n", encoding="utf-8")
    subprocess.run(["git", "-C", repository, "add", "-f", path.name], check=True)
    path.unlink()

    result = validate_git_hygiene(repository)
    assert not result.ok
    assert any("Потенциальный secret tracked/staged: mcp-creds.env" in diagnostic.message for diagnostic in result.diagnostics)


def test_git_hygiene_accepts_mcp_credential_example(repository: Path) -> None:
    path = repository / "mcp-creds.example.env"
    path.write_text("TOKEN=\n", encoding="utf-8")
    subprocess.run(["git", "-C", repository, "add", "mcp-creds.example.env"], check=True)
    assert validate_git_hygiene(repository).ok
    assert subprocess.run(["git", "-C", repository, "check-ignore", "-q", "mcp-creds.example.env"]).returncode == 1


def test_clean_repository_passes(repository: Path) -> None:
    assert validate_git_hygiene(repository).ok


@pytest.mark.parametrize("name", ["nested/mcp-creds.env", "nested/deep/mcp-creds.work.env"])
@pytest.mark.parametrize("state", ["tracked", "staged", "staged-deleted"])
def test_nested_credentials_are_rejected_in_index(repository, name, state):
    path = repository / name
    path.parent.mkdir(parents=True)
    path.write_text("TOKEN=fixture\n")
    subprocess.run(["git", "-C", repository, "add", "-f", name], check=True)
    if state == "tracked":
        subprocess.run(["git", "-C", repository, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture"], check=True)
    elif state == "staged-deleted":
        path.unlink()
    result = validate_git_hygiene(repository)
    assert any(f"Потенциальный secret tracked/staged: {name}" in row.message for row in result.diagnostics)


def test_nested_credential_example_is_allowed(repository):
    path = repository / "nested/mcp-creds.example.env"
    path.parent.mkdir()
    path.write_text("TOKEN=\n")
    subprocess.run(["git", "-C", repository, "add", str(path)], check=True)
    assert validate_git_hygiene(repository).ok
