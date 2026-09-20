# ADR 0007: Local overrides

Статус: принято.

Overrides находятся вне checkout и поддерживают `extend`, `replace`, `disable`. Precedence: upstream < kit < project committed < user global < user project. Enforced policy ослабить нельзя.
