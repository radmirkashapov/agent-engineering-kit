# Быстрый старт

После установки проверьте локальную среду:

```bash
agent-kit resync --no-update
agent-kit validate --ci
agent-kit doctor
agent-kit help
```

В корне продуктового репозитория при необходимости создайте logical project:

```bash
agent-kit project init
agent-kit project status .
agent-kit config explain .
```

Начните задачу через Jira URL или task ID:

```bash
agent task create https://company.atlassian.net/browse/TASK-123
```

Если Jira недоступна, используйте ID напрямую. Проверьте статус workspace и write set до записи:

```bash
agent-kit task status TASK-123
```

После изменений выполните относящиеся к проекту проверки и:

```bash
agent-kit validate
agent-kit doctor
```

После интеграции завершите workspace и освободите lease. Если создавали managed worktree, до task gc удалите его командой git worktree remove.

```bash
agent-kit task complete <project-id> TASK-123
agent-kit task release <project-id> TASK-123
```

См. подробнее: [задачи](Tasks), [logical projects](Projects), [CLI](CLI).
