# Дизайн базовых SDLC-skills и профилей

## Контекст

После расширения набора ролей Kit должен поставлять не только описание ответственности, но и небольшие переиспользуемые workflows для типовых инженерных решений. Skill не подменяет роль, профиль или harness: роль определяет владельца результата, skill помогает выполнить конкретный вид работы, профиль ограничивает доступные возможности, а harness исполняет агентный цикл.

## Базовый набор

К существующим девяти first-party skills добавляются семь:

1. `requirements-analysis` — превращает неполный запрос в scope, non-goals, assumptions и проверяемые acceptance criteria;
2. `architecture-decision` — сравнивает технические варианты и фиксирует решение, последствия, миграцию и rollback;
3. `test-design` — строит risk-based test matrix по критериям приёмки и изменённым контрактам;
4. `threat-modeling` — описывает assets, trust boundaries, abuse cases, mitigations и residual risk;
5. `agent-evaluation` — разделяет deterministic checks и probabilistic evals, задаёт dataset, rubric, baseline и thresholds;
6. `release-readiness` — собирает evidence matrix для compatibility, rollout, observability и recovery;
7. `incident-analysis` — восстанавливает timeline и causal chain без преждевременного назначения root cause.

Итоговый first-party набор содержит ровно шестнадцать skills. Новые skills остаются самодостаточными: в первой версии им не нужны scripts, assets или объёмные references.

## Контракт skill

Каждый новый `SKILL.md` содержит английское поле `description`, начинающееся с `Use when`, и русскоязычную инструкцию. Description описывает только условия выбора skill, а не пересказывает workflow. Тело содержит:

- назначение и наблюдаемые triggers;
- входные данные и границы применимости;
- компактный порядок работы;
- обязательную форму результата;
- stop/escalation conditions;
- типовые ошибки, которые нельзя скрывать успешным verdict.

Skills не дают разрешения на merge, deploy, изменение внешней системы, чтение секретов или иные действия за пределами запроса пользователя и effective policy.

## Профили

Новые profile IDs не вводятся. Сохраняются `developer`, `reviewer` и `tester`, чтобы не раздувать публичный capability contract:

- `developer` получает роли требований и архитектуры, а также skills анализа требований, архитектурного решения и проектирования тестов;
- `reviewer` получает роль security engineer и skill threat modeling рядом с независимым code review;
- `tester` получает evaluation/release roles и skills test design, agent evaluation, release readiness и incident analysis.

Профиль перечисляет доступные роли и skills, но не требует запускать их все и не задаёт линейный workflow. Read-only permissions `reviewer` и `tester` сохраняются.

## Проверка

Тесты должны доказать:

- наличие ровно шестнадцати first-party skills;
- точные IDs и capability requirements семи новых skills;
- discriminating descriptions вида `Use when...`;
- наличие обязательных разделов и русскоязычность инструкций;
- точную связь трёх профилей с новыми ролями и skills;
- отсутствие расширения permissions существующих профилей;
- прохождение полного pytest и `agent-kit validate --ci`.

Для каждого skill выполняется отдельный RED/GREEN application scenario: сначала наблюдается baseline без skill, затем тот же тип задачи проверяется со skill. Выявленные пропуски становятся причиной конкретных инструкций, а не общим методологическим текстом.

## Источники решения

- Agent Skills specification закрепляет переносимый `SKILL.md` и progressive disclosure: <https://agentskills.io/specification>.
- Anthropic рекомендует простые композиционные workflows и явные stopping conditions: <https://www.anthropic.com/engineering/building-effective-agents>.
- OpenAI рекомендует traces для диагностики и datasets/eval runs для повторяемых оценок: <https://developers.openai.com/api/docs/guides/agent-evals>.
- NIST SSDF рассматривает безопасность как проверяемые outcomes на всём SDLC: <https://csrc.nist.gov/projects/ssdf>.
- Google Engineering Practices разделяет design, functionality, complexity, tests и documentation в code review: <https://google.github.io/eng-practices/review/reviewer/looking-for.html>.

## Не входит в объём

- новые MCP, модели или permissions;
- обязательный workflow engine;
- изменение ролей из первого PR;
- автоматический merge, release или deployment;
- изменение `project init`;
- изменение project-skills repository workflow.
