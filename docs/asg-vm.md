# ASG runtime reconstruction

## Goal

The Python implementation must execute the common ASG rule pipeline.  Game
walkthroughs are differential tests, not sources for new command-specific
branches.

## Architecture: a VM that executes data (not an engine with data blobs)

`GAME.COM` + `GAME.000` are a **data-driven interpreter**, not a title with
hard-wired game logic. The world, objects, verb effects, conditions and text are
all operands/opcodes inside `TABLES` and `MESSAGE`; the native code is a fixed
machine that interprets them. Consequences and evidence:

- **Same executable, swapped data.** All eight Mindscape ASG titles ship the
  identical file set (`GAME.000` overlay + a `*.COM` launcher + `MESSAGE` /
  `VOCAB` / `TABLES`). Only the data files differ per title. The engine binary
  is not customized per game.
- **The engine is the interpreter.** `gameengine/vm.py::AsgVm` assembles the
  recovered layers into one runtime: `AsgActivationRuntime` (scene activation
  from `TABLES`), `AsgActionExecutor` (numbered action opcodes `0x32..0x5C`,
  `+N/+R/+S/+T/+V`), `AsgPerTurnDispatcher` (the per-turn record-eval loop),
  `AsgPredicateState`/`AsgPredicateEvaluator` (condition opcodes over the
  eight-byte Pascal sets), and the `MESSAGE` template interpreter (control
  opcodes `^ | ( + % = $ & * \`). None of these encode a specific game's content.
- **Thin per-title bindings prove it.** `games/rambo/config.py` is nine lines
  (name, path, `table_record_size=47`); it runs on the generic
  `gameengine/game.py::AsgGame`, which loads the data and drives the shared
  `AsgVm`. `games/forbidden_castle`, `games/high_stakes` and `games/rambo` carry
  only `config.py` + `play.py` — no game-specific interpreter, records or handlers.

**Implication for multi-title effort.** Once the shared VM in `gameengine/`
faithfully executes the data, a new title is just its data files plus a ~10-line
config binding. Goldfinger's former hand-written stack (`interpreter.py`,
`handlers.py`, `chase.py`, `scenes.py`, `sequences.py`) was **transitional
scaffolding and has now been deleted** (2026-07): Goldfinger runs on the shared
VM via `gameengine/game.py`, config + data only. Effort spent completing the
shared VM pays off across all eight titles simultaneously; per-game handlers do
not generalize, which is why they are gone.

**Caveats (not yet free).** The two disk layouts (40-byte / 47-byte `TABLES`
records) need their loader transform verified per variant before raw disk
offsets are trusted as universal — shared execution begins at the normalized
32-byte runtime record. Each title's `initial_native_room_id` still needs a
trace (`gameengine/game.py` notes that guessing room 2 produced wrong text). See
`docs/engine-compatibility.md` for the per-title reuse matrix.

## Confirmed execution layers

1. `GAME.COM` supplies the shared parser, packed MESSAGE reader, text-control
   dispatcher, screen layout and persistence support.
2. `GAME.000` builds scene-local 32-byte runtime records and executes the
   per-turn/action dispatcher.
3. `TABLES` is compiler output, not directly executable Python state.  The
   loader transforms its disk records into runtime records before rules run.
4. `MESSAGE` contains both prose and conditional/template operands selected by
   dispatcher state.

The activation loader is now structurally decoded. Phases 6, 7 and 8 do not
consume one shared scene record: the common TABLES iterator selects record
types 0, 1 and 2 respectively. It copies payloads starting at disk offset +1
with lengths 0x1d, 0x1e and 0x27 into three native pointer tables.
`AsgActivationTables` implements this for both TABLES strides. In particular,
the second type-6 record supplies phase-6 slot 1, and type-0 records are the
29-byte templates appended at slots 2 onward; they are not synthesized from
rooms. `RuntimeRecordArray` now has an exact
`populate_from_phase6_payloads` path. The older room-derived constructor stays
temporarily as a compatibility path until the post-copy activation mutations
have been fully decoded.

The VM is therefore distributed across data records and native dispatcher
routines; there is no evidence for one isolated bytecode loop.

## Cross-game evidence

All eight installed games use the same record families `0x00..0x09` and the
same supporting files.  Two TABLES disk layouts exist:

| Disk stride | Games |
| --- | --- |
| 40 bytes | Goldfinger, Indiana Jones, High Stakes |
| 47 bytes | A View to a Kill, Forbidden Castle, Rambo, The Mist, Voodoo Island |

Consequently, fields at raw disk offsets cannot be treated as universal
opcodes until each layout's loader transform is known.  Shared execution starts
at the normalized 32-byte runtime-record representation.

## Ported VM slice

`gameengine.vm.AsgVm` now owns the common runtime for all eight bindings. It
loads phases 1..5 from the universal TABLES prelude types `7,4,8,9,6`, builds
the phase 6..9 tables, applies type-3 graph splices, configures predicates from
VOCAB and runs post-action transfers. Phase 1 `+18` exposes the native initial
activation room; title-specific later startup overrides still take precedence.

The direct action primitives `3D/3E/3F` and the `BF6B` field arithmetic used by
`5A..5D` are implemented by `AsgActionExecutor`: addition and saturating
subtraction operate through the native object/global/array field selectors.
MESSAGE action `5Ah` now also consumes its `BF0D` value-source operand and can
mutate global selectors without an active TABLES record.  Thus patterns such
as `(;v` update `DS:1A5F[1]` exactly once after candidate selection instead of
leaking `v` as prose or executing every speculative candidate.
The variable `5Ch/5Dh` forms now decode both BF0D sources (including the
zero-plus-three-symbol literal form), so their arithmetic metadata cannot leak
into prose. Dollar selectors `57h..59h` use the same source decoder for
less-than/equality/less-or-equal sequence gates.
The phase-5 `DS:1A5F` table is now modelled as native four-byte slots: the
first word is used by selector `54h`/`sub_BD67`, and the second word is written
by action `4Ah`.  Actions `4Ch` and `4Dh` implement the confirmed sign toggles
over the first word, and Python SAVE/RESTORE persists both words.  The decoded
phase-5 tail at `DS:1A87..1A8A` is exposed where it feeds shared VM state;
`byte_1A8A` is read by ampersand predicates and toggled by MESSAGE `+N/8F`.

The predicate-set action handlers `32/A49C`, `33/A56A`, `34/A099` (confirmed
primary effects) and `35/A3C8` now move node sets among `0671`, `0679`,
`0699`, `06A1` and room `+18`, while maintaining `word_6AD` and sealing the
processed `+17` link.  Additional confirmed action-state primitives now live
in the common VM:

- `48h`: set one random modulo-six bit in `0670`; the MESSAGE form may carry
  one already-consumed parameter symbol before prose resumes (e.g. `(st...`);
- `53h`: update descriptor cursors `byte_1A4C`, `1A50`, `1A51`, `1A52`;
- `55h`: toggle the TABLES-source flag mirrored as `flag_1DF7`;
- `B74B`: toggle room byte `+1A` and add/remove the descriptor value in
  auxiliary set `4AB6`;
- `BB10`: if a selected room is allowed by target set `+12..+20`, write it to
  target byte `+0E`;
- `EE18`: advance/retreat the linked node cursor `byte_1AB7`, marking or
  clearing node byte `+22`;
- `ADD8`: gate on `byte_1A51` and write the resolved selector into
  `byte_1A52`;
- `BA7D`: after selector resolution, write the confirmed phase-4 selector
  result into `byte_1AEB`.
- `+N`: the confirmed `8Fh` secondary opcode toggles `byte_1A8A`; the alternate
  branch delegates to `B74B` when a caller supplies the resolved room context.
- `+R`: descriptor kind `1` delegates to `BA7D`; other descriptor kinds delegate
  to `BB10` when the caller supplies the resolved target room context.
- `+S`: writes descriptor cursors through the same `byte_1A4C/1A50/1A52/1A51`
  mapping as action opcode `53h`.
- `+T`: `sub_B805` is ported.  It rejects cursor value `1`, finds the
  phase-8 room whose context set `+18..1F` contains `byte_1A4C` (falling back
  to the current room), gates on
  `(source_context union {cursor} union 0671) - 0691 - 06A1`, removes the
  cursor from the source context, removes it from `0671` while decrementing
  `word_6AD` when applicable, and inserts it into the operand-selected target
  room context.
- `+V`: secondary opcodes copy parser scratch `4B63/4B66/4B67/4B68/4B69` into
  `1A4C/1A4F/1A50/1A51/1A52`; `94h` copies `4B7C` into `4ADE`.

`gameengine.dispatcher.AsgPerTurnDispatcher` implements the confirmed
`GAME.000:1F05..2019` prelude:

- iterate slots `2..word_19E7`;
- keep records satisfying the native two-term gate: `+0x17 < 0x63` and
  `+0x14 != 1` (`+0x18 == 0x63` is an observed startup value, not the gate);
- resolve runtime `+0x14` through the 1-based TABLES pointer table;
- expose the runtime rule operand at `+0x0C` (8 bytes);
- expose the linked TABLES context operand at `+0x18` (8 bytes).

The following native calls now have a cross-game structural identification:
Phase-7 add-element paths establish `B710` as set union, while the adjacent
`B71E` entry used here is set difference. Each active frame executes:

`work = context_set - DS:19EF - DS:06A1`

then invokes the `sub_F5BE` effect hook, unions `work` into runtime `+0C..13`,
and subtracts `work` from linked context `+18..1F`. The transfer and both
mutations are implemented by `AsgPerTurnDispatcher.execute_transfers`.

## Predicate bank and first MESSAGE opcode

`gameengine.predicates.AsgPredicateState` models the traced eight-byte Pascal
sets at `DS:0671`, `0679`, `0681`, `0689`, `0691`, `0699`, and `06A1`.
Goldfinger's first-prompt snapshot initializes these sets, and confirmed state
effects now update them:

- OPEN ARMREST clears element 26 in `0681` and `0691`;
- CLOSE ARMREST restores element 26;
- TAKE LIGHTER sets element 32 in `0671` and clears it in `0679`;
- DROP LIGHTER clears element 32 in `0671`.

The native MESSAGE predicate layer is executable incrementally: opcode `$q` at
`GAME.000:CDD9` consumes one MESSAGE symbol, `sub_AE63` uses that numeric symbol
as a seven-byte runtime-VOCAB node index, reads the node's `value_b` at `+6`,
and tests that element in set `0681`. `$u` tests the element in the native set
difference `0679 - 0699`; decoded opcode `0x81` (MESSAGE spelling `$;`) tests

`AsgPredicateEvaluator.evaluate_resolved()` is the common execution entry for
the `$` dispatcher (symbol resolved through the runtime VOCAB node) and the
`&` dispatcher (already-resolved operand cached in its native stack frame).
This keeps q/u/v/f/g/i/t/x semantics shared instead of duplicating them.

The ampersand operand is now resolved through the complete statically-confirmed
`sub_AE27(0x87)` / `sub_AE9E` selector family before predicate dispatch. It is
not a direct Phase-7 node number. Selectors cover the active command node,
Phase-7/8/9 cursors (`1A4C/1A4F/1A50/1A51/1A52`), current and transition rooms
(`6A9`, `1AE3/1AE4/1AE5`), and the `4ADC..4ADF` context globals; selector `87h`
additionally dereferences room field `+12h`. `AsgVm.resolve_amp_operand()` owns
this shared mapping. Selector holes with no native `sub_AE9E` branch remain
unresolved instead of being guessed.

Dollar framing likewise uses native selectors, not printable translations:
`sub_AE27(57h)` adds `0x57` to the raw six-bit MESSAGE symbol. Selectors
`5E..64h`, `6Eh`, `77h`, `78h`, and `7E..80h` pre-read a two-symbol
`msg_ctrl_break(1)` operand before their predicate-specific branch. A live
record-2315 trace confirmed raw `"` -> selector `7Eh` advances the packed
cursor across two additional symbols (`17 -> 21`) before the following pipe.
The pipe/hat skip then applies the recovered `sub_846B` update
`cursor += target - 1`; `GameComMessageEngine` projects that as
`next_index = control_index + 2 + target` inside a local symbol slice.
set `0671`. Static analysis of the TAKE path confirms `sub_4C7C` as set union
and the deliberately offset call `loc_4C88+2` as set difference.

The MESSAGE structural parser now preserves the two-symbol continuation
descriptor after a `|` operand terminator.  `ConditionalSpan` carries
`kind`, `operand`, `op_end`, `frag_start`, `frag_end` and `continuation`, and
`render_with_conditional_spans()` lets callers evaluate a branch with that
native routing metadata intact.  The old `render_with_conditionals(kind,
operand)` API remains a compatibility wrapper.  Goldfinger EXAMINE and the
generic sibling-game EXAMINE path now pass `continuation` through to
`AsgVm.evaluate_message_predicate()`.  The confirmed `aX` continuation form
writes the MESSAGE-symbol value of `X` into `byte_1A4C`; the VM then supplies
`byte_1A4C`, `byte_1A50`, `byte_1A8A` and the current command/object
`value_b` to ampersand predicate evaluation.

`AsgPredicateEvaluator` implements these paths. Goldfinger's captured bank is
currently scoped to the opening chase; later scenes keep their curated fallback
until their activation records populate a fresh bank.

Phase 7's confirmed aggregate tail (`sub_132B:loc_17F0`) is also shared:

- `0691 := 0681 union 0689`
- `06A1 := 06A1 union 0689 union 0699`

This is implemented by `AsgPredicateState.finalize_phase_7`. The preceding
parse-node format and its initial effects are implemented by
`AsgPhase7Node`/`AsgPhase7Evaluator`:

- node `+0..7`: predicate set; `+17`: next link; `+18`: rule type;
  `+1A/+1B`: flags;
- type 0 unions the node set into `0699` and conditionally into `0681`;
- type 2 conditionally adds the node index to `0689` and its set to `06A1`;
- type 3 adds the node index to `0681` and `0699`;
- type 4 with nonzero `+1A` adds the index to auxiliary set `4AB6`.

The linked-node closure in `sub_133A` is also implemented: it follows `+17`
through type-zero nodes, adds the origin index to each linked node set and to
`0699`, and conditionally to `0681` according to the linked node's `+1B` flag.
A cycle guard protects malformed data. The type-2 predicate
(`loc_15EA`/`B5C2..B64E`) is implemented as well: node `+14..17` selects
runtime-record indices, their `+0C..13` rule sets are unioned, and type 2 is
enabled iff that union intersects auxiliary set `4AB6`. Callers may still pass
an explicit callback for trace experiments. `AsgPerTurnDispatcher.runtime_rule_sets`
provides the required slot-to-set mapping directly from normalized runtime
records.

The MESSAGE ampersand predicate `&nX` (decoded opcode `64h`) now ports the
shared `sub_C7DC` chain scan as well.  Starting at selector-resolved node `X`,
it follows the runtime link field until a linked node has the requested mode,
records the origin/target in `4ADE`/`1A4F`, and writes the render gate to
`4B7B`.  A mode-3 origin redirects the native mode-0 request to mode 1; null,
sentinel and cyclic chains fail safely.  This is engine logic and contains no
Goldfinger-specific node ids.

Phase-7 normalization keeps the native offsets unchanged after the type byte
is removed: `+17` is the next-node link and `+18` is the rule/mode byte.
Static `sub_D894` proves the latter by dereferencing `[node+18h]`; treating
Python `[0x17]` as the mode had overwritten links during OPEN and made both
the mode predicates and `sub_C7DC` chains inconsistent.  All action and
MESSAGE users now preserve this distinction.

Generic OPEN now executes its embedded mid-record `*` selector and `+`
program at their authored cursor positions.  `+kt` decodes to opcode `44h`
with selector `8Ah` and enters the shared `sub_DCAD` Phase-7 state branch;
the host command handler no longer mutates future state before MESSAGE
evaluation.  The `=h3` contents control renders its candidate set from the
same type-1 `+18` container relationships used by reachability.  In chase
room 20, pristine `OPEN ARMREST` therefore renders exactly
`You open the armrest. It contains the buttons.` from shared VM/data logic.

Phase 7 also adds every node whose discriminator byte `+0C` equals `9` to the
eight-byte exclusion set `DS:19EF`; this is implemented and persisted across
Python SAVE/RESTORE.

All seven predicate sets now survive Python SAVE/RESTORE. `0671/0679` remain in
the phase-1 scene block; the five dynamic sets `0681..06A1` occupy a separate
40-byte metadata block after the native-field arrays.

## MESSAGE control dispatch loop and render/skip exit

The shared GAME.COM message renderer is `msg_render_loop` (overlay
`seg000:10C95`). Confirmed structure (assembly-grounded; the per-`$`-opcode
*predicate* semantics live in `AsgPredicateEvaluator`, this section covers only
the dispatch + render/skip control flow):

1. Read one translated symbol via `sub_8424` (the per-char reader; result is the
   **ASCII** value after table translation, not the raw 6-bit symbol). Stored at
   `[bp-7]`.
2. Membership test against the 32-byte control Pascal-set at `DS:1B68` decides
   "control vs literal". A literal falls through to `loc_E35` and is emitted.
3. Controls dispatch by ASCII value (chain of `cmp ax, <ascii>; jz`):

   | ASCII | Char | Handler (overlay) |
   | --- | --- | --- |
   | 0x24 | `$` | `msg_ctrl_dollar` (`loc_CC86`) |
   | 0x26 | `&` | `msg_ctrl_amp` (`loc_D8DB`) |
   | 0x28 | `(` | `msg_ctrl_section` |
   | 0x2A | `*` | `msg_ctrl_star` (`loc_6F3`/`loc_F6C`) |
   | 0x2B | `+` | `msg_ctrl_plus` (`sub_F5F9`) |
   | 0x25 | `%` | `msg_ctrl_caps` |
   | 0x3D | `=` | `msg_ctrl_eq` |
   | 0x5C | `\` | `msg_dict_index` + `msg_dict_expand` |
   | 0x5E | `^` | `msg_ctrl_break(1)` + `sub_846B` (paragraph break; reads a 2-symbol operand) |
   | 0x7C | `\|` | **render/skip gate** (`loc_D2E`, see below) |

   After every handler control rejoins `loc_E14` (post-dispatch continue).

`msg_ctrl_eq` is partially executable: its first stage builds an eight-byte
temporary candidate set.  Confirmed opcodes are `u` -> `0679`, `v` ->
`0679 ∪ 0671`, decoded `;`/`81h` -> `0671`, and `t` -> the caller-provided
room/context set at `+18`.  One tail branch is decoded too: when the selected
context record has type byte `+18 == 2`, the candidate set becomes
`candidate - 0699`.  For the other context types, the confirmed outer node
scan walks phase-7 indices `2..byte_19E9` and enters the per-node body only for
indices present in the *current* candidate set.  The decoded per-node body
subtracts the entered node record's leading eight-byte set when that node
record has type byte `+18 == 0` or `+18 == 1`.  The final tail subtracts
singleton element `1`, then renders only if no relevant elements remain
(`eq_apply_node_filter_body()` and `eq_final_render_result()`).  The shared
renderer now exposes an optional live control-evaluator hook that feeds this
result into the native `byte_4B7B`/`|` gate; Goldfinger wires it through
`AsgVm.evaluate_eq_control()`.

`msg_ctrl_star` is reconstructed as a candidate selector. Its entry selector (`sub_83D0`) is
accepted only for modes `0..3`; the same value is stored in the local mode slot
and every later branch depends on that mode. Python exposes this as
`star_control_mode()`.  The first break-count setup is decoded too: mode `0`
uses `msg_ctrl_break(0) % word[loc_6A7+4]`, while modes `1..3` keep the
`msg_ctrl_break(0)` value directly (`star_initial_break_count()`).  The mode
tail's context-set selection is also decoded: context types `0,1,2,3,6,9,10`
test context byte `+3` against native sets
`4B81,4B89,4B8D,4B9C,4B9E,4BB5,4BA6` respectively, while types `5,7,8` test
context byte `+0` against set `4AE2`.  Python exposes that as
`star_context_membership()`.  The post-membership gate is inverted: false
membership consumes a `msg_ctrl_break(1)` skip target, true membership continues
rendering (`star_should_skip_after_membership()`).  The mode-specific per-record
body is now partly recovered by disassembling IDA's raw-byte blob.  In mode `3`,
direct descriptor cases `0,1,2,3,5,6,7,8,9,10` are exposed as
`star_mode3_target_match()`: most compare context byte `+3` with the target
value, descriptor `0` first requires context type `+2 == 0`, descriptor `2`
first compares `context[+3]` directly and then, when `context[+3] ∈ 1ABC`, walks
six bytes from indirect table `025C` offsets `+4..+9`, filtering candidates
through set `4ABE` (the last qualifying candidate wins), descriptor `3` uses the
`sub_974B` resolver for context type `2`, descriptor `9` compares via word table
`4AA8`, and descriptors `5,7,8` compare context byte `+0` with the owner value.
`AsgVm.star_context_sets()` derives the native `4B81..4BB5/4AE2` set blocks
from live phase-8 room/context records, and the Goldfinger renderer routes
confirmed `*` modes through `AsgVm.evaluate_star_control()` into the same
`byte_4B7B`/`|` gate.

The complete outer loop at overlay `06E1..0C91` is now represented in the
renderer.  After the mode symbol it reads the candidate count and final cursor;
mode 3 first resolves one `AE27(87h)` operand.  Each candidate begins with a
two-symbol index into the runtime VOCAB metadata table at `6B2`, followed by
the two symbols consumed by the native pair of `sub_837B` calls.  The first
matching candidate is rendered; descriptor zero is the authored fallback.
Mode 0 selects ordinal `word_6AB mod count`, mode 1 tests the descriptor in the
40-byte set at `4AE9`, mode 2 applies the type-dependent context-set tail, and
mode 3 compares the candidate's four metadata bytes using the resolver kind
and target produced by `sub_AE9E`.  This fixes dynamic noun/agreement records
without object- or title-specific branches.  The rare selector `9Bh` remains
unresolved because its comparison value comes through the separate word table
`4AA8`, whose construction is not yet ported.

### The render/skip exit (the `|` gate)

A `$`/`&` handler does NOT itself render or skip the following fragment. It only
evaluates its predicate and writes the boolean to `ds:byte_4B7B`
(`1` = render, `0` = skip), then returns. The decision is taken by the **next
`|` (0x7C) control** at `loc_D2E`:

- `byte_4B7B != 0` -> `loc_D3A`: render the fragment that follows `|`.
- `byte_4B7B == 0` -> `loc_D4F`: call `msg_ctrl_break(1)`, which reads **two
  symbols** `s0,s1` from the stream and returns the skip target
  `s0*0x40 + s1`; the cursor is repositioned there, skipping the fragment.

Consequence for the port: the two-symbol "continuation descriptor" that follows
a `|` operand terminator (observed as `a5`, `bz`, ... in records such as
`$#e|bz`, `$;al|a5`) is **not opaque metadata** — it is the encoded skip jump
target (a 12-bit `page*0x40 + offset` value). The native skip is an exact
offset jump, NOT a scan to the next `$`/`(`/`^`. This is why the legacy
`gameengine/gamecom.py` heuristic ("look ahead up to 6 bytes for `|`, then skip
to the next control") is structurally wrong and produced the `A5`/`bz` artefacts
and Plaque-style mis-branches.

`msg_ctrl_break(arg)` (overlay `seg000:9824`) has two modes:
- `arg=1`: read two raw symbols (`sub_83D0`), return `s0*0x40 + s1`. Used both
  to read 16-bit `$`-opcode operands inside `msg_ctrl_dollar` and to read the
  skip target at the `|` gate.  The target calculation is ported as
  `msg_ctrl_break_target()`, and the live renderer `byte_4B7B`/`|` gate uses it
  for exact in-stream skips.
- `arg=0`: back up over trailing spaces and insert the break byte
  (`[1BE8]=0x0D`); return the backed-up position.

### `msg_ctrl_dollar` operand decode (`loc_CC86`)

1. `sub_AE27(0x57)` reads ONE opcode byte -> `[bp-0Bh]` (e.g. `r`/`q`/`u`/`w`...).
2. The opcode is tested for membership in the 16-bit-operand set
   `{0x5E,0x5F,0x60,0x61,0x62,0x63,0x64,0x6E,0x77,0x78,0x7E,0x7F,0x80}`
   (built by the `loc_4BC2`/`loc_4BD4` sequence + `sub_4CA8` CONTAINS). If the
   opcode is in that set, `msg_ctrl_break(1)` reads its 16-bit operand into
   `[bp-0Ah]`; selector `0x79` (`$#x` in MESSAGE) reads one raw symbol and
   tests it against `DS:0670`; otherwise zero operand bytes are read.
3. Per-opcode multi-way dispatch writes `byte_4B7B` and jumps to the epilogue
   `loc_D491`.

The active low-level renderer now uses this decode only when a live control
evaluator can actually answer the `$` predicate.  In that case it consumes the
native operand, writes the pending `byte_4B7B` decision, and lets the following
`|` gate perform the exact render/skip action.  Unknown `$` opcodes deliberately
fall back to the older conservative path; this keeps composite prose such as
`$now...` from being misread as a static opcode operand.

The same path now covers the Goldfinger gadget records when the native VM
state is present: `byte_1AE5` feeds selector `98h`/`v`, `DS:1A8D[2]` feeds the
BF0D sequence comparisons, and the selected gadget record mutates those fields
through normal action opcodes while rendering.  The remaining work is to port
the native scene/turn dispatcher that initializes and advances those fields,
not to install a title-specific chase driver.

Normal room movement must also respect the dispatcher entry gate, not just the
static direction byte.  The opening DB5 room's six direction slots all point at
native room 21, but the native `+24h` entry gate marks that target unavailable;
falling through to the plain room graph renders the known bogus `A'` fragment.
`AsgGame` therefore checks `vm.direction_available(room, direction)` before
changing `current_room`.  The still-open work is to make the dispatcher emit the
scene-driving response for such commands, not to move to the blocked room.

The multi-fragment assembler (`sub_8628`) is now wired to the same live VM
render context as ordinary MESSAGE records.  For each resolved fragment,
`turn_resolve_text()`'s section-state result is written through the caller's
callback before the fragment is rendered, and `$`/`&`/other live controls are
forwarded to the VM predicate evaluator.  This keeps dispatcher-selected text
from falling back to static composite expansion once record selection reaches
the assembler.

The first context-set response selector is also ported: a room/context set
selects an in-range runtime record and copies that record's `+0A` response word
into `word_4B7F`.  At the Goldfinger DB5 prompt, room 20's context set selects
runtime slot 4 and therefore `word_4B7F = 7151`, matching the live chase-LOOK
trace.  The renderer still suppresses unresolved one-letter output from that
dialogue composite until the final intra-record Tilly section selector is
identified; the important VM state is now present instead of falling through to
room 21's bogus `A'` text.

`msg_ctrl_amp` is wired through the same live renderer gate for confirmed
two-symbol operands. The low-level renderer consumes opcode + resolved operand,
calls the active control evaluator, stores the returned boolean as the pending
`byte_4B7B` decision, and lets the following `|xx` descriptor either render the
branch or jump to `msg_ctrl_break_target(xx)`. If no evaluator answers, it keeps
the conservative metadata-only skip so unresolved `&` operands cannot surface
as literal letters.

### Open verification before wider renderer use

The SKIP path (`loc_D4F`) clearly consumes the two target symbols via
`msg_ctrl_break(1)`. The RENDER path (`loc_D3A`) consumes the descriptor via
`loc_8379+2`; the live renderer gate now mirrors that byte-accounting. Do not
apply these targets blindly inside the legacy structural
`render_with_conditional_spans()` filter: that helper works on heuristically
found branch spans, not the native active cursor, and static target use
regresses real composites such as chase `$now...` and the stone-stairs `|jn`
branch. Wider `$`/`^` activation must run through the live cursor/gate path.

Raw `^` is separate: its renderer path calls `msg_ctrl_break(1)` and `sub_846B`
directly rather than using the `$`/`byte_4B7B` gate.  The active renderer now
ports this as its own control for plausible forward in-stream targets.
Structural `^XX` predicate rendering remains isolated for EXAMINE-style branch
filters so records such as plans/cable/plaque do not reinterpret their curated
predicate metadata as active jumps.

## Next trace boundary

For one controlled command, capture immediately before and after
`GAME.000:1F62..2019`:

- the active 32-byte runtime record;
- its linked TABLES record;
- `DS:19EF..19F6` and `DS:06A1..06A8`;
- the temporary 8-byte set at `[bp-52h]`;
- state writes performed after `sub_F5BE`.

Repeat the same trace in at least one 40-byte and one 47-byte title.  This will
identify the shared predicate/effect operation without coupling it to
Goldfinger prose.

## Migration rule

Existing game-specific handlers remain regression fixtures.  A handler is
removed only after its output and state transition are reproduced by a shared
runtime rule.  New discrepancies first become tests and trace targets; they do
not automatically become new special cases.
