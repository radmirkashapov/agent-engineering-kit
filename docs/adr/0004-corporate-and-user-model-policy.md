# ADR-0004: corporate и user-local model policy

Статус: принято.

## Контекст

Committed agent definition должна воспроизводиться у команды, а разработчику могут требоваться локальные experimental models.

## Решение

Непустой `models/corporate.yaml` authoritative для Git. `models/user.local.yaml` исключён из Git и расширяет только runtime. При пустом corporate list local policy допустима для локального запуска, но не становится portability guarantee.

## Последствия

CI всегда игнорирует local file. Validator блокирует explicit references вне effective baseline и проверяет providers/duplicates/schema.
