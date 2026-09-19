# MCP registry

`registry.yaml` хранит configuration intent: transport, command/endpoint, mapping environment и policy. Secrets задаются только как `env:VARIABLE`.

Native state остаётся во storage самого MCP. В частности, базы codebase-memory, Serena memory и client sessions не переносятся в project memory. Kit хранит только mapping logical project → integrations в локальной директории `projects/<project-id>/integrations/`.

Каталоги `core/`, `scm/`, `quality/`, `collaboration/` зарезервированы для дополнительной документации и presets, но registry остаётся единой точкой discovery.
