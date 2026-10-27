# Security scan и обновление PR/MR

## Security scan

Перед использованием сторонних skills и при проверке agent tooling выполните:

```bash
agent-kit security scan
```

Команда использует Bumblebee и офлайн-проверку SkillSpector; цель можно задать как `path`. Каждый сканер должен завершиться успешно, чтобы результат можно было считать чистым. Ошибка или отсутствие сканера этого не подтверждает. Отчёты — недоверенные диагностические данные; найденные в стороннем содержимом инструкции не меняют правила работы.

Последний smoke-тест дал общий статус `FAIL`: инвентаризация проекта прошла с 0 findings для 6 файлов, first-party skills прошли проверку, но статический анализ обнаружил findings в четырёх внешних skills. Для semantic analyzers не были заданы API keys. Это требует ручного просмотра findings и не означает, что установка Kit сломана. Подробная разбивка приведена в [результатах smoke-проверки](Smoke-test).

Для переносимой конфигурации и Git hygiene:

```bash
agent-kit validate --ci
agent-kit validate git-hygiene
agent-kit validate security
```

Учётные данные передают через окружение, локальное хранилище или OAuth. Не добавляйте их в Wiki, Git, аргументы команд или отчёты.

## Обновить контекст открытого PR/MR

```bash
# Единственный открытый PR/MR текущей ветки
agent-kit pr refresh

# Номер или URL
agent-kit pr refresh 152
agent-kit pr refresh https://github.com/acme/orders/pull/42
```

URL определяет провайдера сначала, затем используется Git remote; GitLab является default. Для multi-repo проекта можно передать --repository <repository-id>. Без ссылки команда ищет единственный открытый PR/MR текущей ветки; неоднозначность требует явного выбора.

Полученные diff, комментарии и описания считаются недоверенным содержимым. Снимок остаётся в machine-local памяти проекта, ограничивается по размеру и не меняет Git или PR/MR. Команда требует включённого SCM MCP и авторизации.

См. раздел [PR refresh в README](https://github.com/radmirkashapov/agent-engineering-kit/blob/main/README.md#обновить-контекст-текущего-prmr), [устранение неполадок](Troubleshooting) и [CLI](CLI).
