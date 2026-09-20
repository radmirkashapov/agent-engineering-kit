# Skills

Собственные skills находятся в `first-party/` и разрабатываются вместе с kit. Сторонние skills никогда не копируются сюда: `registry.yaml` указывает на desired-state catalog, а `agent-kit resync` устанавливает pinned revision во внешний machine-local storage.

Для Superpowers source of truth — `catalog/skills.yaml`, immutable revision — `locks/skills.lock.yaml`, active checkout — `<data>/installations/skills/superpowers/revisions/<revision>/`. Только candidate, прошедший source, SkillEvaluator, SkillSpector, Gitleaks, Semgrep, model-policy и compatibility checks, получает состояние `ACTIVE`.
