# Корпоративные спецификации, агенты, skills и credentials MCP

Эта инструкция описывает рекомендуемый поток для команды, которая использует корпоративную копию Agent Engineering Kit и хочет:

- безопасно передавать токены MCP через `.env`;
- добавлять корпоративные правила и спецификации;
- публиковать общие корпоративные skills и роли агентов;
- подключать единый репозиторий project-specific skills;
- использовать локальные экспериментальные skills без публикации в Git.

## 1. Где находится каждый слой

Не смешивайте переносимые корпоративные определения и секреты разработчика.

| Задача | Где хранить | Кто видит изменения |
|---|---|---|
| Корпоративные правила и соглашения | `rules/`, `conventions/` в корпоративном форке Kit | Все пользователи этого форка |
| Корпоративная политика моделей | `models/corporate.yaml` | Все пользователи; файл проходит CI |
| Корпоративные роли агентов | `agents/*.md` и ссылки из `profiles/*.yaml` | Все пользователи |
| Корпоративные MCP | `mcp/registry.yaml`, `catalog/mcp.yaml`, `locks/mcp.lock.yaml` | Все пользователи после `resync` |
| Корпоративные skills, поставляемые вместе с Kit | `skills/first-party/<id>/SKILL.md` | Все пользователи этого форка |
| Корпоративные внешние skills | `catalog/skills.yaml` и `locks/skills.lock.yaml` | Все пользователи после проверки и установки |
| Общие skills одного продукта | отдельный Git-репозиторий `project-skills` | Участники logical project |
| Личный экспериментальный skill | machine-local override вне Git | Только один разработчик |
| MCP-токены и пароли | machine-local vault Kit | Только текущая машина |

Итоговое правило: Git хранит определения и контракты, а не значения секретов и не локальные эксперименты.

## 2. Credentials MCP через `.env`

### 2.1. Создайте локальный файл

Шаблон `mcp-creds.example.env` можно коммитить: он содержит только имена переменных. Рабочий файл создайте копированием:

```bash
cp mcp-creds.example.env mcp-creds.env
chmod 600 mcp-creds.env
```

Заполните только нужные переменные, например:

```dotenv
GITHUB_PERSONAL_ACCESS_TOKEN=ghp_...
SENTRY_ACCESS_TOKEN=...
SENTRY_HOST=sentry.corp.example
SONARQUBE_TOKEN=...
SONARQUBE_URL=https://sonarqube.company.example
```

Не добавляйте кавычки, shell-команды, `$(...)`, `${...}`, URL с токеном или дополнительные неизвестные переменные. Не выполняйте `source mcp-creds.env`: Kit сам разбирает файл и не экспортирует его содержимое в shell-историю.

Файлы `mcp-creds.env` и `mcp-creds.*.env` исключены из Git. Если файл уже попал в индекс, удалите его из индекса обычной командой Git и немедленно замените скомпрометированные токены.

### 2.2. Импортируйте значения в локальное защищённое хранилище

```bash
agent-kit mcp creds import --from ./mcp-creds.env
agent-kit mcp creds status
```

Команда:

1. сверяет имена с переменными, объявленными MCP registry;
2. отклоняет неизвестные переменные и небезопасный shell-синтаксис;
3. записывает значения в `<data>/secrets/mcp-creds.env` с правами только владельца;
4. сохраняет в state только имена переменных и статусы, но не значения.

Проверьте учётные данные и примените текущую конфигурацию.

```bash
agent-kit mcp available
agent-kit mcp creds status
agent-kit resync --no-update
agent-kit doctor
```

### 2.3. Как ключи попадают в клиенты

При `resync` Kit автоматически обновляет управляемые регистрации в Codex, Claude Code, OpenCode и Cline. Для stdio MCP с учётными данными клиент получает команду локального launcher. Launcher читает значения из защищённого хранилища и передаёт их при запуске серверного процесса.

Для ручной настройки Claude Desktop можно получить команду запуска уже включённого stdio MCP. Например, для встроенного Context7 с доступным `npx` выполните следующую команду.

```bash
agent-kit mcp launch-command context7
```

Скопируйте выданные `command` и `args` в нативную форму конкретного клиента. Значения credentials вручную в его JSON/YAML не вставляйте.

### 2.4. Ротация и OAuth

После ротации токена повторите импорт:

```bash
agent-kit mcp creds import --from ./mcp-creds.env
```

При смене значения токена действующий launcher прочитает его при следующем запуске MCP. После изменения описания, команды или разрешений уже включённого MCP явно выполните синхронизацию.

```bash
agent-kit resync --no-update
```

Для удалённого MCP с OAuth, например GitLab, завершите вход в соответствующем клиенте и профиле. Встроенный Context7 запускается через stdio. Необязательный ключ `CONTEXT7_API_KEY` повышает лимиты и передаётся дочернему процессу через launcher.

### 2.5. Docker MCP Toolkit при синхронизации

