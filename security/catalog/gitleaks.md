---
schema: agent-engineering-kit/security-tool/v1
id: gitleaks
name: Gitleaks
required: true
source: {type: github, repository: gitleaks/gitleaks}
version: {strategy: pinned, value: v8.30.1}
platforms: [macos, linux, windows]
permissions: {elevated: false}
network: {install: required, runtime: false}
---
# Назначение
Ищет секреты в candidate и содержимом Git.
# Почему используется
Предотвращает активацию и commit утёкших credentials.
# Threat model
Токены, ключи, пароли и credentials с высокой entropy; не проверяет действительность секрета.
# Источник
Официальный `gitleaks/gitleaks`, MIT, точный release commit в lock.
# Поддерживаемые платформы
macOS, Linux, Windows.
# Установка
`go install github.com/zricethezav/gitleaks/v8@<version>` в isolated `GOBIN`: repository переименован в `gitleaks/gitleaks`, но upstream `go.mod` сохраняет legacy module path.
# Проверка
Вызывается security pipeline и Git hygiene.
# Обновление
Изменить lock после валидации candidate.
# Rollback
Вернуть предыдущую версию module.
# Удаление
Удалить root управляемого binary.
# Permissions
Без elevated privileges; доступ к repository и candidate только на чтение.
# Network access
Только при установке.
# Интеграция с agent-kit
Блокирующий scanner для external skills и tracked/staged state.
# Ограничения
Ложные срабатывания требуют review правила; секреты нельзя печатать в diagnostics.
