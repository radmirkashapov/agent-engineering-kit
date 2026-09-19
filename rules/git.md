# Git

- Работай в feature branch; прямые push в `main` запрещены.
- Изменения доставляются через Pull Request и проходят CI.
- Не выполняй destructive reset пользовательских изменений.
- Commit messages: `<type>(<scope>): <description>`, description — с маленькой буквы, в повелительном наклонении.
- Допустимые types: `feat`, `fix`, `test`, `refactor`, `style`, `ci`, `chore`, `docs`.
- Branch: `<prefix>/dd-MM-yyyy-<description>`, prefix: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `ci`, `style`, `ai`.
- После изменения обновляй `app.version` согласно semantic versioning.
