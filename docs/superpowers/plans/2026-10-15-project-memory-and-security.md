# План реализации памяти проекта и проверки безопасности

> **Для агентов-исполнителей:** обязательный дополнительный skill — `superpowers:subagent-driven-development` либо `superpowers:executing-plans`. Выполняйте задачи последовательно и отмечайте шаги флажками.

**Цель:** автоматически индексировать logical project через Codebase Memory и Serena и добавить единую локальную проверку через Bumblebee и SkillSpector.

**Архитектура:** два небольших сервиса координируют запуск внешних CLI и локальные отчёты машины. CLI и управляемые контрольные точки агентов вызывают сервисы, не забирая нативное состояние у MCP и не добавляя фоновый наблюдатель.

**Технологии:** Python 3.10+, argparse, pytest, внешние CLI Codebase Memory, Serena, Bumblebee и SkillSpector.

**Спецификация:** `docs/superpowers/specs/2026-10-15-project-memory-and-security-design.md`

## Общие ограничения

- Индексы и отчёты сохраняются только в machine-local data root.
- SkillSpector запускается с `--no-llm`.
- Новые поведения реализуются test-first.
- Устаревшая оценка неиспользуемого стороннего reviewer удаляется из документации полностью.

---

### Задача 1: координация памяти проекта

**Файлы:**
- Создать: `src/agent_engineering_kit/project_memory.py`
- Изменить: `src/agent_engineering_kit/projects.py`
- Изменить: `src/agent_engineering_kit/cli.py`
- Проверить: `tests/test_project_memory.py`
- Проверить: `tests/test_projects.py`

**Интерфейсы:**
- Результат: `ProjectMemoryManager.index(project, mode) -> dict` и CLI `project memory-refresh`.

- [x] Написать failing-тесты полной и быстрой индексации, пропуска отключённых MCP и ошибки внешнего CLI.
- [x] Запустить целевые тесты и подтвердить ожидаемый FAIL из-за отсутствующего сервиса.
- [x] Реализовать сервис и подключить его к `project init` и явной команде refresh.
- [x] Добавить refresh в `run prepare`, новый task workflow и lane create.
- [x] Запустить целевые тесты до PASS.

### Задача 2: проверка через Bumblebee и SkillSpector

**Файлы:**
- Изменить: `catalog/security.yaml`
- Изменить: `src/agent_engineering_kit/security_tools.py`
- Изменить: `src/agent_engineering_kit/cli.py`
- Проверить: `tests/test_security_tools.py`
- Проверить: `tests/test_cli.py`

**Интерфейсы:**
- Результат: `SecurityToolManager.scan(target, skill_roots) -> (bool, report)` и CLI `security scan`.

- [x] Написать failing-тесты двух scanner invocations, offline SkillSpector и fail-closed результата.
- [x] Запустить целевые тесты и подтвердить ожидаемый FAIL.
- [x] Сделать Bumblebee обязательным и реализовать scan/report orchestration.
- [x] Подключить CLI и автоматический выбор effective skill roots.
- [x] Запустить целевые тесты до PASS.

### Задача 3: очистка документации и итоговая проверка

**Файлы:**
- Изменить: `README.md`
- Изменить: `docs/INDEX.md`
- Изменить: `AI.md`
- Изменить: `app.version`

**Интерфейсы:**
- Использует команды из задач 1–2.

- [x] Удалить устаревший ADR и описать новые команды на русском языке.
- [x] Обновить индекс документации и версию Kit.
- [x] Проверить отсутствие упоминаний литеральным поиском.
- [x] Запустить полный `pytest` и `agent-kit validate --ci`.
