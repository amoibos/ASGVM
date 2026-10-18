# Architecture

## The original engine

The eight Angelsoft/Mindscape adventures of 1985–86 are one Turbo Pascal 3
program with different data. The program comes in two files:

| File | Part | Contents |
|---|---|---|
| `GAME.COM` (`CASTLE.COM` in Forbidden Castle) | resident | TP3 runtime, keyboard and screen, the MESSAGE file reader and its 6-bit codec, the text formatter, file I/O |
| `GAME.000` | overlay | the VOCAB and TABLES loaders, scene activation, the parser and sentence grammar, the per-turn dispatcher, the action VM, people and timers, save/restore |

Neither file contains game content. Everything a game says and does is in
three data files:

| File | Contents |
|---|---|
| `MESSAGE` | all text, written in a small control language (conditions, actions, lists, references to other records) |
| `VOCAB` | the words the parser knows, each with its class, kind and value |
| `TABLES` | the world: people, objects, rooms, routes and the start state |

So the engine is a virtual machine: it loads the data, runs the records the
player's commands select, and those records decide what happens. The port
reimplements that machine in Python and runs the data unchanged.

### Two engine variants

The engine exists in two revisions, told apart by the size of a TABLES record:

| Variant | TABLES record | Titles |
|---|---:|---|
| A | 40 bytes | Goldfinger, Indiana Jones, High Stakes |
| B | 47 bytes | A View to a Kill, Rambo, The Mist, Voodoo Island, Forbidden Castle |

Within a revision the overlay is byte-identical across titles:

| Title | Variant | Resident | Size | Resident MD5 | `GAME.000` size | `GAME.000` MD5 |
|---|---|---|---:|---|---:|---|
| Goldfinger | A | `GAME.COM` | 25,983 | `cd9cb01548f705cfe02f9a926d4d4dbd` | 69,888 | `bfa2351ac27a23bd22102a7138e40d1a` |
| Indiana Jones | A | `GAME.COM` | 25,983 | `cd9cb01548f705cfe02f9a926d4d4dbd` | 69,888 | `bfa2351ac27a23bd22102a7138e40d1a` |
| High Stakes | A | `GAME.COM` | 25,983 | `cd9cb01548f705cfe02f9a926d4d4dbd` | 69,888 | `bfa2351ac27a23bd22102a7138e40d1a` |
| A View to a Kill | B | `GAME.COM` | 25,835 | `18cc3721c39cad2857a025bfbb21827e` | 67,840 | `3d38582dc51fcd6b92371cd508fd6afa` |
| Rambo | B | `GAME.COM` | 25,835 | `18cc3721c39cad2857a025bfbb21827e` | 67,840 | `3d38582dc51fcd6b92371cd508fd6afa` |
| Forbidden Castle | B | `CASTLE.COM` | 25,835 | `71eb05d5af1793dc6375be7ad3d9c90c` | 67,840 | `3d38582dc51fcd6b92371cd508fd6afa` |
| The Mist | B | `GAME.COM` | 24,552 | `410c75624269ce996652e64da44a17aa` | 67,584 | `e495f39a61cb747ef4da8d74d88fdf6f` |
| Voodoo Island | B | `GAME.COM` | 25,835 | `e9c980de5f5f9d7d2e685cda46ee1e87` | 67,840 | `0c6c760199d90129defeef78d8fde48d` |

The files carry no version numbers; the only version-like string is the
compiler stamp `(C) 1985 BORLAND Inc`.

The record fields sit at the same offsets in both variants; variant B's
longer records hold the start state in fewer records, and two of its selector
tables are numbered one higher ([vm.md](vm.md#variant-b)). The port runs both
with the same code, switching on the record size.

## The port

The port is a layered reading of the original. Each layer corresponds to a
part of `GAME.COM` or `GAME.000`; nothing above the data readers contains game
text or game-specific rules.

| Layer | Modules | Original |
|---|---|---|
| Data readers | `data.py`, `packing.py`, `message.py`, `vocab.py`, `tables.py` | the MESSAGE reader and codec, the VOCAB and TABLES loaders |
| Activation | `activation.py`, `runtime_records.py`, `world.py` | the activation chain that turns TABLES into the in-memory tables |
| Parser | `input_encoding.py`, `parser.py`, `grammar.py` | the word matcher and the sentence grammar |
| Dispatcher | `dispatcher.py`, `actions.py`, `predicates.py`, `pascal_set.py` | the per-turn record loop, the action opcodes, the predicate sets (TP3 `set of 0..255`) |
| VM | `vm.py`, `vm_messages.py`, `vm_actions.py`, `vm_listing.py`, `vm_people.py` | the message controls, the action VM, listings, people, timers, Random |
| Text | `gamecom.py`, `gamecom_conditionals.py`, `gamecom_render.py`, `message_controls.py`, `paging.py` | the control interpreter and the text formatter (80 columns, 24 rows, `(MORE)`) |
| Game loop | `game.py`, `game_messages.py`, `game_movement.py`, `game_talk.py`, `game_vehicles.py`, `game_nouns.py`, `config.py`, `savegames.py` | the main loop: boot, commands, movement, talk, vehicles, save/restore |

`AsgVm` (`vm.py`) holds the machine state; `AsgGame` (`game.py`) drives it
turn by turn and owns the parser and the text engine. A title is bound by an
`AsgConfig` in `games/<title>/config.py`: the folder of its data files, the
TABLES record size and a few values the data files do not carry.

The port keeps the original's addresses as names. A field written `1A4C`
or `byte_1A4C` is the byte at `DS:1A4C` in the running original; a routine
called `sub_9AFF` is the routine at that address in the disassembly. This
keeps every rule traceable to the code it ports.

## Running a game

1. **Boot.** The data files are read; the activation chain builds the
   people, object, room and route tables from TABLES and sets the start
   state ([vm.md](vm.md#activation)). The game asks whether to resume a saved
   game; a restore runs the same activation on the save file instead of TABLES.
2. **Start record.** The start record (`word_1A93`) is rendered: the opening
   text and the first room.
3. **Turns.** Each command is parsed, the grammar picks a dispatcher, and the
   dispatcher selects the MESSAGE record that answers. Rendering that record
   evaluates its controls, which test the state and run actions. After the
   answer, the end-of-turn pass moves people, walks routes and counts down
   timers; the records they fire print after the answer
   ([vm.md](vm.md#a-turn)).
4. **End.** A record ends the game (`(y`, game over) or asks to start a new
   one (`(n`).
