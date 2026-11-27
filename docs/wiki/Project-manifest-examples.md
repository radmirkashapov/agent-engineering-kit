# Полные примеры project.yaml

Каждый блок — самостоятельный `.ai-team/project.yaml`. Примеры соответствуют текущей схеме: components пока список. Предложенный ранее include/exclude не входит в проверенную ревизию `4ca8be8`.

## Один репозиторий с несколькими Maven/Gradle-модулями

```yaml
# Один Git-репозиторий; модули обнаруживаются по файлам сборки.
version: 1
id: billing-platform
name: Billing platform
repositories:
  - id: root
    path: .
    required: true
# Не перечисляем все модули вручную; здесь можно добавить owner/criticality.
components: []
conventions: [] # Относительные пути дополнительных соглашений, если они есть.
discovery:
  enabled: true
  exclude_paths: [generated] # Исключить оставшийся каталог из инвентаризации.
documentation:
  index: docs/INDEX.md
  roots: [docs]
memory:
  namespace: billing-platform # Совпадает с id.
skills:
  repository:
    url: git@gitlab.company.example:billing/project-skills.git
    default_branch: main
harness:
  preferred_client: auto
  required_capabilities: [instructions, skills, mcp]
```

## Монорепозиторий с приложениями и библиотеками

```yaml
# Один Git-репозиторий с несколькими сервисами, UI и библиотеками.
version: 1
id: commerce-platform
name: Commerce platform
repositories:
  - id: root
    path: .
    required: true
components:
  # Дополнительная логическая граница; автоматические компоненты сохраняются.
  - id: checkout-domain
    repository: root
    path: services/checkout
    owner: checkout-team
    criticality: critical
conventions: []
discovery:
  enabled: true
  exclude_paths: [archive, generated]
documentation:
  index: docs/INDEX.md
  roots: [docs]
memory:
  namespace: commerce-platform
skills:
  repository:
    url: git@gitlab.company.example:commerce/project-skills.git
    default_branch: main
harness:
  preferred_client: auto
  required_capabilities: [instructions, skills, mcp]
```

## Несколько Git-репозиториев под общим root

```yaml
# workspace/.ai-team/project.yaml; backend, frontend и shared — соседние checkout.
version: 1
id: delivery-platform
name: Delivery platform
repositories:
  - id: backend
    path: backend
    required: true
  - id: frontend
    path: frontend
    required: true
  - id: shared
    path: shared
    required: false # Отсутствие не делает его обязательным checkout.
components: []
conventions: []
discovery:
  enabled: true
  # Для некорневого repository старый механизм использует префикс repository ID.
  exclude_paths: [backend/legacy]
documentation:
  index: docs/INDEX.md
  roots: [docs]
memory:
  namespace: delivery-platform
skills:
  repository:
    url: git@gitlab.company.example:delivery/project-skills.git
    default_branch: main
harness:
  preferred_client: auto
  required_capabilities: [instructions, skills, mcp]
```

Обязательные отсутствующие checkout отражаются в project status; привяжите локальные пути через project bind. Каждый repository может сам быть многомодульным. Для независимой рабочей копии только backend используйте самостоятельный manifest с path: .; общий project.id и тот же источник project-skills связывают namespace. Это не означает, что Kit автоматически клонирует отсутствующий frontend.

## Независимый nested project

```yaml
# platform/tools/migration/.ai-team/project.yaml, отдельно от platform.
version: 1
id: migration-tool
name: Migration tool
parent_project:
  id: commerce-platform
  path: ../.. # Путь от root вложенного проекта к родительскому root.
repositories:
  - id: root
    path: .
    required: true
components: []
conventions: []
discovery:
  enabled: true
  exclude_paths: []
documentation:
  index: docs/INDEX.md
  roots: [docs]
memory:
  namespace: migration-tool
skills:
  repository:
    url: git@gitlab.company.example:tools/migration-skills.git
    default_branch: main
harness:
  preferred_client: auto
  required_capabilities: [instructions, skills, mcp]
```

Создаётся через `agent-kit project init tools/migration --nested --template minimal` из родительского root. Создание внешнего root поверх уже существующих дочерних manifests сейчас отклоняется. Связь parent_project не наследует skills и conventions. Ограничение общей клиентской публикации описано в [Project-scope-and-memory](Project-scope-and-memory).