Toolkit используется по желанию. Если Docker или Toolkit недоступен либо ранее применённый профиль не проходит проверку, `agent-kit resync` выводит `SKIPPED: Docker MCP Toolkit` и возвращает управляемые регистрации клиентов на нативные маршруты. Ошибка установки или регистрации обязательного нативного MCP прерывает синхронизацию. Для MCP, чья нативная команда запуска использует Docker, требуется Docker Engine.

Для изменения выделенного профиля запустите `agent-kit mcp docker plan`, затем явно выполните `agent-kit mcp docker sync`.

## 3. Как добавить корпоративные спецификации

Корпоративный набор обычно состоит из трёх уровней.

### 3.1. Общие обязательные правила

Добавьте или измените Markdown-файлы в `rules/`, например:

```text
rules/security.md
rules/git.md
rules/data-handling.md
```

Правило должно описывать проверяемое поведение агента: границу действия, запрет или обязательную проверку. Не помещайте туда токены, URL с credentials или локальные пути.

### 3.2. Версионируемые conventions

Добавьте YAML в `conventions/`. Каждая запись должна иметь уникальный ID и пройти `schemas/conventions.schema.json`. Например, для соглашения о PR создайте `conventions/corporate-pr.yaml`, а затем проверьте:

```bash
agent-kit validate conventions
agent-kit validate --ci
```

Конфликтующий ID не переопределяется молча: при совпадении validation завершается ошибкой.

### 3.3. Политика моделей и MCP

В корпоративном форке администратор меняет `models/corporate.yaml`, обычно устанавливая `enabled: true` и поддерживая allowlist провайдеров и моделей. MCP описываются в `mcp/registry.yaml`, каталог и точные ревизии — в `catalog/mcp.yaml` и `locks/mcp.lock.yaml`.

После изменений используйте обычный PR/MR:

```bash
git checkout -b chore/12-11-2026-update-corporate-policy
agent-kit validate --ci
git add rules conventions models mcp catalog locks
git commit -m "chore(policy): update corporate agent policy"
git push -u origin HEAD
```

После merge пользователи получают изменения из своей корпоративной копии Kit и выполняют `agent-kit resync --no-update`.

## 4. Как адаптировать роли агентов в корпоративном форке

Для корпоративных требований отредактируйте существующую роль, например `agents/reviewer.md`. Сохраните её ID. Проверка допускает фиксированный набор стандартных ID и требует англоязычное определение длиной не менее 45 строк.

Ниже приведён пример frontmatter для этой роли с дополнительным требованием проверять обработку данных. Сохраните и при необходимости дополните существующий Markdown после frontmatter.

```markdown
---
version: 1
id: reviewer
role: Identify correctness, security, compatibility, and test defects and verify compliance with corporate data handling rules.
policy: configurable
model:
  preferred: claude-opus-4.6
  allowed:
    - gpt-5.6-sol
    - claude-opus-4.6
requires:
  model_capabilities:
    - reasoning
    - coding
    - tool_use
tools:
  - code-search
  - git-diff
  - tests
---
```

Состав стандартного профиля задаётся в соответствующем `profiles/*.yaml`. После правок проверьте роли и профили.

```bash
agent-kit validate agents
agent-kit validate profiles
agent-kit validate --ci
```

Права на merge, публикацию и развёртывание определяют рабочий процесс и клиент, исполняющий роль.

## 5. Как добавить корпоративные skills

### Вариант A: skill поставляется вместе с корпоративным Kit

Для стабильного навыка, который входит в общий инженерный стандарт, перейдите в корень Git checkout корпоративного Kit. Команда пишет в активный checkout Kit. Чтобы явно выбрать текущую копию для импорта и последующих проверок, задайте `AGENT_KIT_REPOSITORY` в рабочей сессии.

```bash
export AGENT_KIT_REPOSITORY="$PWD"
agent-kit skills add --from ../draft-skills/api-contract-review
git status --short
```

Kit проверяет корневой `SKILL.md` и копирует пакет в `skills/first-party/api-contract-review/`. Имя исходного каталога должно точно совпадать с полем `name` в `SKILL.md` и со значением `--id`, если оно передано. Для замены существующего пакета используйте `--replace` в чистом Git checkout с отслеживаемым `SKILL.md`.

Обе команды импорта копируют весь пакет, включая обычные каталоги с Markdown-шагами, контрактами, спецификациями и тестовыми данными. Ссылки между файлами внутри пакета остаются относительными и продолжают работать после импорта. Символические ссылки запрещены.

Проверьте пакет и примените его на своей машине.

```bash
agent-kit validate skills
agent-kit security scan
agent-kit resync --no-update
```

### Вариант B: внешний корпоративный skill-пакет

Используйте `catalog/skills.yaml` для Git-источника, а `locks/skills.lock.yaml` — для конкретного проверенного SHA. Исходники внешнего пакета не копируйте в Kit. До активации candidate проходит security pipeline.

```bash
agent-kit resync --no-update
agent-kit skills status
agent-kit security scan
```

Активным считается только skill со статусом `ACTIVE`. Отклонённый или отключённый skill не должен публиковаться клиентам.

## 6. Project-specific repository для skills

Для skills конкретного logical project создайте отдельный обычный Git-репозиторий, например `delivery-platform-project-skills`:

