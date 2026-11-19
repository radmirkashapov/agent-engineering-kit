from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_engineering_kit.client_models import sync_client_models
from agent_engineering_kit.io import load_yaml
from agent_engineering_kit.model_credentials import ModelCredentialStore
from agent_engineering_kit.paths import KitPaths
from conftest import make_model_repository, model, write_yaml


@pytest.fixture
def real_repository() -> Path:
    return Path(__file__).resolve().parents[1]


def make_paths(tmp_path: Path, repository: Path) -> KitPaths:
    data = tmp_path / "data"
    return KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")


def declare_compatible_provider(repository: Path) -> None:
    document = {
        "version": 1,
        "enabled": True,
        "providers": [{
            "id": "company-ai",
            "name": "Company AI",
            "description": "OpenAI-compatible gateway.",
            "base_url": "https://ai.example.test/v1",
            "api_key_env": "COMPANY_AI_API_KEY",
            "wire_api": "responses",
        }],
        "models": [{
            **model("company-coder", "company-ai"),
            "name": "Company Coder",
            "description": "Coding model.",
            "model_id": "company-coder-v1",
        }],
    }
    write_yaml(repository / "models/corporate.yaml", document)


def test_sync_creates_codex_provider_without_secret_value(tmp_path: Path, real_repository: Path) -> None:
    repository = make_model_repository(tmp_path, real_repository, [])
    declare_compatible_provider(repository)
    paths = make_paths(tmp_path, repository)
    home = tmp_path / "home"

    report = sync_client_models(repository, paths, home=home, clients=("codex",))

    config = (home / ".codex/config.toml").read_text(encoding="utf-8")
    assert report["codex"]["status"] == "SYNCED"
    assert 'base_url = "https://ai.example.test/v1"' in config
    assert 'env_key = "COMPANY_AI_API_KEY"' in config
    assert "COMPANY_AI_API_KEY=" not in config


def test_sync_uses_private_model_credential_for_codex_and_opencode(tmp_path: Path, real_repository: Path) -> None:
    repository = make_model_repository(tmp_path, real_repository, [])
    declare_compatible_provider(repository)
    paths = make_paths(tmp_path, repository)
    source = tmp_path / "model-creds.env"
    source.write_text("COMPANY_AI_API_KEY=super-secret\n", encoding="utf-8")
    ModelCredentialStore(paths).import_file(source, [{"id": "company-ai", "api_key_env": "COMPANY_AI_API_KEY"}])

    sync_client_models(repository, paths, home=tmp_path / "home", clients=("codex", "opencode"))

    codex = (tmp_path / "home/.codex/config.toml").read_text(encoding="utf-8")
    opencode = json.loads((tmp_path / "home/.config/opencode/opencode.json").read_text(encoding="utf-8"))
    assert 'command = "agent-kit"' in codex
    assert "super-secret" not in codex
    assert opencode["providers"]["company-ai"]["settings"]["apiKey"].startswith("{file:")
    assert "super-secret" not in json.dumps(opencode)


def test_sync_keeps_existing_codex_env_key_unchanged(tmp_path: Path, real_repository: Path) -> None:
    repository = make_model_repository(tmp_path, real_repository, [])
    declare_compatible_provider(repository)
    paths = make_paths(tmp_path, repository)
    home = tmp_path / "home"
    config_path = home / ".codex/config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        '# agent-kit:model-provider:company-ai:start\n'
        '[model_providers.company-ai]\n'
        'name = "Old name"\n'
        'base_url = "https://old.example.test/v1"\n'
        'env_key = "USER_SELECTED_KEY"\n'
        'wire_api = "chat"\n'
        '# agent-kit:model-provider:company-ai:end\n',
        encoding="utf-8",
    )

    sync_client_models(repository, paths, home=home, clients=("codex",))

    result = config_path.read_text(encoding="utf-8")
    assert 'env_key = "USER_SELECTED_KEY"' in result
    assert 'base_url = "https://ai.example.test/v1"' in result


def test_sync_keeps_single_quoted_codex_env_key_unchanged(tmp_path: Path, real_repository: Path) -> None:
    repository = make_model_repository(tmp_path, real_repository, [])
    declare_compatible_provider(repository)
    paths = make_paths(tmp_path, repository)
    home = tmp_path / "home"
    config_path = home / ".codex/config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        '# agent-kit:model-provider:company-ai:start\n'
        '[model_providers.company-ai]\n'
        "env_key = 'USER_SELECTED_KEY'\n"
        '# agent-kit:model-provider:company-ai:end\n',
        encoding="utf-8",
    )

    sync_client_models(repository, paths, home=home, clients=("codex",))

    assert 'env_key = "USER_SELECTED_KEY"' in config_path.read_text(encoding="utf-8")


