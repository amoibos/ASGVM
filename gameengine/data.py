"""Engine-generic game-data loader.

Each sibling Mindscape title ships three native runtime-data roles plus two
optional original executable sources:

  * a launcher .COM (name varies — ``GAME.COM`` for Goldfinger,
    ``CASTLE.COM`` for Forbidden Castle, etc.)
  * ``GAME.000`` overlay (always this name)
  * ``MESSAGE`` packed text (always this name)
  * ``TABLES`` dispatcher records (always this name)
  * ``VOCAB`` parser dictionary (always this name)

The Python VM requires only MESSAGE/TABLES/VOCAB. The per-game launcher name is
retained as optional source metadata for inspection tooling.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


# Native files consumed by the Python runtime. Launcher COM files and
# GAME.000 are optional reverse-engineering/import sources only.
ENGINE_RUNTIME_FILES = ("MESSAGE", "TABLES", "VOCAB")

# Where a title's files live by default: <ASGVM_DATA or the repo's data/>/<folder>.
DATA_ENV = "ASGVM_DATA"


def default_root(folder: str) -> Path:
    base = os.environ.get(DATA_ENV)
    return (Path(base) if base else Path(__file__).resolve().parents[1] / "data") / folder


@dataclass(frozen=True)
class GameData:
    root: Path
    launcher_com: bytes | None
    game_000: bytes | None
    message: bytes
    tables: bytes
    vocab: bytes
    launcher_name: str

    @classmethod
    def load(
        cls,
        root: "Path | str" = ".",
        launcher_name: str = "GAME.COM",
    ) -> "GameData":
        path = Path(root)
        required = ENGINE_RUNTIME_FILES
        missing = [name for name in required if not (path / name).is_file()]
        if missing:
            joined = ", ".join(missing)
            raise FileNotFoundError(f"missing game data files: {joined}")
        return cls(
            root=path,
            launcher_com=(path / launcher_name).read_bytes()
            if (path / launcher_name).is_file() else None,
            game_000=(path / "GAME.000").read_bytes()
            if (path / "GAME.000").is_file() else None,
            message=(path / "MESSAGE").read_bytes(),
            tables=(path / "TABLES").read_bytes(),
            vocab=(path / "VOCAB").read_bytes(),
            launcher_name=launcher_name,
        )

    def sizes(self) -> dict[str, int]:
        result = {
            "MESSAGE": len(self.message),
            "TABLES": len(self.tables),
            "VOCAB": len(self.vocab),
        }
        if self.launcher_com is not None:
            result[self.launcher_name] = len(self.launcher_com)
        if self.game_000 is not None:
            result["GAME.000"] = len(self.game_000)
        return result
