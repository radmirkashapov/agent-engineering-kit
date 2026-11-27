# Локальная конфигурация: новые команды

Эта страница описывает реализацию в ветке разработки; до её установки команды могут отсутствовать. Исторический аудит на странице Local-customization относится к baseline 4ca8be8.

## Выбор любой модели клиента

```bash
agent-kit models enforcement off --scope global --resync
agent-kit models enforcement status
agent-kit models enforcement on --scope global --resync
```

Для отдельного проекта используйте --scope project из его root. Проектное значение применяется после глобального. Каталог корпоративных providers продолжает синхронизироваться; ключи и подписки клиента не меняются. CI валидирует committed baseline. Сгенерированные копии skills и effective agents/rules освобождаются от model metadata, но сохраняют model_capabilities. Не закладывайте обязательный vendor в обычную прозу: структурированная политика должна оставаться единственным источником model restrictions.

## Выбор подмножества

```bash
agent-kit override select skills --allow code-review verification --scope global
agent-kit override select agents --allow developer reviewer --scope global
agent-kit override select rules --block models --scope global
agent-kit override select mcp --allow codebase-memory serena --scope global
agent-kit override select conventions --block git-workflow --scope project
agent-kit resync --no-update
```

ID соглашений узнавайте из фактического conventions/*.yaml; git-workflow в примере замените существующим ID. Allow пустой означает отсутствие фильтра; block исключает перечисленные ID. Списки global/project пересекаются: проект не разблокирует глобальное исключение. Каждая команда заменяет списки только одного типа в выбранном access.yaml. Для сброса фильтра повторите select без --allow/--block. Правила технического хранения секретов не являются пользовательской convention.

Conventions доступны через `agent-kit override set conventions <id> --mode extend|replace|disable --from <yaml> --reason <text> --scope global|project`. Передавайте value с description/requirements для изменения соглашения. Для disable достаточно пустого YAML-объекта. Reset выполняется через override reset conventions.

## Коллизии skills

```bash
agent-kit project skills status
agent-kit skills explain code-review
agent-kit skills prefer code-review --source project-skills --scope project
agent-kit resync --no-update
```

Допустимые источники: built-in, external-catalog, project-skills, local-override. При совпадении имён в нескольких внешних пакетах уточните `--catalog-id <id>`. Если выбранный источник исчезнет, публикация завершится ошибкой вместо молчаливой смены реализации. Для сброса всех локальных настроек skill используйте `agent-kit skills reset <id> --scope project`; для сброса только выбора источника удалите `<data>/overrides/<scope>/skill-sources/<id>.yaml`. Не путайте совпадение ID с конфликтом смысла: для навыков с разными именами нужны понятные описания условий запуска и ручное отключение противоречащих навыков.

## Проектная публикация

Полные runtime-копии находятся в `<data>/installations/clients/projects/<project-id>/skills`. В нативных каталогах продукта `.agents/skills` (Codex/OpenCode), `.claude/skills`, `.cline/skills` создаются namespaced загрузчики. Они запрашивают тело через `agent-kit skills read <id> --project-id <id>`. Команда проверяет ближайший project.yaml: из чужого root или независимого nested проекта выдача отклоняется. Такие сгенерированные ссылки не следует коммитить.

Это контроль маршрутизации Kit, а не файловая песочница: пользователь и инструменты клиента сохраняют доступ к локальной файловой системе. В унаследованном discovery клиента может быть видно название загрузчика родителя, но команда не выдаст его инструкции из другого logical project. Существующую сессию клиента после resync перезапустите.

Каталоги discovery сверены с документацией [OpenCode](https://opencode.ai/docs/skills/), [Claude Code](https://code.claude.com/docs/en/skills), [Cline](https://github.com/cline/cline/blob/main/docs/customization/skills.mdx) и [Codex](https://learn.chatgpt.com/docs/build-skills). Поддержка этих путей не доказывает успешное использование skill моделью: это проверяется отдельно в клиентской сессии.

## Автоматическая память

Init устанавливает post-commit/post-checkout/post-merge hooks, если соответствующий hook свободен или уже управляется Kit. Пользовательские hooks сохраняются. Resync повторяет проверку изменившегося проекта, поэтому работает как резервная точка запуска. Индексация выполняется фоновым Python-процессом, не отменяет commit при ошибке и сохраняет результат в `<data>/projects/<id>/state/memory-result-<root-hash>.json`.

При проблеме проверьте этот результат и выполните `agent-kit project memory-refresh`. Отсутствующий MCP означает SKIPPED, а не построенный индекс. На машине должны быть доступны исполнительные файлы MCP и agent-kit в PATH Git hooks. Git for Windows запускает эти hooks через sh; bootstrap для Windows остаётся PowerShell-установщиком.
