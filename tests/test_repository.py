from __future__ import annotations

from pathlib import Path

from agent_engineering_kit.paths import KitPaths
from agent_engineering_kit.validation import validate


def test_repository_passes_ci_validation(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    result = validate(repository, paths, include_local=False)
    assert result.ok, "\n".join(item.render() for item in result.diagnostics)
