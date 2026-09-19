# ADR-0005: structured local overrides

Статус: принято.

## Контекст

Полные локальные копии rules и agents скрывают divergence и усложняют audit.

## Решение

Overrides хранятся вне repository как overlays с target и mode `extend`, `replace` или `disable`. Precedence: upstream, kit, project, user global, user project. Enforced/locked values не ослабляются.

## Последствия

Provenance видим, collisions валидируются. Некоторые сложные merge semantics в MVP намеренно не автоматизированы.
