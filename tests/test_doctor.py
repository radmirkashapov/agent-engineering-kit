from __future__ import annotations

from pathlib import Path

import pytest

from agent_engineering_kit.doctor import doctor
from agent_engineering_kit.mcp_credentials import McpCredentialStore
from agent_engineering_kit.mcp_manager import McpManager
from agent_engineering_kit.paths import KitPaths


REPOSITORY = Path(__file__).resolve().parents[1]


@pytest.fixture
def doctor_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    paths = KitPaths(
        REPOSITORY,
        tmp_path / "data",
        tmp_path / "data" / "runtime",
        tmp_path / "data" / "projects",
        tmp_path / "data" / "overrides",
    )
    server = {
        "id": "sentry",
        "transport": "stdio",
        "required_environment": ["SENTRY_ACCESS_TOKEN"],
        "environment": {
            "SENTRY_ACCESS_TOKEN": "env:SENTRY_ACCESS_TOKEN",
            "SENTRY_HOST": "env:SENTRY_HOST",
        },
    }
    monkeypatch.delenv("SENTRY_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("SENTRY_HOST", raising=False)
    monkeypatch.setattr(McpManager, "desired", lambda self, project=None, access_profile="readonly": [(server, object())])
    monkeypatch.setattr(McpManager, "is_enabled", lambda self, item, project=None: True)
    monkeypatch.setattr(
        McpManager,
        "list",
        lambda self, project=None, access_profile="readonly": [
            {"id": "sentry", "status": "READY", "available": True, "access_reason": "allowed"}
        ],
    )
    return paths, server


def test_doctor_reports_missing_required_name_only(doctor_context) -> None:
    paths, _server = doctor_context

    result = doctor(REPOSITORY, paths)
    messages = "\n".join(item.message for item in result.diagnostics)

    assert "SENTRY_ACCESS_TOKEN" in messages
    assert "sentry: отсутствует обязательная переменная окружения SENTRY_ACCESS_TOKEN" in messages


def test_doctor_accepts_credential_from_vault(doctor_context, tmp_path: Path) -> None:
    paths, server = doctor_context
    source = tmp_path / "credentials.env"
    source.write_text("SENTRY_ACCESS_TOKEN=fixture-secret\n", encoding="utf-8")
    McpCredentialStore(paths).import_file(source, [server])

    result = doctor(REPOSITORY, paths)

    assert not any("SENTRY_ACCESS_TOKEN" in item.message for item in result.diagnostics)
    assert "fixture-secret" not in "\n".join(item.message for item in result.diagnostics)


def test_doctor_accepts_nonempty_environment_value(doctor_context, monkeypatch: pytest.MonkeyPatch) -> None:
    paths, _server = doctor_context
    monkeypatch.setenv("SENTRY_ACCESS_TOKEN", "fixture-secret")

    result = doctor(REPOSITORY, paths)

    assert not any("SENTRY_ACCESS_TOKEN" in item.message for item in result.diagnostics)
    assert "fixture-secret" not in "\n".join(item.message for item in result.diagnostics)


def test_doctor_does_not_require_optional_stdio_environment(doctor_context, monkeypatch: pytest.MonkeyPatch) -> None:
    paths, _server = doctor_context
    optional_server = {
        "id": "sentry",
        "transport": "stdio",
        "required_environment": [],
        "environment": {"OPTIONAL_API_KEY": "env:OPTIONAL_API_KEY"},
    }
    monkeypatch.setattr(
        McpManager,
        "desired",
        lambda self, project=None, access_profile="readonly": [(optional_server, object())],
    )

    result = doctor(REPOSITORY, paths)

    assert not any("OPTIONAL_API_KEY" in item.message for item in result.diagnostics)


def test_doctor_ignores_optional_and_remote_oauth_variables(doctor_context, monkeypatch: pytest.MonkeyPatch) -> None:
    paths, _server = doctor_context
    monkeypatch.setattr(
        McpManager,
        "desired",
        lambda self, project=None, access_profile="readonly": [
            (
                {
                    "id": "oauth-server",
                    "transport": "http",
                    "auth": {"method": "oauth"},
                    "required_environment": ["OAUTH_ACCESS_TOKEN"],
                    "environment": {"OPTIONAL_API_KEY": "env:OPTIONAL_API_KEY"},
                },
                object(),
            )
        ],
    )
    monkeypatch.setattr(
        McpManager,
        "list",
        lambda self, project=None, access_profile="readonly": [
            {"id": "oauth-server", "status": "READY", "available": True, "access_reason": "allowed"}
        ],
    )

    result = doctor(REPOSITORY, paths)
    messages = "\n".join(item.message for item in result.diagnostics)

    assert "OAUTH_ACCESS_TOKEN" not in messages
    assert "OPTIONAL_API_KEY" not in messages
