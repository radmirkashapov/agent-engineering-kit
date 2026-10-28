---
version: 1
name: agent-evaluation
description: Use when prompts, roles, skills, retrieval, models, or tool routing change and probabilistic agent behavior needs a repeatable baseline comparison
policy: configurable
requires:
  model_capabilities:
    - reasoning
    - coding
    - tool_use
---

# Оценка поведения агента

## Назначение

Измеряй поведение AI-агента на представительной выборке и сохраняй достаточно трассировок для объяснения регрессий. Демонстрация на выбранных примерах не является оценкой выпуска.

## Когда применять

- изменились prompt, role, skill, модель, retrieval или маршрутизация инструментов;
- успех зависит от вероятностного выбора, а не только от exit code;
- нужно сравнить candidate с baseline или определить порог выпуска;
- появились опасные, лишние или пропущенные tool calls.

## Входные данные

Зафиксируй версии baseline/candidate, модель, tools, policy, retry и dataset revision. Выборка должна включать типовые, граничные, adversarial и failure cases и не должна состоять только из примеров, использованных при настройке.

## Порядок работы

1. Переведи требования поведения в измеряемые dimensions и критические запреты.
2. Используй exact assertions для результата, маршрута и policy там, где ответ однозначен.
3. Для недетерминированного качества задай rubric с примерами и откалибруй judge на human-reviewed cases.
4. Запусти baseline и candidate в одинаковой конфигурации; для изменчивых результатов используй повторения.
5. Сохрани безопасные traces: testcase, версии, tool decisions, редактированные arguments, outcomes, retries, final output и scores.
6. Сравни распределения, разбери критические случаи и сгруппируй failures по причине.

## Результат

Передай описание dataset и coverage, assertions/rubric, заранее заданные thresholds, таблицу baseline/candidate, failure clusters, representative traces, ограничения и verdict. Средний score не скрывает критическую policy-регрессию.

## Остановка и эскалация

Не давай положительное заключение без воспроизводимой выборки, диагностических traces и заранее заданного release gate. Если данные чувствительны, редактируй содержимое и ограничивай retention, но не удаляй доказательства всех failures. Нестабильный judge требует human review.

## Типовые ошибки

| Ошибка | Коррекция |
|---|---|
| Десять удачных ручных примеров | Отдели tuning set и собери представительную независимую выборку |
| Всё оценивает LLM judge | Exact behavior проверяй детерминированными assertions |
| Сохраняется только aggregate score | Храни безопасные traces и анализируй failure clusters |
| Threshold выбран после результата | Зафиксируй release gate до запуска candidate |