def test_sync_rejects_unmanaged_codex_provider_collision(tmp_path: Path, real_repository: Path) -> None:
    repository = make_model_repository(tmp_path, real_repository, [])
    declare_compatible_provider(repository)
    paths = make_paths(tmp_path, repository)
    home = tmp_path / "home"
    config_path = home / ".codex/config.toml"
    config_path.parent.mkdir(parents=True)
    original = '[model_providers.company-ai]\nenv_key = "USER_KEY"\n'
    config_path.write_text(original, encoding="utf-8")

    with pytest.raises(Exception, match="ownership"):
        sync_client_models(repository, paths, home=home, clients=("codex",))

    assert config_path.read_text(encoding="utf-8") == original


def test_sync_rejects_codex_provider_when_owned_marker_was_removed(tmp_path: Path, real_repository: Path) -> None:
    repository = make_model_repository(tmp_path, real_repository, [])
    declare_compatible_provider(repository)
    paths = make_paths(tmp_path, repository)
    home = tmp_path / "home"
    config_path = home / ".codex/config.toml"
    config_path.parent.mkdir(parents=True)
    original = '[model_providers.company-ai]\nenv_key = "USER_KEY"\n'
    config_path.write_text(original, encoding="utf-8")
    paths.state.mkdir(parents=True)
    (paths.state / "client-models.json").write_text(
        json.dumps({"version": 1, "codex": ["company-ai"], "opencode": []}), encoding="utf-8",
    )

    with pytest.raises(Exception, match="ownership"):
        sync_client_models(repository, paths, home=home, clients=("codex",))

    assert config_path.read_text(encoding="utf-8") == original


def test_sync_does_not_open_or_change_existing_opencode_credentials(tmp_path: Path, real_repository: Path) -> None:
    repository = make_model_repository(tmp_path, real_repository, [])
    declare_compatible_provider(repository)
    paths = make_paths(tmp_path, repository)
    home = tmp_path / "home"
    config_path = home / ".config/opencode/opencode.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(json.dumps({"providers": {"company-ai": {
        "_agent_kit_managed": True,
        "env": ["USER_SELECTED_KEY"],
        "settings": {"apiKey": "{env:USER_SELECTED_KEY}"},
        "models": {"obsolete": {}},
    }}}), encoding="utf-8")

    report = sync_client_models(repository, paths, home=home, clients=("opencode",))

    assert report["opencode"]["status"] == "SYNCED"
    provider = json.loads(config_path.read_text(encoding="utf-8"))["providers"]["company-ai"]
    assert provider["env"] == ["USER_SELECTED_KEY"]
    assert provider["settings"]["apiKey"] == "{env:USER_SELECTED_KEY}"
    assert provider["settings"]["baseURL"] == "https://ai.example.test/v1"


def test_second_opencode_sync_leaves_agent_created_config_untouched(tmp_path: Path, real_repository: Path) -> None:
    repository = make_model_repository(tmp_path, real_repository, [])
    declare_compatible_provider(repository)
    paths = make_paths(tmp_path, repository)
    home = tmp_path / "home"

    sync_client_models(repository, paths, home=home, clients=("opencode",))
    config_path = home / ".config/opencode/opencode.json"
    original = config_path.read_text(encoding="utf-8")
    second = sync_client_models(repository, paths, home=home, clients=("opencode",))

    assert second["opencode"]["status"] == "SYNCED"
    assert config_path.read_text(encoding="utf-8") == original


def test_sync_leaves_opencode_jsonc_untouched(tmp_path: Path, real_repository: Path) -> None:
    repository = make_model_repository(tmp_path, real_repository, [])
    declare_compatible_provider(repository)
    paths = make_paths(tmp_path, repository)
    home = tmp_path / "home"
    config_path = home / ".config/opencode/opencode.jsonc"
    config_path.parent.mkdir(parents=True)
    original = '{\n  // user-owned configuration\n  "providers": {}\n}\n'
    config_path.write_text(original, encoding="utf-8")

    report = sync_client_models(repository, paths, home=home, clients=("opencode",))

    assert report["opencode"]["status"] == "SYNCED"
    document = json.loads(config_path.read_text(encoding="utf-8"))
    assert document["providers"]["company-ai"]["settings"]["baseURL"] == "https://ai.example.test/v1"
    assert not (home / ".config/opencode/opencode.json").exists()


def test_sync_rejects_invalid_local_model_catalog_before_client_write(tmp_path: Path, real_repository: Path) -> None:
    repository = make_model_repository(tmp_path, real_repository, [])
    paths = make_paths(tmp_path, repository)
    paths.overrides.mkdir(parents=True)
    write_yaml(paths.overrides / "models.yaml", {
        "version": 1,
        "providers": [{"id": "company-ai", "base_url": "invalid"}],
        "models": [model("company-coder", "company-ai")],
    })

    with pytest.raises(Exception, match="Некорректный local model catalog"):
        sync_client_models(repository, paths, home=tmp_path / "home", clients=("codex",))


