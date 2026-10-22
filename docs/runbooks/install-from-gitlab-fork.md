# Установка Agent Engineering Kit из корпоративного GitLab

Эта инструкция описывает схему, в которой исходный проект развивается на GitHub, а команда работает со своей копией в GitLab. В локальном клоне используются два удалённых репозитория:

- `origin` — корпоративный GitLab, куда команда отправляет ветки и где создаёт Merge Request;
- `upstream` — исходный GitHub, откуда периодически забираются обновления.

Прямые push в `main` запрещены. Изменения команды и синхронизация с GitHub проходят через отдельную ветку и Merge Request в GitLab.

## 1. Создание копии в GitLab

Если GitLab поддерживает импорт проектов, создайте новый проект через **New project → Import project → Repository by URL** и укажите:

```text
https://github.com/radmirkashapov/agent-engineering-kit.git
```

Если импорт через интерфейс недоступен, выполните однократное копирование веток и тегов в заранее созданный пустой проект GitLab:

```bash
git clone https://github.com/radmirkashapov/agent-engineering-kit.git
cd agent-engineering-kit
git remote rename origin upstream
git remote add origin git@gitlab.company.example:ai/agent-engineering-kit.git
git push -u origin --all
git push origin --tags
```

Замените адрес GitLab на адрес проекта вашей команды. После первичного копирования `origin` должен указывать на GitLab, а `upstream` — на GitHub.

## 2. Установка на другом компьютере

Требуются Git и Python 3.10 или новее. Клонируйте корпоративную копию и добавьте исходный GitHub как `upstream`:

```bash
git clone git@gitlab.company.example:ai/agent-engineering-kit.git
cd agent-engineering-kit
git remote add upstream https://github.com/radmirkashapov/agent-engineering-kit.git
git fetch --all --prune
git remote -v
```

Не устанавливайте Kit из ZIP-архива: для проверки Git hygiene, определения версии и получения обновлений нужен полный checkout. Один и тот же `bootstrap/install.sh` используется для исходной и корпоративной версии. Он устанавливает CLI и регистрирует именно текущий checkout в `<data>/state/repository-path`, поэтому отдельный корпоративный установщик не требуется.

Установите Kit:

```bash
./bootstrap/install.sh
agent-kit resync --no-update
agent-kit validate --ci
agent-kit doctor
```

Sentry по умолчанию выключен и не мешает установке. Если интеграция нужна, включите её локально и получите `SENTRY_ACCESS_TOKEN` из корпоративного хранилища секретов:

```bash
agent-kit mcp enable sentry
export SENTRY_ACCESS_TOKEN
# Для self-hosted Sentry задайте hostname без протокола и пути:
export SENTRY_HOST=sentry.company.example
agent-kit resync --no-update
```

Не сохраняйте token в Git или shell profile.

Если checkout перенесён в другой каталог, сменился корпоративный fork или pointer остался от прежней установки, повторный запуск bootstrap безопасно обновит `<data>/state/repository-path`.

Для постоянного переключения на новый checkout выполните bootstrap из нового каталога, затем запустите `agent-kit resync --no-update`, `agent-kit validate --ci` и `agent-kit doctor`. По умолчанию на Unix текущий указатель можно проверить командой `cat ~/.local/share/agent-engineering-kit/state/repository-path`; на Windows файл находится в `%LOCALAPPDATA%\agent-engineering-kit\state\repository-path`. `AGENT_KIT_DATA_HOME` меняет каталог данных на любой платформе, а `XDG_DATA_HOME` — в Unix. Не удаляйте прежний checkout до успешной проверки нового. После переключения перезапустите долго работающие AI-клиенты и агентные процессы.

Для временной проверки можно задать `AGENT_KIT_REPOSITORY` абсолютным путём к другой рабочей копии. Эта переменная имеет приоритет над сохранённым указателем; удалите её после проверки. При обычном переключении ветки в том же checkout указатель остаётся корректным, но bootstrap нужно повторить, чтобы переустановленный Python-пакет соответствовал выбранной ревизии.

Установщик размещает Python-пакет в пользовательском окружении. Если shell не находит `agent-kit`, добавьте каталог пользовательских исполняемых файлов Python в `PATH` и откройте новый терминал:

