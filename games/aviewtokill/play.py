"""REPL entry point for A View to a Kill -- runs on the shared VM.

Thin binding: CONFIG + DATA (``config.py`` + ``records.py``). The shared VM
(``gameengine.AsgVm`` via ``gameengine.game.AsgGame``) consumes
``MESSAGE``/``VOCAB``/``TABLES`` plus the verb-response data table and runs
the game -- exactly like Goldfinger and the other Mindscape titles.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from gameengine.game import run
from games.aviewtokill.config import CONFIG

__all__ = ["play", "main", "config"]

from . import config  # noqa: E402,F401  (kept for stable import path)


def play(root: "Path | str | None" = None) -> None:
    """Run the A View to a Kill REPL on the shared VM."""
    run(CONFIG, root)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m games.aviewtokill.play")
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args()
    run(CONFIG, args.root)


if __name__ == "__main__":
    main()
