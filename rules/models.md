# Models

- Committed agents/skills/config проверяются только по непустому `models/corporate.yaml`.
- `models/user.local.yaml` никогда не попадает в Git.
- При пустом corporate list user-local models допустимы только для local runtime.
- Skills объявляют capabilities; explicit model ID используется лишь при необходимости.
- Alias не является обходом allowlist: resolver всегда приводит его к corporate model.
- CI не читает user-local policy.
