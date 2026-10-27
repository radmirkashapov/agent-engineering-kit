# Установка на macOS и Linux

Устанавливайте Kit из полного Git checkout. ZIP-архив не содержит Git metadata, нужных для обновления и проверки ревизии.

## Установка

```bash
git clone <repository-url> agent-engineering-kit
cd agent-engineering-kit
./bootstrap/install.sh
agent-kit resync --no-update
agent-kit validate --ci
agent-kit doctor
```

Bootstrap устанавливает Python CLI и записывает абсолютный путь checkout в <data>/state/repository-path. Каталог данных по умолчанию — $XDG_DATA_HOME/agent-engineering-kit либо ~/.local/share/agent-engineering-kit. AGENT_KIT_DATA_HOME задаёт другой data home, а AGENT_KIT_REPOSITORY временно указывает иной checkout и имеет приоритет над сохранённым путём.

Для разработки самого Kit создайте виртуальное окружение:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
```

## Corporate fork в GitLab

Создайте корпоративную копию исходного GitHub-репозитория в GitLab и ведите корпоративные правила как проверенные изменения через PR/MR. Для установки клонируйте именно внутренний URL:

```bash
git clone <gitlab-corporate-url> agent-engineering-kit
cd agent-engineering-kit
./bootstrap/install.sh
agent-kit resync --no-update
agent-kit validate --ci
agent-kit doctor
```

Bootstrap использует manifests из checkout, откуда запущен. Чтобы сменить рабочую копию, клонируйте новую и запустите bootstrap из неё; старую не удаляйте до успешных validate --ci и doctor. Для временного испытания задайте AGENT_KIT_REPOSITORY, затем снимите переменную.

Обновления исходного GitHub в корпоративный fork проводите отдельным PR/MR: проверьте remote и diff, интегрируйте в корпоративную основную ветку, запустите CI и повторно запустите bootstrap на машине, если сменился checkout. Полная последовательность описана в [корпоративном runbook](https://github.com/radmirkashapov/agent-engineering-kit/blob/main/docs/runbooks/install-from-gitlab-fork.md).

## Первый запуск

```bash
agent-kit resync --no-update
agent-kit validate --ci
agent-kit doctor
agent-kit help
```

resync приводит локальные установки, MCP и адаптеры к желаемому состоянию. После переключения checkout перезапустите долгоживущие клиенты. Дополнительно: [быстрый старт](Quick-start) и раздел [установки в README](https://github.com/radmirkashapov/agent-engineering-kit/blob/main/README.md#установка).
