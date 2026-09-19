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


@pytest.mark.parametrize("name", ["models/user.local.yaml", "overrides/local/skill.yaml", ".runtime/state"])
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


def test_clean_repository_passes(repository: Path) -> None:
    assert validate_git_hygiene(repository).ok
