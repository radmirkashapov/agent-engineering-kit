# ADR 0003: Не vendor third-party skills

Статус: принято.

В Git хранятся только source metadata, lock и installation/security contracts. Third-party source устанавливается в user-local data storage. Submodules, subtree, copied forks и `vendor/` запрещены.
