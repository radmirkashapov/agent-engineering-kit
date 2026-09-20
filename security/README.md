# Security toolchain

Security tools объявляются в `catalog/security.yaml`, фиксируются в `locks/security.lock.yaml`, устанавливаются вне Git и описываются contracts из `security/catalog/`. External skill достигает `ACTIVE` только после проверки source и security.

`SkillEvaluator` оркестрирует проверки; `SkillSpector`, `Semgrep` и `Gitleaks` являются blocking scanners. `Bumblebee` проверяет machine inventory/exposure и никогда не получает `PASS` на неподдерживаемой platform.
