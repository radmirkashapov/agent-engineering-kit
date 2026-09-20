---
schema: agent-engineering-kit/security-tool/v1
id: skill-evaluator
name: NVIDIA SkillEvaluator
required: true
source: {type: github, repository: NVIDIA/SkillEvaluator}
version: {strategy: pinned, value: v0.3.0}
platforms: [macos, linux, windows]
permissions: {elevated: false}
network: {install: required, runtime: optional}
---
# Назначение
Оркестрирует статическую оценку Agent Skills и выдаёт структурированный отчёт.
# Почему используется
Даёт единый блокирующий gate поверх специализированных scanners.
# Threat model
Ищет опасные instructions, code patterns, утечки секретов и instruction collisions; экспериментальный инструмент не является sandbox.
# Источник
Официальный `NVIDIA/SkillEvaluator`, Apache-2.0, commit закреплён в lock.
# Поддерживаемые платформы
Python 3.12/3.13 на macOS, Linux и Windows.
# Установка
`uv tool install` из закреплённой Git revision в machine-local storage.
# Проверка
`skillevaluator validate <skills> --type skill --checks security,pii,license,code-integrity,unicode,dependency --no-dedup -r cli`. Специфичные для публикации проверки schema/quality/lint не блокируют использование чужого Agent Skills dialect; names и capabilities отдельно проверяет kit.
# Обновление
Только через review нового lock после сканирования candidate.
# Rollback
Вернуть предыдущий lock и выполнить `security update`.
# Удаление
Удалить управляемый root инструмента и state; Git не затрагивается.
# Permissions
Elevated privileges не нужны; доступ к candidate только на чтение.
# Network access
Нужен при установке; отдельные функции evaluator могут использовать provider API, базовый gate работает offline.
# Интеграция с agent-kit
Блокирующий orchestrator перед `ACTIVE`.
# Ограничения
Upstream помечает продукт как экспериментальный; результат дополняет, а не заменяет review.
