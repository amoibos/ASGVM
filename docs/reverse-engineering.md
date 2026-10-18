# Reverse engineering notes

For the current data-format specification, see
[`data-format.md`](data-format.md). This file keeps the lower-level
disassembly trail and address notes.

## Files

| File | Size | Notes |
| --- | ---: | --- |
| `GAME.COM` | 25,983 | Turbo Pascal 3 executable. Opens and decodes `MESSAGE`. |
| `GAME.000` | 69,888 | Main game overlay/logic (Turbo Pascal 3 overlay file). Opens `VOCAB`, `TABLES`, save files. |
| `MESSAGE` | 48,128 | Packed message text data. |
| `VOCAB` | 6,136 | Packed vocabulary/parser data. Values currently observed in `0..65`. |
| `TABLES` | 4,320 | Game tables for rooms/objects/actions. |

## Important `GAME.COM` addresses

DOS COM files load at offset `0100h`, so the address below is the runtime VMA
shown by `objdump --adjust-vma=0x100`.

| Address | Meaning |
| --- | --- |
| `46AC` | `xtrnip`: extracts one of six bit windows from a byte. |
| `4721` | Combines six bytes into eight 6-bit symbols. |
| `4D3A` | Reads the next packed symbol and translates through `DS:1DF8`. |
| `4EC2` | Emits decoded message characters until `0x40` terminator. |
| `5029` | Initializes `MESSAGE` decoding state and opens `MESSAGE`. |

The IDA Pro export supplied with the project is [`goldfinger.asm`](../goldfinger.asm),
with public symbols in [`goldfinger.map`](../goldfinger.map). The associated
`GAME.idb`, `GAME.id0`, `GAME.id1`, `GAME.nam`, and `GAME.til` files preserve
the IDA database state. The UTF-8 annotation overlay is
[`goldfinger.comments.asm`](../goldfinger.comments.asm).

## Important `GAME.000` addresses

| Address | Meaning |
| --- | --- |
| `068B` | Opens `VOCAB` and initializes parser buffers. |
| `1DF7` | Opens `TABLES` with record size `0x28`. |
| `2050` | Reads a six-byte field in room records. It participates in native movement logic, but is not sufficient by itself to model exits. |

## Disassembly artifact caveat (GAME.000 objdump)

`docs/disassembly/GAME.000.asm` is a linear `objdump` sweep. The Turbo Pascal
string-literal helper at `GAME.000:0xb2b0` (and relatives) is followed by
**inline string data** at its call sites, and it adjusts the return address to
skip that data. `objdump` does not model this, so it misdisassembles the inline
bytes as instructions and can lose instruction-boundary sync for the rest of a
function. Example: inside the vocabulary node-insert `sub_0x282`, the bytes
right after `call 0xb2b0` at `0x2e5..0x2ef` decode as nonsense
(`add`/`and`/`fldcw`/`hlt`); real code resumes at `0x2f0`.

Consequence: frame-local offsets in such functions cannot be fully trusted from
this artifact.

### Resolution: inline-string repair, then coverage pass

GAME.000 has now been disassembled in IDA Pro 5 (loaded as a binary at base
`0x100`, processor `80286r`). The inline-string sync loss was repaired by a
one-time IDC pass that found every `call` to a string helper
(`37B0`, `48B0`, `4EC3`, `B2B0`, `C9C3`) and converted the following
`<len><chars>` into a Pascal string, then re-created code at the call and at the
resume point and re-ran analysis. This took the overlay from ~17% disassembled
(8983 instructions / 45107 `db`) to ~84% (22352 instructions / ~11 KB `db`).
That repair is the first stage of `recover_game_000.idc`; run that master when
loading GAME.000 from scratch.

The residual `db` after that step is not data: it is unconverted code IDA never
reached, in three flavours -- whole Turbo Pascal 3 procedures (entry prologue
`55 8B C4` = `push bp; mov ax,sp`, or the rarer `55 8B EC`); CASE / computed-jump
code entered only through a jump table (the verb dispatcher near runtime `0xFFED`,
long `cmp ax,id; jz; jmp` chains); and mid-function sync loss where IDA simply
halted after an ordinary instruction. The embedded `improve_coverage` stage
recovers all three: it forces `MakeCode` at missed prologues, then linearly fills
the remaining code gaps (guarded so it never touches a defined string or
zero-fill padding). It runs after inline-string repair. This brings the overlay
to **~99.6% code (about 262 `db` bytes left** -- a few small fragments around
`0x19xx`/`0x4B14` plus some zero padding).

