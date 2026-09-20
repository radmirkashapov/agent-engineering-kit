# ADR 0005: Project memory вне kit

Статус: принято.

Working memory хранится в platform-native user data directory по stable project ID. Durable knowledge остаётся в source, tests и `docs/`; MCP и clients сохраняют собственное native state.
