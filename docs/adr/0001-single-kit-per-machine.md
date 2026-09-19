# ADR-0001: один kit на машину

Статус: принято.

## Контекст

Копии policy в каждом repository расходятся и усложняют обновление клиентов.

## Решение

На машине используется один deployment checkout. Platform-aware resolver разделяет repository, runtime, project memory и overrides. Рабочие projects ссылаются на kit через thin client adapters.

## Последствия

Обновление централизовано; session фиксирует Git revision. Для разработки kit нужна отдельная branch/worktree, а dirty deployment checkout не обновляется автоматически.
