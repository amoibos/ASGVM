# Runtime layout

The pure-Python interpreter does not execute DOS machine code, IDA databases,
assembly listings, trace captures, or recovery scripts. It does load the
original game files as data.

## Required Python source

- `gameengine/` — shared ASG/Mindscape VM, parser, renderer and world rules.
- `games/` — game bindings. Keep all subdirectories when `run.bat` offers all
  eight games; for a Goldfinger-only build keep `games/goldfinger/` plus
  `games/__init__.py`.
- `run.bat` — optional Windows multi-game launcher.

Data inspection lives in the development-only `python -m tools._inspect_game`
(RE/dev tooling under `tools/` is `_`-prefixed to mark it non-runtime); no
historical top-level game package is required.

Python's standard library is the only runtime dependency.

## Required original data per game

Each configured game directory needs only `MESSAGE`, `TABLES`, and `VOCAB`.
The launcher `.COM` and `GAME.000` are optional reverse-engineering/import
sources and are no longer required or read by gameplay. `SAVE1`…`SAVE9` are
optional user state.

## Development-only material

None of the following is needed to play:

- `tests/`, `tools/`, `docs/`, `traces/`;
- `*.idb`, `*.gpr`, `*.rep`, `*.asm`, `*.lst`, `*.map`, `*.idc`;
- debugger configs/servers and `MEMDUMP.BIN`;
- `rt_*.bin`, `renderer_dump.bin`, `block_cache.bin`, `rec68_page.bin`;
- DOS installer/title/command files, walkthroughs, audits and planning logs;
- `__pycache__/` directories.

These files should remain in the reverse-engineering archive until the VM is
finished, but should be excluded from a release package.