def test_sync_registers_corporate_catalog_in_cline_and_preserves_user_key(tmp_path: Path, real_repository: Path) -> None:
    repository = make_model_repository(tmp_path, real_repository, [])
    declare_compatible_provider(repository)
    paths = make_paths(tmp_path, repository)
    home = tmp_path / "home"
    providers_path = home / ".cline/data/settings/providers.json"
    providers_path.parent.mkdir(parents=True)
    providers_path.write_text(json.dumps({
        "version": 1,
        "modes": {},
        "providers": {
            "company-ai": {
                "settings": {"provider": "company-ai", "apiKey": "USER_SELECTED_KEY", "model": "company-coder-v1"},
                "updatedAt": "2026-01-01T00:00:00Z",
                "tokenSource": "manual",
            },
            "personal": {
                "settings": {"provider": "personal", "apiKey": "keep-me"},
                "updatedAt": "2026-01-01T00:00:00Z",
                "tokenSource": "manual",
            },
        },
    }), encoding="utf-8")

    report = sync_client_models(repository, paths, home=home, clients=("cline",))

    providers = json.loads(providers_path.read_text(encoding="utf-8"))
    catalog = json.loads((home / ".cline/data/settings/models.json").read_text(encoding="utf-8"))
    assert report["cline"]["status"] == "SYNCED"
    assert providers["providers"]["company-ai"]["settings"] == {
        "provider": "company-ai",
        "apiKey": "USER_SELECTED_KEY",
        "baseUrl": "https://ai.example.test/v1",
        "protocol": "openai-responses",
        "client": "openai-compatible",
        "model": "company-coder-v1",
    }
    assert providers["providers"]["personal"]["settings"]["apiKey"] == "keep-me"
    assert catalog["providers"]["company-ai"]["provider"]["name"] == "Company AI"
    assert catalog["providers"]["company-ai"]["models"]["company-coder-v1"]["name"] == "Company Coder"


def test_sync_imports_model_credential_into_empty_cline_provider_and_honors_path_overrides(
    tmp_path: Path, real_repository: Path,
) -> None:
    repository = make_model_repository(tmp_path, real_repository, [])
    declare_compatible_provider(repository)
    paths = make_paths(tmp_path, repository)
    source = tmp_path / "model-creds.env"
    source.write_text("COMPANY_AI_API_KEY=super-secret\n", encoding="utf-8")
    ModelCredentialStore(paths).import_file(source, [{"id": "company-ai", "api_key_env": "COMPANY_AI_API_KEY"}])
    providers_path = tmp_path / "custom" / "providers.json"

    sync_client_models(
        repository, paths, home=tmp_path / "home", clients=("cline",),
        environment={"CLINE_PROVIDER_SETTINGS_PATH": str(providers_path)},
    )

    providers = json.loads(providers_path.read_text(encoding="utf-8"))
    assert providers["providers"]["company-ai"]["settings"]["apiKey"] == "super-secret"
    catalog = json.loads((providers_path.parent / "models.json").read_text(encoding="utf-8"))
    assert set(catalog["providers"]["company-ai"]["models"]) == {"company-coder-v1"}


def test_cline_catalog_replaces_models_when_corporate_catalog_changes(tmp_path: Path, real_repository: Path) -> None:
    repository = make_model_repository(tmp_path, real_repository, [])
    declare_compatible_provider(repository)
    paths = make_paths(tmp_path, repository)
    home = tmp_path / "home"
    sync_client_models(repository, paths, home=home, clients=("cline",))

    document = load_yaml(repository / "models/corporate.yaml")
    document["models"] = [{
        **model("company-reviewer", "company-ai"),
        "name": "Company Reviewer",
        "model_id": "company-reviewer-v2",
    }]
    write_yaml(repository / "models/corporate.yaml", document)
    sync_client_models(repository, paths, home=home, clients=("cline",))

    catalog = json.loads((home / ".cline/data/settings/models.json").read_text(encoding="utf-8"))
    provider = catalog["providers"]["company-ai"]
    assert set(provider["models"]) == {"company-reviewer-v2"}
    settings = json.loads((home / ".cline/data/settings/providers.json").read_text(encoding="utf-8"))
    assert settings["providers"]["company-ai"]["settings"]["model"] == "company-reviewer-v2"


def test_sync_reports_non_managed_clients_without_creating_configs(tmp_path: Path, real_repository: Path) -> None:
    repository = make_model_repository(tmp_path, real_repository, [])
    declare_compatible_provider(repository)
    paths = make_paths(tmp_path, repository)
    home = tmp_path / "home"

    report = sync_client_models(repository, paths, home=home, clients=("claude-code", "claude-desktop"))

    assert report["claude-code"]["status"] == "MANUAL"
    assert report["claude-desktop"]["status"] == "UNSUPPORTED"
    assert not home.exists()
