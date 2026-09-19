# Security

- Secrets допускаются только через environment variables или внешний secret store.
- В committed config сохраняй `env:VARIABLE`, никогда value.
- Enforced security invariants нельзя ослабить local override.
- Corporate model policy authoritative для committed definitions.
- Перед commit запускай `agent-kit validate git-hygiene` и `agent-kit validate security`.
- Не печатай secrets в logs, doctor output и diagnostic reports.
