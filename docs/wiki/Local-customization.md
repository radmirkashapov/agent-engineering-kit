# Локальная настройка: возможности и границы

Исторический аудит baseline. Реализованные в новой версии команды и изменившиеся границы описаны в [Local-runtime-commands](Local-runtime-commands).

Проверено по исходникам ревизии `4ca8be8`. Это руководство разделяет работающие механизмы и предложения к реализации. Команды из разделов «Предлагается» пока не существуют.

## Где хранить настройки

Обозначение `<data>` далее означает каталог данных Kit: Linux/macOS — `$XDG_DATA_HOME/agent-engineering-kit`, по умолчанию `~/.local/share/agent-engineering-kit`; Windows — `%LOCALAPPDATA%/agent-engineering-kit`. Переменная `AGENT_KIT_DATA_HOME` меняет этот путь.

Глобальный слой: `<data>/overrides/global/`. Проектный: `<data>/overrides/projects/<project-id>/`. Он выбирается по найденному logical project. Настройки локальные, коммитить их в корпоративный Kit не требуется. После изменений выполните `agent-kit resync --no-update` из нужного проекта. Уже открытая сессия клиента может потребовать перезапуска.

## Модели: три независимых механизма

`models/corporate.yaml` задаёт корпоративный каталог и режим проверки committed definitions. `model.allowed` и `model.preferred` в skills/agents — отдельные декларации. Регистрация providers и моделей в клиентах — третий механизм. Изменение одного не гарантирует согласованного изменения остальных.

`enabled: false` в corporate.yaml — изменение общей конфигурации репозитория, а не локальный выключатель. Оно не удаляет `model.allowed` из опубликованного контента. Текущий `models.allowed` допускает локальный policy override, но не обеспечивает сквозной режим «любая модель клиента». Также `models.allowed` появляется в effective policy только при активном непустом корпоративном каталоге: override отсутствующего ключа отвергается.

Предлагается единый локальный режим `models enforcement off|on|status` с областями global/project. Это проект интерфейса, а не доступная команда. В режиме off:

- committed определения и корпоративный каталог остаются валидируемыми без изменений;
- effective представления исключают vendor-specific `model.allowed/preferred`, сохраняя `requires.model_capabilities`;
- модель выбирает клиент через свой provider или подписку; Kit не меняет его аутентификацию;
- список корпоративных моделей остаётся доступным каталогом, но не ограничителем;
- отключение синхронизации каталога в клиент регулируется отдельно от enforcement;
- исходники skills не переписываются; выключение режима восстанавливает ограничения;
- `validate --ci` продолжает проверять корпоративный baseline без локального исключения.

Нужны проверки всех точек: validator, capability kernel, run prepare, effective agents/rules/skills, клиентские конфиги и импортируемые Markdown. Произвольные запреты, написанные обычным текстом в теле skill, нельзя надёжно удалить автоматически: нужен структурированный model contract и явное правило приоритета. Подписка Codex/Claude остаётся механизмом самого клиента; Kit не превращает её в OpenAI-compatible endpoint.

## Skills: выбор подмножества

Посмотрите ID: `agent-kit skills available`, `agent-kit skills list`, `agent-kit skills explain <id>`.

```bash
agent-kit skills disable code-review --scope global
agent-kit skills enable code-review --scope project
agent-kit skills reset code-review --scope global
agent-kit resync --no-update
```

Важно: project enable не отменяет global block. Access layers сейчас пересекаются; сначала сбросьте глобальное исключение. Пустой allow означает «нет фильтра», а не «отключить всё».

Для выбора нескольких skills создайте `<data>/overrides/global/access.yaml`:

```yaml
# Разрешённое подмножество skills на этой машине.
version: 1
skills:
  allow: [code-review, verification]
  block: []
```

Все ID должны существовать. Для внешнего пакета доступ применяется по catalog ID; вложенные skills наследуют его. Проверяйте итог через list/explain, а не только наличие файлов.

## Замена skill

Подготовьте каталог `my-review/SKILL.md` с именем исходного skill, затем:

```bash
agent-kit skills override code-review --from ./my-review --scope global
agent-kit skills explain code-review
agent-kit resync --no-update
```

Замена выбирает целый каталог: сопутствующие scripts и references должны находиться в нём. Для возврата выполните `agent-kit skills reset code-review --scope global`, затем resync. Проектный override задаётся аналогично с `--scope project` из проекта. Требования frontmatter смотрите в [Project-skills](Project-skills).

## Agents и rules

Поддержаны режимы extend, replace, disable. Extend рекурсивно объединяет объекты, но заменяет массивы и строки целиком. Replace требует полного результирующего определения. Передавайте файл значения, а не готовую обёртку target/override.

```yaml
# local-rule.yaml: содержимое локального правила.
value:
  content: |
    Перед изменением публичного API проверь совместимость потребителей.
```

```bash
agent-kit override set rules context --mode extend --from ./local-rule.yaml --reason 'Локальный порядок работы' --scope global
agent-kit override explain rules context --scope global
agent-kit override reset rules context --scope global
```

Для отключения роли подготовьте YAML `{}` и выполните:

```bash
agent-kit override set agents reviewer --mode disable --from ./empty.yaml --reason 'Роль не используется локально' --scope global
agent-kit resync --no-update
```

Аналогично отключается отдельный rule. Единого allowlist для agents/rules пока нет: нужны отдельные disable overrides. Изменение content у agent не обязательно меняет его структурированные поля role/model/requires: проверяйте effective-policy.json в `<data>/installations/clients/shared/`.

## MCP

```bash
agent-kit mcp available
agent-kit mcp disable playwright --scope global
agent-kit mcp enable gitlab --scope project
agent-kit mcp explain gitlab
agent-kit mcp override gitlab --from ./gitlab-override.yaml --scope global
agent-kit resync --no-update
agent-kit doctor
```

MCP allow/block в access.yaml задаётся секцией `mcp` с такими же полями allow/block. Enable означает запрос активации; отдельно проверяются corporate capabilities, boundaries, credentials, установленный runtime и клиентская регистрация. Он не означает успешного подключения. Секреты импортируются через `agent-kit mcp creds import --from ./mcp-creds.env`, их не помещают в overrides.

## Conventions: пока только добавление

Текущий `conventions` в project.yaml — список YAML-путей. Общие conventions всегда загружаются из Kit. Повтор ID отвергается; локального disable/replace нет. Policy kernel фиксирует `conventions.override: false` как инвариант. Поэтому обещать полную локальную свободу для conventions сейчас нельзя.

Предлагается включить conventions в общий resolver с режимами extend/replace/disable и явными provenance. Для всех пяти типов нужны одинаковые CLI enable/disable/reset и selection allow/block с определённой семантикой пустого списка. Локальные решения должны применяться последними; технические инварианты хранения секретов остаются отдельно от пользовательских соглашений.

## Коллизии skills

Совпадение ID возможно. Сейчас приоритет: built-in → external catalog → project-skills → local override. Более высокий слой вытесняет нижний; это не объединение текстов. Источники и вытесненные версии видны в `agent-kit project skills status` и effective-skills.md. В одном project-skills повтор имени отвергается; конфликт с пользовательской ссылкой клиента также может остановить публикацию.

Разные имена не исключают смысловой конфликт: два review-skill могут срабатывать на одну задачу и давать разные указания. Используйте имена с префиксом команды/проекта и точное описание условий применения. Для намеренной замены сохраняйте ID и используйте override. Предлагается диагностика коллизий до активации и явное подтверждение выбора источника; семантические конфликты требуют agent eval, одного сравнения ID недостаточно.
