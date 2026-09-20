---
schema: agent-engineering-kit/security-tool/v1
id: bumblebee
name: Perplexity Bumblebee
required: false
source: {type: github, repository: perplexityai/bumblebee}
version: {strategy: pinned, value: v0.1.2}
platforms: [macos, linux]
permissions: {elevated: false}
network: {install: required, runtime: optional}
---
# Назначение
Инвентаризация machine-level компонентов и проверка exposure в AI development environment.
# Почему используется
Показывает поверхность supply chain после bootstrap, обновлений и во время расследования incidents.
# Threat model
Неожиданные agents, MCP, skills и exposures; инструмент не предназначен для research или валидации skills.
# Источник
Официальный `perplexityai/bumblebee`, Apache-2.0, exact revision в lock.
# Поддерживаемые платформы
macOS и Linux; Go 1.25+. Windows имеет статус `NOT_SUPPORTED`, не `PASS`.
# Установка
Закреплённый `go install` в machine-local storage.
# Проверка
Инвентаризация по запросу после bootstrap или обновления toolchain.
# Обновление
Через проверенный lock.
# Rollback
Переустановить предыдущую закреплённую версию.
# Удаление
Удалить управляемый binary и state.
# Permissions
Без elevated privileges; доступ только на чтение к местам инвентаризации.
# Network access
Сеть нужна при установке; runtime-доступ зависит от выбранных проверок.
# Интеграция с agent-kit
Необязательный компонент doctor/inventory, не блокирующий activation gate.
# Ограничения
Upstream ещё молодой; поддержка платформ ограничена.
