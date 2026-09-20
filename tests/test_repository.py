from __future__ import annotations

from pathlib import Path
import stat

from agent_engineering_kit.paths import KitPaths
from agent_engineering_kit.validation import validate


def test_repository_passes_ci_validation(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    paths = KitPaths(repository, data, data / "runtime", data / "projects", data / "overrides")
    gitleaks = paths.installations / "security/gitleaks/bin/gitleaks"
    gitleaks.parent.mkdir(parents=True)
    gitleaks.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    gitleaks.chmod(gitleaks.stat().st_mode | stat.S_IXUSR)
    result = validate(repository, paths, include_local=False)
    assert result.ok, "\n".join(item.render() for item in result.diagnostics)
