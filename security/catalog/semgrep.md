---
schema: agent-engineering-kit/security-tool/v1
id: semgrep
name: Semgrep Community Edition
required: true
source: {type: github, repository: semgrep/semgrep}
version: {strategy: pinned, value: 1.177.0}
platforms: [macos, linux, windows]
permissions: {elevated: false}
network: {install: required, runtime: false}
---
# Назначение
Статический анализ исполняемого кода внутри skills.
# Почему используется
Находит опасные patterns работы с processes, filesystem и network там, где анализа только Markdown недостаточно.
# Threat model
Вредоносный или небезопасный встроенный код; semantics Markdown анализируется не полностью.
# Источник
Официальный `semgrep/semgrep`, LGPL-2.1, package version и commit закреплены.
# Поддерживаемые платформы
macOS, Linux, Windows в поддерживаемом Python environment.
# Установка
Закреплённая версия PyPI через изолированный `uv tool`.
# Проверка
Запускается из SkillEvaluator security profile.
# Обновление
Только после обновления lock и теста совместимости.
# Rollback
Повторно установить предыдущую версию package.
# Удаление
Удалить machine-local root инструмента.
# Permissions
Без elevated privileges, сканирование только на чтение.
# Network access
Базовый runtime работает offline; cloud rules не используются.
# Интеграция с agent-kit
Проверка блокирует активацию при наличии кода; применимость фиксируется в evidence.
# Ограничения
Без релевантных rules не доказывает безопасность.
