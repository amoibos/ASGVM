# Docs

How the engine is built: the original program, its data files, its memory
and the virtual machine that runs the games, as the port implements them.

| File | Contents |
|---|---|
| [architecture.md](architecture.md) | The original engine (`GAME.COM` + `GAME.000`), the two variants, the eight titles, and how the port's modules map onto it. |
| [file-formats.md](file-formats.md) | `MESSAGE`, `VOCAB`, `TABLES` and the `SAVE<n>` files, byte by byte. |
| [memory-layout.md](memory-layout.md) | The original's memory: the tables the activation builds (people, objects, rooms, routes), the sets, cursors, flags and timers. |
| [vm.md](vm.md) | Activation, a turn from parsing to the end-of-turn pass, the MESSAGE control language, the actions, Random, save and restore. |

Addresses are offsets in the original's data segment (`DS:1A4C`) or code
locations in the disassembly (`sub_9AFF`, `GAME.COM 3DFB`); the port uses the
same names, so every rule can be traced to the code it ports.
