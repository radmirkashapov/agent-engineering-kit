# Model policy

`corporate.yaml` — единственный authoritative allowlist для definitions, которые попадают в Git. При непустом `models` все explicit model references в `agents/`, `skills/`, `rules/`, `clients/`, `mcp/` и `templates/` проверяются только по нему.

Локальные модели задаются в `models/user.local.yaml`. Файл исключён из Git и предназначен только для конкретной машины. Если corporate list пуст, локальный runtime может использовать этот файл, но committed definitions не должны предполагать, что он существует на другой машине. CI всегда запускает `agent-kit validate --ci` и не читает local policy.

Предпочтительный контракт skill — `requires.model_capabilities`; concrete model выбирает resolver. Explicit `model.preferred` и `model.allowed` разрешены для agent, когда нужна воспроизводимость.

Пример local-only файла:

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
