# Local overrides

Tracked каталог содержит только документацию. Реальные overrides хранятся вне repository:

```text
<data>/overrides/
├── global/{rules,skills,agents,mcp}/
└── projects/<project-id>/{rules,skills,agents,mcp}/
```

Structured overlay:

```yaml
target: code-review
override:
  mode: extend
  tools:
    add:
      - custom-local-tool
```

`extend` дополняет target, `replace` заменяет configurable target, `disable` выключает только не-enforced target. Unknown target и отключение enforced skill/agent — validation error. Model overrides действуют только в local runtime и подчиняются corporate policy для Git definitions.
