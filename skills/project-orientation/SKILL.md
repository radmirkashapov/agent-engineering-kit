---
version: 1
id: project-orientation
description: Определить logical project, компоненты, документацию и effective configuration
policy: configurable
requires:
  model_capabilities:
    - reasoning
    - tool_use
---

# Project orientation

Найди ближайший `.ai-team/project.yaml`, проверь `project.id`, repositories и components. Прочитай documentation index и затем `agent-kit config explain`. Git root не подменяет logical project root.
