"""SAVE<n> files: the native save/restore of every title.

A native save file is a TABLES image (same stride, same record order) whose
records hold the live state instead of the shipped one. GAME.000 writes each
record from one buffer: the record's type byte and its runtime image -- the
part the activation chain read from it -- and the buffer's previous contents
behind that (the first record's tail is "TARTRESTORE" junk). Measured
2026-10-17 against SAVE3 written by the original after walkthrough turn 10.

Restoring loads the save in place of TABLES and runs the activation again,
then the boot types RESTORE instead of OPEN into the start record
(GAME.000 2C67..2CB2). So the runtime lengths below are exactly what the
activation reads, and the five phase records carry the DS globals:

* phase 1 (record 0): 670, 0671, 0679, 6A9, 6AA, word 6AD, 1AB5 (3),
  word 1AE1, 1ADD, 1ADE (overlay D61..E43);
* phase 2 (record 1): the cursors 1A4C..1A53 (E43);
* phase 3 (record 2): word 6AB (the move counter; activation also copies
  it to 1A54), 1A56, word 1A57 (E9B);
* phase 4 (record 3): 1AE3, 1AE4, 1AE5, 1AE6, word 1AE8, 1AEA, 1AEB,
  1AE7, 1AED..1AF1 (EEA);
* phase 5 (the type-6 run): 1A59, 1A5A, 1A5B, 1A5C, word 1A5D, then the
  (value, secondary) word pairs of 1A5F -- and of 1A8D in the run's later
  records, which keep their shipped header (FB8).

The dialog texts are GAME.000's inline Pascal strings, identical in all
eight titles.
"""

from __future__ import annotations

from pathlib import Path

ASK_SLOT = "What number would you like to give this game (1-9) ? "
ALREADY_SAVED = "There is already a game #{slot} on this disk.  Do you want to save over it?"
TYPE_Y_OR_N_UPPER = "Type Y OR N"
SAVING = "Saving game #{slot}..."
RESUME_QUESTION = "Would you like to resume a saved game?"
TYPE_Y_OR_N = "Type Y or N."
ASK_RESUME_SLOT = "Which game would you like to resume (1-9) ?"
RETRIEVING = "Retrieving game #{slot}..."
NO_SUCH_GAME = "There is no game #{slot} on this disk..."

# The write buffer's contents before the first record (measured on the
# 40-byte Goldfinger: bytes 0x1D..0x27 of every record not reaching them).
_BUFFER_JUNK_OFFSET = 0x1D
_BUFFER_JUNK = b"TARTRESTORE"

# Runtime image length (type byte included) of the table-driven records:
# persons (0x1D payload, sub_11C6), phase-7 nodes (raw[1:0x1F]), rooms
# (raw[1:0x28]), phase-9 records (raw[1:0x22]).
_RUNTIME_LENGTH = {0: 0x1E, 1: 0x1F, 2: 0x28, 3: 0x22}
_PHASE_LENGTH = (0x1D, 9, 6, 15)


def save_path(root: "Path | str", slot: int) -> Path:
    if not 1 <= slot <= 9:
        raise ValueError("save slot must be 1..9")
    return Path(root) / f"SAVE{slot}"


def missing_save_message(slot: int) -> str:
    """GAME.000's message for a slot without a file."""

    if not 1 <= slot <= 9:
        raise ValueError("save slot must be 1..9")
    return NO_SUCH_GAME.format(slot=slot)


def _phase5_run_length(pristine: bytes, stride: int) -> int:
    count = 0
    index = 4
    while (index + 1) * stride <= len(pristine) and pristine[index * stride] == 6:
        count += 1
        index += 1
    return count


def runtime_lengths(pristine: bytes, stride: int) -> list[int]:
    """How many bytes of each record are live state (type byte included)."""

    count = len(pristine) // stride
    run = _phase5_run_length(pristine, stride)
    lengths: list[int] = []
    for index in range(count):
        if index < 4:
            lengths.append(_PHASE_LENGTH[index])
        elif index < 4 + run:
            lengths.append(stride if stride == 47 else 27)
        else:
            lengths.append(min(stride, _RUNTIME_LENGTH.get(pristine[index * stride], 0)))
    return lengths


def restore_tables(pristine: bytes, save: bytes, stride: int) -> bytes:
    """The TABLES image a save stands for: its live bytes over the shipped ones."""

    if len(save) != len(pristine):
        raise ValueError("save file does not match this title's TABLES")
    effective = bytearray(pristine)
    for index, length in enumerate(runtime_lengths(pristine, stride)):
        base = index * stride
        effective[base + 1 : base + length] = save[base + 1 : base + length]
    return bytes(effective)


def _word(value: int) -> bytes:
    value &= 0xFFFF
    return bytes((value & 0xFF, value >> 8))


