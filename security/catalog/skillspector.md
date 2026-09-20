---
schema: agent-engineering-kit/security-tool/v1
id: skillspector
name: NVIDIA SkillSpector
required: true
source: {type: github, repository: NVIDIA/SkillSpector}
version: {strategy: pinned, value: v2.11.2}
platforms: [macos, linux, windows]
permissions: {elevated: false}
network: {install: required, runtime: false}
---
# Назначение
Статически анализирует структуру и инструкции skills.
# Почему используется
Специализированный анализ дополняет универсальные scanners.
# Threat model
Подозрительные инструкции, обфускация и рискованное содержимое skill; candidate не выполняется.
# Источник
Официальный `NVIDIA/SkillSpector`, Apache-2.0, exact commit в lock.
# Поддерживаемые платформы
Python runtime на macOS, Linux и Windows.
# Установка
Закреплённая Git revision через `uv tool install`.
# Проверка
Запускается SkillEvaluator через явно заданный executable.
# Обновление
Candidate → сканирование → review lock → активация.
# Rollback
Восстановить предыдущий lock и установку инструмента.
# Удаление
Удалить machine-local root инструмента.
# Permissions
Без elevated privileges, доступ к candidate только на чтение.
# Network access
Сеть нужна только при установке; базовый runtime работает offline.
# Интеграция с agent-kit
Обязательный блокирующий scanner external skills.
# Ограничения
Эвристики допускают ложные срабатывания и требуют review.