Measure coverage on `goldfinger_overlay.lst` (it carries addresses and is the
freshest export); `goldfinger_overlay.asm` can lag behind the `.lst` if only the
listing was re-exported. Prefer either over the objdump for GAME.000 work.

### Same cleanup for GAME.COM (`goldfinger`)

GAME.COM has the identical TP3 inline-string problem, but with its OWN helpers,
so the GAME.000 script does not apply. The confirmed GAME.COM inline-string
helpers are `sub_28D9` (print inline string: `pop bx; mov cl,cs:[bx]; ...; jmp bx`)
and `sub_11C6` (copy inline string constant to the stack: `pop si; ...; rep movsb;
jmp si`). The desync from these garbled the GAME.COM renderer region around
runtime `0x4E68` (e.g. the inline string `'Repos error. Aborting ...'`). Run
the `fix_inline_strings_gamecom` stage (helpers `0x28D9`, `0x11C6`) in
`recover_game_com.idc`, followed by its generic coverage stage, then
re-export `goldfinger.asm`/`.lst`.

After this cleanup, an important negative result is confirmed: the GAME.COM
formatter does **not** interpret `$ \ ^ |` (see `docs/data-format.md`,
"Template control character set"). `render_segment` only stops at `@`/applies
`%`; `sub_3DFB` only auto-capitalises; `sub_4D3A` (symbol->char) is called only
from `render_segment`. So those controls are resolved upstream in GAME.000,
before the char stream reaches the formatter. The GAME.000 resolver is not yet
located statically -- see the live trace plan below.

### Live DOSBox-X trace plan: locate the template resolver

