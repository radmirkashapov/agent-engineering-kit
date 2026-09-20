# agent-engineering-kit

## Что это

`agent-engineering-kit` — единый локальный набор engineering policy, reusable skills, agent roles, MCP intent и client adapters для AI coding agents на одной машине. Один kit одновременно обслуживает много независимых logical projects и никогда не становится хранилищем их mutable данных.

```text
1 machine → 1 kit → N logical projects → N isolated memories/indexes/states
```

## Основные принципы

- Global, versioned, universal content хранится в этом Git repository.
- Project-specific durable knowledge хранится в project source/tests/docs.
- Mutable project memory, local overrides и generated client config лежат во внешнем user data directory.
- MCP/client native state остаётся у владельца.
- Непустой corporate model allowlist authoritative для committed definitions.
- Любое изменение проверяется локально и в CI без user-local inputs.

## Один kit на машину

Canonical checkout один. Он служит control plane для Codex, Claude Code, Claude Desktop, OpenCode и Cline и одновременно обслуживает множество logical projects.

## Что находится в Git

Rules, agents, first-party skills, catalogs, locks, schemas, security contracts, thin client adapters, bootstrap scripts, tests и ADR.

## Что никогда не находится в Git

Third-party source, binaries, project memory, MCP databases/cache, sessions, OAuth state, credentials, user models, local overrides, indexes и generated client configuration.

## Архитектура desired state

`AI.md` — короткая machine-readable точка входа. Каталоги задают desired state, lock-файлы — approved revisions, а Python CLI materializes только machine-local state.

Пути определяет единый resolver:

| Назначение | Unix по умолчанию | Windows по умолчанию |
|---|---|---|
| deployment repository | `<data>/repository` | `<data>\repository` |
| installations | `~/.local/share/agent-engineering-kit/installations` | `%LOCALAPPDATA%\agent-engineering-kit\installations` |
| state/locks/logs | `~/.local/share/agent-engineering-kit/{state,locks,logs}` | `%LOCALAPPDATA%\agent-engineering-kit\{state,locks,logs}` |
| project memory | `~/.local/share/agent-engineering-kit/projects` | `%LOCALAPPDATA%\agent-engineering-kit\projects` |
| overrides | `~/.local/share/agent-engineering-kit/overrides` | `%LOCALAPPDATA%\agent-engineering-kit\overrides` |

`XDG_DATA_HOME`, `LOCALAPPDATA`, `AGENT_KIT_DATA_HOME` и `AGENT_KIT_REPOSITORY` учитываются. Repository, runtime, project memory и native state намеренно не совпадают.

### Почему Python

MVP написан на Python 3.10+: он доступен на macOS/Linux, поддерживается на Windows, даёт зрелые PyYAML/jsonschema/pytest и не требует собственного daemon. Packaging стандартный (`pyproject.toml`), CLI остаётся thin, а filesystem и subprocess APIs cross-platform.

## Установка

Для deployment checkout:

```bash
./bootstrap/install.sh
agent-kit doctor
```

PowerShell:

```powershell
.\bootstrap\install.ps1
agent-kit doctor
```

