# Goldfinger data format

This document describes the current known on-disk format for the DOS release of
`James Bond 007: Goldfinger`. It is intentionally conservative: fields marked
`known` have a reproduced implementation, fields marked `observed` are backed
by file/disassembly evidence but still need semantic names, and fields marked
`unknown` must not be treated as stable interpreter API yet.

## File set

| File | Size | Role | Status |
| --- | ---: | --- | --- |
| `GAME.COM` | 25,983 | DOS COM executable, Turbo Pascal 3 runtime, `MESSAGE` loader/decoder. | known |
| `GAME.000` | 69,888 | Main game overlay (Turbo Pascal 3 overlay file). Loads `VOCAB`, `TABLES`, save files. | observed |
| `MESSAGE` | 48,128 | Packed text/message stream. | partially known |
| `VOCAB` | 6,136 | Parser vocabulary and verb/noun classification data. | observed |
| `TABLES` | 4,320 | World tables for game state, rooms, objects, and actions. | observed |
| `TITLE` | 1,127 | Pascal source for the title screen. | known |
| `TITLE.COM` | 11,967 | Compiled title program. | known |

## Addressing conventions

`GAME.COM` and `GAME.000` are disassembled as raw 8086 binaries with
`objdump -b binary -m i8086 -D --adjust-vma=0x100`. Runtime addresses in the
notes therefore include the DOS COM load bias of `0100h`.

When this document gives a file offset, it is zero-based within the named file.
When it gives a `GAME.COM` or `GAME.000` address, subtract `0100h` to get the
corresponding file offset.

## `MESSAGE`

Status: partially known.

`MESSAGE` is a packed text data file opened by `GAME.COM`. The file is not
plain ASCII. The confirmed low-level representation is a stream of packed
6-bit symbols.

Observed file facts:

| Property | Value |
| --- | --- |
| Size | `48128` bytes |
| Unique byte values | `255` |
| Byte range | `0x00..0xff` |
| Full 6-byte groups | `8021` |
| Decoded symbols from full groups | `64168` |
| Trailing bytes after 6-byte grouping | `2` |
| First 16 bytes | `00 00 00 50 8f 3d 43 e1 00 88 02 69 85 c0 0e 68` |
| Last 16 bytes | `61 86 18 61 86 18 61 86 18 61 86 18 61 86 18 61` |

### 6-bit packing

Status: known.

The extraction routine is `GAME.COM:46AC`, referred to by the program's own
error message as `xtrnip`.

| Part | Expression |
| ---: | --- |
| 1 | `(byte & 0xfc) >> 2` |
| 2 | `(byte & 0x03) << 4` |
| 3 | `(byte & 0xf0) >> 4` |
| 4 | `(byte & 0x0f) << 2` |
| 5 | `(byte & 0xc0) >> 6` |
| 6 | `byte & 0x3f` |

Six bytes are decoded into eight symbols by `GAME.COM:4721`:

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

This logic is implemented in [`gameengine/packing.py`](../gameengine/packing.py).

### Symbol stream

Status: known at packing level, partially known at character level.

The first 32 unpacked 6-bit symbols from the current `MESSAGE` file are:

```text
00 00 00 00 14 08 3c 3d 10 3e 04 00 22 00 09 29
21 1c 00 0e 1a 06 06 06 06 06 04 06 34 01 29 18
```

The final text character is not directly the 6-bit value. `GAME.COM:4D3A`
reads a packed symbol and then indexes a runtime translation table at
`DS:1DF8`. A translated byte value of `0x40` terminates the current decoded
message loop in `GAME.COM:4EC2`.

Known control values:

| Value | Meaning |
| ---: | --- |
| `0x40` | Message/segment terminator after translation through `DS:1DF8`. |

### Segment renderer (`GAME.COM:4ECC..4F35`)

Status: known.

The native renderer reads translated characters one at a time via `sub_4D3A`
and:

- **Terminates** the loop when the translated character equals `0x40` (`'@'`)
  at `GAME.COM:4ED7..4EE1`. So a decoded `'@'` is a control, never literal
  prose. (Symbol `0x21` translates to `0x40`.)
- **Capitalizes** while its caller-supplied flag (`[bp+4]`) is set: a lowercase
  letter in `0x61..0x7a` is upper-cased by `sub 0x20` (`GAME.COM:4F0B`, gated by
  the `'a'..'z'` range test at `4EFD..4F08`).
- Emits each surviving character through `sub_3DFB`.

This is ported as `GameComMessageEngine.render_segment(cursor, capitalize)` and
mechanically explains the confirmed `% x@` form: the outer dispatcher enters
capitalize mode at `%`, renders the following one-letter segment (e.g. `b`) as
`B`, and the `@` ends that segment so the outer loop continues (`% b@ond`
-> `Bond`, `% d@unhill` -> `Dunhill`, both observed in the decoded stream).

### Length-prefixed record open (`GAME.COM:4A89` + seek `GAME.COM:4525`)

Status: known. This is a **separate** access path from the room-description
prose pointer, and confirming the difference resolves a long-standing ambiguity.

`sub_4A89(arg)` opens a length-prefixed MESSAGE *record*:

- `sub_4525(arg)` seeks. `arg` is a six-byte-window index: `arg / 0x55` selects a
  disk page (pages are `0x202` bytes = 4-byte header + `0x55`=85 windows of 6
  bytes), and `arg % 0x55` selects the window inside the page (`byte_48F2`, later
  scaled `*6 + 4` into the page buffer). So the prose symbol position is
  `arg*8`, matching the room `+2` interpretation.
- `word_1DE1 = 2`: reading begins at the **third** symbol of the window, i.e. the
  first two packed symbols are skipped.
- `word_1DE7 = sym1*0x40 + sym2`: those two skipped symbols are a **base-64
  length** header. `word_1DE3` counts consumed symbols and `sub_4CE6` raises the
  end flag (`byte_1B46`, surfaced as the `0x40` terminator) once the count passes
  the length.

