# Memory layout

Addresses are offsets in the original's data segment (`DS`) unless they name
another segment. The port keeps them as names: `byte_1A4C`, `set 0671`,
`word_6AB`.

## The DOS program

`GAME.COM` is a tiny-model COM file compiled with Turbo Pascal 3. At start it
computes its segments behind its code (`sub_AB7`): the data segment follows
the code, the stack follows the data, and the heap is a bump allocator
between them (`word_18A:word_18C`, no `free`). It then loads the overlay:
`GAME.000` is read in one piece to `DS:2CB6` and entered at `loc_2CCD`.

The overlay loads VOCAB, then TABLES, opens MESSAGE through the resident
reader and runs the activation chain. Overlay and resident call each other
through far-pointer tables in `DS`. Part of the message renderer runs in a
segment of its own (`CS=0815h` in Goldfinger), sharing `DS` with the rest.

MESSAGE is read through a page cache: the record seek (`GAME.COM:4525`)
divides a record number by 85 to find the page and keeps pages as 514-byte
blocks in RAM.

## Tables in memory

The activation chain copies each TABLES family into a table of far pointers
([file-formats.md](file-formats.md#record-families)). Offsets below are
in-memory offsets (the record offset minus one). A field holding 1 means
"none"; sets are Turbo Pascal `set of 0..63` or `set of 0..255` bit arrays.

### People — `DS:0438[2 .. word_19E7]`

| Offset | Field |
|---|---|
| `00` | word: the person's description record |
| `02` | VOCAB word of the name |
| `04`, `06`, `08` | words: the records for trade, greeting and give |
| `0A` | word: the talk record |
| `0C` | set: what the person holds |
| `14` | the room the person is in (1 = off the map, e.g. dead) |
| `15` | state (fights and other scenes count on it) |
| `16` | heading: the direction the person walks |
| `17` | below 99: the person picks up loose things in their room |
| `18` | percent chance of staying put each turn |
| `19` | the object that is the person's body |
| `1B` | stays this turn |
| `1C` | not yet described |

### Objects — `DS:04B4[2 .. byte_19E9]` (phase-7 nodes)

| Offset | Field |
|---|---|
| `00..07` | set: the contents (for a container) |
| `08` | word: the description record |
| `0A` | VOCAB word of the name |
| `0C`, `0D` | values the records read and change (`0D` orders the held things: the cheapest goes first in a trade) |
| `0E` | set: the verbs that apply to the object (their union is `DS:4B6B`) |
| `16` | a value the records read |
| `17` | the container the object is in (1 = none) |
| `18` | type: `2` container, `3` liquid, `4` light source, `5` a body, others |
| `19` | article flag |
| `1A` | a light source's state |

### Rooms — `DS:025C[2 .. byte_19EA]` (phase-8 images)

Rooms are numbered from 1; room 1 is the null room. Scenery (doors, windows,
vehicles, passages) are rooms too: a room reaches its scenery through its
exits.

| Offset | Field |
|---|---|
| `00` | word: the description record |
| `04..09` | exits N, S, E, W, U, D (room numbers; 0 or 1 = no exit) |
| `11` | a power the player needs to enter (a bit of `byte_670`) |
| `12` | an object the player needs to enter |
| `14..17` | set: the people in the room |
| `18..1F` | set: the things in the room |
| `23` | set for scenery and passages: the record carries state |
| `24` | open/closed (`0` = open, the exit can be used) |
| `25` | a second state flag |

### Route records — `DS:05B0[2 .. byte_19EB]` (phase-9)

Vehicles and things that move along a route.

| Offset | Field |
|---|---|
| `04` | VOCAB word of the name |
| `0E` | the room it is in |
| `0F` | article flag |
| `11` | `2` for a vehicle |
| `12..20` | set: the rooms it can go to |

### Runtime records — `DS:4BE0`

32-byte rule records the per-turn dispatcher walks (`dispatcher.py`,
`runtime_records.py`). `DS:0438` indexes them in steps of 4.

## Globals

### Sets

| Address | Contents |
|---|---|
| `0670` | powers granted so far (bit 0 from the start) |
| `0671` | in the player's hand |
| `0679` | worn or on the player |
| `0681` | hidden: not visible until uncovered (opening a container uncovers its contents) |
| `0689` | surfaces that have something on them |
| `0691` | out of reach: inside something closed |
| `0699` | inside a container (cannot be dropped or listed on its own) |
| `06A1` | on or in another thing (moves with it; not traded or picked up on its own) |
| `1AB8` | described: people and things already introduced in the current room |
| `19EF` | kept out of the room's loose things (people do not pick them up) |

### Position and counters

| Address | Contents |
|---|---|
| `06A9` | the current room |
| `06AA` | the direction of the last move |
| `word_6AB` | the move counter (`MOVE #n`) |
| `1AE3`, `1AE4` | the previous room and the one before |
| `1AE5` | the scenery the vehicle is on (driving and flying move this) |
| `1AEB` | the person following the player (1 = nobody) |
| `1AEC` | vehicle mode |
| `01FC` | the Random seed (TP3 `Random`, seed 0 at start) |

### Cursors

The records work on cursors: the things a command names, set by the parser
and changed by actions.

| Address | Cursor |
|---|---|
| `1A4C` | the direct object |
| `1A4D` | its container |
| `1A4F` | the indirect object ("WITH …", "IN …") |
| `1A50` | the person |
| `1A51` | the selected vehicle |
| `1A52` | a room: the room the presence tests run against, the room ahead |
| `1A54`, `1A56`, `word_1A57` | the referent of "it"/"them": move number, kind, index |
| `1A44` | the previous command's `1A4C` (for pronouns) |
| `4ADC` | a person typed in the command |
| `4ADE` | an object typed in the command |
| `4B63..4B6A` | the parser's cursor results, kept for `+V` to restore |

### Parser results

| Address | Contents |
|---|---|
| `4AE2` | the classes of the typed words |
| `4AE9` | the typed word nodes |
| `4B81`, `4B89`, `4B8D`, `4B9C` | the typed values by kind (object, person, room, other) |
| `4B73` | scratch set: the candidates of the current action (e.g. room things, in hand and worn, minus `0691`) |

### Result and control flags

| Address | Contents |
|---|---|
| `byte_4B7B` | the result of the last test or action; `\|` spans and many actions read it |
| `word_4B7F` | the response record the dispatcher selected |
| `4B11` | the current section label (for the `(` selector) |
| `4BCB` | game over (`(y`) |
| `4BCC` | start a new game (`(n`) |
| `1AE0` | render the start record instead of the response (boot, after saving) |

### Timers and engine records

| Address | Contents |
|---|---|
| `1A59..1A5D` | phase-5 globals |
| `1A5F` | ten timers: (signed countdown, MESSAGE record); a timer that reaches zero fires its record at the end of the turn |
| `1A8D` | ten (value, record) pairs; the records are the start record (`1A93`), the swear answer (`1A97`), a route record's arrival (`1A9B`) and the move on foot (`1A9F`) |