```text
project-skills/
└── skills/
    ├── INDEX.md
    ├── order-api-review/SKILL.md
    └── release-readiness/SKILL.md
```

Для нового логического проекта передайте источник при инициализации.

```bash
agent-kit project init \
  --skills-repository-url git@gitlab.company.example:delivery/delivery-platform-project-skills.git \
  --skills-default-branch main
```

`--skills-default-branch` допускается вместе с URL. Без указания ветки используется `main`. При интерактивной инициализации без URL команда предлагает ввести URL или пропустить настройку. Для уже созданного логического проекта укажите одинаковый источник в `.ai-team/project.yaml` всех продуктовых репозиториев.

```yaml
id: delivery-platform
skills:
  repository:
    url: git@gitlab.company.example:delivery/delivery-platform-project-skills.git
    default_branch: main
```

Требования:

- `project.id` должен быть одинаковым во всех репозиториях logical project;
- URL не должен содержать логин, пароль, token, query или fragment;
- доступ к Git настраивается через SSH agent или системный credential helper;
- изменения в `project-skills` проходят обычные branch → commit → push → PR/MR → merge.

Из корня продуктового репозитория подготовьте отдельный checkout и добавьте пакет.

```bash
agent-kit project skills checkout --into ../delivery-platform-project-skills
git -C ../delivery-platform-project-skills switch -c feat/23-11-2026-order-api-review
agent-kit project skills add \
  --from ../draft-skills/order-api-review \
  --checkout ../delivery-platform-project-skills
git -C ../delivery-platform-project-skills status --short
```

`checkout` клонирует ветку из манифеста в новый или пустой каталог. В `--checkout` передайте корень обычной самостоятельной Git-копии с собственным каталогом `.git` и `origin`, совпадающим с проектным источником. Kit отклоняет связанные копии, созданные через `git worktree add`, даже при совпадающем `origin`. Выберите каталог вне продуктовых репозиториев и управляемого хранилища Kit. Имя исходного каталога, `--id` и `--replace` проверяются по тем же правилам, что и при импорте корпоративного пакета.

`project skills add` обновляет отслеживаемый в Git каталог `skills/INDEX.md`. После ручных правок пересоберите его командой `agent-kit project skills index --checkout ../delivery-platform-project-skills`. Включите пакет и индекс в один коммит, отправьте ветку и откройте PR/MR.

После merge:

```bash
agent-kit resync
agent-kit project skills status
agent-kit skills list
```

Для проверки ветки до merge:

```bash
agent-kit project skills use-branch feat/23-11-2026-order-api-review
agent-kit resync
agent-kit project skills status
agent-kit project skills use-main
agent-kit resync
```

Копии skills в продуктовые репозитории не создаются. Разработчику, у которого есть только один репозиторий из multi-repo проекта, достаточно его корректного `.ai-team/project.yaml`.

После `resync` клиентские адаптеры получают локальный `<data>/installations/clients/shared/effective-skills.md` с итоговым набором, источниками, статусами и сведениями о вытесненных навыках. `effective-skills.md` генерируется при синхронизации и хранится вне Git. Отслеживаемый `skills/INDEX.md` в рабочей копии перечисляет только проектные пакеты.

## 7. Локальные пользовательские skills

Храните экспериментальную версию вне корпоративного Git до командной проверки. Локальная замена требует известного ID навыка, для которого разрешено переопределение. В примере используется встроенный `greeting` с политикой `configurable`. Подготовьте собственный валидный `SKILL.md` с полем `name: greeting` в указанном исходном каталоге.

```bash
agent-kit skills override greeting \
  --from "$HOME/src/local-skills/greeting" \
  --scope global \
  --resync
```

Для текущего logical project запускайте команду из его корня и используйте `--scope project`:

```bash
agent-kit skills override greeting \
  --from "$HOME/src/local-skills/greeting" \
  --scope project \
  --resync
```

Локальный override хранится вне Git в `<data>/overrides/`. Проверить источник и приоритет можно так:

```bash
agent-kit skills explain greeting
agent-kit override list --scope global
agent-kit project skills status
```

Сброс локальной замены:

```bash
agent-kit skills reset greeting --scope global --resync
```

Приоритет источников: встроенный Kit → внешний каталог → project-skills → глобальный локальный override → локальный override проекта. При одинаковом ID побеждает более высокий слой; содержимое каталогов автоматически не объединяется.

## 8. Ежедневный контроль после изменений

После обновления корпоративной копии, project-skills или локального override выполните:

```bash
agent-kit resync --no-update
agent-kit validate --ci
agent-kit doctor
agent-kit config explain .
```

Если MCP не получает ключ:

```bash
agent-kit mcp creds status
agent-kit mcp status
agent-kit doctor
```

Если skill не появился у клиента:

```bash
agent-kit skills status
agent-kit project skills status
agent-kit security scan
agent-kit resync --no-update
```

Не коммитьте `mcp-creds.env`, локальные overrides, generated client adapters, memory и state. Они относятся к конкретной машине и должны оставаться за пределами корпоративной Git-истории.
