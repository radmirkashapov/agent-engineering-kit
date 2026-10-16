"""Кроссплатформенный launcher isolated pre-commit hooks."""

from __future__ import annotations

import sys
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "src"))


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "tests":
        import pytest

        return pytest.main(["-q"])

    from agent_engineering_kit.cli import run

    return run(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
