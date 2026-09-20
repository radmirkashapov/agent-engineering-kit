# ADR 0002: Desired state и resync

Статус: принято.

Catalogs описывают желаемое состояние, locks — approved immutable revisions, local state — наблюдаемое состояние. `agent-kit resync` сравнивает их, устанавливает candidates, валидирует и только затем атомарно активирует. Повторный запуск идемпотентен.
