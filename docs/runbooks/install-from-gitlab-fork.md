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

Установите Kit:

```bash
./bootstrap/install.sh
agent-kit doctor
agent-kit validate --ci
agent-kit resync --no-update
```

Установщик размещает Python-пакет в пользовательском окружении. Если shell не находит `agent-kit`, добавьте каталог пользовательских исполняемых файлов Python в `PATH` и откройте новый терминал:

```bash
printf '\nexport PATH="$(python3 -m site --user-base)/bin:$PATH"\n' >> ~/.zshrc
export PATH="$(python3 -m site --user-base)/bin:$PATH"
agent-kit doctor
```

Для Bash используйте `~/.bashrc` вместо `~/.zshrc`. На Windows запустите `bootstrap\install.ps1` из PowerShell.

## 3. Обычная работа команды

Перед началом задачи обновите локальный `main`, затем создайте рабочую ветку:

```bash
git switch main
git pull --ff-only origin main
git switch -c feat/15-10-2026-short-description
```

Допустимые префиксы: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `ci`, `style`. Дата задаётся в формате `dd-MM-yyyy`. Коммиты оформляются как `<type>(<scope>): <description>`, например:

```bash
git commit -m "feat(mcp): add corporate server profile"
git push -u origin feat/15-10-2026-short-description
```

После push создайте Merge Request в `main` корпоративного GitLab. Перед слиянием выполните тесты и проверку конфигурации:

```bash
python3 -m pytest -q
agent-kit validate --ci
```

## 4. Получение изменений из исходного GitHub

Синхронизацию выполняйте в отдельной ветке. Это позволяет проверить изменения и разрешить конфликты до обновления корпоративного `main`:

```bash
git fetch upstream --prune
git switch main
git pull --ff-only origin main
git switch -c chore/15-10-2026-sync-upstream
git merge upstream/main
python3 -m pytest -q
agent-kit validate --ci
git push -u origin chore/15-10-2026-sync-upstream
```

После этого создайте Merge Request из `chore/15-10-2026-sync-upstream` в `main` GitLab. Если ветка с таким именем уже существует, добавьте короткий уникальный суффикс. Не отправляйте изменения напрямую в GitHub и не сливайте `upstream/main` непосредственно в корпоративный `main` без проверки через Merge Request.

## 5. Обновление установленного Kit

После слияния изменений в GitLab обновите локальный клон и повторите установку:

```bash
git switch main
git pull --ff-only origin main
./bootstrap/install.sh
agent-kit validate --ci
agent-kit resync --no-update
agent-kit doctor
```

`resync --no-update` применяет текущую версию репозитория, не пытаясь самостоятельно менять Git-состояние. Локальные настройки, память проектов, секреты и состояние MCP хранятся вне репозитория. Секреты передавайте через переменные окружения; в Git допускается только перечень переменных без значений в `.env.example`.

## 6. Быстрая проверка схемы remote

Ожидаемый результат:

```text
origin    git@gitlab.company.example:ai/agent-engineering-kit.git (fetch)
origin    git@gitlab.company.example:ai/agent-engineering-kit.git (push)
upstream  https://github.com/radmirkashapov/agent-engineering-kit.git (fetch)
upstream  https://github.com/radmirkashapov/agent-engineering-kit.git (push)
```

Команда работает только с `origin`. `upstream` используется как источник чтения для периодической синхронизации.
