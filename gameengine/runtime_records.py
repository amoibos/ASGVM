"""Runtime-record array (DS:0x4BE0, 32-byte stride).

The GAME.000 loader builds a per-scene runtime-record array at DS:0x4BE0
when the activation chain runs. These records are NOT the 40-byte
on-disk TABLES records -- they are 32-byte rebuilt structures with
relocated message pointers and resolved direction far-pointers.

The exact activation path copies 29 bytes from TABLES type-0 payloads and the
Python view pads them to 32 bytes. Confirmed fields are:

  +0x00       rule/response discriminator (not the TABLES family byte)
  +0x01..02   message pointer (LE word, relocated to runtime address)
  +0x03       reserved (0)
  +0x04..0b   four rule/message words
  +0x14       linked native room id used through DS:025C
  +0x15       continuation of state byte (0x14..0x15 are conceptually one
              word but the loader writes them as discrete bytes)
  +0x17       dispatcher upper-bound byte (must be < 0x63)
  +0x18       auxiliary byte (not the gate)
  +0x1a       flag byte (not a room id)
  +0x1c..0x1f flags (4 bytes)

The dispatcher's `DS:0x438` far-pointer table indexes into this array
by 4-byte stride (word_19E7 entries, but only `[2..word_19E7]` are
live; entries 0 and 1 are reserved).

The older room-derived builder remains only for captured-test compatibility;
normal activation uses ``populate_from_phase6_payloads``.
"""

from __future__ import annotations

from dataclasses import dataclass


RUNTIME_RECORD_SIZE = 32

# Field offsets within the 32-byte runtime record.
RR_OFFSET_TYPE = 0x00
RR_OFFSET_MSG_PTR = 0x01          # 2 bytes LE
RR_OFFSET_DIR_FAR_PTRS = 0x04      # 8 bytes = 4 x (segment:offset)
RR_OFFSET_STATE_BYTE = 0x14
RR_OFFSET_STATE_BYTE_HI = 0x15
RR_OFFSET_GATE_LIMIT = 0x17
RR_OFFSET_ACTIVE_MARKER = 0x18
RR_OFFSET_ROOM_ID = 0x1A
RR_OFFSET_FLAGS = 0x1C             # 4 bytes

# Value observed at +0x18 in the startup capture. It is retained for binary
# fidelity but is not the dispatcher gate.
RR_ACTIVE_MARKER = 0x63
RR_GATE_LIMIT = 0x63


@dataclass(frozen=True)
class RuntimeRecord:
    """A single 32-byte runtime record from the DS:0x4BE0 array.

    Field accessors expose the documented offsets; raw bytes are kept
    accessible for tests/audits via the ``raw`` attribute.
    """

    index: int                  # array-slot index (0..N)
    raw: bytes                  # 32 bytes

    def __post_init__(self) -> None:
        if len(self.raw) != RUNTIME_RECORD_SIZE:
            raise ValueError(
                f"RuntimeRecord size {len(self.raw)} != {RUNTIME_RECORD_SIZE}"
            )

    @property
    def record_type(self) -> int:
        """The +0x00 type byte (0x02 = room, matches on-disk)."""
        return self.raw[RR_OFFSET_TYPE]

    @property
    def message_pointer(self) -> int:
        """The +0x01..02 LE word -- relocated runtime message address."""
        return self.raw[RR_OFFSET_MSG_PTR] | (self.raw[RR_OFFSET_MSG_PTR + 1] << 8)

    @property
    def direction_far_pointers(self) -> bytes:
        """The +0x04..0x0B 8-byte block holding 4 resolved direction far pointers."""
        return self.raw[RR_OFFSET_DIR_FAR_PTRS : RR_OFFSET_DIR_FAR_PTRS + 8]

    @property
    def state_byte(self) -> int:
        """Compatibility name for the linked native room id at +0x14."""
        return self.raw[RR_OFFSET_STATE_BYTE]

    @property
    def linked_native_id(self) -> int:
        return self.raw[RR_OFFSET_STATE_BYTE]

    @property
    def active_marker(self) -> int:
        """Observed +0x18 byte, retained for capture compatibility.

        This is not the dispatcher gate; see :attr:`is_active`.
        """
        return self.raw[RR_OFFSET_ACTIVE_MARKER]

    @property
    def is_active(self) -> bool:
        """Exact ``loc_1F36..1F5D`` two-term dispatcher gate."""
        return (
            self.raw[RR_OFFSET_GATE_LIMIT] < RR_GATE_LIMIT
            and self.raw[RR_OFFSET_STATE_BYTE] != 1
        )

    @property
    def room_id(self) -> int:
        """Legacy synthetic-builder field at +0x1A.

        Exact phase-6 payloads use this byte as a flag; native linkage is
        :attr:`linked_native_id` at +0x14.
        """
        return self.raw[RR_OFFSET_ROOM_ID]

    @property
    def flags(self) -> bytes:
        """The +0x1C..0x1F 4-byte flags block."""
        return self.raw[RR_OFFSET_FLAGS : RR_OFFSET_FLAGS + 4]

    def with_rule_set(self, value: "bytes") -> "RuntimeRecord":
        if len(value) != 8:
            raise ValueError("runtime rule set must be 8 bytes")
        raw = bytearray(self.raw)
        raw[0x0C:0x14] = value
        return RuntimeRecord(self.index, bytes(raw))


