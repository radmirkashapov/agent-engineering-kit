# Глобальное отключение правил Agent Engineering Kit

## Цель

Добавить machine-local команды `agent-kit disable` и `agent-kit enable`, которые временно выключают или включают применение профилей, ролей, rules и skills Kit к новым агентным запускам на текущем компьютере.

## Семантика

- Состояние хранится вне Git в `<data>/state/agent-kit-status.json`.
- По умолчанию Kit включён, даже если файл состояния отсутствует.
- `agent-kit disable` записывает `enabled: false`, время изменения и источник команды.
- `agent-kit enable` записывает `enabled: true`.
- Команды идемпотентны и не требуют logical project.
- Файлы проектов, profiles, rules, roles, skills и MCP registry не изменяются.
- Пользовательские и уже зарегистрированные MCP не удаляются и не отключаются автоматически; для MCP используются отдельные команды.

## Граница применения

Когда Kit выключен:

- `run prepare` завершает работу с понятным сообщением и не создаёт request manifest с roles, profiles, rules или skills;
- `config explain` показывает `agent_kit.enabled: false` и источник machine-local state;
- `doctor` и `resync` показывают состояние disabled;
- существующие пользовательские конфигурации клиентов не удаляются автоматически;
- `agent-kit enable` возвращает обычное построение effective policy и request manifests.

При выключенном Kit `validate` продолжает проверять репозиторий и схемы: отключение runtime-применения не должно скрывать ошибки в Git-конвенциях, profiles, roles, skills или MCP manifests.

## Реализация

- Добавить маленький модуль состояния с атомарным чтением/записью и безопасным default `enabled=true`.
- Расширить `KitPaths` путём `state/agent-kit-status.json` через существующий `paths.state`.
- Добавить поле `agent_kit` или `agent_kit.enabled` в explain/run policy output, не меняя versioned policy schema.
- Добавить верхнеуровневые CLI-команды `disable` и `enable`, а также `status` для диагностики.
- Проверять состояние перед `run prepare`; `resync` не должен silently re-enable Kit.
- Сохранить обратную совместимость существующих команд и machine-local overrides.

## Безопасность и восстановление

Файл состояния не содержит секретов и не может отключать неизменяемые security invariants. Отключение — обратимое локальное решение; оно не считается корпоративным policy override и не попадает в Git. При повреждённом JSON команда должна завершаться ошибкой с путём файла и предложением выполнить `agent-kit enable --reset` либо удалить только этот machine-local state после проверки.

## Проверка

- По умолчанию `status` показывает enabled.
- `disable` меняет состояние на disabled, повторный `disable` не меняет результат.
- `enable` возвращает enabled.
- В disabled состоянии `run prepare` не создаёт request manifest.
- `validate --ci` продолжает проходить или показывать обычные repository errors независимо от toggle.
- `config explain` и `doctor` отображают источник и состояние toggle.
- Состояние изолировано от project-local overrides и не меняет Git tree.
