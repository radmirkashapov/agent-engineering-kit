# Agent Engineering Kit

Добро пожаловать в руководство по Agent Engineering Kit. Wiki объясняет, как установить набор, подключить проект, выбрать клиент и безопасно вести задачи.

Agent Engineering Kit — переносимый control plane для AI coding agents. Он собирает правила, роли, skills, MCP, модели и локальные переопределения в эффективную конфигурацию. Цикл работы агента и его sandbox остаются у клиента — например, Codex, Claude Code, OpenCode или Cline.

## Начните отсюда

- [Установка на macOS и Linux](Install)
- [Быстрый старт](Quick-start)
- [Команды CLI](CLI)
- [Logical projects](Projects)
- [Задачи, worktree и leases](Tasks)

## Руководство

- [Об архитектуре и границе harness](Overview)
- [Репозиторий project-skills](Project-skills)
- [Клиенты, MCP и credentials](Clients-and-MCP)
- [Overrides и ACL](Overrides)
- [Profiles и роли](Profiles-and-roles)
- [Security scan и обновление PR](Security-and-PR)
- [Память, Codebase Memory и Serena](Memory)
- [Результаты smoke-проверки](Smoke-test)
- [Соглашения](Conventions)
- [Устранение неполадок](Troubleshooting)
- [Частые вопросы](FAQ)

## Проверка CLI

Основные команды прошли ручную smoke-проверку во временном проекте. В ней отдельно проверены ограничения и ожидаемые состояния, зависящие от доступности интеграций. Подробности приведены на странице [результатов smoke-проверки](Smoke-test).

Эти страницы — версионируемый источник для последующей публикации в GitHub Wiki.

Идентификаторы конфигурации, названия команд, статусы, поля схем и значения description по умолчанию сохраняются без перевода. Полные контракты опубликованы в [README репозитория](https://github.com/radmirkashapov/agent-engineering-kit/blob/main/README.md) и [индексе документации](https://github.com/radmirkashapov/agent-engineering-kit/blob/main/docs/INDEX.md).
