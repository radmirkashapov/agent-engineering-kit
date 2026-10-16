from __future__ import annotations

import getpass


def main() -> None:
    print(f"Привет, {getpass.getuser()}!")


if __name__ == "__main__":
    main()
