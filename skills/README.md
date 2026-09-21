# Skills

Собственные skills находятся в `first-party/` и разрабатываются вместе с набором. Сторонние skills никогда не копируются сюда: `registry.yaml` указывает на каталог желаемого состояния, а `agent-kit resync` устанавливает закреплённую ревизию во внешнее локальное хранилище машины.

Для Superpowers источником истины служит `catalog/skills.yaml`, неизменяемая ревизия записана в `locks/skills.lock.yaml`, а активная рабочая копия находится в `<data>/installations/skills/superpowers/revisions/<revision>/`. Только кандидат, прошедший проверку источника, SkillEvaluator, SkillSpector, Gitleaks, Semgrep, политику моделей и совместимость, получает состояние `ACTIVE`.
