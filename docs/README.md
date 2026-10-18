# Docs

Reverse-engineering notes from the development of the port. Some are in
English, some in German.

| File | Contents |
|---|---|
| [data-format.md](data-format.md) | The original files byte by byte: MESSAGE packing and controls, VOCAB, TABLES, the dispatcher, the activation chain. |
| [asg-vm.md](asg-vm.md) | How the original engine works as a VM that executes data, and how the port mirrors it. |
| [engine-compatibility.md](engine-compatibility.md) | The eight titles, the two engine variants (40/47-byte TABLES records). |
| [reverse-engineering.md](reverse-engineering.md) | Disassembly notes on GAME.COM and GAME.000 (Turbo Pascal 3). |
| [runtime-layout.md](runtime-layout.md) | Memory layout of the running game. |
| [runtime-trace-targets.md](runtime-trace-targets.md) | Addresses for live tracing in DOSBox-X. |
| [savegame-format.md](savegame-format.md), [speicher-und-lademechanismus.md](speicher-und-lademechanismus.md) | Save and restore. |
| [vm-migration-audit.md](vm-migration-audit.md) | Dated log of porting the engine into the shared VM. |

The notes refer to files of the development workspace that are not part of
this repository: the disassembly (`docs/disassembly/`), tests (`tests/`),
trace logs (`traces/`) and tools (`tools/`). Older entries also name modules
that were later removed or renamed (the hand-written Goldfinger interpreter,
`sibling.py`, now `gameengine/game.py`).
