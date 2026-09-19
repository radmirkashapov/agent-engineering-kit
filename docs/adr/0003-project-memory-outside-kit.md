# ADR-0003: project memory вне kit

Статус: принято.

## Контекст

Mutable summaries, checkpoints и sessions не универсальны и не должны загрязнять global repository.

## Решение

Local memory хранится в user data directory как `projects/<project-id>/`. Root hash защищает от collision. Durable knowledge остаётся в project source/docs/tests; MCP-native state остаётся у MCP.

## Последствия

Git pull kit безопасен для project state. Local memory нужно отдельно backup'ить при необходимости и нельзя считать authoritative.
