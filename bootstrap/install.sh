#!/usr/bin/env sh
set -eu

REPOSITORY=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
python3 -m pip install --user "$REPOSITORY"
printf '%s\n' "agent-kit установлен. Запустите: agent-kit doctor"