@dataclass
class RuntimeRecordArray:
    """The per-scene runtime-record array at DS:0x4BE0.

    The native engine builds this array when the activation chain runs;
    `word_19E7` holds the array's active-entry count. The dispatcher's
    `DS:0x438` far-pointer table indexes by 4 (the stride of a
    segment:offset pair), so an entry value N points at runtime-record
    index N inside this array.

    Construction normalizes disk rooms into the confirmed runtime fields;
    loader-resolved links are explicit inputs rather than raw disk-offset
    guesses.
    """

    records: list[RuntimeRecord]

    def __init__(self) -> None:
        self.records = []

    def __len__(self) -> int:
        return len(self.records)

    def get(self, index: int) -> "RuntimeRecord | None":
        if 0 <= index < len(self.records):
            return self.records[index]
        return None

    def append(self, record: RuntimeRecord) -> None:
        self.records.append(record)

    def replace(self, index: int, record: RuntimeRecord) -> None:
        if not 0 <= index < len(self.records):
            raise IndexError("runtime record index outside array")
        if record.index != index:
            raise ValueError("runtime record slot/index mismatch")
        self.records[index] = record

    def clear(self) -> None:
        self.records.clear()

    @staticmethod
    def resolve_direction_slot_pointers(
        on_disk_record: bytes,
        pointer_table: "tuple",
    ) -> bytes:
        """Resolve the 8-byte direction-pointer block (record[+0x04..+0x0B]).

        The on-disk room record has 6 direction slots at +0x05..+0x0A
        (1-based native room ids; 0 / 1 = blocked). The native loader
        condenses these into 4 resolved pointers at the runtime record's
        +0x04..+0x0B field (8 bytes = 4 LE words).

        Hypothesis (matches the example bytes ``8a1b 8e1b 781b 221a`` of a
        live dump):
          * Store the FIRST FOUR slot resolutions as LE words.
          * Each word = the resolved target's slot index in the
            pointer table (0 if blocked / null room).
          * Slots beyond the first 4 (U/D = up/down) are dropped
            because the native runtime record only has 8 bytes here.

        Slots map to N/S/E/W (the cardinal directions; same order as
        the VOCAB direction ids 0/1/2/3).

        Returns 8 bytes ready to be spliced into the runtime record.
        """
        from .tables import (
            NATIVE_DIRECTION_SLOT_OFFSET,
            NATIVE_NULL_ROOM_ID,
        )
        if len(on_disk_record) < NATIVE_DIRECTION_SLOT_OFFSET + 4:
            return b"\x00" * 8
        result = bytearray(8)
        for slot in range(4):  # N, S, E, W
            native_id = on_disk_record[NATIVE_DIRECTION_SLOT_OFFSET + slot]
            if native_id <= NATIVE_NULL_ROOM_ID:
                # 0 or 1 = blocked / null room
                continue
            # Validate id is within the pointer table.
            if 0 <= native_id - 1 < len(pointer_table):
                # Store the native id as LE word (target slot in
                # pointer table; the on-disk id IS the runtime index).
                result[slot * 2] = native_id & 0xFF
                result[slot * 2 + 1] = (native_id >> 8) & 0xFF
        return bytes(result)

    @staticmethod
    def build_runtime_record_for_room(
        slot_index: int,
        on_disk_record: bytes,
        active: bool = True,
        direction_slot_pointers: "bytes | None" = None,
        native_room_id: "int | None" = None,
        linked_native_id: "int | None" = None,
    ) -> RuntimeRecord:
        """Build a 32-byte runtime record from a 40-byte on-disk TABLES room record.

        This is the structural disk -> runtime transform. The native
        loader builds runtime records FIELD BY FIELD, not memcpy'd, so:

          * `+0x00` = on_disk[+0x00]               (type byte preserved)
          * `+0x01..02` = on_disk[+0x02..0x03]      (message pointer; native
                                                    relocates this but the
                                                    raw bytes are the same)
          * `+0x04..0x0B` = caller-supplied 8-byte ``direction_slot_pointers``
                            (4 resolved near pointers into the runtime room
                            array, built from the disk record's 6 direction
                            slots via the DS:0x25C pointer table). If
                            ``None``, this region stays zero.
          * `+0x14` = loader-resolved linked native room id
          * `+0x17` = 0 for active, 0x63 for explicitly inactive
          * `+0x18` = observed startup value 0x63 (not the gate)
          * `+0x1A` = native room id
          * Other fields (flags at +0x1C..) stay zero; the loader's
            scene-state init populates them from data we don't yet
            model.

        Pass on_disk as bytes (typically ``room_record.raw``).
        """
        if len(on_disk_record) < 0x15:
            raise ValueError(
                f"on-disk record too short: {len(on_disk_record)} bytes, "
                f"need at least 0x15"
            )
        runtime = bytearray(RUNTIME_RECORD_SIZE)
        runtime[RR_OFFSET_TYPE] = on_disk_record[0x00]
        # Message pointer relocation: on-disk +0x02..0x03 is a BIG-ENDIAN
        # word (six-byte-block index into MESSAGE). The native loader
        # converts this to a relocated runtime ADDRESS at runtime +0x01..02.
        # In our pure-Python port we don't relocate to RAM addresses --
        # but we DO match the native endianness (LE in the runtime
        # record, regardless of the on-disk BE). Storing the LE form
        # makes `message_pointer` accessor return the correct group
        # index (matches `TableRecord.be_word(2)` on the on-disk record).
        msg_group_index = (on_disk_record[0x02] << 8) | on_disk_record[0x03]
        runtime[RR_OFFSET_MSG_PTR] = msg_group_index & 0xFF
        runtime[RR_OFFSET_MSG_PTR + 1] = (msg_group_index >> 8) & 0xFF
        if direction_slot_pointers is not None:
            if len(direction_slot_pointers) != 8:
                raise ValueError(
                    f"direction_slot_pointers must be 8 bytes, got "
                    f"{len(direction_slot_pointers)}"
                )
            runtime[RR_OFFSET_DIR_FAR_PTRS : RR_OFFSET_DIR_FAR_PTRS + 8] = (
                direction_slot_pointers
            )
        if native_room_id is None:
            native_room_id = slot_index + 1
        if linked_native_id is None:
            linked_native_id = native_room_id
        runtime[RR_OFFSET_STATE_BYTE] = linked_native_id & 0xFF
        runtime[RR_OFFSET_GATE_LIMIT] = 0 if active else RR_GATE_LIMIT
        runtime[RR_OFFSET_ACTIVE_MARKER] = RR_ACTIVE_MARKER
        runtime[RR_OFFSET_ROOM_ID] = native_room_id & 0xFF
        return RuntimeRecord(index=slot_index, raw=bytes(runtime))

    def populate_from_native_room_ids(
        self,
        native_ids: "list[int] | tuple[int, ...]",
        pointer_table: "tuple",
    ) -> None:
        """Build runtime records for the given native room ids (1-based).

        Ports the per-scene loader pass that fills `DS:0x4BE0` from the
        DS:0x25C pointer table. The runtime array is built with:

          * Index 0: header / null entry (zeroed 32 bytes; the native
            engine reserves this slot but never iterates it).
          * Index 1: header entry 2 (also zeroed; native uses index 0..1
            as bookkeeping; the per-turn loop only iterates 2..word_19E7).
          * Indices 2..N+1: one runtime record per ``native_ids[i]``,
            built via ``build_runtime_record_for_room`` against the
            corresponding pointer-table entry.

        Records past the supplied list are left zeroed (the native
        engine has an "empty entry" shared across unused slots; we
        model it as separate zero-records here).

        After this call, ``state.scene.word_19E7`` should be set to
        ``len(native_ids) + 1`` so the per-turn loop iterates exactly
        the populated range (2..word_19E7 inclusive).
        """

        self.clear()
        # Indices 0 and 1: header / null entries (zeroed but with the
        # native marker so they don't match active-record filters by
        # accident).
        for header_idx in range(2):
            raw = bytearray(RUNTIME_RECORD_SIZE)
            raw[RR_OFFSET_GATE_LIMIT] = RR_GATE_LIMIT
            self.append(RuntimeRecord(index=header_idx, raw=bytes(raw)))
        # Indices 2..N+1: one runtime record per native room id
        for slot, native_id in enumerate(native_ids, start=2):
            if not 1 <= native_id <= len(pointer_table):
                # Out-of-range id: append a zero entry as a stand-in.
                raw = bytearray(RUNTIME_RECORD_SIZE)
                raw[RR_OFFSET_GATE_LIMIT] = RR_GATE_LIMIT
                self.append(RuntimeRecord(index=slot, raw=bytes(raw)))
                continue
            on_disk = pointer_table[native_id - 1]
            slot_pointers = RuntimeRecordArray.resolve_direction_slot_pointers(
                on_disk.raw, pointer_table
            )
            self.append(
                RuntimeRecordArray.build_runtime_record_for_room(
                    slot_index=slot,
                    on_disk_record=on_disk.raw,
                    active=True,
                    direction_slot_pointers=slot_pointers,
                    native_room_id=native_id,
                    linked_native_id=native_id,
                )
            )

    def populate_from_phase6_payloads(self, payloads: "tuple[bytes, ...]") -> None:
        """Build the native array copied by ``sub_11C6``.

        Type-0 TABLES records contribute exactly 0x1d bytes beginning at
        disk offset +1.  Slot zero is unused; the first payload is pointer
        table slot 1 and the dispatcher subsequently iterates slots
        ``2..word_19E7``.  Three zero bytes only pad our safe Python view to
        the 32-byte maximum accessed elsewhere; they are not disk fields.
        """
        self.clear()
        self.append(RuntimeRecord(index=0, raw=bytes(RUNTIME_RECORD_SIZE)))
        for index, payload in enumerate(payloads, start=1):
            if len(payload) != 0x1D:
                raise ValueError(
                    f"phase-6 payload must be 29 bytes, got {len(payload)}"
                )
            self.append(
                RuntimeRecord(
                    index=index,
                    raw=payload + bytes(RUNTIME_RECORD_SIZE - len(payload)),
                )
            )
