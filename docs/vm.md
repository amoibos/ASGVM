# The VM

How the engine runs a game: activation, a turn, the MESSAGE language the
records are written in, the actions, and the end-of-turn pass. Addresses are
explained in [memory-layout.md](memory-layout.md); the files in
[file-formats.md](file-formats.md).

## Activation

At boot (and again on restore) the overlay runs a chain of nine phases over
TABLES (`sub_D61` and its callees; `gameengine/activation.py`):

| Phase | Source | Effect |
|---|---|---|
| 1 | record 0 (type 7) | powers `670`, the sets `0671`/`0679`, the start room `6A9`, `6AA`, `word_6AD` |
| 2 | record 1 (type 4) | the cursors `1A4C..1A53` (and their copy at `4B63`) |
| 3 | record 2 (type 8) | the move counter `word_6AB`, the referent block `1A54` |
| 4 | record 3 (type 9) | the globals `1AE3..1AF1` |
| 5 | the type-6 run | `1A59..1A5D`, the timers `1A5F`, the engine records `1A8D` |
| 6 | type-0 records | the people table `DS:0438` (high-water mark `word_19E7`) |
| 7 | type-1 records | the object nodes `DS:04B4` (`byte_19E9`) |
| 8 | type-2 records | the room images `DS:025C` (`byte_19EA`) |
| 9 | type-3 records | the route records `DS:05B0` (`byte_19EB`); vehicles are bridged into the room graph |

The verb-response table (`DS:05F0`, one MESSAGE record per verb) is built at
load as well, from a packed MESSAGE record named by the activation data
(`AsgActivationTables.build_verb_response_records`).

At the start of a game the people's holdings are completed: a person holds
the contents of what they hold (`GAME.COM 54D4`).

## A turn

`AsgGame.handle` runs one command:

1. **Parse.** The input is encoded into symbols and matched against VOCAB,
   longest phrase first (`parser.py`). The typed words fill the parser sets
   (`4AE2`, `4AE9`, `4B81..4B9C`) and the cursors: the first object becomes
   `1A4C`, a "WITH"/"IN" object `1A4F`, a person `1A50`, and so on; "it" and
   "them" resolve to the previous command's object. A word naming a dead
   person becomes the word for their body.

2. **Grammar.** A fixed chain of sentence patterns picks the dispatcher
   (`grammar.py`, IDA 7570..7B9F). Speech (questions, give, trade, greetings)
   is recognised first; then:

   | Pattern | Sentence | Dispatcher |
   |---|---|---|
   | 67DC | TAKE / RIDE + vehicle or place | 4B36 |
   | 641D | OPEN/CLOSE class [+ noun / WITH] | 3AD5 |
   | 5A58 | KILL person [WITH noun] | 3CCC |
   | 5BC3 | IN/INTO + noun | 3E2E |
   | 65BF | PUT / PUT ON TOP … | 46FD |
   | 6083 | a person first ("TILLY, …") | 410C |
   | 5F66 | verb + route record | 3FDA |
   | 6284 | verb + noun / WITH | 4857 or 423E |
   | 6C32 | a movement word or direction | 4A74 or 4B36 |

   A sentence no pattern takes goes to the talk default.

3. **Dispatch.** The dispatcher chooses the response record (`word_4B7F`):
   the verb-response record, an object's record for that verb, a person's talk
   or speech record, or the movement record. Movement walks the room graph:
   exits, passages (scenery the player walks through when open), powers and
   required objects (`step_allowed`), vehicles and the person following the
   player.

4. **Render.** The record is rendered. Its controls test the state, run
   actions and choose which parts of the text appear (see below). Actions
   change the state while the record renders, so text after an action sees
   its effect.

5. **End of turn** (IDA 10F43..111AB, `AsgVm.end_of_turn`). Unless the
   record ended the game, started a new one, or the turn saved the game:
   - after a swear word, the swear record (`1A97`);
   - the people update: every person not in the player's room rolls Random
     against their chance of staying (`+18`); the others walk along their
     heading, and people with a pick-up threshold (`+17`) take the loose
     things of their room;
   - every fifth move the route records walk their routes and announce
     themselves when they arrive in the player's room;
   - the timer pass: each running timer of `1A5F` counts down, and the record
     of every timer that reaches zero is rendered.

   The records fired here print after the response, in this order.

6. **Output.** The text goes through the formatter (`GAME.COM 3DFB`): after
   `.`, `!`, `?` (and `:` not followed by a digit) the next word is
   capitalised; lines wrap at 79 columns; output pages at 24 rows with
   `(MORE)`. A turn ends with the separator line and the prompt `->`, and the
   status line shows `MOVE #n` (and, in some titles, the day and time).

## The MESSAGE language

A record is text with controls. Rendering walks the symbols; plain symbols are
printed, controls are executed (`gamecom_render.py`, `vm_messages.py`). Most
controls take one or two operand symbols; an operand is decoded by adding a
fixed base to the symbol (`sub_AE27`): `+57h` for `$` and `&` tests, `+32h`
for actions, `+87h` for cursor selectors.