def build_save_image(vm, pristine: bytes, stride: int, *, current_room: int, move_counter: int) -> bytes:
    """The SAVE<n> bytes for the VM's live state, record by record."""

    state = vm.action_state
    table_state = vm.table_state
    predicates = vm.predicates
    count = len(pristine) // stride
    lengths = runtime_lengths(pristine, stride)
    run = _phase5_run_length(pristine, stride)
    buffer = bytearray(stride)
    junk_end = min(stride, _BUFFER_JUNK_OFFSET + len(_BUFFER_JUNK))
    buffer[_BUFFER_JUNK_OFFSET:junk_end] = _BUFFER_JUNK[: junk_end - _BUFFER_JUNK_OFFSET]
    counters = {0: 0, 1: 0, 2: 0, 3: 0}
    out = bytearray()

    def keep(index: int, start: int, end: int) -> bytes:
        return pristine[index * stride + start : index * stride + end]

    timer_entries = [
        _word(table_state.array_1a5f.get(slot, 0)) + _word(table_state.array_1a5f_secondary.get(slot, 0))
        for slot in range(10)
    ]
    event_entries = [
        _word(table_state.array_1a8d.get(slot, 0)) + _word(table_state.array_1a8d_secondary.get(slot, 0))
        for slot in range(10)
    ]
    header5 = bytes((
        state.byte_1a59 & 0xFF, state.byte_1a5a & 0xFF,
        state.byte_1a5b & 0xFF, state.byte_1a5c & 0xFF,
    )) + _word(state.word_1a5d)

    for index in range(count):
        kind = pristine[index * stride]
        image = bytearray((kind,))
        if index == 0:
            image += bytes((predicates.byte_670 & 0xFF,))
            image += predicates.blocks[0x671].to_bytes()[:8]
            image += predicates.blocks[0x679].to_bytes()[:8]
            image += bytes((current_room & 0xFF, vm.direction_cursor_6aa & 0xFF))
            image += _word(state.word_6ad)
            image += keep(index, 22, 29)  # 1AB5, 1AE1, 1ADD, 1ADE: not modelled
        elif index == 1:
            image += bytes((
                state.byte_1a4c, state.byte_1a4d, state.byte_1a4e, state.byte_1a4f,
                state.byte_1a50, state.byte_1a51, state.byte_1a52, state.byte_1a53 & 0xFF,
            ))
        elif index == 2:
            image += _word(move_counter) + bytes((state.byte_1a56 & 0xFF,)) + _word(state.byte_1a57)
        elif index == 3:
            shipped = keep(index, 0, 15)
            image += bytes((
                state.byte_1ae3, state.byte_1ae4, state.byte_1ae5,
                getattr(state, "byte_1ae6", shipped[4]),
            ))
            image += _word(table_state.word_1ae8)
            image += bytes((
                getattr(state, "byte_1aea", shipped[7]),
                state.byte_1aeb,
                getattr(state, "byte_1ae7", shipped[9]),
                state.byte_1aed, state.byte_1aee, state.byte_1aef,
                getattr(state, "byte_1af0", shipped[13]), getattr(state, "byte_1af1", shipped[14]),
            ))
        elif index < 4 + run:
            position = index - 4
            if stride == 47:
                entries = timer_entries if position == 0 else event_entries
                header = header5 if position == 0 else keep(index, 1, 7)
                image += header + b"".join(entries)
            else:
                timers = position < 2
                entries = timer_entries if timers else event_entries
                slot = (position % 2) * 5
                header = header5 if timers else keep(index, 1, 7)
                image += header + b"".join(entries[slot : slot + 5])
        elif kind in counters:
            counters[kind] += 1
            number = counters[kind]
            if kind == 0:
                record = vm.runtime_records.get(number)
                payload = keep(index, 1, 0x1E) if record is None else bytes(record.raw[:0x1D])
            elif kind == 1:
                node = vm.phase7_runtime.get(number)
                payload = keep(index, 1, 0x1F) if node is None else bytes(node[:0x1E])
            elif kind == 2:
                room = vm.graph.room(number)
                payload = keep(index, 1, 0x28) if room is None else bytes(room[:0x27])
            else:
                record = vm.phase9_runtime[number - 1] if number <= len(vm.phase9_runtime) else None
                payload = keep(index, 1, 0x22) if record is None else bytes(record[:0x21])
            image += payload
        image = image[: lengths[index]] if lengths[index] else image[:1]
        buffer[: len(image)] = image
        # Writes the port keeps beside the images (the visited byte +22h,
        # the entry flag +25h) belong to the same record bytes.
        # A room's +18h set lives in its image; the TABLES copy the
        # dispatcher reads is refreshed from it and may be stale.
        for (record_index, offset), value in table_state.overrides.items():
            if record_index != index or offset >= len(image):
                continue
            if kind == 2 and 0x19 <= offset < 0x21:
                continue
            buffer[offset] = value
        out += buffer
    return bytes(out)
