# ADR 0009: Locking external dependencies

Статус: принято.

Kit checkout и external dependencies обновляются независимо. Каждый external component имеет full revision; `latest` не активируется автоматически. Previous validated revision сохраняется для rollback.
