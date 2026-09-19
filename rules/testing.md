# Testing

- Каждое поведение покрывай позитивным и релевантным негативным сценарием.
- Проверяй public behavior, а не внутреннюю реализацию.
- Для filesystem tests используй isolated temporary directories.
- Test не должен зависеть от user-local overrides, home directory или network.
- Перед delivery запускай targeted tests и полный suite; CI работает без local inputs.
