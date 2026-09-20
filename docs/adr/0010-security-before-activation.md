# ADR 0010: Security before activation

Статус: принято.

External candidate проходит source verification, SkillEvaluator, SkillSpector, Gitleaks, применимый Semgrep, instruction/model/compatibility checks до `ACTIVE`. Failure даёт `BLOCKED` и не заменяет предыдущую revision.
