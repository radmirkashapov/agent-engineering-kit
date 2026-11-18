# Git

- Работай в отдельной ветке; прямые отправки изменений в `main` запрещены.
- Изменения доставляются через Pull Request и проходят CI.
- Не выполняй разрушительный сброс пользовательских изменений.
- Формат сообщения коммита: `<type>(<scope>): <description>`; описание начинается со строчной буквы и формулируется в повелительном наклонении.
- Допустимые типы: `feat`, `fix`, `test`, `refactor`, `style`, `ci`, `chore`, `docs`.
- Формат ветки: `<prefix>/dd-MM-yyyy-<description>`; допустимые префиксы: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `ci`, `style`, `ai`.
- После изменения обновляй `app.version` по правилам семантического версионирования.
- Если commit выполняет AI-агент, добавляй в конец сообщения Git trailers, сохраняя автора Git разработчика:

  ```text
  Agent-Generated: true
  Agent-Client: <client-id>
  ```

  `<client-id>` — стабильный ID активного harness: `codex`, `claude-code`, `opencode`, `cline` или `claude-desktop`. Не добавляй trailers к коммитам, созданным разработчиком вручную.