Goal: find the GAME.000 routine that resolves the `\` word dictionary and the
`$...|...^...` conditional, and the dictionary table's address.

Tooling: this DOSBox-X build exposes a debugger **TCP server on
`127.0.0.1:28912`**, driven by `tools/dosbox_debug.py` (a custom build; the
source changes are not part of this repository). Enable with `debugger tcp port = 28912` and
`debuggerrun = debugger` in `dosbox-x.conf`. Key points learned the hard way:

- The debugger only processes TCP commands while **paused**. Send `BREAK` first
  (a custom command added to this build) to make it enter the debugger; resume
  with `RUN` (not `G`).
- Read memory with `MEMDUMPBIN SEG OFS NUM` (three hex args) which writes
  `MEMDUMP.BIN`; register/`D` output goes to the curses window, not TCP, and `R`
  is not even a valid verb here.
- Answer the game's start prompt with `TYPE n` (custom keystroke-injection
  command) instead of the SDL window.
- Batch commands over one connection (`dosbox_debug.py A B C`); the server now
  survives reconnects but one connection is cleaner.

Finding GAME.COM's `CS`: `R` does not work over TCP, so dump low memory / the
PSP chain with `MEMDUMPBIN` and locate the GAME.COM segment, then form
breakpoints as `<that CS>:offset` (a `.COM` runs at `CS:0100`; `CS` is the
program's PSP segment, not `F000`/BIOS).

Differential shortcut (no debugger): much of the mechanism can be recovered by
comparing on-screen text to the raw template, since the game has already
resolved the controls. This already confirmed the prologue is almost entirely
`\`-dictionary tokens (see `docs/data-format.md`, "Word-abbreviation blocker").
The live trace is still needed to recover the dictionary *table* and the `$`
state test.

Key fact: the `\` is symbol value `0x2F` (and `$`=`0x1F`, `^`=`0x1B`, `|`=`0x1C`)
in the packed stream. GAME.000 must branch on it while *reading symbols*, before
translation. Every MESSAGE symbol is produced by the GAME.COM 6-bit extractor
`loc_4721` (runtime offset `0x4721`); higher readers are `sub_4CE6` (`0x4CE6`,
read one symbol) and `sub_4D3A` (`0x4D3A`, symbol->char). Record open is
`sub_4A89` (`0x4A89`).

Procedure (DOSBox-X built-in debugger):

1. Launch the game, open the debugger, and break once to read `CS` (a `.COM`
   loads its code at `CS:0x0100`, so the GAME.COM offsets above are
   `CS:offset`). The GAME.000 overlay lives in a separate overlay buffer; its
   runtime segment:offset is discovered in step 4, not assumed.
2. Trigger a description that contains a `\`. Good targets (symbol `0x2F` appears
   early): room 36 (`\` at description offset +2), room 33 (`\a8...` at +29).
   Any message with a `\` works; the aim is to make `loc_4721` return `0x2F`.
3. `BP CS:4721` (breakpoint at the symbol extractor). It returns the symbol in
   `AL`. Continue until `AL == 0x2F` on return (step over the body to the `retn`;
   or set the breakpoint at the instruction right after the body computes the
   symbol). That hit is a `\` being read.
4. Walk the stack (`D SS:SP`) at that moment: the return addresses identify the
   caller chain. The first caller OUTSIDE the GAME.COM `0x4xxx` renderer is the
   GAME.000 resolver -- record its segment:offset. (Map it back to the IDA
   overlay by subtracting the overlay load base so it matches a `sub_xxxx`.)
5. Single-step that GAME.000 routine through the `\` handling. It will read the
   next symbol(s) as an index and then read from a table -- watch the effective
   address of that table read (`D <seg>:<off>` it). That table is the word
   dictionary; dump it for static decode.
6. Repeat with a `$` description (room 27, "the door is $...open^...closed") and
   breakpoint on `AL == 0x1F` to capture the conditional handler and which state
   byte it tests.

Record the resolver address, the dictionary base/stride, and the `$` state test
in `docs/data-format.md`; then port them so `render_run` resolves `\`/`$`
instead of stopping at them.

### Provenance: Turbo Pascal 3 and the overlay format

The inline-string convention above is not a bespoke obfuscation; it is the
standard **Turbo Pascal 3** code-generation pattern (string literal stored
immediately after the `call`, helper advances the return address past it). Taken
with the numbered overlay filename `GAME.000` (TP3 emits one `<exe>.NNN` file per
overlay group, paged in by the resident `.COM`) and the uniform `bp`-based frames
wrapped in `sub_FB2`/`sub_F12` stack thunks, the program was **most likely built
with Turbo Pascal 3**. Because the TP3 overlay file format is documented, the
overlay's structure (group header, resident/overlaid split, per-procedure
relocation) can be read against the published TP3 layout instead of being
inferred byte by byte. See `docs/data-format.md` (`GAME.000` > Toolchain and
overlay structure) for the consolidated note.

## 6-bit packing

The symbol extraction routine is:

| Part | Expression |
| ---: | --- |
| 1 | `(byte & 0xFC) >> 2` |
| 2 | `(byte & 0x03) << 4` |
| 3 | `(byte & 0xF0) >> 4` |
| 4 | `(byte & 0x0F) << 2` |
| 5 | `(byte & 0xC0) >> 6` |
| 6 | `byte & 0x3F` |

Six bytes produce eight symbols:

```text
s1 = part1(b0)
s2 = part2(b0) + part3(b1)
s3 = part4(b1) + part5(b2)
s4 = part6(b2)
s5 = part1(b3)
s6 = part2(b3) + part3(b4)
s7 = part4(b4) + part5(b5)
s8 = part6(b5)
```

## Open questions

- Implement the native action/condition dispatcher that consumes room fields.
- Map remaining `MESSAGE` control symbols to capitalization, quoting, and
  paragraph breaks.
- Map `TABLES` object fields and action/condition scripts.

## `VOCAB` loader notes

`GAME.000:068B` opens `VOCAB`. The file size proves the fixed record width:
`6136 / 26 = 236`. Each record begins with a Pascal string field and ends with
four parser metadata bytes.

Examples:

| Offset | Word | Metadata |
| ---: | --- | --- |
| `0000` | `airport` | `33 02 02 08` |
| `0034` | `armrest` | `33 02 00 11` |
| `04ac` | `door` | `33 02 02 25` |
| `0aaa` | `inventory` | `2d 02 06 03` |
| `0c2c` | `look` | `18 02 06 05` |
| `0e18` | `north` | `00 02 05 00` |

## `TABLES` loader notes

`GAME.000:1DF7` opens `TABLES` with record size `0x28`. The file contains 108
records. Records beginning with `0x02` are loaded into the room pointer table.
At `GAME.000:2050`, the program loops over a six-byte room field and tests for
the value `1`. Earlier notes treated this field as standalone exits; testing
against the associated MESSAGE templates disproves that interpretation. The
field must be evaluated with the action/condition dispatcher before it can
drive Python movement.

## TABLES field access-site notes (in progress, 2026-06-30)

Open hypotheses from reading access sites for the still-unnamed record fields.
**Graded `observed`/`hypothesis` only — not yet ported.** Line numbers refer to
**`goldfinger.asm` = GAME.COM** (the resident, per `speicher-und-lademechanismus.md`
§10) — NOT the GAME.000 overlay. The core TABLES dispatcher/action-VM lives in
`docs/disassembly/GAME.000.asm`; the two routines below are GAME.COM-side and
most likely belong to the message renderer's room/context resolution (cf. the
`msg_ctrl_star` mode-3 descriptor-2 walk over `DS:025C` slots `+4..+9` in
`asg-vm.md`), not the dispatcher's record-state writes.

Cross-check before trusting these for TABLES semantics: `savegame-format.md` §6
already documents the on-disk 40-byte layout from the SAVE diff, including
**`+0x0D` = activation flag (00 fresh / 01 active)** for object/room/global
records. So the `+0x0D` "rank" reading below is about the `DS:0x4B4` table, a
**different** structure, and must not be conflated with the TABLES `+0x0D` field.

### `sub_56A5` (asm:11844..11937) — fixed-direction room-chain walk

Reads a record's `+0x14` room index, follows it through the `DS:0x25C` room
pointer table, then uses `record[+0x16]` as a **1-based direction-slot index**
into the linked room: it computes `room_ptr + record[+0x16]` and reads `+4` of
that (asm:11871-11872), i.e. `room_record[record[+0x16] + 4]`. Room direction
slots begin at `+5`, so `record[+0x16] == 1` selects slot N (`+5`), `2` selects
S (`+6`), etc. The resulting slot value (a 1-based room id) becomes the next
step; the walk loops, following the same stored `+0x16` direction, until the
slot id is `1` (null room). **Observed.**

- Open question: is this the same byte as the action-VM operand-3 write target
  on object records (`+0x16`, see `data-format.md`)? If so, action opcodes that
  write operand 3 would be *setting the stored direction* this walk consumes —
  plausible but **unconfirmed**; needs a trace before unifying the two roles.

Per-step gate in the loop body (`loc_56F4`, asm:11881-11903) reads `+0x23` then
`+0x24` from `var_C` (a separate far-pointer arg, **not** the room pointer just
resolved) and requires both `!= 0`. `+0x24` is the known aux entry-gate offset
(`native_entry_allowed`); `+0x23` is an adjacent gate byte checked alongside it.
- Open question: is `var_C` a room record? If yes, `+0x23` is a second per-room
  gate. Family of `var_C` is **unconfirmed** — trace the caller of `sub_56A5`.

### `sub_5764` (asm:11944..12078) — max-`+0x0D` selector over `DS:0x4B4`

A loop (`loc_57DA`..`loc_583C`, `inc var_3`) iterates entries of the `DS:0x4B4`
table, keeps only those whose `+0x17 == 1` (asm:12034-12037), and tracks the
entry with the **maximum `+0x0D`** value (asm:12042-12055), returning its index.
So within `DS:0x4B4` entries `+0x0D` behaves as a rank/priority and `+0x17 == 1`
is a category marker. **Observed.**

- Caution: this walks `DS:0x4B4`, which is built at `GAME.000:0x17da` (see
  `data-format.md` parser notes) and is **not confirmed** to share the 40-byte
  TABLES object-record layout. Do **not** attribute this `+0x0D`/`+0x17` meaning
  to TABLES object records without further evidence — the action-VM operand-4
  mapping (`+0x0D`) is a separate, already-documented access role.

## Runtime text table

`GAME.000:23BA..2706` constructs the `DS:1DF8` MESSAGE translation table. In
addition to the letters, it establishes punctuation, digits, and a terminator:
`^|*($%@#.,-?\";'!:&=+\\`, `0..9`, with unmapped symbol `0x3f` translating to
`0x40` (end of message). Several of these printable characters occur in native
templates and are control syntax at the game-logic level, not player prose.
