# DOSBox-X Runtime Trace Targets

This document lists the **specific memory ranges and game moments** that
must be captured live in DOSBox-X to unblock the remaining ports.

After the IDC annotations from `annotate_msg_ctrl_dispatchers.idc`, every
predicate opcode's structure is documented in the .asm (see `loc_CC86`
and `loc_D8DB`). What is still missing is the **runtime content** of the
8-byte set tables those opcodes test against.

## What to capture

| DS address | Size | Purpose | Targeted by opcodes |
|---:|---:|---|---|
| `ds:0670` | 1 byte | byte_670 (1-byte test) | `$/&  'y'` (single-byte CONTAINS) |
| `ds:0671` | 8 bytes | string_671 (Pascal set) | `$/&  0x81` |
| `ds:0679` | 8 bytes | string_679 (Pascal set) | `$/&  'u'` |
| `ds:0681` | 8 bytes | unmodeled set #1 | `$/&  'q'` |
| `ds:0689` | 8 bytes | unmodeled set #2 | SET-COPY working storage |
| `ds:0691` | 8 bytes | unmodeled set #3 | SET-COPY working storage |
| `ds:0699` | 8 bytes | unmodeled set #4 | SET-COPY working storage |
| `ds:06A1` | 8 bytes | unmodeled set #5 | SET-COPY working storage |

**Capture as:** `ds:0670` for **57 bytes** (`0x6A9 - 0x670 = 0x39`).

## When to capture

The set CONTENTS change as the game progresses. To reverse-engineer which
bits track which state, capture at **multiple checkpoints** and diff.

### Minimal viable diff: 4 captures of the walkthrough

| # | Game moment | What it reveals |
|---:|---|---|
| 1 | First REPL prompt (after intro) | baseline / "no state" set |
| 2 | After `OPEN ARMREST` succeeds | which bit tracks "armrest opened" |
| 3 | After `TAKE LIGHTER` | which bit tracks lighter location |
| 4 | After `LIGHT LIGHTER` | which bit tracks lighter lit/unlit |

If a specific bit toggles between captures 1 and 2, that bit is
"armrest is open". If a different bit toggles between captures 3 and 4,
that bit is "lighter is lit". Across 4 captures of 57 bytes each, we
get enough leverage to identify all the predicates the walkthrough
exercises.

### Full coverage: 20 captures

For complete predicate-evaluator coverage, capture at every distinct
scene state in the walkthrough — see `walkthrough.txt`. The script
`tools/dump_scene_block.idc` in IDA Pro / DOSBox-X-debugger is the
right place to add a one-shot dump helper.

## How to capture in DOSBox-X

See `memory/dosbox-re-tooling.md` for the custom debugger setup.

Quick recipe:

1. Pause execution at the desired moment (post-command, before prompt).
2. In the debugger console, dump memory:
   ```
   D ds:0670 39
   ```
3. Copy the hex bytes into a file under
   `traces/scene_block_<checkpoint_name>.hex`.

Standard captures should commit alongside `walkthrough.txt` as
trace-confirmed ground truth.

## How to feed captures back into the port

Once captures exist:

1. Extend `SceneGlobals` with the 5 missing fields (`pred_table_681`,
   `_689`, `_691`, `_699`, `_6A1`).
2. Extend `_scene_globals_pack`/`_unpack` to round-trip them.
3. Add a `PredicateEvaluator` class in `gameengine/predicates.py` that
   exposes the per-opcode evaluators (`'y'`, `'q'`, `'u'`, `0x81` for the
   set tests; `'r'`, `'w'`, `'z'`, etc. for the field-based tests).
4. In `handle_examine`, replace the remaining object-specific EXAMINE
   decisions with calls to `PredicateEvaluator.evaluate(kind, operand,
   scene_globals)` as their native opcodes are decoded.

## What can be done WITHOUT trace data

Already done:

- IDC annotations document the dispatcher and per-opcode handler
  structure (`annotate_msg_ctrl_dispatchers.idc`).
- The old `EXAMINE_BRANCH_SUPPRESSIONS` table has been removed. `plaque` has
  moved to live container-state selection; cable `$"ah` uses the shared `$"`
  fall-through structural default; cable `^a:` follows the live `PULL CABLE`
  state; plans/chart/letter mutilated-paper alternatives are explicit
  intact-document decisions; frame fully-guarded behavior is explicit handler
  logic.
- `parse_conditional_operands` returns the kind+operand pairs that the
  real evaluator will consume.

## Captures collected so far

`traces/scene_block_baseline.hex` -- captured 2026-06-28 by driving
DOSBox-X (`tools/dosbox_debug.py`) past the restore prompt to the
chase prompt (`MOVE #0`). Contents:

```
ds:0670  01 00 00 00 00 00 00 00     byte_670 = 1
ds:0678  00 00 00 00 01 00 00 00     string_679 set: bit 0 of byte 4
ds:0680  00 08 10 24 00 00 00 00     pred_table_681 set: {11, 20, 26, 29}
ds:0688  00 00 00 80 00 00 00 00     pred_table_689 set: {31}
ds:0690  00 08 10 a4 00 00 00 00     pred_table_691 set: {11, 20, 26, 29, 31}
ds:0698  00 08 10 24 00 00 00 00     pred_table_699 = same as _681
ds:06A0  00 c8 10 a4 00 00 00 00     pred_table_6A1 set: {11, 19, 20, 26, 29, 31}
```

Observation: pred_table_699 is an exact copy of pred_table_681 in this
state, suggesting one of them is the working copy of the other during
the active scene's Pascal-set test (msg_ctrl_dollar opcode 'q' targets
both addresses; the dispatcher's prologue at `loc_CC86` copies via
`sub_4B93` between record-relative slots and these globals).

LOOK injected via BIOS keyboard buffer (`SM 40:28 W:266C W:186F W:186F
W:256B W:1C0D; SM 40:1C W:0032`) executed correctly (MOVE #1, Tilly's
chase response rendered) but produced **zero byte changes** in
`ds:0670..0x6A8`. Confirmed: pure LOOK is read-only on scene state.

## Next captures needed

The walkthrough's first state-mutating command is `OPEN ARMREST` (12
chars, above the BIOS injection limit). To capture post-armrest state,
the SDL window must be driven manually, or the
``sub_2D3A``-area-BP-injection workaround mentioned in
`memory/trace-keyboard-injection-limit.md` must be implemented.
