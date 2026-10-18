# File formats

The engine reads three data files: `MESSAGE`, `VOCAB` and `TABLES`. A saved
game (`SAVE1` … `SAVE9`) is a fourth, in the TABLES format. Offsets are
zero-based and hexadecimal unless noted.

## Symbols

Text in MESSAGE and VOCAB is written in 6-bit symbols, not ASCII. The
translation table (`DS:1DF8` in the original, `DEFAULT_SYMBOL_TABLE` in
`gameengine/message.py`) is the same in all eight titles:

| Symbols | Characters |
|---|---|
| `00`–`19` | the letters `a p e t i x m b q f u j y n c r g v k z o d s h w l` |
| `1A` | space |
| `1B`–`22` | the controls `^ \| * ( $ % @ #` |
| `23`–`2B` | `. , - ? " ; ' ! :` |
| `2C`–`2F` | the controls `& = + \` |
| `34`–`3D` | the digits `0`–`9` |

Letters are lower case; capitals come from the `%` control and from the text
formatter's sentence rule. The controls `^ | ( + % = $ & * \` are the control
alphabet (the set at `DS:1B68`); `@` (symbol `21`) ends a segment. What each
control does is described in [vm.md](vm.md#the-message-language).

## MESSAGE

### Pages

The file is a sequence of 512-byte pages. Each page starts with a two-byte
header followed by 85 six-byte groups (510 bytes). Dropping the headers and
joining the groups gives the continuous stream the reader walks
(`depage()` in `gameengine/message.py`); a record may run across a page
boundary.

### 6-bit packing

Each six-byte group holds eight 6-bit symbols, most significant bits first
(`GAME.COM:46AC`, called `xtrnip` in the program's own error message, and
`GAME.COM:4721`):

```text
b0       b1       b2       b3       b4       b5
aaaaaabb bbbbcccc ccdddddd eeeeeeff ffffgggg gghhhhhh
s1 = a   s2 = b   s3 = c   s4 = d   s5 = e   s6 = f   s7 = g   s8 = h
```

(`gameengine/packing.py`.)

### Records

A record is addressed by its group index: record *n* starts at depaged byte
offset *n* × 6. Its first two symbols are a base-64 length, `s0 × 64 + s1`;
the payload is the next *length* symbols (`GAME.COM:4A89`, seek at `4525`).
The engine refers to text only by record number: TABLES fields, VOCAB-derived
tables and MESSAGE references all hold record numbers.

A `\` in a record is a reference: the three symbols after it form a base-64
record number (`s0 × 4096 + s1 × 64 + s2`), and that record is rendered in
place, controls included. Names, frequent words and shared sentences are
stored once and referenced this way.

## VOCAB

A sequence of 26-byte records, one per word or phrase (`GAME.000:068B`):

| Offset | Size | Field |
|---|---:|---|
| `00` | 1 | length of the text |
| `01` | 21 | the text, one symbol per byte |
| `16` | 1 | `class_id`: the word's class (the verb class for verbs, e.g. TAKE `14`, RIDE `12`, KILL `2A`) |
| `17` | 1 | `group_id`: how the word is printed — `0` in capitals (DB5, M), `1` capitalised (Goldfinger), `2` as it is |
| `18` | 1 | `value_a`: the word's kind — `0` object, `1` person, `2` room or scenery, `5` direction, `6` verb, `0A` speech word, and others |
| `19` | 1 | `value_b`: the word's value — the index of the object, person or room it names, the direction 0–5 (N, S, E, W, U, D), the verb number |

At load the engine builds a node table at `DS:06AF` (seven bytes per word:
type, length, text offset, then the four metadata bytes, which the engine
reads at `06B2 + 7 × word`). The parser matches
the longest phrase first; several words may share a value (synonyms).

## TABLES

A sequence of fixed-size records: 40 bytes in variant A, 47 bytes in variant
B ([architecture.md](architecture.md#two-engine-variants)). The first byte is
the record type; the field offsets are the same in both variants.

### Record families

The activation chain ([vm.md](vm.md#activation)) copies each family into its
own in-memory table. The copy starts at record byte `01`, so in-memory offsets
are the record offsets minus one; this documentation uses the in-memory
offsets.

| Type | Family | Table | Bytes copied (variant A) | Index |
|---:|---|---|---:|---|
| `00` | people | `DS:0438` | 29 | `2 .. word_19E7` |
| `01` | objects (phase-7 nodes) | `DS:04B4` | 30 | `2 .. byte_19E9` |
| `02` | rooms (including scenery) | `DS:025C` | 39 | `2 .. byte_19EA` |
| `03` | route records (vehicles, walkers) | `DS:05B0` | 33 | `2 .. byte_19EB` |
| `07`, `04`, `08`, `09`, `06` | start state, phases 1–5 (the first records, in this order) | the globals | | |

Slot 1 of every table is an empty record, the null entry ("nobody", "nothing", "nowhere"),
which is why a cursor or field holding 1 means "none". The field layouts of
each family are in [memory-layout.md](memory-layout.md#tables-in-memory).

### Start state

The first records hold the start state the activation copies into the globals:

| Record (type) | Phase | Fields (record offsets) |
|---|---|---|
| 0 (`07`) | 1 | `+01` `byte_670` (powers), `+02..09` set `0671` (in hand), `+0A..11` set `0679` (worn), `+12` start room `06A9`, `+13` direction `06AA`, `+14..15` `word_6AD` |
| 1 (`04`) | 2 | `+01..08` the cursors `1A4C..1A53` |
| 2 (`08`) | 3 | `+01..02` the move counter `word_6AB`, `+01..05` the referent block `1A54` |
| 3 (`09`) | 4 | the globals `1AE3..1AF1` (previous rooms, vehicle state, follower) |
| 4… (run of `06`) | 5 | `1A59..1A5D`, then ten (value, record) word pairs for the timers `1A5F` and ten for `1A8D` |

In variant A the type-6 run is four records of five entries (`+07..+1A`): the
first two hold the timers, the last two `1A8D`. In variant B it is two
records of ten entries (`+07..+2E`).

`1A8D` names records the engine itself uses: `1A93` (entry 1's record) is the
start record, `1A97` the answer to swearing, `1A9B` a route record's arrival,
`1A9F` the answer to a move on foot.

## SAVE files

`SAVE<n>` (n = 1–9) is a TABLES image: the same record size and order, with
each record holding the live state instead of the shipped one. The game writes
it to the game directory (the original asked for a separate storage disk; the
port does not).

Each record is written from one buffer: the type byte and the runtime image
the activation reads from it, followed by whatever the buffer held before
(the first record's tail is left-over `TARTRESTORE` text). Restoring loads the
save in place of TABLES and runs the activation again; the boot then renders
the start record with the word RESTORE. So the live length of each record is
exactly what the activation reads, and the start-state records carry the
globals:

| Record | Saved globals |
|---|---|
| 0 (phase 1) | `670`, `0671`, `0679`, `6A9`, `6AA`, `word_6AD`, `1AB5` (3 bytes), `word_1AE1`, `1ADD`, `1ADE` |
| 1 (phase 2) | the cursors `1A4C..1A53` |
| 2 (phase 3) | `word_6AB` (the move counter; activation copies it to `1A54`), `1A56`, `word_1A57` |
| 3 (phase 4) | `1AE3`, `1AE4`, `1AE5`, `1AE6`, `word_1AE8`, `1AEA`, `1AEB`, `1AE7`, `1AED..1AF1` |
| type-6 run (phase 5) | `1A59`, `1A5A`, `1A5B`, `1A5C`, `word_1A5D`, then the (value, record) pairs of `1A5F` and, in the later records, `1A8D` |

See `gameengine/savegames.py`.
