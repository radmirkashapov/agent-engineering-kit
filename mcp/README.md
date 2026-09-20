# MCP registry

`registry.yaml` хранит configuration intent, source, install method, conditional activation и policy; `locks/mcp.lock.yaml` фиксирует approved revisions. Secrets задаются только как `env:VARIABLE` или native OAuth.

Native state остаётся во storage самого MCP. В частности, базы codebase-memory, Serena memory и client sessions не переносятся в project memory. Kit хранит только mapping logical project → integrations в локальной директории `projects/<project-id>/integrations/`.

Core: Codebase Memory отвечает за graph/impact, Serena — symbols/refactoring, Context7 — актуальную документацию; они не взаимозаменяемы. Conditional GitHub/GitLab/SonarQube/Playwright/Atlassian активируются project signals, причём multi-repo может включить несколько SCM одновременно.

## Границы и routing

| MCP | Единственная основная роль | Когда не вызывать |
|---|---|---|
| Codebase Memory | architecture graph, callers/callees, cross-repo impact | для точечного чтения уже известного symbol |
| Serena | symbol lookup, references, semantic editing/refactoring | для общей dependency map всего workspace |
| Context7 | актуальная внешняя документация library/framework/API | для анализа локального source |
| GitHub / GitLab | provider-specific repository, issue и PR operations | если provider не обнаружен в logical project |
| SonarQube | существующие server-side quality findings | вместо локальных tests или review |
| Playwright | browser interaction и web verification | для non-web project |
| Atlassian | Jira/Confluence collaboration context | без настроенного tenant/OAuth |

Сначала выбирается один MCP по требуемому виду evidence. CBM и Serena разрешено сочетать последовательно: graph определяет область impact, затем Serena уточняет symbols и references. Параллельный широкий поиск обоими инструментами без конкретной причины считается избыточным. Каждый MCP сохраняет native state отдельно и регистрируется namespaced именем `agent-kit-<id>`, поэтому команды, databases и caches не пересекаются.

CBM ставится pinned release installer из exact source revision с explicit release URL и обязательной SHA-256 verification; `curl | bash` не используется. Это соответствует v0.11, где `update` только направляет к локальному installer script.
