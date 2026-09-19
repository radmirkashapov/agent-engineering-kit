# ADR-0002: logical project не равен Git repository

Статус: принято.

## Контекст

Один продукт может быть monorepo, набором repositories или иметь несколько components внутри одного repository.

## Решение

Identity и topology задаёт `.ai-team/project.yaml` в logical root. Manifest хранит stable `id`, repositories, components и documentation roots.

## Последствия

Agents всегда начинают с manifest. Git operations могут выполняться в нескольких roots; memory и integrations адресуются по project ID.
