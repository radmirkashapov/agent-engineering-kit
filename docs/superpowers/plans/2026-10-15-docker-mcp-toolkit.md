# План реализации профиля Docker MCP Toolkit

> **Для агентов-исполнителей:** обязательный дополнительный skill — `superpowers:executing-plans`. Выполняйте задачи последовательно и отмечайте шаги флажками.

**Цель:** реализовать управляемый профиль Docker MCP Toolkit с безопасным переключением между нативной регистрацией и единым gateway.

**Архитектура:** отдельный менеджер объединяет версионируемую конфигурацию и локальные overrides, строит план Docker CLI и сохраняет подтверждённый routing snapshot. Регистрация клиентов читает только подтверждённый snapshot, поэтому не создаёт дубликаты и сохраняет нативный fallback при ошибке Docker.

**Технологии:** Python 3.10+, argparse, YAML, JSON, Docker MCP CLI, pytest.

**Спецификация:** `docs/superpowers/specs/2026-10-14-docker-mcp-toolkit-design.md`

## Общие ограничения

- Профиль называется `agent-engineering-kit`, gateway — `agent-kit-docker`.
- Docker runtime по умолчанию отключён.
- Неизвестные записи Docker profile не удаляются.
- Клиент переключается только после успешного sync.
- Credentials в mapping URI запрещены.

---

### Задача 1: конфигурация, routing и sync

**Файлы:**
- Создать: `mcp/docker-toolkit.yaml`
- Создать: `src/agent_engineering_kit/docker_mcp.py`
- Проверить: `tests/test_docker_mcp.py`

- [x] Написать failing-тесты merge overrides, plan, safe sync, idempotency и недоступного Docker Toolkit.
- [x] Реализовать загрузку конфигурации, URI validation, status, plan, sync и локальный state.
- [x] Запустить целевые тесты до PASS.

### Задача 2: CLI и взаимное исключение регистрации

**Файлы:**
- Изменить: `src/agent_engineering_kit/cli.py`
- Изменить: `src/agent_engineering_kit/clients.py`
- Проверить: `tests/test_cli.py`
- Проверить: `tests/test_clients.py`

- [x] Написать failing-тесты команд и исключения native registrations.
- [x] Добавить `mcp docker status|plan|sync|enable|disable`.
- [x] Подключить подтверждённые routes к регистрации gateway и удалению нативных дублей.
- [x] Запустить целевые тесты до PASS.

### Задача 3: документация и общая проверка

**Файлы:**
- Изменить: `README.md`
- Изменить: `docs/INDEX.md`

- [x] Описать команды, fallback и базовый набор MCP.
- [x] Запустить полный pytest, CI validation и diff check.
