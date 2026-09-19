# ADR-0007: изоляция upstream dependencies

Статус: принято.

## Контекст

Смешение first-party и third-party skills затрудняет license/security review и обновление.

## Решение

Third-party vendored content размещается только в `upstream/<name>/` с license, source и pinned revision. First-party content находится в `skills/`.

## Последствия

Provenance и ownership однозначны. Marketplace и автоматический updater не входят в MVP.