Для разработки:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
```

## Первый запуск

```bash
agent-kit doctor
agent-kit validate
agent-kit resync --no-update
agent-kit project init /path/to/workspace --id stable-project-id
agent-kit project status /path/to/workspace
agent-kit config explain /path/to/workspace
```

`project init` создаёт только `.ai-team/project.yaml` и отсутствующий `docs/INDEX.md`, находит top-level Git repositories и probable components, затем регистрирует внешний memory namespace. Повторный запуск идемпотентен.

## Resync

`agent-kit resync` валидирует checkout, читает `catalog/` + `locks/`, устанавливает security tools, fetches external candidates, выполняет security/compatibility gates, атомарно активирует и синхронизирует client discovery. Повторный запуск идемпотентен. `agent-kit install` выполняет тот же materialization без обновления checkout.

## Обновление

Kit update (`git fetch` + `pull --ff-only`) отделён от dependency update. External component никогда не следует `latest`: новая версия проходит candidate validation, lock review и activation. `skills rollback <id>` возвращает предыдущую validated revision.

Revision фиксируется в начале session и не меняется посреди активной task.

## Client adapters

Создайте `clients/<id>/adapter.yaml` и `README.md`. Adapter обязан ссылаться на `AI.md`, `skills/` и `mcp/registry.yaml`, а не копировать их. Добавьте client ID в `CLIENTS`, golden/validation test и native integration notes. Generated absolute paths создаются только в `<data>/runtime/clients/<id>/`.

### Codex / Codex Desktop

Используются official `AGENTS.md`, `~/.agents/skills` и `~/.codex/config.toml`; namespaced core MCP регистрируются без замены чужих entries.

### Claude Code

Используются `~/.claude/CLAUDE.md`, `~/.claude/skills` и user-scope MCP. OAuth endpoints требуют интерактивного подтверждения.

### Claude Desktop

Отдельный contract охватывает MCP и Desktop Extensions; он не считается Claude Code.

### OpenCode

Предпочитаются native `AGENTS.md`, `~/.agents/skills` и собственный MCP config.

### Cline

Используются Cline Rules/`AGENTS.md` и native MCP settings; недокументированные global paths не перезаписываются.

## Поддерживаемые клиенты

- Codex / Codex Desktop — global `AGENTS.md`, `config.toml`, skills и MCP.
- Claude Code — global `CLAUDE.md`, skills и MCP.
- Claude Desktop — MCP/resource integration; filesystem instructions зависят от возможностей клиента.
- OpenCode — global `AGENTS.md`, config, skills и MCP.
- Cline — `AGENTS.md`/`.clinerules`, skills где поддерживаются и MCP.

## Rules

`rules/` содержит обязательные engineering, Git, testing, review, documentation, security, context/precedence и model rules. Project configuration может уточнять их, но не ослаблять enforced invariants.

## First-party skills

First-party skills находятся в `skills/first-party/*/SKILL.md`, имеют schema-validated front matter и объявляют model capabilities.

## External skills

`catalog/skills.yaml` и `locks/skills.lock.yaml` управляют external skills без vendoring. Baseline `obra/superpowers` закреплён на validated revision и устанавливается только в `<data>/installations/skills/`; обязательные upstream capabilities проверяются перед `ACTIVE`. Source tree никогда не копируется в этот Git repository.

## Agents

`agents/` содержит roles `scout`, `implementer`, `reviewer`, `verify`, `auditor`. Agent metadata задаёт role, model capabilities, optional corporate model preferences, tools и policy.

## MCP

`mcp/registry.yaml` хранит configuration intent, а не credentials и не базы. Environment передаётся как `env:NAME`. Native CBM/Serena/другой cache остаётся в storage соответствующего MCP. Local mapping project → integration допускается в `projects/<id>/integrations/`.

## Corporate model policy

### Corporate models

`models/corporate.yaml` tracked и задаёт providers, model IDs, aliases и capabilities. Если список непуст, только эти IDs разрешены в committed agents/skills/client/MCP/template definitions.

## User-local models

`models/user.local.yaml` defensive-ignored. Он разрешает local runtime models конкретного разработчика. Файл не расширяет corporate Git baseline. При пустом corporate list local runtime может использовать local models, но committed definition не получает portability guarantee.

### Validation rules

Проверяются schema, duplicate IDs, unknown providers, explicit references, отсутствие user-only dependency и Git ignore/tracked/staged state. CI запускается с `--ci` и не загружает local file.

## Local overrides

Overrides находятся вне repository:

```text
<data>/overrides/global/{rules,skills,agents,mcp}/
<data>/overrides/projects/<project-id>/{rules,skills,agents,mcp}/
```

Precedence: `upstream < kit < project committed < user global < user project`. Режимы overlay: `extend`, `replace`, `disable`. Unknown target, отключение enforced target, ослабление locked security/MCP policy и отключение validation блокируются.

## Logical projects

`.ai-team/project.yaml` задаёт stable ID, repositories, components, documentation roots и memory namespace. Git repository — topology element, а не project identity.

## Project memory

`<data>/projects/<project-id>/` содержит `state`, `sessions`, `summaries`, `checkpoints`, `integrations`. Collision ID для разных roots блокируется. Это mutable local knowledge; authoritative knowledge остаётся в project.

## Monorepo

Один repository entry может иметь несколько components. Paths component относительны repository root, documentation roots — logical project root.

## Multi-repo workspace

Logical root содержит `.ai-team/`, а `repositories` перечисляет sibling repositories относительными paths. Agents оценивают impact по всем components, Git commands выполняются отдельно для каждого repository.

## docs/INDEX.md

Это canonical карта durable knowledge: architecture, ADR и runbooks. Bootstrap создаёт минимальный индекс, но не переписывает существующий.

## Validation

```bash
agent-kit validate
agent-kit validate models
agent-kit validate agents
agent-kit validate skills
agent-kit validate mcp
agent-kit validate clients
agent-kit validate overrides
agent-kit validate git-hygiene
agent-kit validate security
agent-kit validate --ci
pytest
```

Diagnostics имеют severity `ERROR`, `WARNING`, `INFO`; exit code ненулевой только при `ERROR`.

## Security

Secrets хранятся только в environment/secret store, список переменных — в `.env.example`. Installation contracts описывают SkillEvaluator, SkillSpector, Semgrep, Gitleaks и Bumblebee. Внешний skill проходит source verification и blocking scanners до activation. Bumblebee используется для inventory/exposure scanning, не research. Pre-commit удобен, CI обязателен.

## Lock files

`skills.lock.yaml`, `mcp.lock.yaml`, `security.lock.yaml` содержат full revisions. Catalog без lock или stale lock — validation error. Rollback использует сохранённую предыдущую active revision.

## Dependency updates

Сначала обнаруживается новая upstream version, затем source и security validation, compatibility tests и review lock-файла. Только после commit lock новая candidate может стать `ACTIVE`.

## Rollback

`agent-kit skills rollback <id>` атомарно возвращает предыдущую validated revision. Для MCP/security откат выполняется возвратом lock-файла и повторным `resync`; project/native state не удаляется.

## Git workflow самого agent-engineering-kit

Branch: `<prefix>/dd-MM-yyyy-<description>`, включая `ai/` для agents/models/skills/MCP. Прямой push в `main` запрещён; delivery только Pull Request после tests/CI. Commit message: `<type>(<scope>): <description>`. Версия в `app.version` обновляется с изменением; Python package version синхронизируется.

## Troubleshooting

- `Logical project не найден`: выполните `agent-kit project init` в logical root.
- `Collision project.id`: выберите уникальный stable ID в manifest; не удаляйте чужую memory автоматически.
- Dirty checkout при `sync`: commit/stash изменения или используйте чистый deployment checkout; reset не выполняется.
- MCP unavailable: проверьте command/endpoint и наличие environment variable, не выводя её значение.
- Неясный source effective value: выполните `agent-kit config explain`.
- Validation отличается от CI: повторите `agent-kit validate --ci`; local overrides в CI намеренно отключены.
