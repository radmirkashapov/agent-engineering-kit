# Agent Engineering Kit — machine entry point

Этот repository — глобальный, versioned и универсальный источник правил для AI coding agents на одной машине. Он определяет **как** работать, но не хранит данные конкретного проекта.

## Session bootstrap

1. При старте новой session запусти `agent-kit resync`; текущая Git revision и effective snapshot записываются в local state.
2. Не меняй revision kit посреди активной task.
3. Найди logical project по ближайшему вверх `.ai-team/project.yaml`.
4. Если manifest отсутствует, предложи `agent-kit project init`, не приравнивай Git repository к project автоматически.
5. Запусти `agent-kit project status` и `agent-kit config explain`.
6. Открой project documentation из `documentation.index`, обычно `docs/INDEX.md`.
7. Загрузи обязательные global rules и только релевантные skills/agents/MCP.

## Version и paths

Версия kit находится в `app.version`, точная deployed revision — в Git `HEAD`, session revision — в `<data>/state/session-revision.json`.

Canonical path resolver реализован в `agent_engineering_kit.paths`. На Unix data root: `$XDG_DATA_HOME/agent-engineering-kit` или `~/.local/share/agent-engineering-kit`; на Windows: `%LOCALAPPDATA%\agent-engineering-kit`. `AGENT_KIT_DATA_HOME` и `AGENT_KIT_REPOSITORY` — явные deployment overrides.

Всегда сохраняй границу:

```text
repository != installations != control-plane state != project memory != MCP-native state != client-native state
```

## Logical project

Project identity задаёт `<logical-project-root>/.ai-team/project.yaml`. `id` стабилен и используется как memory namespace. `repositories` поддерживает single-repo, monorepo и multi-repo workspace; `components` может ссылаться на вложенные части. Для произвольно расположенных repositories logical root должен быть общим workspace с относительными paths.

Local memory находится в `<data>/projects/<project-id>/` и содержит `state/`, `sessions/`, `summaries/`, `checkpoints/`, `integrations/`. Collision одинакового `project.id` для разных roots блокируется. Эта память не authoritative; canonical knowledge — source, tests и project docs.

## Обязательные rules

Всегда применяй:

- `rules/engineering.md`
- `rules/git.md`
- `rules/testing.md`
- `rules/review.md`
- `rules/documentation.md`
- `rules/security.md`
- `rules/context.md`
- `rules/models.md`
- `rules/external-tools.md`

Project committed instructions могут уточнять global rules, но не ослаблять enforced security, model policy и mandatory validation.

## Skills и agents

First-party skills находятся в `skills/first-party/*/SKILL.md`. External skills разрешаются через `catalog/skills.yaml` + lock в machine-local installation; Git checkout никогда не содержит их тела. Используй только `ACTIVE` effective exposure.

Agent roles находятся в `agents/*.md`. Role выбирается по задаче: `scout` для discovery, `implementer` для изменения, `reviewer` для review, `verify` для проверки, `auditor` для границ/policy. `policy: enforced` нельзя отключить local override.

## MCP

Источник configuration intent — `mcp/registry.yaml`, version intent — `locks/mcp.lock.yaml`. Core MCP обязательны; conditional MCP выбираются по project signals. Secrets читаются только из environment/native OAuth. Базы/cache MCP остаются в native storage.

## Model policy

Если `models/corporate.yaml` содержит модели, committed definitions валидируются **только** по corporate allowlist. `models/user.local.yaml` может расширить local runtime, но никогда Git baseline. Если corporate list пуст, local runtime может использовать user-local models; committed definitions всё равно не должны скрытно требовать machine-specific model. Skills по возможности объявляют `requires.model_capabilities`.

## Overrides и precedence

Local overrides находятся вне repository: `<data>/overrides/global/` и `<data>/overrides/projects/<project-id>/`. Режимы: `extend`, `replace`, `disable`; collision всегда явный.

Порядок merge:

```text
upstream < kit global < project committed < user global < user project
```

Ни один overlay не может ослабить `enforced`/`locked` value, разрешить user-only model для committed definition, отключить validation или внедрить secret в Git.

## Multi-repo и monorepo

Работай от logical root. Определи component текущего файла через `repositories[].path` и `components[].path`; оцени impact по всем связанным components, даже если у них разные `.git`. Git operations выполняй отдельно в каждом repository. Documentation index может содержать roots из нескольких repositories.

## Завершение task

Запусти релевантные tests и `agent-kit validate`. Для проверки corporate baseline используй `agent-kit validate --ci`. Обновляй durable project docs, когда изменился contract или архитектура; session notes оставляй в local memory. Не коммить generated client config, local models, overrides, runtime, indexes или secrets.
