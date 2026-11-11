# План реализации: глобальный переключатель Agent Engineering Kit

> **Для исполнителя:** выполняй задачи последовательно, после каждого шага запускай указанные проверки.

## Цель

Добавить локальные команды `agent-kit disable`, `agent-kit enable` и `agent-kit status`. Переключатель не меняет Git-репозиторий, но сразу обновляет управляемые блоки инструкций поддерживаемых клиентов, поэтому уже настроенные harness получают явное указание не применять профили, роли, rules и skills Kit.

## Задачи

### 1. Зафиксировать контракт machine-local состояния

**Файлы:** новый `src/agent_engineering_kit/agent_kit_state.py`, тесты состояния.

- Хранить JSON в `paths.state / "agent-kit-status.json"`.
- При отсутствии файла возвращать `enabled=true`.
- Читать и записывать только ожидаемую схему, атомарно и без секретов.
- Сделать операции `status`, `set_enabled` и `reset`; повторные вызовы должны быть идемпотентными.
- Повреждённый JSON должен выдавать диагностическую ошибку с путём файла.

### 2. Добавить CLI-команды и немедленное обновление инструкций

**Файлы:** `src/agent_engineering_kit/cli.py`, `src/agent_engineering_kit/clients.py`, тесты CLI/clients.

- Зарегистрировать верхнеуровневые команды `disable`, `enable`, `status`; для `enable` поддержать `--reset`.
- После изменения состояния вызвать единый instruction bridge.
- Расширить `expose_native_instructions` параметром `agent_kit_enabled`; enabled-блок оставляет текущие инструкции, disabled-блок явно запрещает применение Kit и показывает `agent-kit enable`.
- Сохранить пользовательский текст до и после managed-блока, не создавать дубли при повторном вызове.
- Сделать обновление безопасным: при ошибке синхронизации вернуть ненулевой код и не скрывать путь проблемного файла.

### 3. Применить toggle к запуску и resync

**Файлы:** `src/agent_engineering_kit/cli.py`, `src/agent_engineering_kit/resync.py`, `src/agent_engineering_kit/run_contract.py` при необходимости.

- В `run prepare` проверять локальное состояние до построения profile/roles/skills/MCP и не создавать request manifest в disabled-режиме.
- В `resync` не включать Kit автоматически; синхронизировать managed instruction block в соответствии с текущим состоянием.
- Не менять поведение `validate`: repository validation продолжает работать независимо от runtime toggle.
- Не удалять и не менять пользовательские MCP registrations.

### 4. Показать состояние в диагностике

**Файлы:** `src/agent_engineering_kit/explain.py`, `src/agent_engineering_kit/doctor.py`, тесты диагностики.

- Добавить в `config explain` поля состояния и источника machine-local файла.
- Добавить в `doctor` понятную строку enabled/disabled.
- Не включать toggle в versioned policy schema и корпоративные immutable invariants.

### 5. Обновить документацию и версию

**Файлы:** `README.md`, `docs/wiki/*` или канонический индекс документации, `app.version`, `src/agent_engineering_kit/__init__.py`.

- Описать сценарии отключения, область действия, мгновенное обновление managed-файлов и восстановление.
- Объяснить, что Git-репозиторий и пользовательский текст не изменяются.
- Поднять patch/minor версию по принятой схеме проекта.

### 6. Проверка

- Запустить целевые тесты состояния, CLI, clients, resync и run contracts.
- Запустить полный `pytest`.
- Выполнить `git diff --check` и `agent-kit validate --ci` через локальное окружение проекта.
- Проверить повторные `disable`/`enable`, отсутствие изменений в Git tree и сохранение пользовательских строк.