```bash
printf '\nexport PATH="$(python3 -m site --user-base)/bin:$PATH"\n' >> ~/.zshrc
export PATH="$(python3 -m site --user-base)/bin:$PATH"
agent-kit doctor
```

Для Bash используйте `~/.bashrc` вместо `~/.zshrc`. На Windows запустите `bootstrap\install.ps1` из PowerShell.

## 3. Корпоративная конфигурация

В оригинальном репозитории `models/corporate.yaml` поставляется с `enabled: false`, поэтому работает без корпоративного allowlist. В корпоративной ветке включите политику и замените пример собственными разрешёнными моделями:

```yaml
version: 1
enabled: true
providers:
  - id: company-provider
models:
  - id: company-coding-model
    provider: company-provider
    capabilities:
      reasoning: true
      coding: true
      tool_use: true
```

Корпоративные MCP описывайте в `catalog/corporate/mcp.yaml`, а секреты оставляйте ссылками `env:VARIABLE`. Изменения схем, allowlist, MCP, ролей и правил проходят через обычный Merge Request в GitLab. Локальные пользовательские overrides хранятся вне репозитория и не являются способом распространения корпоративной конфигурации.

## 4. Обычная работа команды

Перед началом задачи обновите локальный `main`, затем создайте рабочую ветку:

```bash
git switch main
git pull --ff-only origin main
git switch -c feat/20-10-2026-short-description
```

Допустимые префиксы: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `ci`, `style`. Дата задаётся в формате `dd-MM-yyyy`. Коммиты оформляются как `<type>(<scope>): <description>`, например:

```bash
git commit -m "feat(mcp): add corporate server profile"
git push -u origin feat/20-10-2026-short-description
```

После push создайте Merge Request в `main` корпоративного GitLab. Перед слиянием выполните тесты и проверку конфигурации:

```bash
python3 -m pytest -q
agent-kit validate --ci
```

## 5. Получение изменений из исходного GitHub

Синхронизацию выполняйте в отдельной ветке. Это позволяет проверить изменения и разрешить конфликты до обновления корпоративного `main`:

```bash
git fetch upstream --prune
git switch main
git pull --ff-only origin main
git switch -c chore/20-10-2026-sync-upstream
git merge upstream/main
python3 -m pytest -q
agent-kit validate --ci
git push -u origin chore/20-10-2026-sync-upstream
```

После этого создайте Merge Request из `chore/20-10-2026-sync-upstream` в `main` GitLab. Если ветка с таким именем уже существует, добавьте короткий уникальный суффикс. Не отправляйте изменения напрямую в GitHub и не сливайте `upstream/main` непосредственно в корпоративный `main` без проверки через Merge Request.

Конфликты корпоративных файлов разрешайте в пользу осознанной корпоративной настройки, затем вручную переносите совместимые изменения upstream. Особенно внимательно проверяйте `models/corporate.yaml`, `catalog/corporate/`, lock-файлы, схемы и bootstrap. Слияние должно завершаться полным тестовым прогоном и `agent-kit validate --ci`.

## 6. Обновление установленного Kit

После слияния изменений в GitLab обновите локальный клон и повторите установку:

```bash
git switch main
git pull --ff-only origin main
./bootstrap/install.sh
agent-kit resync --no-update
agent-kit validate --ci
agent-kit doctor
```

`resync --no-update` применяет текущую версию репозитория, не пытаясь самостоятельно менять Git-состояние. Локальные настройки, память проектов, секреты и состояние MCP хранятся вне репозитория. Секреты передавайте через переменные окружения; в Git допускается только перечень переменных без значений в `.env.example`.

## 7. Быстрая проверка схемы remote

Ожидаемый результат:

```text
origin    git@gitlab.company.example:ai/agent-engineering-kit.git (fetch)
origin    git@gitlab.company.example:ai/agent-engineering-kit.git (push)
upstream  https://github.com/radmirkashapov/agent-engineering-kit.git (fetch)
upstream  https://github.com/radmirkashapov/agent-engineering-kit.git (push)
```

Команда работает только с `origin`. `upstream` используется как источник чтения для периодической синхронизации.
