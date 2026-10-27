# Задачи, worktree и leases

Рабочее пространство задачи фиксирует логический проект, ID задачи, ревизии репозиториев и область записи. Это помогает обнаружить локальные конфликты до того, как параллельная работа перезапишет файлы.

## Начать задачу

Короткая команда поддерживает создание задачи через issue URL или обычный ID. Например, во временном проекте успешно создалась задача DEMO-7:

~~~bash
agent task create DEMO-7 --type docs --write 'docs/**'
~~~

Короткий интерфейс `agent task` также принимает `lane create`, но не поддерживает просмотр статуса и параметр `--summary`. Для статуса, аренды и остальных действий используйте `agent-kit`. Если Jira настроена и задача найдена, Kit может получить краткое описание; если задача не найдена, исходный ID всё равно используется. Параметр `--type` задаёт префикс ветки.

Низкоуровневый вариант требует write set:

```bash
agent-kit task create SOME-42 \
  --type feat \
  --summary local-smoke \
  --write 'src/**'
agent-kit task status SOME-42
```

Проверка создала ветку `feat/27-10-2026-some-42-local-smoke` и рабочее дерево; команды `status` и `lease` для задачи завершились успешно. Аренда ограничивает пересекающиеся области записи только на этой машине. При конфликте следующая задача получает состояние `WAITING`, а поле `blocked_by` указывает блокирующую задачу. Проверка DEMO-8 с тем же шаблоном области записи показала блокировку со стороны DEMO-7. Аренда не синхронизируется между компьютерами.

## Параллельные lanes

Для независимых частей задачи создавайте отдельные lanes:

```bash
agent task lane create TASK-123 worker-a --write 'src/**'
agent task lane create TASK-123 worker-b --write 'src/**'
agent-kit task lane status TASK-123 worker-a
agent-kit task lane status TASK-123 worker-b
```

В smoke-проверке `worker-a` получил состояние `active`, а `worker-b` — `waiting` из-за пересечения областей записи. Перед записью проверяйте статус через `agent-kit task lane status <task-id> <lane-id>`: короткий интерфейс не предоставляет подкоманду status. Состояние `WAITING` запрещает менять файлы. При расширении области записи повторите проверку. Каждая lane, в которой выполняется запись, должна владеть отдельной веткой и рабочим деревом; общие файлы изменяются по очереди.

## Интеграция и завершение

```bash
agent task lane integrate TASK-123 api
# Выполните напечатанные Git-команды после проверки плана.
agent task lane complete TASK-123 api
agent-kit task complete orders TASK-123
agent-kit task release orders TASK-123
```

Команда `lane integrate` проверяет состояние и печатает план Git; Kit не выполняет commit или merge. После обычного Git merge команда `lane complete` подтверждает интеграцию и продвигает очередь. После `task complete` освободите аренду. Если создавали управляемое рабочее дерево, удалите его командой `git worktree remove`, затем используйте `agent-kit task gc <project-id> <task-id>`. Сборка мусора откажется удалять неизвестные файлы, активную аренду или существующее рабочее дерево.

## Между компьютерами

Локальная аренда защищает от пересекающихся write sets на одной машине. Между компьютерами координируйтесь через remote branches, PR/MR, CI и merge queue. Не копируйте worktree между ПК и не давайте двум writable lanes владеть одним checkout.

Подробный workflow — в разделе [работы с проектом в README](https://github.com/radmirkashapov/agent-engineering-kit/blob/main/README.md#как-работать-с-проектом); архитектурные границы — в [ADR 0013](https://github.com/radmirkashapov/agent-engineering-kit/blob/main/docs/adr/0013-capability-kernel.md).
