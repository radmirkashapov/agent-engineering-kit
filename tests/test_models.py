from __future__ import annotations

from pathlib import Path

import pytest

from agent_engineering_kit.io import load_yaml
from agent_engineering_kit.models import load_policy, validate_models
from conftest import make_model_repository, model, write_yaml


@pytest.fixture
def real_repository() -> Path:
    return Path(__file__).resolve().parents[1]


def write_agent(repository: Path, model_id: str) -> None:
    (repository / "agents/reviewer.md").write_text(
        f"---\nmodel:\n  preferred: {model_id}\n---\n# Reviewer\n", encoding="utf-8"
    )


def test_corporate_non_empty_and_committed_allowed_model_passes(tmp_path: Path, real_repository: Path) -> None:
    repository = make_model_repository(tmp_path, real_repository, [model("corp-model")])
    write_agent(repository, "corp-model")
    assert validate_models(repository).ok


def test_corporate_non_empty_rejects_committed_user_only_model(tmp_path: Path, real_repository: Path) -> None:
    repository = make_model_repository(
        tmp_path, real_repository, [model("corp-model")], [model("local-model", "ollama")]
    )
    write_agent(repository, "local-model")
    result = validate_models(repository)
    assert not result.ok
    assert "local-model" in "\n".join(item.message for item in result.diagnostics)


def test_corporate_empty_uses_local_model_at_runtime(tmp_path: Path, real_repository: Path) -> None:
    repository = make_model_repository(tmp_path, real_repository, [], [model("local-model", "ollama")])
    write_agent(repository, "local-model")
    assert validate_models(repository, include_local=True).ok
    assert load_policy(repository).runtime_allowed_ids == {"local-model"}


def test_disabled_corporate_catalog_does_not_restrict_runtime_models(
    tmp_path: Path,
    real_repository: Path,
) -> None:
    repository = make_model_repository(tmp_path, real_repository, [model("documented-default")])
    corporate_path = repository / "models/corporate.yaml"
    corporate = load_yaml(corporate_path)
    corporate["enabled"] = False
    write_yaml(corporate_path, corporate)
    write_agent(repository, "documented-default")

    result = validate_models(repository, include_local=False)
    policy = load_policy(repository, include_local=False)

    assert result.ok, "\n".join(item.render() for item in result.diagnostics)
    assert policy.corporate_active is False
    assert policy.committed_allowed_ids == set()


def test_local_models_extend_non_empty_runtime_policy(tmp_path: Path, real_repository: Path) -> None:
    repository = make_model_repository(
        tmp_path, real_repository, [model("corp-model")], [model("local-model", "ollama")]
    )

    assert load_policy(repository).runtime_allowed_ids == {"corp-model", "local-model"}


def test_unknown_model_fails(tmp_path: Path, real_repository: Path) -> None:
    repository = make_model_repository(tmp_path, real_repository, [model("corp-model")])
    write_agent(repository, "missing-model")
    assert not validate_models(repository).ok


def test_duplicate_model_id_fails(tmp_path: Path, real_repository: Path) -> None:
    repository = make_model_repository(tmp_path, real_repository, [model("duplicate"), model("duplicate")])
    result = validate_models(repository)
    assert not result.ok
    assert any("Повторяющийся" in item.message for item in result.diagnostics)


def test_unknown_provider_fails(tmp_path: Path, real_repository: Path) -> None:
    repository = make_model_repository(tmp_path, real_repository, [model("mystery", "unknown")])
    assert not validate_models(repository).ok
