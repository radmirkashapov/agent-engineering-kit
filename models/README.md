# Политика моделей

`corporate.yaml` — единственный авторитетный список разрешённых моделей для определений, попадающих в Git. В исходной поставке он содержит `enabled: false`: список остаётся проверяемым примером, но не ограничивает локальный runtime. Корпоративный fork устанавливает `enabled: true` и заменяет пример своим allowlist; после этого все явные ссылки на модели в `agents/`, `skills/`, `rules/`, `clients/`, `mcp/` и `templates/` проверяются только по нему.

Локальные модели задаются в `models/user.local.yaml`. Файл исключён из Git и предназначен только для конкретной машины. Если корпоративный список пуст, локальная среда выполнения может использовать этот файл, но закоммиченные определения не должны предполагать, что он существует на другой машине. CI всегда запускает `agent-kit validate --ci` и не читает локальную политику.

## Описание provider и регистрация в клиентах

Помимо обязательного `id`, provider может содержать следующие поля:

- `name` — короткое отображаемое имя;
- `description` — понятное назначение provider;
- `base_url` — URL OpenAI-compatible endpoint, начинающийся с `http://` или `https://`;
- `api_key_env` — только имя переменной с ключом, без её значения;
- `wire_api` — `responses` или `chat` для Codex-compatible transport.

Модель может содержать `name`, `description`, `model_id` (ID на стороне gateway), `context_window` и `max_output_tokens`. Эти поля описывают технический контракт, но не являются секретами.

```yaml
# Локальный provider. Файл хранится вне Git, ключ остаётся в окружении пользователя.
version: 1
providers:
  - id: company-ai
    name: Company AI Gateway
    description: OpenAI-compatible endpoint for engineering workloads.
    base_url: https://ai.company.example/v1
    api_key_env: COMPANY_AI_API_KEY
    wire_api: responses
models:
  - id: company-coder
    provider: company-ai
    name: Company Coder
    description: Preferred coding model for local development.
    model_id: company-coder-v1
    context_window: 128000
    max_output_tokens: 16000
    capabilities:
      coding: true
      tool_use: true
```

После изменения каталога выполните `agent-kit models sync`. Codex получает endpoint и сохраняет существующий `env_key`. OpenCode создаёт стартовый config только при его отсутствии; любой существующий `opencode.json` или `opencode.jsonc` остаётся полностью ручным и не читается Kit, поэтому дальнейшие изменения в нём выполняются пользователем. Cline, Claude Code и Claude Desktop не редактируются: подробности даёт `agent-kit models explain <client>`.

Предпочтительный контракт skill — `requires.model_capabilities`; конкретную модель выбирает механизм разрешения. Явные поля `model.preferred` и `model.allowed` разрешены для роли агента, когда нужна воспроизводимость.

Пример файла только для локального использования:

```yaml
version: 1
providers:
  - id: ollama
models:
  - id: local-qwen-coder
    provider: ollama
    capabilities:
      coding: true
      tool_use: true
```
