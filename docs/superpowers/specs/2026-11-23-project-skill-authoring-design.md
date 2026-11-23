# Авторинг корпоративных и project-specific skills

## Статус

Предложено и согласовано для реализации.

## Контекст и цель

Agent Engineering Kit уже читает skills из встроенного корпоративного слоя, внешнего каталога, отдельного Git-репозитория `project-skills` и machine-local overrides. Однако автору приходится вручную копировать skill в правильный Git checkout, а `project init` не может объявить источник project skills в интерактивном режиме. Агентам также нужен компактный каталог доступных skills с их происхождением.

Цель — добавить безопасный authoring workflow, не меняя владение Git-историей: Kit подготавливает и проверяет файлы, а автор по-прежнему создаёт ветку, commit, push и PR/MR обычными средствами Git.

## Границы и инварианты

- Корпоративный bundled skill принадлежит корпоративному fork Kit и находится в `skills/first-party/<id>/`.
- Внешний корпоративный пакет продолжает объявляться только через `catalog/skills.yaml` и `locks/skills.lock.yaml`; исходники пакета не vendoring в Kit.
- Project-specific skill принадлежит отдельному Git-репозиторию из `.ai-team/project.yaml`, а не product repository.
- Пользовательский checkout `project-skills` может быть sibling-каталогом product repository, например `../delivery-platform-skills`; он не является managed checkout Kit.
- Managed checkout в data directory остаётся read-only техническим состоянием Kit: authoring-команды никогда не пишут в него.
- Новые команды не делают commit, push, merge, PR/MR или создание удалённого репозитория.
- `SKILL.md` и его frontmatter валидируются до любой записи в destination. Идентификатор совпадает с `name` и именем destination-каталога.
- Без явного `--replace` существующий destination не перезаписывается.

## Решение

### Корпоративный bundled skill

Добавить:

```text
agent-kit skills add --from <directory> [--id <id>] [--replace]
```

Команда принимает каталог skill, выводит destination в текущем Kit repository, валидирует его, затем копирует в `skills/first-party/<id>/`. Идентификатор берётся из frontmatter либо из явного `--id`; несовпадение является ошибкой. После копирования команда валидирует итоговую директорию и печатает последующие проверки, но не запускает `resync` и не изменяет Git index.

### Project-specific skill

Добавить:

```text
agent-kit project skills checkout --into <empty-directory>
agent-kit project skills add --from <directory> --checkout <directory> [--id <id>] [--replace]
agent-kit project skills index --checkout <directory>
```

`checkout` читает project-skills URL из найденного logical project и клонирует его только в явно указанный пустой каталог. `add` проверяет, что переданный checkout — Git repository, его `origin` нормализованно совпадает с URL manifest, а каталог не лежит внутри product repository или managed storage. Затем команда копирует skill в `<checkout>/skills/<id>/` и обновляет `skills/INDEX.md`. `index` пересобирает только этот tracked каталог из корректных дочерних `SKILL.md` и позволяет исправить ручные изменения или проверить freshness в CI.

Обе project-команды требуют настроенный `skills.repository`; ошибка объясняет, как добавить URL через `project init` или manifest.

### Настройка при `project init`

Добавить non-interactive параметры:

```text
--skills-repository-url <git-url>
--skills-default-branch <branch>   # default: main; допустим только вместе с URL
```

В интерактивном TTY, когда URL не передан, `project init` спрашивает один раз: пропустить настройку или ввести URL project-skills. Никакого prompt нет при перенаправленном stdin, при переданном URL или когда manifest уже существует. Init только записывает manifest; sibling checkout создаётся отдельной явной командой `project skills checkout`.

### Индексы для агентов

Используются два разных каталога, чтобы не смешивать авторский набор и effective runtime:

1. `project-skills/skills/INDEX.md` — tracked Markdown, содержащий только project-owned skills: ID, description, путь и назначение. Его обновляют `project skills add` и `project skills index`.
2. `effective-skills.md` — generated Markdown в native client installation, создаваемый при `resync`. Он перечисляет все effective skills из built-in, external catalog, project-skills и local overrides с source, status и provenance. Он не становится skill и не коммитится в project repository.

Client adapters получают generated index вместе с skills и могут ссылаться на него в своей документации. Конфликты ID показывают только выигравший effective source и список shadowed источников.

## Ошибки и восстановление

- Не-Git checkout, несовпадающий origin, невалидный `SKILL.md`, path traversal, symlink за пределы source/destination или конфликт ID завершаются до записи.
- Copy использует temporary sibling и атомарную замену. При ошибке прежний skill и `INDEX.md` остаются нетронутыми.
- `--replace` создаёт backup в Git working tree не должен: восстановление содержимого обеспечивается обычным Git. Команда требует destination без uncommitted изменений, иначе отказывается и предлагает пользователю решить конфликт через Git.
- Повторный `index` детерминирован: сортировка по ID и одинаковый результат при неизменном наборе skills.

## Проверяемые критерии

| Условие | Действие | Наблюдаемый результат |
|---|---|---|
| Валидный skill вне Kit | `skills add` | Появляется только `skills/first-party/<id>`, Git не коммитится |
| Неизвестный или конфликтующий bundled ID | `skills add` без `--replace` | Ошибка до записи |
| Настроенный project source и пустой sibling path | `project skills checkout` | Создан обычный Git checkout с правильным origin |
| Managed checkout либо product root | `project skills add --checkout` | Отказ без изменения файлов |
| Валидный project skill | `project skills add` | Skill и детерминированный `skills/INDEX.md` обновлены вместе |
| Интерактивный stdin без URL | `project init` | Предлагает URL или skip и сохраняет ответ в manifest |
| Не-TTY или явный URL | `project init` | Не читает stdin; manifest соответствует аргументам |
| Любой успешный `resync` | client sync | Публикует effective skills index с provenance |

## Вне области

- Git hosting API, создание remote repository, branch/commit/push/PR/MR.
- Автоматическое добавление sibling checkout в product workspace или Git metadata.
- Копирование внешних catalog skill packages в Kit.
- Изменение семантики local overrides и приоритета источников.