| Control | Meaning |
|---|---|
| `@` | ends a segment (a capitalised name, a question, a list) |
| `\abc` | renders record *abc* (base 64) in place |
| `$xy` | a state test; the result goes to `byte_4B7B` |
| `&xy` | the second test family (kinds, presence, visited); result to `byte_4B7B` |
| `\|ab` | a gate: if `byte_4B7B` is false, jump to target *ab*; otherwise go on |
| `^ab` | an unconditional jump to target *ab* (ends the branch before it) |
| `(x…` | runs action opcode *x* + 32h with its operands |
| `*…` | chooses one of several candidate texts (by the move counter, by the cursor's kind, …) |
| `=…` | mentions or lists things: `=d` names a cursor's thing and marks it described, `=h` lists a set ("a gun and a knife") |
| `+…` | further primitives: `+T` moves an object, `+V` restores the parser's cursors, `+N` toggles a flag |
| `%…` | formatting and names (below) |
| `$-…@` | asks a yes/no question; the answer goes to `byte_4B7B` |

`%` controls:

| Form | Meaning |
|---|---|
| `% x@` | the letters up to `@` in capitals (`% pg@` → PG); `%x@` capitalises one letter |
| `%d<word>` | renders the description record of the thing a VOCAB word names |
| `%l` | lists the people in the context room ("Goldfinger is here.") |
| `%w` | lists the route records in the context room |
| `%t`, `%j`, `%e`, `%i`, … | the name of a cursor's thing (`%j` the current room, `%i` the room in `1A52`) |
| `%p<source>` | a value printed in decimal |
| `%*name:@` | a speaker tag ("Pussy:") |
| `%^`, `%\|` | a line break; one form centres its line |

### Tests

`$` tests (opcode = symbol + 57h) read the sets and fields: whether a thing
is in hand (`0671`), worn (`0679`), hidden (`0681`), in the room; a field
compared with a value; whether the player typed a given word (`7Fh`);
whether something is present (`74h`, the same code as `&` 74h). `&` tests
check a word's kind (`6Ah..6Eh`, `70h`: object, person, room, …, a body),
presence and whether a room was visited (`80h`).

### Sections

A record can hold several answers, for example an object's answers to OPEN
and to CLOSE. The dispatcher's turn resolution (`sub_4E03`, `tables.py`)
writes a section state to `4B11`, and that state selects which part of the
record renders.

### Variant B

Variant B adds one entry to two selector tables, so its cursor selectors
from 92h on, and its `%` selectors, are numbered one higher than variant A's.
The port numbers them in variant A's terms and shifts them for the 47-byte
titles (`cursor_selector`).

## Actions

Action opcodes run inside records (`(x`) and work on the cursors. The ones
the port implements (`vm_actions.py`, `actions.py`, `vm_people.py`):

| Opcode | Action |
|---|---|
| 33h | drop `1A4C` |
| 34h | take `1A4C` (from the room, a container or a surface) |
| 37h | pour a liquid |
| 38h | move through an exit; inside a vehicle, rewire the vehicle into the room graph |
| 39h, 3Ah | set or clear a room's `+25` |
| 3Ch | step `1A4F` over what the person `1A50` holds |
| 3Dh | a global flag |
| 3Eh | game over (`4BCB`) |
| 3Fh | new game (`4BCC`) |
| 40h | move a route record to its next room |
| 41h | take something from a person |
| 42h | give `1A4C` to the person |
| 43h | trade with the person |
| 44h, 45h | open / close (room `+24`, or the object node: uncover its contents) |
| 46h | put `1A4C` into or onto `1A4F` |
| 47h | kill the person `1A50`: they leave the map, their body and their things stay in the room |
| 49h | advance the clock |
| 4Ah, 4Bh | set a timer's record / countdown |
| 51h | advance the object cursor to the next node |
| 52h | walk a person or a route record |
| 53h | set a cursor from a VOCAB descriptor |
| 5Ah, 5Bh, 5Ch, 5Dh | add to / subtract from a field (by one, or by an amount) |

Most actions write `byte_4B7B` (success or failure), which a following `|`
reads.

## Random

The engine uses Turbo Pascal 3's `Random`, seeded with 0 at every start
(the game never calls `Randomize`): `Seed := Seed × 129 + 361962E9h`
(mod 2³²), and `Random(n)` is the new seed's high word, shifted right once,
mod *n* (`GAME.COM 10BB`). Chances are `percent > Random(101)`. Because the
seed is fixed, a game replays identically from the same commands; every
Random call has to happen in the original's order for that to hold.

## Save and restore

SAVE writes the live state as a TABLES image ([file-formats.md](file-formats.md#save-files))
and ends the turn with the start record's "Now let's continue." — no
end-of-turn pass. RESTORE (or answering Y at boot) runs the activation on the
save file and renders the start record with the word RESTORE; the player
stays in the saved room.