So `render_record(group_index)` (the length-bounded reader) is the faithful port
of *this* path. **Room descriptions do not use it**: a room's `+2` value points
mid-shared-record at a sentence fragment (e.g. room 9's `+2*8` lands at " narrow
road heads north toward the mountains." inside a `@`-bounded run that also holds
a neighbouring room's "...leads south from town" sentence), with no per-room
length header at that position. Room text therefore renders via `render_run()`
(prose until a control/terminator), while system/inventory-style records that
*are* length-prefixed render via `render_record()`. The two must not be
conflated.

### Template control character set (`GAME.COM:5160..5171`)

Status: known (which chars are controls), semantics partially known.

The setup routine at `GAME.COM` builds a membership set at `DS:0x1b68`
containing exactly the control characters `^ | ( + % = $ & * \` (`0x5e 0x7c
0x28 0x2b 0x25 0x3d 0x24 0x26 0x2a 0x5c`). The renderer tests each translated
character against this set to decide whether it is literal prose or a control.
This pins down the control alphabet; the per-control action is still being
recovered (only `%` capitalization is confirmed, via `render_segment`).

Where the controls are NOT handled (confirmed on the cleaned GAME.COM export):
the GAME.COM text formatter does **not** interpret `$ \ ^ |`. `render_segment`
(`4ECC`) only stops at `@` and applies the `%` capitalize flag; `sub_3DFB` only
does auto-capitalisation/spacing and tests a sentence-punctuation set. Neither
tests the `DS:0x1b68` control set. `sub_4D3A` (symbol->char) is called only from
`render_segment`. So the template controls must be resolved **upstream in
GAME.000** (which selects/*assembles* the text and positions the cursor), before
the char stream reaches the GAME.COM formatter -- they are not decoded by the
low-level renderer. The GAME.000 routine that does this is not yet located; the
`cmp ax,5Ch` sites in GAME.000 are the keyboard/input dispatcher (`sub_F113`),
not the message-template resolver. A live DOSBox-X trace breakpointing the
renderer and watching a `\` symbol is the most reliable way to find it.

#### The resident control dispatcher -- LOCATED (live dump + capstone disasm)

Status: **located and structurally decoded**; per-handler semantics still being
recovered. (2026-06-21)

The "upstream GAME.000" template resolver the paragraph above could not find is a
**resident overlay routine at code segment `CS=0x0815`** (segment base linear
`0x8150`). It is absent from both static disassemblies, so it was recovered by
dumping the live 64 KB code segment (`tools/dump_renderer.py`, MEMDUMPBIN
`815:0 10000`) and disassembling it offline with capstone in 16-bit mode
(`tools/da.py`, dump offset = `linear - 0x8150`). The `\` handler push-ax anchor
(`BP 1587:6` = linear `0x15876` = `0815:D726`, confirmed by `trace_dict.py`)
fixed the segment.

The renderer **main loop** is at linear `0x156FB..0x158DB`:

- `call 0x1CE8A` returns the next character in `AL` (the symbol->char reader; the
  GAME.000 analogue of GAME.COM `sub_4D3A`). Cursor lives in the `DS:0x1DE1/
  0x1DE3/0x1DE5/0x1DED` globals already documented; `DS:0x1DE5` = current record
  index (live-confirmed: prologue `3899`->`3491`"Mercedes"->`68`"Goldfinger").
- The char is tested for membership in the control set `DS:0x1B68` (the
  `^ | ( + % = $ & * \` alphabet). **Non-members are literal prose**; members
  fall into a `cmp ax,<ctrl>; jz <handler>` chain (linear `0x15763..0x1585D`).
- After dispatch it loops back to `0x156FB`; a translated `0x40` (`@`) is the
  segment terminator (`0x1589B`/`0x158C2`), matching GAME.COM `render_segment`.

Per-control handlers (the `cmp` is against the **translated** char, not the raw
6-bit symbol):

| Char | Translated | Handler (linear) | Notes |
| --- | ---: | ---: | --- |
| `^` | `0x5E` | `0xE274` then `0x1CED1` | **Line/para break**, not a conditional: `0xE274` scans the line buffer back over spaces and writes the break byte `[0x1BE8]`(=`0x0D`). |
| `\|` | `0x7C` | flag `[0x4B7B]` ? `0x1CDE1` : `0xE274`+`0x1CED1` | Break control, gated by state byte `DS:0x4B7B`. |
| `*` | `0x2A` | `0x15147` | unknown |
| `(` | `0x28` | `0x12C98` | section selector (the `(`-label span chooser already ported as `render_message_record(section=)`). |
| `+` | `0x2B` | `0x13FB9` | unknown |
| `$` | `0x24` | `0x11448` | conditional state test (`$...|...^...` open/closed selection); calls `0x112F5` then `0x105D5`. |
| `&` | `0x26` | `0x11F01` | conditional (unknown predicate) |
| `%` | `0x25` | `0x14369` | capitalize-next (already ported). |
| `=` | `0x3D` | `0x14CDE` | unknown |
| `\` | `0x5C` | `0xE2C4` then `0xE517` | dictionary expand: read 3 symbols -> base-64 index, render record inline (already ported as the `\` expansion). |

So `^` and `|` being **break** controls (not conditionals) corrects the earlier
room-27 hypothesis below: the open/closed selection is driven by `$`/`&`, while
`|`/`^` punctuate the alternatives as line breaks.
Disassemble any handler with `python tools/da.py <linear-addr> <len>`.

**Render entry points / seek (linear, CS=0x0815) -- decoded.**

| Routine | Linear | Role |
| --- | ---: | --- |
| seek | `0xCBD9` | `seek(index)`: `[0x1DE1]=2` (skip the 2-symbol length header), `[0x1DE3]=0` (consumed counter), `[0x1DE5]=index`. Page-seek via `0xC675`. The GAME.000 analogue of GAME.COM `sub_4525`. |
| record-open | `0xCC08` | `open(index)`: `seek(index)` then `[0x1DE7] = sym1*0x40 + sym2` (the base-64 **length** header). = GAME.COM `sub_4A89`. |
| render-record | `0x158DC` | `render_record(index)`: `open(index)` then runs the control-dispatch loop (`0x156FB`) bounded by `[0x1DE7]`. A `[bp+4]` arg of `0x7FFF` is a **sentinel** = "render at the already-positioned cursor" (used for inline continuation, e.g. after a `\` expand restores the saved cursor). |

This confirms the Python `render_record(group_index)` port path is exactly
`0x158DC`: the room/system text is a **length-prefixed record addressed by
index**, read from the depaged stream, NOT a flat `+2*8` run. (The interpreter's
`render_run(+2*8)` is therefore the wrong model and is the source of the leading
"K alley..." gibberish: it starts on the flat stream at the length-header symbol.)

**Conditional handlers -- decoded structurally.**

- `$` (`0x11448`): calls predicate `0x112F5`, which walks the active-condition
  **linked list** (`[bp+4]` head), takes the current node, null-checks it
  (`0x9759`), and tests **`node[+8] == 1`**; if so it renders the following
  fragment via `0x105D5`, else it is skipped. So `$<op>` is "render this fragment
  iff the referenced active-condition node's `+8` flag is set."
- `&` (`0x11F01`, overlay `loc_D8DB`): a second **state-predicate dispatcher**,
  not text substitution. It consumes exactly two symbols (opcode plus cached
  operand), resolves parser/room context, and writes the boolean `DS:4B7B`.
  Confirmed direct cases `j/k/l/p/m/n` compare phase-7 node byte `+18h` with
  types `2/0/1/3/4/5`; `o` reads room byte `+23h`, and `w` tests room byte
  `+11h` against the one-byte set at `0670h`. `_` selects either global
  `byte_1A8A` or node flag `+1Ah`; `b` tests the current command's `value_b`
  against node set `+0Eh`, and `a` tests the cached operand against runtime
  record set `+0Ch`.

**Remaining link (cross-segment).** `render_record` (`0x158DC`) has **no caller
inside CS=0x0815**, so the move/look handler that computes a room's text record
index and the verb-conditional prefix ("you slip into" / "you are in" / "you're
back at") lives in the **game-logic overlay segment** (the `sub_1DEB` per-turn
dispatcher area) and invokes the renderer by far call. Mapping how the room
record `+2` becomes the `render_record` index is the next decode step; it needs a
dump+disasm of the dispatcher segment, not the renderer segment dumped here
(`tools/dump_renderer.py`).

**Full move/look text-emit pipeline (recovered 2026-06-21 via the
`label_message_renderer` stage now embedded in `recover_game_000.idc`).**
Running the IDC labeller turned the unanalysed `db` block into named code and gave
the xrefs that expose the whole chain, top to bottom:

```
token dispatcher (IDA ~0xCF52 chain, case 0x7C)
  -> sub_8628                MULTI-FRAGMENT ASSEMBLER: calls turn_resolve_text
                             repeatedly with different args (7, [bp-5], byte_1BE8),
                             emitting one fragment each (the "native multi-fragment
                             assembler" the docs were missing)
     -> sub_4E03  (turn_resolve_text)   per-record text resolve:
            les di,[bp+10h]; al = record[+6]          ; record kind discriminator
            cmp 0x11 -> word_4B7F = record[+4], [4B11]=6  (+ visited-state compare,
                         byte_1A4C vs byte_1A4F, calls sub_4D65)
            cmp 0x16 -> word_4B7F = record[+8], [4B11]=6
            cmp 0x1C -> word_4B7F = record[+6], [4B11]=7
            cmp 0x17 -> uses record[+2]/record[+3]
            default  -> [4B11]=5
     -> msg_emit_response                if byte_1AE0: render word_1A93
                                         else: render word_4B7F  (the resolved ref)
        -> msg_render_by_ref (=0x6024)   render the referenced record...
           -> msg_render_record -> msg_record_open(index) -> msg_seek; [1DE7]=len
              -> msg_render_driver       char loop -> the control dispatcher
                 (CS=0x0815, msg_render_loop) -> %, @, |, \, and the
                 $/& conditionals decoded above
```

So a room's player-facing text is **not** `render_run(+2*8)`: the per-turn
dispatcher hands `turn_resolve_text` a record, which by `record[+6]` picks one of
the record's *word text-reference fields* (`+4`/`+6`/`+8`) into `word_4B7F` and a
section label into `[4B11]`; the assembler stitches several such fragments; each
is rendered by the length-prefixed record reader through the control dispatcher.
The verb-conditional ("slip into"/"are in"/"back at") is the visited-state compare
in the `0x11` case (`byte_1A4C` vs `byte_1A4F`, `sub_4D65`). Porting this chain
(record field semantics + the `[4B11]` section labels + the visited compare) is
the room-description/feedback implementation; all routines are now named in the
GAME.000 database via the embedded `label_message_renderer` stage.

**`render_record` body + the response emitter (decoded 2026-06-21).** Reading
`render_record` (runtime `0x158DC`) and its neighbour:

- `render_record(index)`: if `index == 0x7FFF` it prints the inline string
  `**ERROR**` (so `0x7FFF` is an *invalid-index marker*, not a "continue with
  current cursor" sentinel as first guessed); otherwise `record-open(index)`,
  check the end flag `[0x1B46]`, and if not already ended call the render driver
  (runtime `0x11112` -> IDA `0xC6AC`) which runs the char loop.
- **Response emitter** (runtime `0x15933` -> IDA `0x10ECD`): sets the
  section-selector state `[0x4B11]=0x0B` (the exact value seen during the
  prologue), reads the current room `[0x6A9]`, and renders the **dispatcher
  result global `word_4B7F`** (and `word_1A93`) via the index->word renderer
  (runtime `0xE174` = docs `0x6024`). So a verb handler leaves the room/scene
  **text reference in `word_4B7F`** and this routine renders it -- this is the
  move/look text-emit path. The last missing piece is therefore *how the move
  handler computes `word_4B7F` from the room record's `+2`*; its caller (xref on
  `msg_emit_response`/`word_4B7F`) is the per-turn dispatcher. Run
  `recover_game_000.idc` in IDA to get those xrefs.

**Two render paths (live, 2026-06-21).** The current-record-index global
`DS:0x1DE5` has two writers: (A) `0xCBFC` inside `seek` (`0xCBD9`), reached only
via `render_record` (`0x158DC` -> `record-open 0xCC08`); and (B) `0xD314`, the
`\`-expander / composite path. A live BP on each during the **new-game prologue**
(reachable without driving the chase) shows the **prologue render uses path B
(`0xD314`), not the seek path** -- so the `(`-selector + `\`-dictionary record
(3899) does not go through `render_record`. Catching which path a *room*
description uses needs a live room render, which the chase-move driver currently
crashes (see `memory/live-trace-gotchas.md`); a **savegame restored into a
walkable room** would sidestep that.

**Offline-reader shortcut is DISPROVEN for flat positional reads, but a
*structured* port using the observed segment framing renders many rooms
correctly.** Tested every simple flat reader for room `+2` against
`walkthrough.txt`: a flat length-bounded read (`render_record`) renders room 12
cleanly ("alley behind the factory building...") but room 9 mid-word; the
depaged read (`render_message_record`) renders room 9's neighbour and runs
room 12 *into the next room*. No single flat-offset interpretation aligns all
rooms, because the start fragment + verb prefix are chosen by the dispatcher
per game state.

What *does* work without the full dispatcher: each room's `+2` lands inside
a composite record whose segments are framed as
``<prev_segment_tail>.@@@@<label_1_or_2><room_prose>@@@@<next_label>...``.
The ``@`` (sym 0x21) terminator runs of 3+ symbols mark the gap between
adjacent segments, and the next 1-2 literal symbols form a short section label
(observed: ``q'``, ``p%``, ``id``, ``t?``) that the native `(`-style selector
matches against state. `GameComMessageEngine.render_room_segment` skips to past
the first such gap, skips the label, then renders the next segment through the
full control dispatcher (% @ | \) until the next gap. This is verified to
match the walkthrough for rooms 6/15/18/23 (regression-locked in
`tests/test_dictionary.py`'s `render_room_segment` coverage).

**Known limitation.** When a room's `+2` lands inside a composite record with
multiple sibling segments, the renderer returns the FIRST sibling rather than
the room-specific one -- so rooms sharing a composite (e.g. the field area
R31..R44) all render the same "Ankle-high bluegrass..." text. Fixing this
requires the dispatcher's per-room section-label selector, which is the
"how the move handler computes `word_4B7F` from the room record's `+2`"
piece flagged below as the last unresolved trace target.

Observed (superseded in part by the dispatcher map above) -- the **conditional
selection** `$...|...^...`. In
room 27 the run reads `...northern wall is $geg|afopen ^abclosed.` and renders in
the game as "...the door is **open**" or "**closed**" depending on door state.
The pattern is `$<args> | <args> <text-A> ^ <args> <text-B>`: `$` opens a state
test, `|` and `^` delimit the two literal alternatives (`open` / `closed`). The
`<args>` bytes (`geg`, `af`, `ab`) presumably name the flag/object tested and the
branch, but their encoding is not decoded yet, so the renderer stops at `$`.

### MESSAGE paging and the backslash dictionary (CONFIRMED via live trace)

Status: **RESOLVED**. Recovered with a live DOSBox-X debugger trace of the
GAME.000 control dispatcher; ported in `gameengine/message.py` (`depage`,
`MessageDecoder.record_by_index`) and `gameengine/gamecom.py`
(`record_symbols`, `render_message_record`), with regression tests in
`tests/test_dictionary.py`.

**MESSAGE is a paged file.** It is exactly 94 fixed pages of 512 bytes
(48128 = 94*512). Each page is a two-byte header followed by 510 data bytes =
85 six-byte symbol groups. The native record seek `GAME.COM:4525` divides a
record index by `0x55` = 85 and strides the RAM block cache by `0x202` = 514
bytes per page. To get the contiguous symbol stream the reader actually walks,
drop each page's two-byte header and concatenate the 510-byte data regions
(`depage()`); a record longer than one page then reads straight across what
were page boundaries on disk. **This is why a flat unpack of the raw file is
wrong** for any record past the first page.

**A `\` token is a record reference, not a separate dictionary.** The control
dispatcher case at `GAME.000:0x10df7` (`cmp $0x5c` = `\` after table
translation) does: `call sub_1985e` to read the index, then `call sub_19ab1`
to expand it. Decoded from the resident runtime (absent from both static
disassemblies, dumped live):

- `sub_1985e` reads **three** packed symbols via the symbol reader
  (`GAME.COM:4ce6`) and forms a base-64 index:
  `index = s0*4096 + s1*64 + s2`. (So a `\` token is four symbols: `0x2f` plus
  three index symbols; the frequent `0x00` after `\` is the high base-64 digit.)
- `sub_19ab1` saves the current cursor, calls the index->word renderer
  (`0x6024` -> `0x7731` -> IDA `0x10e76` -> `0x181a2` = the record reader
  `GAME.COM:4ab8`), then restores the cursor and resumes. The "word" is simply
  **MESSAGE record #index**, rendered inline through the same engine, so it may
  itself contain controls (e.g. record 68 = `% g@oldfinger` -> "Goldfinger").

Record `index` therefore lives at depaged group `index` (depaged offset
`index*6`): two base-64 length symbols then `length` payload symbols.

Confirmed index/word pairs from the trace and the file: `0` -> "error",
`1` -> "what?", `68` -> "Goldfinger", `3491` -> "Mercedes" (cross-page, page 41,
proving the per-page header model). Record `3899` is the Aston Martin chase
prologue and now renders verbatim with all `\` words resolved ("...silver Aston
Martin streaks down a dark Alpine road... suspected gold smuggler Auric
Goldfinger... the lead Mercedes roars its approach... Tilly Masterson...
You're Bond, James Bond, 007, and licensed to kill...").

Confirmed prose controls in the recursive renderer: `%` capitalises the next
letter (`@` ends the one-letter segment, e.g. `% g@`), `|` (0x1c) is a line
break, `\` is the expansion above. **Still untraced** (skipped by the renderer
rather than emitted as raw glyphs): the segmentation/conditional controls
`* ( ) $ ^ & = +` that frame *which* span of a composite record is shown and
the sentence-start auto-capitalisation `sub_3DFB`. Those are the remaining work
to frame a full screen exactly (record 3899 holds more than just the prologue).

#### Inline `$` state tests and `^` breaks (corrected from assembly)

The chase-scene responses are MESSAGE records assembled from `^`/`$`-guarded
fragments. Driving the running game (`look` in the opening chase) prints
*"Tilly: ... can't this thing go any faster?"* and *"... is gaining ground on
you. it's now only 50 meters behind you."*; locating that text in the decoded
stream (symbols ~29009..29150, near the value left in `word_4B7F`=`0x7151`)
shows the structure:

```
...fires a shot.^t3 $pbaaat |p5 \a2? $pjb |a y remains ^pu $ajb |a
^now has fallen back to ^a' is gaining ground on you.  it's now only 50 meters
behind you. ^p1 ...
```

The later renderer disassembly supersedes the earlier interpretation here:
`$` (raw symbol `0x1f`) enters `msg_ctrl_dollar` and evaluates native
scene/runtime records. `^` (raw symbol `0x1b`) is the paragraph break by
default but ALSO carries a 2-byte conditional opcode when the next two
symbols are non-controls -- pattern `^XX` (e.g. `^ac` closed-state,
`^a:` cable-loose, `^if` plans-readable, `^ef` plaque-default). When the
byte after `^` is a control like `%` (READ LETTER's `^% n`), `^` remains a
bare paragraph break with no operand. This 2025-2026 EXAMINE-record
analysis supersedes the earlier "only `$` is a predicate" rule.

##### `msg_ctrl_dollar` opcode dispatch (overlay `loc_CC86`, addr 27938+)

The dispatcher reads ONE opcode byte (via `sub_AE27` mode `0x57`), then
per-opcode multi-way dispatches. Every handler writes the boolean result to
`ds:byte_4B7B`; downstream code (`sub_9AFF` at 21020) reads `byte_4B7B` and
calls `msg_ctrl_break` with skip=1 to drop the fragment when false.

Opcodes identified from the disassembly (semantics still partially traced):

| Opcode | ASCII | Handler addr | Reads | Notes |
| ---: | :---: | ---: | --- | --- |
| `0x66` | `f` | `loc_CF64` | context record flag `+1C` or `+25` | **Ported evaluator**, shared with g/i. |
| `0x67` | `g` | `loc_CF64` | context record flag `+1B` or `+24` | **Ported evaluator**; opens many EXAMINE branches (`$gpi`, `$ga=`, `$gak`). |
| `0x68` | `h` | `loc_CF9C` | `sub_C93C`: phase-node type `2`, empty node set, then `sub_ABE0` cursor selection | **Ported predicate; cursor side effect exposed by callback.** |
| `0x69` | `i` | `loc_CF64` | inverse of g flag | **Ported evaluator**, shared with f/g. |
| `0x6E` | `n` | (default) | takes zero operand bytes; observed as `$now has...` literal-prose marker |
| `0x6B` `0x6C` `0x70` `0x6D` | `k` `l` `p` `m` | `loc_DA5B`/`loc_DA73`/`loc_DA8B`/`loc_DAA3` | all four dispatch to the SAME shared `sub_D894(mode)` with mode `0`/`1`/`3`/`4` respectively | **Ported (2026-07-04, confirmed live).** Live DOSBox-X `STEPINTO` trace of `OPEN ARMREST` (record 2315's own `$` predicates) resolved the two open questions: `ss:[bx-17h]` (a caller-local value from `msg_ctrl_dollar`'s own frame) equalled `byte_1A4C` exactly (17/0x11) at the breakpoint, and the dereferenced node's `+0x18` byte is the SAME field this port already reads/writes as `node[0x17]` for opcodes 0x32/0x33 (`AsgActionExecutor.execute_set_action`) -- i.e. a Phase-7 runtime node selected by the already-ported `byte_1A4C` cursor, not the separate, still-unlocated VOCAB parse-node tree the earlier version of this row (and the VOCAB section above) warned about. `sub_D894` compares that node's `+0x18`/`node[0x17]` byte against its compiled-in `mode` constant and writes the boolean to `byte_4B7B`. Ported as `AsgVm.evaluate_message_control`'s new `k`/`l`/`m`/`p` branch; `k`/`l`/`m` added to `gamecom.py`'s `_DOLLAR_ZERO_OPERAND_OPCODES` (`p` was already there). Regression-covered in `tests/test_vm.py`. **Not yet fully connected end-to-end**: `OPEN ARMREST`'s overall rendered text is still garbled, because reaching this predicate correctly requires the record's earlier `&:`-nested predicate and dictionary expansion to leave `byte_1A4C`/the node's `+0x18` field in the exact live-observed state first, which this session did not additionally verify byte-for-byte. See TODO.md item 1 and `traces/ab48_section_selector.md`. |
| `0x71` | `q` | `loc_CDD9` | `sub_AE63` -> test against `[+681h]` table | **Ported.** Operand symbol indexes the 7-byte runtime VOCAB node; node `+6` (`value_b`) selects the set element. |
| `0x72` | `r` | `loc_CD4D` | non-empty test of record set `[+18h] - DS:0699` | **Ported evaluator with dispatcher context.** |
| `0x73` | `s` | `loc_CDFF` | parser-cursor chunk (`sub_6408` in sibling exports), then constant true | **Ported; cursor side effect exposed by callback.** |
| `0x74` | `t` | `loc_CDC1` | multi-route test selected by context record `+2` | **Ported.** Types 2/4 enter `sub_665B`, whose paths all return true at `loc_672A` (while optionally advancing parser pointers). |
| `0x75` | `u` | `loc_CED7` | `sub_AE63` -> membership in set difference `[+679h] - [+699h]` | **Ported evaluator.** |
| `0x76` | `v` | `loc_CF0A` | `sub_AE63` -> membership in caller-local 8-byte set | **Ported evaluator with dispatcher context.** |
| `0x77` | `w` | `loc_CD7B` | context room record byte `+11h` membership in one-byte set `0670h` | **Ported with dispatcher room context.** |
| `0x78` | `x` | `loc_CF78` | `sub_BFF3`: reject `value_b == 1`, else test indirect record byte `+12h` in `(caller-local set union {1})` | **Ported evaluator with dispatcher context.** |
| `0x79` | `y` | `loc_CE17` | raw symbol read; membership in one-byte set `[+670h]` | **Ported evaluator.** Observed `$ya`, `$ypo` (plaque alternatives). |
| `0x7A` | `z` | `loc_CE3D` | dispatcher builds a candidate set via `byte_1A51`, `[+5B0h]`, context `+6`, and local-set intersection | **Ported final rule:** nonempty candidate set is true and advances `byte_1A4C` through `sub_ABE0`; candidate construction remains dispatcher-owned. |
| `0x81` | `\x81` (`$;` in MESSAGE) | `loc_CF34` | `sub_AE63` -> test against `[+671h]` table | **Ported evaluator.** |
| `0x22` | `"` | fall-through to `loc_D491` | no dedicated handler; leaves `byte_4B7B` unchanged | **Ported structural default.** In EXAMINE structural evaluation there is no prior live gate to carry, so this is false. Observed `$"ah` cable sagging branch. |

Goldfinger EXAMINE handler decisions:

* **device** (`$ga=`, `$;a`, `^ac`) -- `^ac` "is closed" suppressed when open.
* **cable / guardrail** (`$"ah`, `$;al`, `^a:`) -- `$"ah` is now handled by
  the shared `$"` fall-through rule; the `^a:` loosened-cable branch is
  selected from `PULL CABLE` state.
* **frame** -- fully guarded in `handle_examine`; falls back to room
  description until the native picture-frame states are fully mapped.

Ported outside the suppression table:

* **plaque** (`$e'`, `^ef`, `^mo`, `$ya`, `$ypo`x2, `^au`, `$;a`) -- the
  repeated `$ypo` alternatives are selected from live container state:
  club+ball, club-only, or ball-only on the plaque.
* **cable `^a:`** -- selected from live object state: before `PULL CABLE` it
  is hidden; after `PULL CABLE` the loosened-cable text is rendered.
* **plans/chart/letter mutilated-paper branches** -- selected by an explicit
  intact-document EXAMINE decision. No implemented Goldfinger action currently
  mutilates these documents, so the "badly mutilated" alternatives stay hidden.

Without runtime trace of every `byte_4B7B`-feeding table, the remaining
object-specific handler decisions substitute for the final unmapped predicate
contexts. A future trace session should populate the opcode handlers with
their real predicates; the object-specific decisions can then shrink further.

Audit after the active `$`/`^` cursor port (2026-06-30): the cursor/gate
mechanics are no longer the blocker for ordinary MESSAGE rendering. PLAQUE's
occurrence-specific `$ypo` alternatives are now ported through object-container
state in `handle_examine`; cable `$"ah` is ported as the `$"` structural
fall-through default.

##### Confirmed: chase LOOK assembles records 7151 + 3637 (offline trace + decode)

Live-trace evidence (2026-06-21, see `memory/trace-keyboard-injection-limit.md`):
``look`` at the chase prompt sets ``word_4B7F = 0x1BEF = 7151`` and
``DS:0x1DE5 = 3511``, after which the screen shows two-line response
*"Tilly: Can't this thing go any faster?" / "The lead car is gaining ground on
you. It's now only 50 meters behind you."* Offline decode of those record
indices (`tools/dosbox_debug.py`-free, just `goldfinger.engine`) shows:

* **Record 7151 (1239 symbols)** = the Tilly-response composite. ALL of Tilly's
  in-character lines are in this single record, separated by `@` terminators
  and gated by `^/$` conditional operands. The terminator pattern
  `..nervously.<@>a<@>can't this thing go any faster?` puts the chase look-line
  at the end of the record. Other sections include "I'm here to kill that
  monster Goldfinger", "She was my only sister", "So you're James Bond",
  "Looks like a nice lighter", "Sounds like a command performance", "Jill
  didn't mention anything about plans", "Handy gadgets...", "You are into
  things, aren't you?" (parser fallback), "The fat pervert murdered my sister
  Jill", "Goldfinger's manservant. Jill was terrified of him", "At least you
  were smart enough to escape the Koreans", "I won't rest easy until
  Goldfinger no longer walks this earth", "Those Koreans mean business...".
* **Record 3637 (1434 symbols)** = the chase-distance status composite. Its
  branches: "Gaining ground on you. It's now only 50 meters behind you.",
  "<x> is still <prev distance>", "now has lost ground. It's <x> more than a
  hundred meters back.", "the final <x>...". Distance branches are gated by
  ``^pX``/``$pX`` (chase phase: p1, p4, p6, pz) and ``$ajb``/``^ay``/etc.
* **The multi-fragment assembler (``sub_8628``)** stitches output from 7151 +
  3637 (and likely others, one per scene aspect) for one LOOK turn. Without
  that routine ported, neither record renders cleanly in isolation -- they
  always hold MANY alternatives that the conditional system would normally
  prune to one.

Observed `^/$` operands in record 3637 (28 total): `^p1`, `$pjb`, `^a2`,
`$ajb`, `$now has`, `^av% chas`, `$aqaaae`, `^ajone of`, `$aqaaap`, `^a8`,
`$p`, `^a` (multiple times), `$e?`, `$e4`, `^ay`, `$ebj`, `^awyou're`,
`^ak\\a5`, `^ spikes, 007.me`, `$#t`, `^ smoke, 007.`, `^x!`, `$ey`, `^p`.
Operand lengths vary 1..8 chars; many contain inline literal-prose text
glued to the operand (the chase status sentences themselves), so the
operand parser must stop at known control symbols, not at a fixed length.

Goldfinger constants exposed in code:
* `gameengine/verbs.py`, `games/goldfinger/records.py`, and `tests/test_verbs.py`
  -- the verb dispatch chain (the shared VM's `gameengine/game.py::AsgGame`
  drives it; there is no per-title handler module anymore).
* The MESSAGE positions below are the first-pass chase LOOK/action segment
  captures. The fully general records 7151 / 3637 still need the ^/$ operand
  evaluator + chase state model (see `docs/vm-migration-audit.md`), but the
  traced LOOK spans are now rendered.

Opening chase action segment positions (MESSAGE, not code -- rendering is
via `gameengine/gamecom.py`, not a per-title module):

| Action | MESSAGE position | Port status |
| --- | ---: | --- |
| `LOOK` from the chase prompt | Tilly symbol `58415` + status symbol `29098` | renders the live-traced "can't this thing go any faster?" / 50-meter status pair. |
| `W` / `WEST` from the chase prompt | room segment at record-ish `4365` | renders the hairpin-turn road segment. |
| `PRESS BLACK BUTTON` | symbol `29459` | renders the oil-slick action opener; conditional outcome branches still need `^/$`. |
| `PRESS WHITE BUTTON` | symbol `29732` | renders the spikes action opener; conditional outcome branches still need `^/$`. |
| `PRESS GRAY BUTTON` | symbol `30110` | renders the smoke action opener; conditional outcome branches still need `^/$`. |

These are MESSAGE locations, not replacement prose. The first-pass port renders
the clean action opener before the still-unported conditional branches that
select which Mercedes is affected and how the chase status changes.

#### The `(` section selector

Record 3899 is a *composite*: the visible Aston Martin prologue is one span,
bounded by `(` controls (`<(>lqaaai` immediately precedes "your brand new
silver", `<(>lfaaaa` immediately follows "...listen to Q."). Other spans in the
same record are unrelated messages ("It's over for now. The End.", "welcome
back", the "you see ..." look-table, "Korean guard growls", etc.).

`(` (symbol 0x1e) dispatches to `GAME.000:0x1e232` (runtime 0815:AB48), the
section selector. It reads a label from the stream, branches on the state byte
`DS:0x4b11`, and calls a far-pointer comparison (`0x7c4c` via `0x985f`) to
decide whether to render or skip the following span. So *which* `(` section is
shown is **game-state driven** -- the active label comes from the action/
condition dispatcher (PLAN Phase 5), not from MESSAGE alone.

**Ported (label-parameterised):** `GameComMessageEngine.render_message_record(
index, section=<label>)` implements the selector's *mechanism*: it scans the
record for a `(` whose following symbols equal the requested label and renders
only that span, up to the next `(`. The label is supplied by the caller (the
dispatcher in Phase 5); `render_message_record(3899, section="lqaaai")` returns
exactly the Aston Martin prologue and nothing else, verified against a DOSBox-X
screen capture (`tests/test_dictionary.py::SectionSelectorTest`). An unmatched
label returns `""` (unresolved reference -> no prose, never gibberish). The span
is *located in the data* by scanning markers -- the symbol offsets are never
hardcoded, so AGENT.md's no-hardcoded-span rule holds. With `section=None`
(no dispatcher resolution) the whole composite is still expanded for inspection.

**HYPOTHESIS (not yet trace-confirmed):** the label length. Labels in record
3899 vary (`lqaaai` = 6 symbols, `wwac` = 4), and how the native selector
delimits a label was not visible at the `0815:AB48` entry breakpoint. The port
sidesteps this by matching exactly `len(label)` symbols from the caller-supplied
label; confirming the general label-parse/terminator rule needs a single-step
trace *inside* the selector (a game restart to re-reach the prologue render).

Live trace of the selector (`tools/trace_paren.py`, BP `0815:AB48`) during the
opening render of record 3899, columns = symbol position within the record:

```
hit  sym   label fragment
1..9 56..92  (p6 (e (t (lwaa (wwac (w (m (za   <- short/empty fragments, skipped
10   96    (lqaaai                              <- the new-game prologue fragment
11   1149  (lf...                               <- next fragment; prologue ended
```

So the visible Aston Martin prologue is record 3899 **symbols ~98..1148** -- the
single long fragment following the `(lqaaai` marker. Every earlier `(` fragment
is a few symbols long (label only, no prose) and the record's true head
(symbols 2..55: "now let's continue / It's over for now / The End / play
again") is suppressed by early `$`/`&` conditionals. The state byte `DS:0x4b11`
stayed `0x0b` throughout; the per-fragment render/skip decision is taken inside
`0x985f`/`0x7c4c` against a target the selector receives by far pointer, not
visible at this entry. Resolving *which* fragment is active for a given event
(here, "new game" -> `lqaaai`) is the remaining Phase-5 dispatcher work.

Static re-audit of the captured runtime body in `rt_paren.bin` shows why
`byte_4B11` is insufficient as a standalone selector key. The AB48 routine
also reads the active record through a far pointer (including record bytes
`+6` and `+9`), consumes parser/room cursors, and dispatches through several
far-pointer comparison helpers before reaching render/skip. Consequently the
remaining port target is this full caller context, not a guessed mapping from
state values 5/6/7/0Bh to MESSAGE labels.

One state transition inside that context is now confirmed and ported. At
captured offsets `0x143..0x165` (local type 2) and `0x1DB..0x1F0` (other local
types), the routine performs the same merge: if `byte_4B11 == 5`, retain 5;
otherwise assign the resolved local type byte from `[BP-5]`. This is
`AsgVm.merge_section_state()` and Goldfinger applies it through
`apply_resolved_section_type()`. It does not identify a MESSAGE label by
itself; the upstream far-pointer/type resolver is still required.

The next function in the runtime capture is ported as
`AsgActionState.initialize_dispatch_cursors()`. It copies `1A44..1A4B` to
`1A4C..1A53`, then writes 1 to `1A4C`, `1A4D`, `1A4E`, `1A4F`, `1A50`, and
`1A52`, sets `4B11=0Bh`, and writes `1A51=1` unless `1AEC==1`. The primitive
is invoked at its confirmed top-level `msg_record_open` xref (`loc_81DF`), not
during inline dictionary expansion. The remainder of `sub_7BB7` is modelled
too: work-block clearing, gate defaults, `word_4B12`, and the `1A56` compare.
`sub_7DAC/sub_33F6` creates the node-0 cursor; `sub_7DB8` implements the
two-stage `-2C/-2D` local gate write.

Tooling: register reads over the debug TCP socket were added to the DOSBox-X
build (`R` command in `src/debug/debug.cpp`); helpers `tools/find_handler.py`
(signature-scan to locate the handler in guest RAM regardless of load segment)
and `tools/trace_dict.py` / `tools/collect_indices.py` drive the capture.

#### Word-wrap / screen layout (CONFIRMED)

After a record is rendered to characters, GAME.COM lays the text onto the
80-column screen with a word-wrap routine at `loc_3662..loc_38D1` (helper
`sub_363A`). Confirmed structure plus live values dumped from the running game
(shared `DS`, here `0x15dd`):

- **Wrap column**: a printed-column counter held by a far pointer (`[bp+4]`) is
  compared `cmp ax, 4Fh` (79); on reach the line wraps (`loc_3836`/`loc_3844`
  resets the column to 0). A word that would pass column 79 moves whole to the
  next line (`loc_3778` backs up the column to `0x4E` and re-emits the word).
- **Rows**: `word_1AF4` is the current row; at `0x18` (24) the screen scrolls
  (`loc_3858`) instead of advancing.
- **Separators** (runtime values): `byte_1BE8 = 0x0D` is the hard break;
  `byte_48F3 = 0x7F` is the soft word-break, substituted to `byte_1AF6 = 0x08`
  (`loc_36EE`/`loc_3702`) which then drives the wrap path (`loc_371E`). These
  break markers are *inserted by the control logic*, not produced by the symbol
  table (no symbol maps to 0x0D/0x7F/0x08). The exact injection point is not yet
  traced.
- **Line buffer** `DS:0x1BEC` holds the composed line; dumped mid-prologue it
  read `"You're Bond, James Bond, 007, a"` -- already single-spaced with
  punctuation attached, confirming the routine normalises separators.

Ported as `GameComMessageEngine.layout_text()` (presentation step in
`GoldfingerGame.opening_text`): per paragraph it collapses separator runs to one
space, attaches punctuation (no space before `. , ; : ! ?`, one space after),
then greedily wraps at column 79; `|` paragraph breaks become a blank line. This
reproduces a DOSBox-X capture of the new-game prologue screen line-for-line
(`tests/test_dictionary.py::SectionSelectorTest
::test_layout_matches_dosbox_prologue_screen`), e.g. "Auric Goldfinger." (no
space before the period), "Tilly Masterson, out", single-spaced "Mercedes
roars". The screen scroll/cursor mechanics are intentionally not ported (a text
REPL has no fixed 80x25 frame).

#### Status header and input prompt (CONFIRMED)

GAME.COM draws a **top status line** and a separate **bottom input prompt**;
the dash rule belongs to the prompt, not the status line.

- **Top status line** (`sub_4D3A`, near `loc_521B`): prints `aMove db 6,'MOVE #'`
  then the move number via the numeric routine (`sub_2835`); the day-of-week
  label (`'SUNDAY'`, ...) is printed beside it from `byte_1AEE`. The move
  counter starts at **0** (the first turn is `MOVE #0`). Ported as
  `GameComMessageEngine.status_line(n)` / `GoldfingerGame.status_header()`.
- **Bottom input prompt** (asm `9223..9278`): prints 34 spaces then the inline
  `db 10,'----------'` (ten dashes centred on the 79-column screen, column
  `(0x4F - 0x0A) // 2 == 34`), drops the cursor to the bottom row (`word_1AF4 =
  0x18`) and prints the literal prompt `db 3,'-> '` (asm `9264`). Ported as
  `GameComMessageEngine.status_separator()` + `GoldfingerGame.input_prompt()`
  (centred rule, newline, `-> `).

The move counter is a per-turn viewer counter for now; the native increment
timing and the calendar/day-of-week state belong to the dispatcher (Phase 5)
and are not yet ported.

Confirmed low-case symbol mappings used by both `MESSAGE` and `VOCAB`:

| Symbol | Char | Symbol | Char | Symbol | Char |
| ---: | --- | ---: | --- | ---: | --- |
| `0x00` | `a` | `0x01` | `p` | `0x02` | `e` |
| `0x03` | `t` | `0x04` | `i` | `0x05` | `x` |
| `0x06` | `m` | `0x07` | `b` | `0x08` | `q` |
| `0x09` | `f` | `0x0a` | `u` | `0x0b` | `j` |
| `0x0c` | `y` | `0x0d` | `n` | `0x0e` | `c` |
| `0x0f` | `r` | `0x10` | `g` | `0x11` | `v` |
| `0x12` | `k` | `0x14` | `o` | `0x15` | `d` |
| `0x16` | `s` | `0x17` | `h` | `0x18` | `w` |
| `0x19` | `l` | `0x1a` | space | `0x23` | `.` |
| `0x24` | `,` | `0x25` | `-` | `0x26` | `?` |
| `0x27` | `"` | `0x28` | `;` | `0x29` | `'` |
| `0x2a` | `!` | `0x2b` | `:` | `0x2c` | `&` |
| `0x2d` | `=` | `0x2e` | `+` | `0x2f` | `\\` |
| `0x34..0x3d` | `0..9` | | | | |

Unknown:

- Semantics of MESSAGE template control syntax (including `^`, `|`, `*`, `%`,
  and `@`) in game-logic strings.
- Message index/header layout.
- Whether the final two bytes are padding, checksum, or part of an alternate
  access path.

### TABLES message addresses

The big-endian message value in a room record (`+2`) is a position in six-byte
`MESSAGE` blocks, so the symbol stream begins at `offset*8`. It points into a
shared stream of literal prose and script/template controls; it is **not** a
self-contained record prefixed by a 12-bit length. `render_run()` decodes the
literal run there (with `% x@` capitalisation and `sub_3DFB`
auto-capitalisation/spacing) and stops at the first unresolved control, so only
prose reaches the player.

The literal/control boundary uses the **confirmed** control alphabet
(`^ | ( + % = $ & * \`, from `GAME.COM:5160`), not a symbol-range guess. Two
fixes that this corrected:

- Symbol `0x13` was unmapped (rendered `?`); it is **`z`** (confirmed by the
  literal run `do<0x13>ens` = "dozens", and `bree<0x13>e` = "breeze"). It was the
  only missing letter; the table is now complete a..z.
- Literal digits (`0`..`9`) and in-sentence punctuation (`. , - " ; ' ! : ?`,
  the real `?` is symbol `0x26`) are prose, not controls. The earlier
  symbol-range test wrongly treated them as controls and truncated descriptions
  at the first number or `?`. With the corrected test, many rooms render their
  full description (e.g. room 12 now ends "...waver in the slight breeze.", and
  the airport prologue reads in full).

Symbols `0x30..0x33` and `0x3E..0x3F` remain unmapped: they are native template
markers (very frequent in template regions, absent from clean prose), so a
literal run ends when one appears.

Some `+2` offsets still land mid-fragment, and rooms whose text is assembled from
the `\` word dictionary or selected by the conditional `$...|...^...` control
still stop at that control: the native multi-fragment assembler, the
inter-sentence controls (`^ | $ # \`), and the `\` dictionary are not ported yet.

The opening text is a composed native template. It must not be substituted
with prose from an unrelated literal run merely because that run is readable.

## `VOCAB`

Status: record framing known, parser semantics partially known.

`VOCAB` is opened by `GAME.000` around runtime address `068B`. It is not ASCII;
all observed bytes are small token values. The file is a fixed-record file:
`6136 = 236 * 26`.

Each 26-byte record is:

| Offset | Size | Meaning | Status |
| ---: | ---: | --- | --- |
| `0x00` | 1 | Pascal string length, max `21`. | known |
| `0x01` | 21 | Word text encoded with the `MESSAGE` symbol alphabet. Bytes after length are stale/ignored. | known |
| `0x16` | 1 | Parser class/token byte. | observed |
| `0x17` | 1 | Parser group byte. `0x02` is normal parser vocabulary. | observed |
| `0x18` | 1 | Parser value A/subclass. | observed |
| `0x19` | 1 | Parser value B/id. | observed |

Observed file facts:

| Property | Value |
| --- | --- |
| Size | `6136` bytes |
| Unique byte values | `65` |
| Byte range | `0x00..0x41` |
| First 16 bytes | `07 00 04 0f 01 14 0f 03 00 19 09 00 06 29 05 31` |
| Last 16 bytes | `02 1a 16 03 02 01 16 16 14 39 18 15 33 02 0a 02` |

Most frequent values:

| Value | Count | Current interpretation |
| ---: | ---: | --- |
| `0x02` | `808` | observed separator/control candidate |
| `0x14` | `618` | observed alphabet/token value |
| `0x16` | `472` | observed alphabet/token value |
| `0x0f` | `405` | observed alphabet/token value |
| `0x15` | `403` | observed alphabet/token value |
| `0x18` | `345` | observed alphabet/token value |
| `0x19` | `254` | observed alphabet/token value |
| `0x03` | `248` | observed alphabet/token value |
| `0x39` | `239` | observed separator/control candidate |
| `0x00` | `219` | observed separator/control candidate |
| `0x04` | `197` | observed alphabet/token value |
| `0x01` | `195` | observed separator/control candidate |
| `0x33` | `153` | observed separator/control candidate |

Useful parser observations:

| Pattern | Meaning |
| --- | --- |
| `class=0x33, group=0x02, value_a=0x00` | Object noun id in `value_b`. |
| `class=0x33, group=0x02, value_a=0x02` | Location noun id in `value_b`. |
| `group=0x02, value_a=0x05` | Direction word; `value_b` is direction id. |
| `group=0x02, value_a=0x06` | Action verb; `value_b` is verb id. |

The `value_a` byte (record `+0x18`) is the part-of-speech discriminator. The
direction case is fully verified against the shipped `VOCAB`: every one of the
12 `value_a == 0x05` entries is a direction word, and their `value_b` values
cover exactly `{0,1,2,3,4,5}` — the same ids consumed by the dispatcher
direction loop. This is ported as `VocabEntry.is_direction` /
`VocabEntry.direction_id` and `VocabDecoder.directions()`, so a parsed
direction word feeds straight into `TableDecoder.resolve_entry`.
`ParsedCommand` also exposes the raw ids for the observed action-verb,
object-noun, and location-noun patterns above. These ids are data available to
the future native dispatcher, not a claim that their action semantics are
already ported.

Observed `value_a` distribution: `2` (66), `6` (56, verbs), `10` (48),
`0` (33, nouns), `5` (12, directions), `8`/`9` (7 each), `1` (4), `7` (2),
`3` (1). The verb/noun groupings are strongly indicated by the data but are not
yet confirmed from the disassembly: the routine that matches a typed word
against the 26-byte `VOCAB` records and reads their `+0x18` discriminator has
not been located. Anchors checked and ruled out:

- `GAME.000:0x068b` is the `VOCAB` file loader (open + read into memory), not
  the input matcher. It does not keep the on-disk layout: it reorganizes data
  into an in-memory structure (e.g. a stride-`0x100` loop from base `DS:0x0e6f`).
- `GAME.000:0x133a` walks a runtime parse-node chain through a far-pointer
  table at `DS:0x04b4` (built at `GAME.000:0x17da`). Its `+0x17`/`+0x18` are
  parse-node link/flag fields, not the `VOCAB` `group`/`value_a` bytes — same
  offsets, different structure. Do not treat this as the part-of-speech trace.

The input lookup/update path is located in `GAME.COM:2D3A..2F6A`. It uses the
loader-built word structures rooted at `DS:06AF` and the 256-byte character
buckets at `DS:0E6F`, then leaves a result index in `DS:1A0E`. The overlay
consumes that result as `DS:06AF + index * 7` (`GAME.000:5660..5692` and
`7E36..7E5C`), so it is definitely an index into the loader-built 7-byte node
table, not directly a 26-byte on-disk `VOCAB` record index.

The node table is a **binary search tree**, not a flat sorted array. The loader
build at `GAME.000:0x68b` reads `VOCAB` records sequentially and calls the
insert routine `sub_0x282` for each one; the matcher at `GAME.COM:2D3A`
navigates the tree (`GAME.COM:2E4C` forms `(lo+hi)/2` and indexes
`mid*7 + 0x6af`). So the node index is an insertion/tree position and is
definitely **not** the file-order disk-record index.

Node 0 is a header/root, initialized at `GAME.000:0x770..0x797` to the 7 bytes
`[1, 2, 1, 0x33, 2, 0x0a, 1]`. Its `0x33` (51) and `0x0a` (10) match the
51-entry array cleared at `DS:0x19b3` and the ten 256-byte buckets built at
`DS:0x0e6f` -- so the header carries structure counts, and the same 7-byte slot
shape is reused for real word nodes.

`sub_0x282` is now read cleanly from the IDA disassembly of GAME.000
(`goldfinger_overlay.asm`, loaded at base `0x100`). Its insert logic:

- `node = [bp+4] * 7 + 0x6af` (`0x293..0x29c`).
- `node+1 := record[0]` (the Pascal word length), via the parent static link
  `[bp-4]` reading `ss:[bx-0x1e]` (`0x2c0..0x2c8`).
- A **4-byte block at `node+3`** is filled by `sub_AFED` (count = 4,
  `0x2a2..0x2b5`).

Resolved earlier puzzle: the `les di,[bp-0Ch]` at `0x2a2` is *not* a mystery
pointer -- it reloads the `(ds:node)` pair just pushed at `0x2a0/0x2a1`, so the
copy destination is simply `node+3`. The 4-byte **source** is a loader-frame
local reached through the Turbo Pascal static link (`lea di, ss:[bx-8]` with
`bx = [bp-4]`).

**Confirmed by live DOSBox-X memory dump (`DS:0x6af`).** The node 0 header reads
`01 02 01 33 02 0A 01` exactly as decoded from the loader, and across the 236
word nodes the bytes at **`node+3..node+6` equal that word's four `VOCAB`
metadata bytes** (`class`, `group`, `value_a`, `value_b`). Example: node 1 is
`01 07 03 | 33 02 02 08` -- `node+1 = 0x07` is the length of `airport`, and
`33 02 02 08` is `airport`'s metadata. All 236 word-node payloads match a VOCAB
metadata tuple. So the recovered 7-byte node layout is:

| Offset | Meaning |
| ---: | --- |
| `+0` | node type/flag (`0x01` for word nodes; header node 0 also `0x01`). |
| `+1` | word length (`record[0]`). |
| `+2` | offset of the word text in the loader string pool (monotonic across nodes). |
| `+3..+6` | the four `VOCAB` metadata bytes: `class`, `group`, `value_a`, `value_b`. |

This closes the node->attribute bridge: the matcher (`GAME.COM:2D3A`) returns a
node index in `DS:0x1a0e`, and the dispatcher reads the parsed word's
`class/group/value_a/value_b` straight from `node+3`. It also confirms the
`value_a` part-of-speech discriminator end to end (disk record -> tree node ->
dispatcher). The Python parser
currently reproduces lexical matching from the original encoded disk entries.
`RuntimeVocabNodeTable.raw_by_node` now materialises the exact seven-byte
runtime layout, so native node attributes use confirmed bytes.

Confirmed on the input path: typed text is re-encoded into the 6-bit symbol
alphabet through the ASCII->symbol table at `DS:0x1e38`, built in the
`GAME.000:0x23ba..0x2706` range (the inverse of `DEFAULT_SYMBOL_TABLE`; the same
range already credited for reconstructing the decode table). So the parser
compares words in symbol space, consistent with `VOCAB` storing word text in
that alphabet. This initialization is ported in `gameengine/input_encoding.py`:
the 128-byte table folds ASCII letter case, maps digits/space/punctuation, and
leaves unmapped ASCII bytes at zero as in the native cleared table.
`GoldfingerParser` performs its vocabulary phrase lookup against these encoded
symbol tuples rather than against a separately normalised text representation.

### Sentence assembly (`GAME.000:0x4DA..0x5C7`, now disassembled)

Status: routing known; full role semantics still being mapped.

Once a word is matched, the parser routes it by `value_a` (`node+5`, read as
`es:[di+2]` off the metadata block):

- `value_a` in `0..5`: stored into a positional slot, `word_19A7 + value_a*2`
  (six slots).
- `value_a` in `{0x06, 0x0A}` (`GAME.000:0x544`): recorded into the sentence
  array as `array_19B3[class] := value_b`, i.e. keyed by the word's **class**
  byte (`node+3`). So `class` is the grammatical slot/role and `value_b` is the
  id placed in it. The 51-byte `array_19B3` (cleared at loader init) is the
  assembled command.
- other `value_a` values take further branches (`value_a==1` indexes the
  `0x438` table; `value_a==9` has its own path).

Correction to the earlier simple reading: `value_a` is a routing category, not a
clean part-of-speech tag. `value_a==0x05` (directions) is exact, and the common
`0x00`/`0x06` cases are object-noun/action-verb, but `value_a==0x0A` is
**heterogeneous**: it holds movement verbs (`go`, `enter`, `climb`, `drive`,
`get in/out` -- all `value_b==0x0D`) *and* content nouns/adjectives (`black`,
`gold`, `guard`, `golden girls`). Within a `value_a` class, `class` and
`value_b` disambiguate the actual role. The verb->action mapping itself is a
table lookup `word_4B7F := table_0x5F0[value_b]` via `sub_3A88`.

Direction ids:

| Id | Direction |
| ---: | --- |
| `0` | north |
| `1` | south |
| `2` | east |
| `3` | west |
| `4` | up |
| `5` | down |

Unknown:

- Exact meaning of all parser class bytes.
- Synonym conflict priority in the original parser.

### TABLES record families and direction availability

Every `TABLES` record is 40 bytes and begins with a raw family byte at `+0`.
The shipped file starts with a single `0x07` record, followed by other
non-room families, before the `0x02` room records. Therefore room id `0` is
the first type-`0x02` record in the loader-built pointer order, not file record
`0`. `TableDecoder.records_by_type()` preserves that native ordering without
assigning speculative meanings to the other families.

`GAME.000:213B..21A9` evaluates all six direction slots using the same rule as
the selected movement path. The six slots live at record offset **`+0x05`**
(not `+0x04`; the `+0x04` byte is a separate field that is `0` in every room)
and are ordered to match the VOCAB direction ids `N, S, E, W, U, D`. Each slot
holds a **1-based** native room id: id `1` is the null room (type-`0x02` index
`0`) and means "no exit"; id `v >= 2` resolves to type-`0x02` index `v - 1`. A
target is enterable only when its live `+0x24` byte is zero.

This layout is established by **offline direction-aware reciprocity**: pairing
each exit with its compass opposite (`N<->S`, `E<->W`, `U<->D`) over the 65 room
records, base `+0x05` with the 1-based mapping yields **146/166 (87%)**
reciprocal links, versus only `16/143 (11%)` at base `+0x04` or with the naive
direct index. The remaining ~13% are genuine one-way passages (falls/slides).
The result is exposed as `TableDecoder.native_direction_availability()` and
`resolve_entry()`, stored in `GameState.direction_available` when Python
evaluates a move, and locked by `tests.test_tables.test_direction_graph_is_reciprocal`.
It is raw state only; it does not justify rendering an exit list or a room
description before the native template dispatcher is ported.
- Full multi-word grammar handling for indirect objects/prepositions.

## `TABLES`

Status: record framing known, table semantics partially known.

`TABLES` is opened by `GAME.000` around runtime address `1DF7`. It appears to
hold the structured world model and action data.

Observed file facts:

| Property | Value |
| --- | --- |
| Size | `4320` bytes |
| Unique byte values | `186` |
| Byte range | `0x00..0xff` |
| First 16 bytes | `07 01 00 00 00 00 00 00 00 00 00 00 00 00 00 00` |
| Last 16 bytes | `fd d2 4a 03 00 00 00 00 00 00 01 00 00 01 00 01` |

Most frequent values:

| Value | Count | Current interpretation |
| ---: | ---: | --- |
| `0x00` | `2774` | empty/default field candidate |
| `0x01` | `755` | boolean/id/default candidate |
| `0x02` | `89` | small enum/id candidate |
| `0x06` | `24` | unknown |
| `0x14` | `23` | unknown |
| `0x20` | `23` | space/flag/id candidate |
| `0x1e` | `21` | unknown |
| `0x09` | `21` | unknown |

`GAME.000:1DF7` opens `TABLES` with record size `0x28`, so the file is
`108 * 40` byte records.

Known record families by first byte:

| Type | Count | Current role |
| ---: | ---: | --- |
| `0x01` | 26 | Object state records. |
| `0x02` | 65 | Room/location records. |
| `0x03` | 4 | Late-game/special records. |
| `0x06` | 4 | Global/config records. |
| `0x00`, `0x04`, `0x07`, `0x08`, `0x09` | 9 total | Special parser/story records. `0x00` (5 records) = NPC dialogue/narrative records, structure decoded below. |

Room records (`type=0x02`) currently decoded:

| Offset | Size | Meaning | Status |
| ---: | ---: | --- | --- |
| `0x00` | 1 | Record type `0x02`. | known |
| `0x02` | 2 | Big-endian `MESSAGE` offset for room prose. | known |
| `0x04` | 1 | Separate field, `0` in every room (not a direction slot). | observed |
| `0x05` | 6 | Six direction slots `N, S, E, W, U, D`; 1-based room ids (`1` = no exit, `v` -> index `v-1`). Confirmed by 87% opposite-direction reciprocity. | known |
| remaining | 30 | Flags, conditions, dynamic state. | observed |

Room-record field survey (2026-07-01, pristine TABLES, all 65 records):

| Offset | Pristine values | Note | Status |
| ---: | --- | --- | --- |
| `0x01` | 57 distinct | Per-room near-unique id/index (sub-type or authored room id). | observed |
| `0x04`,`0x0B`,`0x0C`,`0x0D`,`0x0E`,`0x10`,`0x26` | all `0` | Unused / runtime-only for rooms. (`+0x0D` = the activation flag set `0->1` at runtime; `0` pristine confirms savegame-format §5.2.) | observed |
| `0x0F` | `0`(64) `1`(1) | Rare per-room flag. | observed |
| `0x11` | `0`(46) `4`(2) `16`(5) `32`(12) | Looks like a room-attribute **bitfield** (single-bit values 4/16/32). Meaning unconfirmed. | observed |
| `0x12`..`0x13` | `+12` mostly `0` (one `6`); `+13` all `1` | `+0x12` = runtime MESSAGE pointer (dispatcher-set; pristine ~0). `+0x13` constant `1`. | observed |
| `0x19`,`0x1A`,`0x1B`,`0x1C` | mostly `0`, few varied | `+0x1A` = runtime room id (savegame-format); others rare per-room state. | observed |
| `0x25` | `1`(56) `0`(9) | Flag; `1` for most rooms. Meaning unconfirmed. | observed |
| `0x27` | all `1` | Constant marker. | observed |

Object records (`type=0x01`) are loaded as 26 object slots. The object id used
by `VOCAB` corresponds to this slot number for known nouns such as `car key`,
`armrest`, `buttons`, `desk`, `plans`, and `lighter`.

Object records (`type=0x01`) currently decoded:

| Offset | Size | Meaning | Status |
| ---: | ---: | --- | --- |
| `0x00` | 1 | Record type `0x01`. | known |
| `0x09` | 2 | Little-endian `MESSAGE` record index for EXAMINE text. | known |
| `0x0C` | 1 | Native object location/container byte. `TAKE LIGHTER` hit `sub_BC69` branch `0xBD16` (discriminator 2), whose writer is `mov es:[di+0Ch], al`. The same trace wrote `AX=0x0053`, so `0x53` is the observed carried/inventory marker. **Runtime-only field: all 26 object records have `+0x0C == 0` in pristine TABLES** (initial placement is encoded by the `+0x18` container link, not `+0x0C`). Confirmed value range (2026-07-01): `0` = unplaced, `0x53` = carried, `1..65` = a 1-based room id (DROP/THROW write `current_room+1` — always the *current* room in Goldfinger's action set), `container.value_b` = placed in a container (PUT). No Goldfinger action places an object in a *non-current* room, so the three ported rules cover every case; non-current-room placement stays open only for sibling titles. | observed |
| `0x0D` | 1 | Native action-field target for `sub_BC69`/`sub_BD67` discriminator `4`. Value semantics still depend on the calling action opcode. | known field |
| `0x15` | 1 | Native action-field target for discriminator `1`. Opcode `0x5A/0x5B/0x4B` paths write through this slot. | known field |
| `0x16` | 1 | Native action-field target for discriminator `3`. Value semantics still depend on the calling action opcode. | known field |
| `0x18` | 1 | Initial container VOCAB `value_b` for object records; `0`/`1` mean no container. Examples: plans -> desk (`0x0B`), chart/letter -> safe (`0x0A`), club/golf ball -> plaque (`0x17`). | ported |

Object-record field survey (2026-07-01, pristine TABLES, all 26 records):

| Offset | Pristine values (count) | Note | Status |
| ---: | --- | --- | --- |
| `0x0D` | `0`(5) `1`(4) `2`(2) `3`(2) `5`(1) `9`(12) | Per-object value 0..9 -- **NOT** the activation flag (that is the *room* `+0x0D`, which is `0` in all 65 pristine room records; savegame-format §5.2's "00->01" is rooms/global, not objects). Object meaning unconfirmed (category/zone?). Also the `sub_BC69` discriminator-4 target. | observed |
| `0x15` | `0`(26) | All-zero pristine -> runtime/mutable field (like `+0x0C`); `sub_BC69` discriminator-1 target. | observed |
| `0x16` | `0`(26) | All-zero pristine -> runtime/mutable field; `sub_BC69` discriminator-3 target. | observed |
| `0x19` | `0`(6) `2`(2) `4`(2) `5`(4) `6`(12) | Per-object value 0..6, meaningful (authored). Meaning unconfirmed. | observed |
| `0x1B` | `0`(26) | All-zero pristine -> runtime/unused. | observed |
| `0x1C` | `1`(21) `0`(5) | Flag; `0` only for {device, photos, desk, liquid, armrest}, `1` for the rest. The `:` conditional opcode (0x3A) uses a record's `+0x1C` as a **mutable show-once flag** (test-and-set; see `traces/chase_state_localization.md`) -- but that toggles the record at the amp/dollar handler's `[bp-15h]`, which may not be this type-0x01 object record. Whether the pristine object `+0x1C` pattern is the same show-once field or a separate static attribute is unconfirmed. **New confirmed use (2026-07-04):** for the 4 known container objects (desk/safe/armrest/plaque), this field also cleanly predicts whether the container needs opening before its contents are reachable: `0` for desk/safe/armrest (real enclosures, each with a confirmed OPEN/CLOSE cycle in the walkthrough) vs `1` for plaque (a display mount -- `TAKE BALL` succeeds immediately in the walkthrough with no `OPEN PLAQUE` step ever occurring). Ported as `AsgGame._is_hidden_in_unopened_container`'s container-gate check. Whether this is the SAME semantic field as the show-once flag above, or a coincidental correlation over only 4 data points, is not further confirmed -- flagging both uses here so a future session doesn't treat them as unrelated discoveries. | ported (container-gate use) |

Trace note (2026-06-25): `tools/trace_take_drop.py` was run against the
DOSBox-X debug TCP build. The relevant hit was runtime linear `0x13E66`
(`CS:IP 13E6:0006`), i.e. overlay `0xBD16` after adding the resident overlay
base `0x8150`. The observed TAKE value was `0x53`, now exposed as
`OBJECT_INVENTORY_LOCATION_VALUE`. Generic `PUT <object> IN/ON
<object-container>` now writes the target container's VOCAB `value_b` to this
same mutable `+0x0C` field; e.g. PUT PLANS IN DESK writes `0x0B`.
Special object-container action branches use the same representation: PUT
BALL IN HOLE writes `hole.value_b` (`0x08`) and the branch-specific side
effect opens the secret door. DROP writes the current native room id
(`state.current_room + 1`) into the same field, and LOOK's visible-object
tail reads that value back. The POCKET pseudo-container is different: the item
remains carried (`+0x0C == 0x53`), while a save-compatible stash flag on the
object id selects the "already in your pocket" branch. Other non-object
pseudo-container values still need semantic mapping.

Static object-containment follow-up (2026-06-30): object record `+0x18`
stores the authored initial container relationship. Goldfinger now derives
the initial container contents for OPEN/TAKE/EXAMINE PLAQUE from this TABLES
field instead of hard-coded `_INITIAL_*CONTAINER*` maps.
One game-specific wrinkle: VOCAB `value_b=0x0A` names both the picture frame
and the revealed safe interaction. The authored `+0x18` links chart/letter to
that record; once `TYPE MY GOLDEN GIRLS` seeds the live `"safe"` container,
runtime container state takes precedence for player-facing text
(`"out of the safe"` rather than `"out of the frame"`). OPEN/CLOSE preserve
the exact parsed noun for this alias too, so `OPEN SAFE` after reveal reports
the safe state rather than falling through to the shared frame object name.

Static follow-up (2026-06-26): `GAME.000:sub_BBC3` decodes action operands
into a selector namespace and index. Operands `0..5` use selector `0x41`
for the current object record; `6..15` use selector `0x58` for the 4-byte
stride word array at `DS:1A8D`; operands `>=16` use selector `0x54` for the
4-byte stride word array at `DS:1A5F`. `sub_BC69` writes and `sub_BD67`
reads the same targets:

| Operand | Target |
| ---: | --- |
| `0` | literal `0` on read, no write |
| `1` | current object record `+0x15` |
| `2` | current object record `+0x0C` |
| `3` | current object record `+0x16` |
| `4` | current object record `+0x0D` |
| `5` | global `word_1AE8` |
| `6..15` | `DS:1A8D[(operand - 6) * 4]` word |
| `>=16` | `DS:1A5F[(operand - 16) * 4]` word |

`GAME.COM:loc_5499` prints the literal `SCORE:` followed directly by
`word_1A8D`. Therefore operand `6` / selector `0x58`, index `0` is the native
score word. The Python runtime exposes it as `TableRuntimeState.score`; it is
mutated by the existing action-field opcodes and preserved in the selector
array save extension.

This mapping is ported as `TableRuntimeState.decode_native_field_operand`,
`read_native_field`, and `write_native_field`; regression coverage lives in
`tests/test_tables.py`.

### NPC records (`type=0x00`) -- structure located (2026-07-04)

Status: record layout confirmed via direct decode; per-character identity
and full per-slot semantics not yet confirmed. This is new ground -- no
prior static or live-trace work had examined these 5 records.

Goldfinger's TABLES has exactly 5 `type=0x00` records (also 40 bytes, same
stride as every other family). Byte-by-byte decode of all 5:

| Offset | Field | NPC0 | NPC1 | NPC2 | NPC3 | NPC4 |
| ---: | --- | --- | --- | --- | --- | --- |
| `0x00` | type | `0` | `0` | `0` | `0` | `0` |
| `0x01`-`0x02` | LE word (MESSAGE raw-symbol offset A) | `0x0000` | `0x1a02` | `0x1bd4` | `0x1ba0` | `0x1ca9` |
| `0x03`-`0x04` | LE word (small, NOT a MESSAGE offset) | `0x0000` | `0x0053` | `0x00d0` | `0x008e` | `0x00a1` |
| `0x05`-`0x06` | LE word (MESSAGE raw-symbol offset B) | `0x1a00` | `0x1b8a` | `0x1ca4` | `0x1bd2` | `0x1e35` |
| `0x07`-`0x08` | LE word (MESSAGE raw-symbol offset C) | `0x19ff` | `0x1b8e` | `0x1ca6` | `0x1bd3` | `0x1e36` |
| `0x09`-`0x0a` | LE word (MESSAGE raw-symbol offset D) | `0x1a01` | `0x1b78` | `0x1c8b` | `0x1bd1` | `0x1e1b` |
| `0x0b`-`0x0c` | LE word (MESSAGE raw-symbol offset E) | `0x19a3` | `0x1a22` | `0x1bef` | `0x1bc0` | `0x1ccc` |
| `0x18` | byte | `0x01` | `0x1d` | `0x14` | `0x16` | `0x16` |
| `0x19` | byte | `0x00` | `0x00` | `0x00` | `0x00` | `0x02` |
| `0x1b` | byte | `0x00` | `0x63` | `0x63` | `0x63` | `0x63` |
| `0x1d` | byte | `0x01` | `0x05` | `0x09` | `0x0f` | `0x16` |

**Confirmed by direct decode**: the four fields at `+0x05`, `+0x07`, `+0x09`,
`+0x0b` (offsets B/C/D/E) are raw offsets into `MESSAGE`'s depaged symbol
stream (`GameComMessageEngine.dict_symbols`, the *same* addressing space as
the already-documented `MESSAGE_SYMBOL_*` constants in `records.py` -- not
record indices). Decoding each one directly (`dict_symbols[offset:offset+N]`
through `DEFAULT_SYMBOL_TABLE`) produces coherent, character-specific prose
for every single slot on every NPC:

- NPC2's slots contain "...growls: give me the password... only invited
  guests allowed... [Goldfinger] looks you over and says: since you are so
  interested..." -- this is the **Auric Stud guard/Goldfinger capture
  narrative** (traces/ab48_section_selector.md's "Resolved" section this
  session). NPC3's slots overlap heavily with the same narrative ("nods to
  a couple of other guards who grab you and take you to Goldfinger").
- NPC1's slots contain a fight/struggle fragment ("bursts into... you leap
  at him but he fires a tranquilizer dart...").
- NPC4's slots contain the losing-ending fragment ("...you find yourself
  and Pussy tied up on the roof of Fort [Knox]... when you come to...").
- NPC0 (all pointers clustered at `0x19ff..0x1a01`, immediately adjacent to
  each other) looks like an empty/placeholder or shared-template slot.

**Not yet confirmed**: which record is which named character (`tilly`/
`pussy`/`goldfinger`/`oddjob`/`guard`, VOCAB `value_b` `3`/`5`/`2`/`4`/`38`
respectively); none of the small per-record id-like fields checked so far
(`+0x1d`: `1,5,9,15,22`) matched a VOCAB `value_b` cleanly except NPC1's
`5` coincidentally matching `pussy`'s `value_b` -- but NPC1's decoded text
(a struggle + dart) doesn't obviously read as a Pussy scene, so this is
very likely NOT a direct `value_b` cross-reference and needs more evidence
before trusting it. The `+0x03`/`+0x04` small-word field (`0x53`, `0xd0`,
`0x8e`, `0xa1` for NPC1..4) is also unexplained -- too large for a room id,
not in MESSAGE-offset range either. Whether the 5 MESSAGE-offset slots per
record are a fixed schema (e.g. slot B = "capture/failure text", slot D =
"topic reply") or vary per-NPC is unconfirmed; this needs either more
character-by-character decoding across the full text each offset belongs
to (not just a short window) or a live trace of which slot the dispatcher
reads for a given in-game NPC interaction.

This does NOT yet unblock the free-form dialogue TODO item (`tell me about
X` / `ask X about Y`) -- there is still no evidence here of a *topic name ->
slot index* lookup; the parser's `dialogue_request`/`tell_about_topic`
fields still have nothing in `gameengine/game.py` consuming them. But it is
the first concrete lead into what a `type=0x00` record actually contains,
and it directly explains the narrative text behind this session's "guard
captures you" investigation.

### Dispatcher condition gate (`GAME.000:1f36..1f5d`)

Status: known.

Before the dispatcher renders/processes a record it evaluates two byte fields
and ANDs the results (`GAME.000:1f59`):

| Field | Test | Source |
| ---: | --- | --- |
| `+0x17` | value `< 0x63` | `GAME.000:1f3c` |
| `+0x14` | value `!= 0x01` | `GAME.000:1f4f` |

A record is processed only when **both** hold; otherwise the dispatcher jumps
to `GAME.000:2019` and skips it. This is ported as
`TableRecord.dispatcher_active()` and `TableDecoder.dispatcher_active_records()`.
In the shipped `TABLES`, 43 of the 108 records pass the gate; no record has
`+0x17 >= 0x63`, so today the `+0x14 != 1` term is the deciding factor, but the
`+0x17` bound is still enforced as confirmed by the disassembly.

### Verb-to-MESSAGE-record lookup table (`DS:0x5F0`)

Status: known. Captured 2026-06-22 via DOSBox-X `MEMDUMPBIN 15DD 5F0 80`
after a new-game starts.

The native dispatcher resolves `word_4B7F = table[verb_value_b]` via
`sub_3A88(verb_value_b)` which reads from a 68-byte LE-word table at
`DS:0x5F0`. The table is **runtime-built** (not a static `dw` block), but
the builder IS in the GAME.000 overlay (corrected 2026-07-01): the loop at
`GAME.000.asm:0x2dbf..0x2e53` iterates verb ids and, per verb, decodes three
six-bit symbols read via source #7 (`sub_B09C` cx=7 + `0xedd0`) into
`record = s0*0x1000 + s1*0x40 + s2`, storing it at `DS:0x5F0[verb*2]`. (The
earlier claim "NOT present in the GAME.000 static disassembly" was wrong --
see the disproved-hypotheses section.) The following values were captured at
the chase-prompt state of a fresh new game:

| Verb id | Verb | Record |
| ---: | --- | ---: |
| `0x01` | quit | 2180 |
| `0x02` | save | 2167 |
| `0x03` | inventory | 309 |
| `0x04` | wear / put on | 1592 |
| `0x05` | look | 1672 |
| `0x06` | take | 1480 |
| `0x07` | pour | 2830 |
| `0x08` | read | 2079 |
| `0x09` | examine | 2097 |
| `0x0A` | throw | 2726 |
| `0x0B` | kill | 2502 |
| `0x0C` | break | 1635 |
| `0x0D` | burn | 1665 |
| `0x0E` | restore | 1666 |
| `0x0F` | drop | 1447 |
| `0x10` | remove | 1621 |
| `0x11` | open | 2315 |
| `0x12` | put | 2508 |
| `0x13` | lock | 2465 |
| `0x14` | unlock | 2501 |
| `0x15` | close | 2427 |
| `0x16` | take off of | 1590 |
| `0x17` | put on top | 2725 |
| `0x18` | take out of | 1591 |
| `0x19` | prt | 2752 |
| `0x1A` | restart | 2174 |
| `0x1B` | wait | 1408 |
| `0x1C` | press | 3823 |
| `0x1D` | type | 2281 |
| `0x1E` | kiss | 2838 |
| `0x1F` | kick | 3041 |
| `0x20` | flip | 3110 |
| `0x21` | light | 2754 |
| `0x22` | extinguish | 2816 |
| `0x23` | duck | 3296 |

**Each value is a BASE template**, not the final rendered prose. The
actual response is selected from the base record by the `(`-section
selector (`msg_ctrl_section`, see "MESSAGE template control character set"
above) based on chase/scene/inventory state. For example, record 3296
(duck) starts with "Just remember, 007, you're manacled to J." for the
manacled state and falls through to "you duck." for the default state.

**Now built data-driven (2026-07-08), not frozen.** The builder is ported in
`AsgActivationTables.build_verb_response_records` and wired into
`AsgGame` (`self.verb_response_records`), replacing the per-title memdump
capture at runtime. The source pointer was located statically: the **phase-1
activation record carries, at `+0x19` (LE word), the MESSAGE record index of a
packed verb table** (Goldfinger: record 7921). `record_symbols(pointer)` frames
it; verb id `v`'s record is `sym[v*3]*0x1000 + sym[v*3+1]*0x40 + sym[v*3+2]`
(zero = unused slot), i.e. the exact `2df3..2e51` fold. Verified to reproduce
all four exactly-captured titles (Goldfinger/Indiana/AViewToAKill/Voodoo) and to
recover The Mist verb `0x1E` (record 3409) that the hand-capture missed. The
frozen `VERB_RESPONSE_RECORDS` dicts in `games/*/records.py` are now validated
oracles only (`tests/test_verbs.py`): as of 2026-07-10 they are **no longer
wired into any title's config** (`verb_response_records=` removed from all 5
configs that set it; `AsgConfig.verb_response_records` is now just an unused
optional override). The runtime derives the table for every title from MESSAGE
data at load time.

### Scene/room activation (`GAME.000:0d61`)

Status: observed.

The current-room global `DS:0x06a9` has exactly one writer in `GAME.000`: the
store at `GAME.000:de0`, inside the routine that begins at `GAME.000:0d61`.
Room transitions therefore do **not** happen through a direct `0x06a9 :=` in a
movement handler; instead the dispatcher re-runs this activation routine with a
new source record.

`0d61` takes a far pointer to a source record (pushed as `-0x2/-0x4(bp)`) and
copies its fields into the live state globals, including:

| Global | Role (observed) |
| --- | --- |
| `DS:0x0670` | 1-byte field (flag/id). |
| `DS:0x0671` | 8-byte string field. |
| `DS:0x0679` | 8-byte string field. |
| `DS:0x06a9` | Current room id. |
| `DS:0x06aa` | Companion room byte. |
| `DS:0x06ad` | Word field. |
| `DS:0x1ae1`, `DS:0x1add` | Scene flags/counters. |

The activation routine is the first entry in the intro/cutscene sequence
invoked from the dispatcher init (`GAME.000:1ea0` calls `0xd61`, followed by
`0xe43`, `0xe9b`, `0xeea`, ... each preceded by `mov cx,N; call 0xb09c`). This
identifies room/scene activation but not yet the interactive input loop that
selects which record to activate from a parsed `VOCAB` direction/verb token.

#### Full activation chain (2026-06-21 — IDA force-decode via the embedded `disassemble_dispatch_chain` stage)

After running `recover_game_000.idc` (its dispatch-chain stage forces `MakeCode`
at the documented dispatcher addresses since IDA's flow-analysis didn't
reach them via the `55 8B C4` prologue scan), the chain is now visible in
`goldfinger_overlay.asm` and structured as:

```
loc_1EA0:                          ; dispatcher init -- calls phase chain
    call sub_D61                   ; phase 1 -- scene activation
    mov cx, 0Ah; call sub_B09C     ; delay/pacing loop, cx = duration
    call sub_E43                   ; phase 2
    mov cx, 0Ah; call sub_B09C
    call sub_E9B                   ; phase 3
    mov cx, 0Ah; call sub_B09C
    call sub_EEA                   ; phase 4 (also called from msg_emit_response+1F)
    mov cx, 0Ch; call sub_B09C
    call sub_FB8                   ; phase 5
    mov cx, 0Ah; call sub_B09C
    call sub_11C6                  ; phase 6
    mov cx, 0Ah; call sub_B09C
    call sub_132B                  ; phase 7
    mov cx, 0Ah; call sub_B09C
    call sub_1848                  ; phase 8
    mov cx, 0Bh; call sub_B09C
    call loc_1989                  ; phase 9
    ; -- then per-turn evaluation (record loop + direction-slot loop) --
```

**Common phase structure (sub_D61 / sub_E43 / sub_E9B / sub_EEA / sub_FB8 read
side-by-side):** Each phase opens with the same prologue:

```
push bp; mov ax, sp; push [bp-2]; push [bp-4]; mov bp, ax; push bp; jmp $+3
mov bx, [bp-4]
db 36h; lea di, [bx-5Dh]; push ss        ; load record field at -0x5D
call near ptr loc_CA84+2                  ; 32-byte copy op?
mov bx, [bp-4]
db 36h; lea di, [bx-85h]; push ss        ; load record field at -0x85
call sub_CAA3                             ; another copy op
call near ptr loc_B0EC+1                  ; setup
```

Then each phase reads DIFFERENT bytes from the source record and writes
to DIFFERENT globals:

| Phase | Record offset(s) read | Globals written |
|---|---|---|
| `sub_D61` | `[bx-84]`, `[bx-83]`(x8), `[bx-7B]`(x8), `[bx-73]`, `[bx-72]`, `[bx-71]`(word), `[bx-6F]`(x3), `[bx-6C]`, `[bx-6A]`, `[bx-69]` | `loc_670` (1B), `loc_670+1` (8B = DS:0x671), `loc_678+1` (8B = DS:0x679), **`byte_6A9` (current room)**, `byte_6AA`, `word_6AD`, `loc_1AB3+2` (3B), `word_1AE1`, `byte_1ADD`, `byte_1ADE` |
| `sub_E43` | `[bx-...]` | `loc_1A4B+1` (= `DS:0x1A4C`) |
| `sub_E9B` | `[bx-84]` (word) | `word_6AB`, `loc_1A53+1` (= `DS:0x1A54`) |
| `sub_EEA` | `[bx-84]` | `byte_1AE3` -- *also called from `msg_emit_response+1F` for response rendering, so this phase is reused* |
| `sub_FB8` | `[bx-84..-7F]`, then five 4-byte chunks at `[bx-7E+i*4]` | `byte_1A59..byte_1A5C`, `word_1A5D`, then `DS:1A5F+i*4` for `i=0..4`; a second loop repeats the same source chunks into slots `5..9` |

The negative offsets (`[bx-5Dh]` .. `[bx-85h]`) mean `bx` points PAST the
record base (`bx = record_base + ~0x85`). Each phase is essentially a
small field-copy: take specific bytes from the same scene record and put
them into specific globals.

**The Scene Record itself** is what `loc_1EA0`'s caller pushes onto the
stack via `[bp-2]/[bp-4]`. It's larger than a 40-byte TABLES record --
the offsets go to at least `-0x85` = 133 bytes from `bx`, and `bx`
itself is the record base + 0x85 or so. This suggests the Scene Record
is several hundred bytes, possibly a structured composite of multiple
parts. Locating the call site that prepares this record is the next
trace target -- that's where Goldfinger's player-start scene record
comes from.

**Per-phase global ports needed** for a full Python port of the
activation chain:

| Native global | Python equivalent | Notes |
|---|---|---|
| `byte_6A9` | `GameState.current_room` (via byte->index translation) | already ported (`activate_initial_scene`) |
| `byte_6AA` | (new field) | companion room |
| `word_6AD` | (new field) | word value |
| `byte_1ADD`, `byte_1ADE` | (new fields) | scene flags |
| `word_1AE1` | (new field) | scene counter |
| `DS:0x670`, `DS:0x671`, `DS:0x679` | (new fields) | flag + two 8-byte strings (possibly scene short-name + long-name) |
| `byte_1AE3`, `byte_1A59` | (new fields) | additional flags written by EEA/FB8 |

Once these are modelled in `GameState`, each phase routine ports to a
straightforward field-copy method that takes a Scene Record as input
and writes the listed globals.

### Command dispatch (GAME.000, now fully disassembled)

Status: located and readable; per-handler semantics still being ported.

Correction: `GAME.000:~0x2caf` (which stores `word_1A0E -> word_4B12` after
`call sub_CE27`) is the **startup / restore prompt** path (its inline strings
are "Which game would you like to resume (1-9) ?", "Type Y or N."), not the main
per-turn loop. `sub_CE27` is the shared word input+lookup routine.

Confirmed dispatch state and access pattern (`goldfinger_overlay.asm`):

| Global | Role |
| --- | --- |
| `word_4B12` | node index of the current command word (from `word_1A0E`). |
| `word_4B7F` | per-handler result/working value (written by 10+ handlers). |
| `byte_6A9` | current room id. |

The action code reads the command word's metadata as
`node = word_4B12 * 7 + 0x6B2` (i.e. `node+3`, the four metadata bytes), and the
room record via `byte_6A9 << 2` indexed into the `DS:0x25c` room pointer table.
The dispatch is **not** a jump table: it is a sequence of per-verb/rule handler
calls, each leaving its outcome in `word_4B7F`. Porting these handlers (their
conditions and effects) is PLAN Phase 5; the disassembly that makes this
tractable only became available after the inline-string repair pass (see
`docs/reverse-engineering.md`).

### Per-turn dispatcher control flow (`sub_1DEB`, `GAME.000:1DEB..21EB`)

Status: structure mapped from `goldfinger_overlay.asm`; effects not yet ported.

`sub_1DEB` is the per-turn evaluation routine. Reading it end to end gives the
skeleton the already-ported fragments (the `+0x17/+0x14` gate, the direction
loop) hang on:

1. **Parser-global init (`loc_1E58`).** Sets `word_19EC=1` and the
   `byte_6B6` triple (`[0]=1,[1]=2,[2]=1`), clears the working buffers
   `byte_1AB8` (4), `byte_1ACB` (15), `byte_1ADA` (2), then runs a fixed
   **phase chain** of sub-calls, each preceded by `mov cx,N; call sub_B09C`:
   `sub_D61` (room/scene activation, writes `DS:0x06a9`), `sub_E43`, `sub_E9B`,
   `sub_EEA`, `sub_FB8`, `sub_11C6`, `sub_132B`, `loc_1848`, `loc_1989`.
   Their observable field copies, completion markers, and the phase-5
   `DS:1A5F` slot array are ported; the remaining decode target is the
   parser-tree/set logic that consumes the constructed pointer tables.
   A `byte_1AE0 ^ 1` test then branches to the record-evaluation loop or skips it.
2. **Record-evaluation loop (`loc_1F05..2019`).** Iterates an index from `2` to
   `word_19E7` (count of active records for the scene), loads each record
   pointer from the `DS:0x438` table (`les di,[di+438h]`), and applies **exactly
   the `dispatcher_active` gate** (`+0x17 < 0x63` AND `+0x14 != 1`, `loc_1F18..
   1F58`). Active records (`loc_1F62`) resolve their room record via
   `record[0x14] << 2` into the `DS:0x25C` table, copy the room record's `+0x18`
   field (8 bytes) into a work buffer, and process the `+0x0C` field through the
   Pascal set/string helpers (`sub_B593`/`sub_B68A`/`loc_B5F9`). The confirmed
   prelude is implemented by `gameengine.dispatcher.AsgPerTurnDispatcher`:
   runtime `+0x14` resolves the linked TABLES record, runtime `+0x0C..13` is
   the 8-byte rule operand, and linked TABLES `+0x18..1F` is the context
   operand. The following set operation/effect is not yet confirmed.
3. **Direction-slot loop (`loc_202A..210B`).** Driven by `byte_19EA`; this is the
   six-slot exit/entry pass already ported as `resolve_entry` /
   `native_direction_availability` (see below).

The verb-handler dispatch (`word_4B12*7+0x6B2`, `sub_3A88`, result in
`word_4B7F`) is reached on the *command* path, not this per-turn evaluation;
driving it dynamically needs a parsed command, which the in-game keystroke
injection limitation currently blocks (see `memory/live-trace-gotchas.md`). The
record-evaluation pass (step 2), by contrast, runs during new-game startup and
is therefore validatable by a startup trace without keyboard input.

**Startup-trace findings (observed, `DS=0x15dd`).** Validated via a memory-write
breakpoint `BPM 15DD:06A9` on the room global plus `MEMDUMPBIN` of the loop
inputs:

- At the *first* write to `byte_6A9` (the room global), `byte_6B6 = 01 02 01`
  (the `loc_1E58` triple init) is already set, room id = `0x0F`, but `word_19E7`
  and the `DS:0x438` table are still zero -- so the active-record list is built
  by the *later* phase subs (`sub_E43..1989`), after `sub_D61` activates the
  room. By the time the prologue prompt is reached the room is `0x14` (20).
- At the prompt (pass complete) `word_19E7 = 5` and `DS:0x438` has exactly four
  non-default entries at indices `[2..5]` (matching the loop bound `2..word_19E7`).
- **Crucial:** the `0x438` entries are far pointers into a *runtime* record
  array at `DS:0x4BE0`, **32-byte stride** (NOT the 40-byte on-disk TABLES
  records). `0x438[2..word_19E7]` point at array entries `1..4` for the start
  scene; unused slots point at the shared empty entry.

**Runtime record layout (32 bytes, observed for the active type-02 entries):**

| Offset | Observed | Meaning (hypothesis) |
| --- | --- | --- |
| `+0x00` | `02` | record type (matches on-disk: `02`=room) |
| `+0x01..02` | `1a 53` etc. | text/message pointer, **relocated** to a runtime address |
| `+0x03` | `00` | (disk `+3` is also `00`) |
| `+0x04..0x0b` | `8a1b 8e1b 781b 221a` | four **resolved far pointers** built from the disk room record's six direction slots |
| `+0x14..0x15` | `00 1d` / `00 14` / `00 16` | state / category byte |
| `+0x18` | `63` | observed startup value; **not** the active gate. The executed gate is `+17h < 63h && +14h != 1`. |
| `+0x1a` | `05 09 0f 16` | **room id** (`0x0f`=15 was the start room seen at the `06a9` trace) |
| `+0x1c..` | `01 00 01 ..` | flags |

**Disk -> runtime transform.** The on-disk type-02 room record is
`02 [msgptr_lo msgptr_hi] 00 [slot0..slot5] ...` (six direction slots at `+4..9`,
`01`=blocked). The runtime record is **built field by field**, not memcpy'd:
breaking on the array write (`BPM 15DD:4C00`) stops at `0815:0F0C` with the
destination `ES:DI=1A9D:0004` (the array) but the source `DS:SI` pointing at the
**stack**, i.e. the routine computes each field (relocating the message pointer,
resolving the direction slots into far pointers via the `0x25C` table) rather
than copying a disk block. Porting this construction is the remaining bulk of
task #9; the on-disk room-record field layout above is the input, the 32-byte
runtime record is the output.

### Driving in-game turns for differential tracing (CONFIRMED)

The in-game command loop ignores DOSBox `TYPE` injection, but a turn can be
driven by writing the **BIOS keyboard buffer** with the debugger `SM` command:
at the `->` prompt (head=tail, e.g. `0x28`) write keystroke words
`(scancode<<8)|ascii` from the tail in `0040:001E..003D`, then advance the tail
word `0040:001C`. Example "look\r": `SM 40:28 W:266C W:186F W:186F W:256B W:1C0D`
then `SM 40:1C W:0032`; the game consumes the keys and runs the command.

This gives a differential oracle: drive a command, then read the resulting
screen (`MEMDUMPBIN B800 ...`) and globals (`word_4B12`, `word_4B7F`, room).
First confirmed turn (new game -> the Aston Martin chase scene, command `look`):
the move counter advanced to `MOVE #1`, `word_4B7F` = `0x7151`, room = `0x14`,
and the game printed the chase responses *"Tilly: Can't this thing go any
faster?"* and *"The lead car is gaining ground on you. It's now only 50 meters
behind you."* So the opening playable scene is a **vehicle/chase sequence**, not
ordinary room navigation. (Pace BREAK/RUN gently; aggressive churn can reset the
game to a blank/room=0 state.) See `memory/live-trace-gotchas.md`.

### Dispatcher state globals and pointer table

Status: observed from `GAME.000` code.

| Location | Meaning | Source |
| --- | --- | --- |
| `DS:0x06a9` | Current room id (byte). Written at `GAME.000:de0`, read by the direction loop at `GAME.000:210b`/`213c` and many action sites. | observed |
| `DS:0x06aa` | Companion byte written next to the current room at `GAME.000:dec`. | observed |
| `DS:0x025c` | Base of the type-2 room-record far-pointer table. The dispatcher indexes it with `record[0x14] << 2` (`GAME.000:1f6f`, `205d`, `2141`) and with the current room id. | observed |
| `DS:0x0438` | Secondary far-pointer table indexed by record index `<< 2` (`GAME.000:1f28`). | observed |

So the `+0x14` field is both the gate's state byte and the index used to look up
the associated room record in the `DS:0x025c` table; value `1` means "no link /
blocked" in both roles.

### Exit resolution and entry gate (`GAME.000:215e..21a6`)

Status: known.

When the dispatcher evaluates the current room's six direction slots
(`record[0x4+j]`, `j=0..5`):

1. A slot value of `1` is blocked and skipped (`GAME.000:215e`).
2. Otherwise the slot value is the **target room id**, used to index the
   `DS:0x025c` room pointer table (`GAME.000:217e..2189`).
3. The target's `+0x24` aux-state byte gates availability: the global
   `DS:0x1aec` is set to `1` when `target[0x24] == 0`, else `0`
   (`GAME.000:218d..21a6`).

This is ported as `TableRecord.native_entry_allowed()` and
`TableDecoder.resolve_entry(record, direction)`, which returns
`(target_record, entry_allowed)`. The `DS:0x1aec` global itself is runtime
state. `TableRuntimeState` supplies a mutable overlay for this and other
dispatcher writes while keeping the shipped TABLES file immutable. Separately,
`GAME.000:21d0..21e1` marks a room visited by writing `1` to its `+0x22` byte;
the port records that write through this overlay.

Unknown:

- Full object field semantics.
- Action/condition script layout beyond the gate above.
- Timer and combat state fields.
- Initial value of the current-room global `DS:0x06a9` (set from a local record
  field at `GAME.000:dca..de0`, not a static constant).

## `GAME.000`

Status: observed.

`GAME.000` is the main program overlay and includes strings and file-open code
for `VOCAB`, `TABLES`, `SAVE`, and `RESTORE`.

### Toolchain and overlay structure (Turbo Pascal 3)

The program was most likely built with **Turbo Pascal 3**, and the overlay file
`GAME.000` therefore follows TP3's **documented** overlay format. Evidence and
consequences:

- The numbered overlay filename scheme `GAME.000` (a program's first overlay
  group) is exactly the TP3 convention: the compiler emits one overlay file per
  overlay group, named `<exe>.NNN`. The `.COM` core (`GAME.COM`) stays resident
  and pages overlay code in from `GAME.000` on demand.
- The pervasive `call <helper>` followed by an inline `<len-byte><chars>` string
  literal (the convention that desynchronised linear disassemblers until the
  inline-string repair pass) is the TP3 inline-string calling convention: the
  string is stored immediately after the `call`, and the helper bumps the return
  address past it. This is documented TP3 code-generation behaviour, not a custom
  scheme.
- TP3 runtime conventions (the `bp`-based frames, the `sub_FB2`/`sub_F12`
  stack-management thunks wrapping every procedure, base-`0x100` COM layout)
  match what we observe throughout `GAME.COM`/`GAME.000`.

**Consistency with the flat-binary disassembly recipe.** The recommended IDA
recipe (load `GAME.000` as a raw binary at base `0x100`, processor `80286r`,
mark code, repair the inline strings, then run the embedded coverage stage) is
consistent with the TP3 overlay format, and the file's own bytes confirm it:

- `GAME.000` begins directly with executable code (`E8 94 AC ...` = a near
  `call`), **not** a container header at offset 0. TP3 overlay files are
  essentially the overlaid code laid out to be paged into a fixed overlay buffer;
  they do not carry the per-segment relocation header that later Turbo Pascal
  `.OVR` files (TP4+) do. That is exactly why a flat disassembly at the COM load
  bias `0x100` resolves cleanly (the first absolute `call` only resolves at base
  `0x100`).
- The residual `~1130 db` bytes after analysis are **not** overlay segment
  headers or relocation tables. They are unconverted code: the regions begin with
  the standard TP3 procedure prologue `55 8B C4 FF 76 FE FF 76 FC 8B E8 55 E9`
  (`push bp; mov bp,sp; ...`). They just need to be marked as code; nothing about
  the overlay structure has to be parsed to read them.

So the flat-image assumption holds *for TP3 specifically*. The one boundary
where it could break is absolute (DS-relative) references in any code that
belonged to a *different* overlay group loaded at a *different* base; near calls
(`E8 rel16`) are base-independent and unaffected. The evidence so far
(contiguous code from offset 0, all calls resolving at base `0x100`, and DOSBox-X
memory dumps matching the static read) is consistent with `GAME.000` being read
as a single contiguous code image. This is provenance/context for interpreting
`GAME.000`; the per-record game-data formats above still stand on their own
file/disassembly evidence.

Relevant string offsets:

| String | File offset | Runtime address |
| --- | ---: | ---: |
| `VOCAB` | `0x059c` | `0x069c` |
| `TABLES` | `0x1d13` | `0x1e13` |
| `SAVE` | `0x0bc2` | `0x0cc2` |
| `RESTORE` | `0x2b85` | `0x2c85` |

Known code areas:

| Runtime address | Meaning |
| --- | --- |
| `068B` | Initializes/loads vocabulary-related buffers and opens `VOCAB`. |
| `1DF7` | Opens `TABLES` or alternate table source depending on runtime state. |

## Save files

Status: observed from strings only.

`GAME.000` contains prompts for save slots `1..9` and storage disks. The exact
save-file layout is not mapped yet.

Observed names/strings:

- `SAVE`
- `RESTORE`
- `save`
- `Retrieving game #`
- `Saving game #`

Unknown:

- Save file naming convention on disk.
- Save header/magic.
- Serialized game-state fields.

## Implementation status

Implemented:

- File loader and size summary in [`gameengine/data.py`](../gameengine/data.py).
- 6-bit extraction and six-byte unpacking in [`gameengine/packing.py`](../gameengine/packing.py).
- `MESSAGE` record unpacking and partial text decoding in [`gameengine/message.py`](../gameengine/message.py).
- `VOCAB` fixed-record parser in [`gameengine/vocab.py`](../gameengine/vocab.py).
- `TABLES` fixed-record parser in [`gameengine/tables.py`](../gameengine/tables.py).
- Shared VM (`gameengine/AsgVm`) driving the game via [`gameengine/game.py`](../gameengine/game.py)::`AsgGame`; `games/goldfinger/` is config + data only (the old hand-written `interpreter.py` was deleted, see `docs/vm-migration-audit.md`).
- Full winning command path accepted by the interpreter.

Not implemented yet:

- Full message formatting/control-code handling.
- Full action/condition script execution.

## Disproved / superseded hypotheses

Dated record of hypotheses that later evidence overturned. Kept so the same
wrong turns are not repeated. Newest first.

### 2026-07-03

- **`msg_dict_expand`'s `call sub_846B` really targets physical `0xCAD1`.** —
  *Wrong.* A hand-arithmetic slip while applying the 16-bit wraparound
  (`0x640C + 0xE975` miscomputed as `0x14981` instead of the correct
  `0x14D81`) pointed at an address that happened to *also* decode into
  plausible-looking Turbo-Pascal code -- the "any address in dense compiled
  code looks legit" trap. The real target, confirmed by actually
  single-stepping there (`STEPINTO`, added to the custom DOSBox-X debugger
  this session), is `0xCED1` -- a dictionary/MESSAGE symbol-cursor advance +
  bounds check, not a new subsystem. See `traces/sub_846b_resolution.md`.
- **`AB48`'s 4-arg/5-arg entries (`0xAC0B`/`0xAB87`) prepare the section-
  state/label-selection context for a plain data-driven verb response
  (e.g. OPEN's composite record 2315).** — *Wrong.* Breakpoints on both
  entries never fired across a full driven prologue + `open armrest`
  sequence. They are real and do set `byte_1A4C`/test the confirmed `+0x0C`
  SET field/write the `byte_4B7B` gate, but for this call path they simply
  never execute -- they likely belong to a different predicate context
  (chase-related). How record 2315's own `(@LABEL` spans actually get
  selected is still open. See `traces/ab48_section_selector.md`.

### 2026-07-01

- **"The `DS:0x5F0` verb-record table is NOT present in the GAME.000 static
  disassembly / is built by the GAME.COM loader."** — *Wrong.* The builder is
  in the GAME.000 overlay at `GAME.000.asm:0x2dbf..0x2e53`: it decodes three
  six-bit symbols per verb (source #7 via `sub_B09C`/`0xedd0`) into
  `s0*0x1000 + s1*0x40 + s2` and writes `DS:0x5F0[verb*2]`. The captured table
  in `records.py` is that builder's output. (What is still open is the source-#7
  data layout the reader pulls from — see TODO Migration 2 / Task #11.)
- **Single-scene-record activation model** (`GoldfingerGame.apply_scene_record`
  applying all 9 phases to ONE passed record, offsets `SR_OFFSET_*`). —
  *Superseded* by the per-record model in `gameengine/activation.py`
  (`AsgActivationState`/`AsgActivationTables`), where phases 1..5 read the
  distinct type-`7,4,8,9,6` prelude records. The single-record code + its tests
  were removed 2026-07-01 (byte-identical field extraction, so no output change).
  See `docs/asg-vm.md` and `docs/vm-migration-audit.md`.
- **Chase distance/phase lives in the predicate region `ds:0670..06A8`.** —
  *Wrong.* `LIGHT LIGHTER` changed zero bytes there, and a broad-region diff
  located the opening-chase state globals at `DS:0x1A95/0x1ACD/0x1AE5` instead
  (see `traces/chase_state_localization.md`).

### earlier

- Standalone-exit interpretation of the six-byte room direction field
  (see `docs/reverse-engineering.md`, "TABLES loader notes"): disproved by
  MESSAGE-template comparison; the field must be evaluated by the
  action/condition dispatcher. The `+0x3f` terminator / fixed-offset / regex
  cleanup heuristics for MESSAGE are likewise disproved (project rule).
