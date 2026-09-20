# Автоматическая установка

`agent-kit security install` использует `uv tool install` или `go install` в user-local data directory. Команда никогда не выполняет `curl | bash`, не требует elevated permissions и идемпотентна относительно lock state. `update` переустанавливает тот же approved lock; изменение upstream требует review и commit lock-файла.
