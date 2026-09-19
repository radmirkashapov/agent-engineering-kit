# Review

- Приоритет: correctness, security, data loss, compatibility, observability, test gaps.
- Каждый finding содержит severity, точный location, impact и исправление.
- Проверяй assumptions по source/tests, а не по имени symbol.
- Отдельно проверяй границы state и возможность попадания local-only файлов в Git.
- Если blocking findings нет, сообщи это явно.
