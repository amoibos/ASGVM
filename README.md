# ASGVM

A pure-Python interpreter for the eight text adventures Angelsoft wrote for
Mindscape in 1985–86. It runs each game from its original data files
(`MESSAGE`, `VOCAB`, `TABLES`) and does not emulate the 8086.

All eight games shipped the same Turbo Pascal 3 engine (`GAME.COM` +
`GAME.000`) and differ only in their data. ASGVM is a port of that engine:
`gameengine/` is the shared VM, and each `games/<title>/` is a small binding
that holds configuration and data captured from the original.

| Title | Engine variant |
|---|---|
| James Bond 007: Goldfinger | A (40-byte `TABLES` records) |
| Indiana Jones in Revenge of the Ancients | A |
| Dick Francis: High Stakes | A |
| James Bond 007: A View to a Kill | B (47-byte records) |
| Rambo: First Blood Part II | B |
| Stephen King's The Mist | B |
| Voodoo Island | B |
| Forbidden Castle | B |

## Status

Every title can be played to the end. During development, a full winning
command list per game was replayed on the port and on the original (DOSBox-X),
and every answer was compared word for word:

| Title | Turns matching the original |
|---|---:|
| Goldfinger | 107 / 107 |
| A View to a Kill | 205 / 205 |
| Indiana Jones | 129 / 129 |
| High Stakes | 190 / 190 |
| Rambo | 84 / 84 |
| The Mist | 141 / 141 |
| Voodoo Island | 208 / 208 |
| Forbidden Castle | 178 / 178 |

The port also includes saving and restoring. Save files use the original's
`SAVE<n>` format and are written to the game's data directory.

## Requirements

- Python 3.10 or newer, standard library only.
- Windows, Linux or macOS. Single-key prompts such as `(MORE)` and yes/no
  questions use `msvcrt` on Windows and `termios` elsewhere.
- The original game files (see below).

## Game data

**The original game files are not included and must not be committed.** They
are copyrighted. Copy them from your own copy of each game into `data/`, one
folder per title. The repository contains these folders empty; `.gitignore`
excludes everything you put into them.

```
data/
  goldfinger/        MESSAGE  VOCAB  TABLES
  aviewtokill/       MESSAGE  VOCAB  TABLES
  indiana_jones/     ...
  rambo/
  the_mist/
  voodoo_island/
  forbidden_castle/
  high_stakes/
```

Only `MESSAGE`, `VOCAB` and `TABLES` are needed to play. Copying the whole
game folder (including `GAME.COM` and `GAME.000`) does no harm.

To keep the data somewhere else, point the environment variable `ASGVM_DATA`
at a folder with the same layout. To use a single game folder directly, pass
`--root`:

```bash
python -m games.rambo.play --root /path/to/rambo
```

## Playing

```bash
python run.py
```

This shows a menu of the eight titles. You can also start one directly, either
through the menu script (`python run.py rambo`) or as a module
(`python -m games.rambo.play`). On Windows, double-clicking `run.bat` opens the
same menu.

The package names are `goldfinger`, `aviewtokill`, `indiana_jones`, `rambo`,
`the_mist`, `voodoo_island`, `forbidden_castle` and `high_stakes`.

## Walkthroughs

`walkthroughs/<title>_mywalkthrough.txt` holds the winning command list of
each game, one command per `> ` line; lines starting with `#` are comments.
To watch a game play itself through to the end, feed it the list, for example:

```bash
(echo n; grep "^> " walkthroughs/rambo_mywalkthrough.txt | cut -c3-) | python -m games.rambo.play
```

The leading `n` answers the question whether to resume a saved game.

## Layout

| Path | Contents |
|---|---|
| `gameengine/data.py`, `packing.py`, `message.py`, `vocab.py`, `tables.py` | Readers for the original files: the 6-bit text packing, MESSAGE paging, VOCAB entries and TABLES records. |
| `gameengine/parser.py`, `grammar.py`, `input_encoding.py` | The parser and the sentence grammar. |
| `gameengine/activation.py`, `runtime_records.py`, `world.py` | Scene activation: the runtime records and the state they hold. |
| `gameengine/dispatcher.py`, `actions.py`, `predicates.py`, `pascal_set.py` | The per-turn dispatcher, the action opcodes and the predicate tests. |
| `gameengine/vm.py`, `vm_*.py` | `AsgVm`, the VM: message controls, actions, listings, people and timers. |
| `gameengine/gamecom.py`, `gamecom_*.py`, `message_controls.py` | The MESSAGE renderer of `GAME.COM`: conditionals, the control interpreter and the 80-column layout. |
| `gameengine/game.py`, `game_*.py`, `config.py` | `AsgGame`, the game loop: messages, movement, talk, vehicles, nouns; `AsgConfig` binds a title. |
| `gameengine/savegames.py`, `paging.py` | `SAVE<n>` files and the `(MORE)` pager. |
| `games/<title>/` | Per-title bindings: `config.py`, sometimes `records.py` (data captured from the original), and `play.py`. |
| `walkthroughs/` | A winning command list per title. |
| `docs/` | Reverse-engineering notes on the original engine and its files ([overview](docs/README.md)). |
| `run.py`, `run.bat` | The menu. |

## License

ISC, see [LICENSE](LICENSE). The license covers the code in this repository,
not the original games.
