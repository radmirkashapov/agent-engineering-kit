#!/usr/bin/env sh
set -eu

REPOSITORY=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if ! GIT_ROOT=$(git -C "$REPOSITORY" rev-parse --show-toplevel 2>/dev/null); then
    printf '%s\n' "ERROR: bootstrap/install.sh необходимо запускать из полного Git checkout, а не из ZIP-архива." >&2
    exit 1
fi
GIT_ROOT=$(CDPATH= cd -- "$GIT_ROOT" && pwd)
if [ "$GIT_ROOT" != "$REPOSITORY" ]; then
    printf '%s\n' "ERROR: bootstrap/install.sh необходимо запускать из полного Git checkout, а не из ZIP-архива." >&2
    exit 1
fi
python3 -m pip install --user "$REPOSITORY"

# CLI использует полный checkout как канонический источник manifests и документации.
if [ -n "${AGENT_KIT_DATA_HOME:-}" ]; then
    DATA_HOME=$AGENT_KIT_DATA_HOME
elif [ -n "${XDG_DATA_HOME:-}" ]; then
    DATA_HOME=$XDG_DATA_HOME/agent-engineering-kit
else
    DATA_HOME=$HOME/.local/share/agent-engineering-kit
fi
STATE_DIR=$DATA_HOME/state
POINTER=$STATE_DIR/repository-path
POINTER_TMP=$STATE_DIR/repository-path.tmp.$$
mkdir -p "$STATE_DIR"
printf '%s\n' "$REPOSITORY" > "$POINTER_TMP"
mv "$POINTER_TMP" "$POINTER"

# Заполненные env-файлы локальны и игнорируются Git. Импортируем их сразу,
# чтобы первая синхронизация использовала тот же private vault, что и CLI.
if [ -f "$REPOSITORY/mcp-creds.env" ]; then
    python3 -m agent_engineering_kit.cli mcp creds import --from "$REPOSITORY/mcp-creds.env"
fi
if [ -f "$REPOSITORY/model-creds.env" ]; then
    python3 -m agent_engineering_kit.cli models creds import --from "$REPOSITORY/model-creds.env"
fi
python3 -m agent_engineering_kit.cli models sync

printf '%s\n' "agent-kit установлен. Канонический repository: $REPOSITORY"
printf '%s\n' "Не перемещайте checkout без повторного запуска bootstrap/install.sh."
printf '%s\n' "Запустите: agent-kit resync --no-update && agent-kit validate --ci && agent-kit doctor"
