---
version: 1
name: release-readiness
description: Use when a reviewed change approaches merge, artifact publication, deployment, migration, or staged exposure and current readiness evidence must be assembled
policy: configurable
requires:
  model_capabilities:
    - reasoning
    - coding
    - tool_use
---

# Готовность выпуска

## Назначение

Дай проверяемое заключение по каждой границе выпуска. Готовность к merge не равна готовности к deployment, миграции или включению функции для всех пользователей.

## Когда применять

- изменение приближается к merge, публикации артефакта или развёртыванию;
- есть миграция, совместимость смешанных версий или внешний эффект;
- нужен staged rollout с измеримыми условиями продолжения и остановки;
- доказательства собраны разными ролями и средами.

## Входные данные

Собери точный commit/artifact, acceptance evidence, CI, review, security/evaluation verdicts, compatibility, migration rehearsal, observability, runbook и recovery proof. Укажи время, среду и владельца каждого доказательства.

## Порядок работы

1. Раздели gates: merge, build/publish, deploy, migrate и expose.
2. Для каждого применимого требования поставь `PASS`, `FAIL`, `BLOCKED`, `UNVERIFIED` или `N/A` с основанием.
3. Проверь соответствие доказательств текущему commit, target environment и версии конфигурации.
4. Опиши rollout stages, объём воздействия, success metrics, pause/abort thresholds и владельцев.
5. Проверь rollback или forward recovery с учётом данных, смешанных версий и внешних эффектов.
6. Подготовь release notes, operator actions, known limitations и период наблюдения.

## Результат

Передай evidence matrix, отдельный verdict для каждого gate, план rollout, наблюдаемость, recovery, коммуникацию и нерешённые риски. Заключение не выполняет merge или deployment и не заменяет отдельную авторизацию.

## Остановка и эскалация

Не давай GO для gate с обязательным `FAIL`, `BLOCKED` или `UNVERIFIED`. Устаревший либо неподходящий по среде результат не считается `PASS`. Если rollback разрушает данные, требуется проверенный forward recovery и решение уполномоченного владельца риска.

## Типовые ошибки

| Ошибка | Коррекция |
|---|---|
| Зелёные unit tests означают готовность выпуска | Собери evidence по интеграции, среде, наблюдаемости и recovery |
| Merge и включение на 100% объединены одним verdict | Дай отдельное решение по каждому gate |
| Rollback равен возврату commit | Проверь данные, протоколы и внешние эффекты |
| Метрики добавят после rollout | Success и abort signals должны существовать до воздействия |
