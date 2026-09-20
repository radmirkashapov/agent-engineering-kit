# Политика безопасности

Секреты, credentials, внешние source trees, binaries, OAuth state и machine paths не коммитятся. Загрузки закрепляются полной revision или неизменяемой версией package. Candidates проверяются до атомарной активации; отклонённый candidate остаётся `BLOCKED` и не может заменить предыдущую `ACTIVE` revision.

Upstream skills проходят блокирующие проверки security, PII, license, code-integrity, Unicode и dependencies. Publication-only проверки schema/quality/lint от SkillEvaluator записываются отдельно, но не блокируют использование, если в upstream Agent Skills dialect нет специфичных для NVIDIA publishing metadata; kit независимо проверяет names, обязательные capabilities и границы.

Review ложных срабатываний привязан к revision и коду finding: принятые коды SkillSpector перечисляются в skill catalog только для точного неизменяемого commit. Любой новый код или revision блокирует активацию. Findings уровня `CRITICAL` и findings Gitleaks этим механизмом никогда не принимаются. Effective state записывает `PASS_WITH_REVIEWED_FINDINGS` и machine-local path отчёта.
