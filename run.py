"""Pick a title and play it: ``python run.py`` (or ``python run.py rambo``)."""

from __future__ import annotations

import sys
from importlib import import_module

# Menu key -> games/<package>.
TITLES = {
    "G": "goldfinger",
    "V": "aviewtokill",
    "I": "indiana_jones",
    "R": "rambo",
    "M": "the_mist",
    "O": "voodoo_island",
    "F": "forbidden_castle",
    "H": "high_stakes",
}


def main(argv: list[str]) -> None:
    from gameengine.game import run

    configs = {key: import_module(f"games.{name}.config").CONFIG for key, name in TITLES.items()}
    if argv:
        choice = argv[0]
    else:
        print("ASGVM\n")
        for key, config in configs.items():
            print(f"  [{key}] {config.display_name}")
        print("  [Q] Quit\n")
        try:
            choice = input("Choice: ").strip()
        except EOFError:
            return
    choice = choice.upper()
    if choice == "Q":
        return
    key = next((k for k, name in TITLES.items() if choice in (k, name.upper())), None)
    if key is None:
        sys.exit(f"unknown title: {choice}")
    run(configs[key])


if __name__ == "__main__":
    main(sys.argv[1:])
