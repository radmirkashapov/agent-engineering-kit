# Автоиндексация памяти проекта и единая проверка безопасности

## Контекст

Agent Engineering Kit управляет конфигурацией harness, но не должен подменять нативное хранилище MCP. При создании logical project требуется сразу подготовить индексы Codebase Memory и Serena, а во время управляемых запусков агентов — обновлять их в предсказуемых контрольных точках. Установка Kit также должна гарантировать наличие Bumblebee и SkillSpector, а одна команда должна запускать оба анализатора с безопасными настройками.

## Решение

1. Добавить сервис `ProjectMemoryManager`, который:
   - на полной индексации запускает `codebase-memory-mcp cli index_repository --repo-path <root> --mode full` и `serena project index <root> --name <project-id>`;
   - на обновлении запускает Codebase Memory в режиме `fast` и повторяет индексирование Serena;
   - сохраняет machine-local отчёт в `<data>/projects/<id>/integrations/memory-index.json`;
   - не пишет индексы MCP в Git и не считает недоступный optional MCP успешным.
2. `agent-kit project init` выполняет полную индексацию после создания или обнаружения manifest. `agent-kit project memory-refresh` предоставляет явное восстановление. `run prepare`, высокоуровневый `task create` и создание lane выполняют refresh перед передачей управления агенту.
3. Bumblebee и SkillSpector становятся обязательными security tools. Обычный `agent-kit install`/`resync` уже вызывает общий установщик security tools, поэтому отдельный механизм загрузки не создаётся.
4. `agent-kit security scan [path]`:
   - требует ACTIVE Bumblebee и SkillSpector;
   - запускает `bumblebee scan --profile project --root <path>`;
   - запускает SkillSpector с `--no-llm` для каждого effective skill каталога, а при явном skill-path — только для него;
   - сохраняет сводный JSON-отчёт в machine-local state и возвращает ненулевой код при ошибке инструмента или блокирующей оценке;
   - не отправляет исходный код или результаты во внешнюю модель.
5. Удалить устаревший ADR о неиспользуемом стороннем инструменте проверки кода и все ссылки на него. Альтернативная реализация code review в рамках этой задачи не добавляется.

## Отказоустойчивость

- Инициализация проекта завершается ошибкой, если обязательный Codebase Memory или Serena установлен, но индексирование завершилось ошибкой. Отсутствующий или отключённый политикой MCP фиксируется как `SKIPPED`, чтобы project init оставался пригодным до установки компонентов.
- Security scan не устанавливает инструменты скрыто: он сообщает, какие инструменты следует установить через `agent-kit security install` или `agent-kit install`.
- Все внешние команды запускаются списками аргументов без shell-интерполяции.

## Проверка

- Unit-тесты команд и отчётов используют детерминированный runner.
- CLI-тесты подтверждают `security scan` и `project memory-refresh`.
- Регрессия проверяется полным `pytest` и `agent-kit validate --ci`.
