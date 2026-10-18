"""TABLES codec — fixed-stride dispatcher records.

Engine-pure: the 40-byte (Variant A) / 47-byte (Variant B) record
stride is the engine-format split; field offsets within records are
consistent across both variants. Per-game record meaning (which
type-byte means "object" / "room" / etc.) is a game-binding concern
but the type-byte-at-+0 convention is shared.
"""

from __future__ import annotations

from dataclasses import dataclass


# Default TABLES record size for the Goldfinger engine variant.
# Other engine titles use 47-byte records;
# `TableDecoder` auto-detects from file size, falling back to this default.
TABLE_RECORD_SIZE = 40
# Sibling games use 47B records. Both layouts share the type-byte-at-+0
# convention; only the record stride differs.
TABLE_RECORD_SIZE_VARIANT_B = 47
KNOWN_TABLE_RECORD_SIZES = (40, 47)
TABLE_RECORD_TYPE_OFFSET = 0
# Direction slots. Offline direction-aware reciprocity over the type-2 room
# graph (N<->S, E<->W, U<->D) decides the disk layout: base +5 yields 146/166
# (87%) reciprocal links versus 16/143 (11%) at +4; the remaining ~13% are
# genuine one-way passages (falls/slides). The byte at +4 is a separate field
# that is 0 in every room. Slot values are 1-based native room ids: id 1 is the
# null room (type-2 index 0) and means "no exit"; id v>=2 -> type-2 index v-1.
NATIVE_DIRECTION_SLOT_OFFSET = 5
NATIVE_DIRECTION_SLOT_COUNT = 6
NATIVE_NULL_ROOM_ID = 1
NATIVE_ROOM_ID_BASE = 1
NATIVE_RECORD_STATE_OFFSET = 0x14
NATIVE_RECORD_SCRIPT_OFFSET = 0x17
NATIVE_RECORD_VISITED_OFFSET = 0x22
NATIVE_RECORD_AUX_STATE_OFFSET = 0x24
# The exit gate at GAME.000:218d reads the target's in-memory +24h -- the open
# flag (0 = closed, scenery records start closed and OPEN sets it). TABLES
# records carry one leading family byte that the in-memory image does not
# (exits sit at raw +05h, in-memory +04h), so that byte is raw +25h here. The
# old reading of raw +24h was in-memory +23h, the "is scenery" flag, with the
# polarity inverted; for the pristine data the two errors cancel (an ordinary
# room has +23h = 0 and +24h = 1, closed scenery the reverse), which is why it
# only showed once a door was opened.
NATIVE_RECORD_OPEN_FLAG_OFFSET = 0x25

# GAME.000:1f3c compares the +0x17 byte against 0x63; GAME.000:1f4f compares
# the +0x14 byte against 1. Both must pass for the dispatcher to process a
# record. Kept as named raw thresholds so the port stays auditable.
NATIVE_GATE_SCRIPT_LIMIT = 0x63
NATIVE_GATE_BLOCKED_STATE = 1

# Object record (type=0x01) field offsets. Confirmed by enumerating all 26
# object records and rendering MESSAGE at the +9..+10 LE word for each
# walkthrough-known object: oil slick, spikes, cable, lighter, badge, armrest,
# button, desk, letter, frame all match. Object records follow the same 1-based
# slot convention as rooms: VOCAB ``value_b`` N -> ``object_records[N - 1]``,
# so slot 0 is the null/header object and real objects start at vb=1.
OBJECT_EXAMINE_REF_OFFSET = 9       # LE word: depaged MESSAGE record index for EXAMINE description
OBJECT_LOCATION_OFFSET = 0x0C       # Native TAKE trace: sub_BC69 discriminator=2 writes record[+0x0C]
OBJECT_INITIAL_CONTAINER_OFFSET = 0x18  # Object's initial container VOCAB value_b (0/1 = none)
OBJECT_INVENTORY_LOCATION_VALUE = 0x53  # TAKE LIGHTER trace wrote AX=0x0053 to record[+0x0C]
NATIVE_OBJECT_ID_BASE = 1           # VOCAB value_b is 1-based; index = value_b - 1
NATIVE_FIELD_SELECTOR_RECORD = 0x41  # sub_BBC3 selector for fields on the current object record
NATIVE_FIELD_SELECTOR_ARRAY_1A8D = 0x58  # sub_BBC3 selector for 4-byte stride word array DS:1A8D
NATIVE_FIELD_SELECTOR_ARRAY_1A5F = 0x54  # sub_BBC3 selector for 4-byte stride word array DS:1A5F
NATIVE_OBJECT_FIELD_15 = 1          # sub_BC69/sub_BD67: record[+0x15]
NATIVE_OBJECT_FIELD_LOCATION = 2    # sub_BC69/sub_BD67: record[+0x0C]
NATIVE_OBJECT_FIELD_16 = 3          # sub_BC69/sub_BD67: record[+0x16]
NATIVE_OBJECT_FIELD_0D = 4          # sub_BC69/sub_BD67: record[+0x0D]
NATIVE_OBJECT_FIELD_WORD_1AE8 = 5   # sub_BC69/sub_BD67: global word_1AE8

# turn_resolve_text discriminator (GAME.000:sub_4E03 at offset 0x4E03)
# Direct port of the IDA-decoded switch on ``record[+6]``:
#
#   record[+6] | section [4B11] | word_4B7F source            | extra effects
#   -----------|----------------|-----------------------------|---------------------------
#   0x11       | 6              | record[+4] (LE word)        | visited compare 1A4C vs 1A4F
#   0x16       | 6              | record[+8] (LE word)        | continuation in func chunk
#   0x1C       | 7              | record[+6] (LE word at +6)  | none
#   0x17       | 5              | record[+2]/[+3] (byte path) | sub-routing via bp-14h+2
#   0x19       | 5              | record[+4] via 1A4C buffer  | sets byte_1A4F
#   default    | 5              | (none -- caller picks up)   | falls through to common
#
# These are kept as named constants so the discriminator switch in
# ``TableRecord.turn_resolve_text`` (below) stays auditable against the
# original assembly.
TURN_RESOLVE_DISCRIMINATOR_OFFSET = 0x06
TURN_DISCRIM_REF_AT_4 = 0x11        # word_4B7F = record[+4]
TURN_DISCRIM_REF_AT_8 = 0x16        # word_4B7F = record[+8]
TURN_DISCRIM_REF_AT_6 = 0x1C        # word_4B7F = record[+6]
TURN_DISCRIM_USES_2_3 = 0x17        # record[+2]/[+3] byte path
TURN_DISCRIM_BUFFER_PATH = 0x19     # byte_1A4C buffer path (untraced effect)

# Section-selector state [DS:0x4B11] values set by sub_4E03 per branch.
SECTION_STATE_DEFAULT = 5
SECTION_STATE_REF = 6
SECTION_STATE_REF_AT_6 = 7


@dataclass(frozen=True)
class TableRecord:
    index: int
    offset: int
    raw: bytes

    def byte(self, offset: int) -> int:
        return self.raw[offset]

    @property
    def record_type(self) -> int:
        """Return the unclassified native record-family byte at ``+0``."""

        return self.byte(TABLE_RECORD_TYPE_OFFSET)

    def le_word(self, offset: int) -> int:
        return self.raw[offset] | (self.raw[offset + 1] << 8)

    def be_word(self, offset: int) -> int:
        return (self.raw[offset] << 8) | self.raw[offset + 1]

    def native_direction_slots(self) -> tuple[int, int, int, int, int, int]:
        """Return the six direction-slot ids, ordered N, S, E, W, U, D.

        The slots are six byte values beginning at record offset +5 (see the
        module-level note for the reciprocity evidence). The order matches the
        VOCAB direction ids (north=0, south=1, east=2, west=3, up=4, down=5).
        Values remain raw 1-based native room ids: their pointer resolution and
        state conditions belong to the dispatcher.
        """

        values = self.raw[
            NATIVE_DIRECTION_SLOT_OFFSET : NATIVE_DIRECTION_SLOT_OFFSET + NATIVE_DIRECTION_SLOT_COUNT
        ]
        return tuple(values)  # type: ignore[return-value]

    def native_direction_target(self, direction: int) -> int | None:
        if not 0 <= direction < NATIVE_DIRECTION_SLOT_COUNT:
            raise ValueError("native direction must be in range 0..5")
        target = self.native_direction_slots()[direction]
        # id 0 (unused) and id 1 (null room) both mean "no exit".
        return None if target <= NATIVE_NULL_ROOM_ID else target

    def native_state_fields(self) -> dict[str, int]:
        """Expose mutable fields read/written by the GAME.000 dispatcher.

        Names describe access role only. Semantic interpretation remains tied
        to the individual dispatcher operation being ported.
        """

        return {
            "state": self.byte(NATIVE_RECORD_STATE_OFFSET),
            "script": self.byte(NATIVE_RECORD_SCRIPT_OFFSET),
            "visited": self.byte(NATIVE_RECORD_VISITED_OFFSET),
            "aux_state": self.byte(NATIVE_RECORD_AUX_STATE_OFFSET),
        }

    def dispatcher_active(self) -> bool:
        """Port the condition gate at GAME.000:1f36..1f5d.

        The dispatcher reads the +0x17 byte (cond1 = value < 0x63) and the
        +0x14 byte (cond2 = value != 1) as unsigned bytes and processes the
        record only when ``cond1 and cond2`` hold (the native ``and`` at
        GAME.000:1f59). All other records are skipped to GAME.000:2019.
        """

        return (
            self.byte(NATIVE_RECORD_SCRIPT_OFFSET) < NATIVE_GATE_SCRIPT_LIMIT
            and self.byte(NATIVE_RECORD_STATE_OFFSET) != NATIVE_GATE_BLOCKED_STATE
        )

    def native_entry_allowed(self) -> bool:
        """Port the +0x24 aux-state gate at GAME.000:218d..21a6.

        When the dispatcher evaluates an open exit it inspects the *target*
        room's +0x24 aux-state byte and sets the availability global DS:0x1aec
        to 1 when that byte is 0, and to 0 otherwise. Exposed here as a
        predicate on the target record so the rule stays auditable; the global
        itself is runtime state and is not modelled statically.
        """

        return self.byte(NATIVE_RECORD_OPEN_FLAG_OFFSET) != 0

    def be_message_refs(self, max_offset: int) -> list[tuple[int, int]]:
        refs: list[tuple[int, int]] = []
        # Variant-B records are 47 bytes long.  The final unpaired byte cannot
        # form a 16-bit reference and must not be passed to ``be_word``.
        for offset in range(0, len(self.raw) - 1, 2):
            value = self.be_word(offset)
            if 0 < value < max_offset:
                refs.append((offset, value))
        return refs

    def turn_resolve_text(self) -> "TurnResolveResult":
        """Port of GAME.000:sub_4E03 -- compute (word_4B7F, section_state).

        Direct port of the IDA-decoded discriminator switch on
        ``record[+6]``. Returns ``TurnResolveResult`` carrying:

          * ``message_ref``: the value the native dispatcher stores in the
            global ``word_4B7F`` (i.e. the MESSAGE record / index the
            response emitter renders), or ``None`` for branches that don't
            set it directly (default / 0x17 / 0x19 -- those select the
            content via routing into other globals not modelled here).
          * ``section_state``: the value written to ``[DS:0x4B11]``
            (the ``(``-section-selector state byte).
          * ``discriminator``: the raw ``record[+6]`` byte, preserved for
            audit.

        Effects not modelled here (kept as documented hypotheses):
          * 0x11 branch also runs a visited-state compare
            (``byte_1A4C`` vs ``byte_1A4F``) and calls ``sub_4D65``.
          * 0x16 branch's continuation in the function chunk at 4F49
            is partially traced.
          * 0x17 and 0x19 branches route into other state globals
            (``byte_4ADC``, ``byte_1A4F``, ``byte_1A51``, ``byte_1A52``,
            ``byte_1A56``, ``byte_1A57``) whose semantics are untraced.

        This is the dispatcher routine *every* verb handler uses via the
        multi-fragment assembler ``sub_8628`` to find its response record,
        so porting it unblocks data-driven verb-handler response rendering.
        """

        disc = self.byte(TURN_RESOLVE_DISCRIMINATOR_OFFSET)
        if disc == TURN_DISCRIM_REF_AT_4:
            return TurnResolveResult(
                message_ref=self.le_word(0x04),
                section_state=SECTION_STATE_REF,
                discriminator=disc,
            )
        if disc == TURN_DISCRIM_REF_AT_8:
            return TurnResolveResult(
                message_ref=self.le_word(0x08),
                section_state=SECTION_STATE_REF,
                discriminator=disc,
            )
        if disc == TURN_DISCRIM_REF_AT_6:
            return TurnResolveResult(
                message_ref=self.le_word(0x06),
                section_state=SECTION_STATE_REF_AT_6,
                discriminator=disc,
            )
        if disc == TURN_DISCRIM_USES_2_3:
            # Routes via record[+2]/[+3] into other state globals; no
            # direct word_4B7F set. Section state := 5 (default).
            return TurnResolveResult(
                message_ref=None,
                section_state=SECTION_STATE_DEFAULT,
                discriminator=disc,
            )
        if disc == TURN_DISCRIM_BUFFER_PATH:
            # byte_1A4C buffer copy path; word_4B7F not set directly.
            return TurnResolveResult(
                message_ref=None,
                section_state=SECTION_STATE_DEFAULT,
                discriminator=disc,
            )
        # Default branch (loc_50B3 entry): only section state is set.
        return TurnResolveResult(
            message_ref=None,
            section_state=SECTION_STATE_DEFAULT,
            discriminator=disc,
        )


@dataclass(frozen=True)
class TurnResolveResult:
    """Output of ``TableRecord.turn_resolve_text`` (port of sub_4E03)."""

    message_ref: int | None      # value written to word_4B7F (None when path doesn't set it)
    section_state: int           # value written to [DS:0x4B11]
    discriminator: int           # raw record[+6] for audit


@dataclass(frozen=True)
class NativeFieldRef:
    """Decoded operand target from GAME.000:sub_BBC3.

    The native routine maps an operand number to a selector namespace and
    an index. Selector ``0x41`` addresses fields on the current object record;
    ``0x58`` and ``0x54`` address two scene-global word arrays with 4-byte
    strides.
    """

    selector: int
    index: int


@dataclass
class TableRuntimeState:
    """Mutable overlay for dispatcher writes to immutable TABLES records.

    GAME.000 mutates loaded table records in memory.  The on-disk TABLES file
    is kept read-only by this project, so the Python port stores only changed
    bytes keyed by original record index and offset.
    """

    overrides: dict[tuple[int, int], int]
    word_1ae8: int
    word_1ae8_dirty: bool
    array_1a8d: dict[int, int]
    array_1a5f: dict[int, int]
    array_1a5f_secondary: dict[int, int]

    def __init__(self) -> None:
        self.overrides = {}
        self.word_1ae8 = 0
        self.word_1ae8_dirty = False
        self.array_1a8d = {}
        self.array_1a8d_secondary: dict[int, int] = {}
        self.array_1a5f = {}
        self.array_1a5f_secondary = {}

    def read_byte(self, record: TableRecord, offset: int) -> int:
        if not 0 <= offset < len(record.raw):
            raise ValueError("TABLES offset outside record")
        return self.overrides.get((record.index, offset), record.byte(offset))

    def write_byte(self, record: TableRecord, offset: int, value: int) -> None:
        if not 0 <= offset < len(record.raw):
            raise ValueError("TABLES offset outside record")
        if not 0 <= value <= 0xFF:
            raise ValueError("TABLES byte value outside range")
        self.overrides[(record.index, offset)] = value

    def read_bytes(self, record: TableRecord, offset: int, size: int) -> bytes:
        if size < 0 or offset < 0 or offset + size > len(record.raw):
            raise ValueError("TABLES byte range outside record")
        return bytes(self.read_byte(record, offset + index) for index in range(size))

    def write_bytes(self, record: TableRecord, offset: int, value: bytes) -> None:
        if offset < 0 or offset + len(value) > len(record.raw):
            raise ValueError("TABLES byte range outside record")
        for index, byte in enumerate(value):
            self.write_byte(record, offset + index, byte)

    def native_entry_allowed(self, record: TableRecord) -> bool:
        """Port GAME.000:218d..21a6 against the live record value."""

        return self.read_byte(record, NATIVE_RECORD_OPEN_FLAG_OFFSET) != 0

    def mark_visited(self, record: TableRecord) -> None:
        """Port the target-room write at GAME.000:21d0..21e1."""

        self.write_byte(record, NATIVE_RECORD_VISITED_OFFSET, 1)

    def decode_native_field_operand(self, operand: int) -> NativeFieldRef:
        """Port GAME.000:sub_BBC3's operand-to-field mapping.

        ``operand`` is the value carried by action opcodes before
        ``sub_BC69``/``sub_BD67``. The native code first checks a Pascal-set
        helper; when the value is outside that accepted set it falls back to
        selector ``0x41``, index ``0``. For the accepted ranges visible in the
        disassembly:

        * ``0..5`` -> selector ``0x41`` with the same index.
        * ``6..15`` -> selector ``0x58`` with index ``operand - 6``.
        * ``>=16`` -> selector ``0x54`` with index ``operand - 16``.
        """

        if not 0 <= operand <= 0xFFFF:
            raise ValueError("native field operand outside word range")
        if operand < 6:
            return NativeFieldRef(NATIVE_FIELD_SELECTOR_RECORD, operand)
        if operand < 0x10:
            return NativeFieldRef(NATIVE_FIELD_SELECTOR_ARRAY_1A8D, operand - 6)
        return NativeFieldRef(NATIVE_FIELD_SELECTOR_ARRAY_1A5F, operand - 0x10)

    def read_native_field(self, record: TableRecord | None, operand: int) -> int:
        """Read a modelled native field without applying signed post-processing.

        This is the raw value stored in the mutable TABLES overlay.  Native
        callers that go through ``sub_BD67`` use :meth:`read_native_field_abs`,
        which mirrors the final signed-absolute-value step at
        ``GAME.000:BE76..BE92``.
        """

        ref = self.decode_native_field_operand(operand)
        if ref.selector == NATIVE_FIELD_SELECTOR_RECORD:
            if ref.index == 0:
                return 0
            if ref.index == NATIVE_OBJECT_FIELD_15:
                if record is None:
                    return 0
                return self.read_byte(record, 0x15)
            if ref.index == NATIVE_OBJECT_FIELD_LOCATION:
                if record is None:
                    return 0
                return self.read_byte(record, OBJECT_LOCATION_OFFSET)
            if ref.index == NATIVE_OBJECT_FIELD_16:
                if record is None:
                    return 0
                return self.read_byte(record, 0x16)
            if ref.index == NATIVE_OBJECT_FIELD_0D:
                if record is None:
                    return 0
                return self.read_byte(record, 0x0D)
            if ref.index == NATIVE_OBJECT_FIELD_WORD_1AE8:
                return self.word_1ae8
            return 0
        if ref.selector == NATIVE_FIELD_SELECTOR_ARRAY_1A8D:
            return self.array_1a8d.get(ref.index, 0)
        if ref.selector == NATIVE_FIELD_SELECTOR_ARRAY_1A5F:
            return self.array_1a5f.get(ref.index, 0)
        return 0

    @staticmethod
    def _signed_word(value: int) -> int:
        value &= 0xFFFF
        return value - 0x10000 if value & 0x8000 else value

    @staticmethod
    def _unsigned_word(value: int) -> int:
        return value & 0xFFFF

    def read_native_field_abs(self, record: TableRecord, operand: int) -> int:
        """Port the signed absolute return value of ``GAME.000:sub_BD67``."""

        return abs(self._signed_word(self.read_native_field(record, operand)))

    def read_array_1a5f_signed(self, index: int) -> int:
        """Read ``DS:1A5F[index]`` as the signed word used by opcodes 4Ch/4Dh."""

        return self._signed_word(self.array_1a5f.get(index, 0))

    @property
    def score(self) -> int:
        """Native score displayed by GAME.COM from ``DS:word_1A8D``.

        The action VM addresses this word as field operand 6, i.e. the first
        entry of the four-byte-stride selector-0x58 array.
        """

        return self.array_1a8d.get(0, 0)

    @score.setter
    def score(self, value: int) -> None:
        if not 0 <= value <= 0xFFFF:
            raise ValueError("native score outside word range")
        self.array_1a8d[0] = value

    def write_array_1a5f_signed(self, index: int, value: int) -> None:
        """Write ``DS:1A5F[index]`` preserving the native 16-bit representation."""

        self.array_1a5f[index] = self._unsigned_word(value)

    def read_array_1a5f_secondary(self, index: int) -> int:
        """Read the second word in a 4-byte ``DS:1A5F`` entry."""

        return self.array_1a5f_secondary.get(index, 0)

    def write_array_1a5f_secondary(self, index: int, value: int) -> None:
        """Port direct writes to ``DS:1A5F[index]+2``."""

        self.array_1a5f_secondary[index] = self._unsigned_word(value)

    def write_native_field(self, record: TableRecord | None, operand: int, value: int) -> None:
        """Port GAME.000:sub_BC69 for the modelled TABLES targets."""

        if not 0 <= value <= 0xFFFF:
            raise ValueError("native field value outside word range")
        ref = self.decode_native_field_operand(operand)
        if ref.selector == NATIVE_FIELD_SELECTOR_RECORD:
            byte_value = value & 0xFF
            if ref.index == NATIVE_OBJECT_FIELD_15:
                if record is not None:
                    self.write_byte(record, 0x15, byte_value)
            elif ref.index == NATIVE_OBJECT_FIELD_LOCATION:
                if record is not None:
                    self.write_byte(record, OBJECT_LOCATION_OFFSET, byte_value)
            elif ref.index == NATIVE_OBJECT_FIELD_16:
                if record is not None:
                    self.write_byte(record, 0x16, byte_value)
            elif ref.index == NATIVE_OBJECT_FIELD_0D:
                if record is not None:
                    self.write_byte(record, 0x0D, byte_value)
            elif ref.index == NATIVE_OBJECT_FIELD_WORD_1AE8:
                self.word_1ae8 = value
                self.word_1ae8_dirty = True
            return
        if ref.selector == NATIVE_FIELD_SELECTOR_ARRAY_1A8D:
            self.array_1a8d[ref.index] = value
            return
        if ref.selector == NATIVE_FIELD_SELECTOR_ARRAY_1A5F:
            self.array_1a5f[ref.index] = value


class TableDecoder:
    """Decoder for the fixed-width `TABLES` file.

    GAME.000:1DF7 opens TABLES with record size 0x28 in Goldfinger. Other
    sibling games (Forbidden Castle, View to a Kill, Rambo, The Mist,
    Voodoo Island) use the same engine with a 47-byte record stride.
    Both variants share the type-byte-at-+0 convention; only the stride
    differs.

    Pass ``record_size=`` explicitly to disambiguate, or let auto-detect
    pick the first ``KNOWN_TABLE_RECORD_SIZES`` value that divides the
    file size evenly.
    """

    def __init__(self, data: bytes, record_size: "int | None" = None) -> None:
        if record_size is not None:
            if record_size not in KNOWN_TABLE_RECORD_SIZES:
                raise ValueError(
                    f"TABLES record_size {record_size} not in "
                    f"{KNOWN_TABLE_RECORD_SIZES}"
                )
            if len(data) % record_size:
                raise ValueError(
                    f"TABLES size {len(data)} not divisible by {record_size}"
                )
            self.record_size = record_size
        else:
            self.record_size = self._detect_record_size(data)
        self.data = data

    @staticmethod
    def _detect_record_size(data: bytes) -> int:
        """Pick the first KNOWN size that divides ``len(data)``.

        Both 40 and 47 are coprime, so a given TABLES file divides by at
        most one of them, making detection unambiguous.
        """
        for candidate in KNOWN_TABLE_RECORD_SIZES:
            if data and len(data) % candidate == 0:
                return candidate
        raise ValueError(
            f"TABLES size {len(data)} not divisible by any known record "
            f"size {KNOWN_TABLE_RECORD_SIZES}"
        )

    def records(self) -> list[TableRecord]:
        return [
            TableRecord(index, offset, self.data[offset : offset + self.record_size])
            for index, offset in enumerate(range(0, len(self.data), self.record_size))
        ]

    def dispatcher_active_records(self) -> tuple[TableRecord, ...]:
        """Records that pass the GAME.000:1f36..1f5d condition gate."""

        return tuple(record for record in self.records() if record.dispatcher_active())

    def native_room_records(self) -> tuple[TableRecord, ...]:
        """Return the type-2 record pointer order used by GAME.000.

        GAME.000 builds a pointer table over the room records and later indexes
        it with the raw direction-slot id. This exposes that order without
        asserting that every target is currently traversable.
        """

        return self.records_by_type(0x02)

    def records_by_type(self, record_type: int) -> tuple[TableRecord, ...]:
        """Return records in original file order for one raw family byte.

        The loader preserves this ordering when it builds the pointer tables.
        Keeping the type raw avoids assigning unsupported gameplay meanings to
        the non-room families (for example the initial type-``0x07`` record).
        """

        if not 0 <= record_type <= 0xFF:
            raise ValueError("TABLES record type must be a byte")
        return tuple(record for record in self.records() if record.record_type == record_type)

    def resolve_native_room(self, room_id: int) -> TableRecord | None:
        # Slot ids are 1-based (id 1 = null room); convert to a type-2 index.
        index = room_id - NATIVE_ROOM_ID_BASE
        rooms = self.native_room_records()
        if not 0 <= index < len(rooms):
            return None
        return rooms[index]

    def room_pointer_table(self) -> tuple[TableRecord, ...]:
        """Return the DS:0x025C pointer-table equivalent: type-2 records in
        order, indexed by 1-based native room id.

        The native dispatcher reads `record[+0x14] << 2` to index into
        `DS:0x025C` (4-byte stride = far-pointer per entry). Position 0
        is the null room (never traversed); positions 1..N are real
        rooms ordered by their disk-file slot. This method returns the
        same ordering as a tuple so callers can index with the raw
        native room id.

        The first entry (index 0) is the null/header room (always the
        type-2 record with all-zero direction slots) -- preserved here
        so that `room_pointer_table()[native_id]` works directly.
        """

        return self.native_room_records()

    def resolve_native_direction(self, record: TableRecord, direction: int) -> TableRecord | None:
        target = record.native_direction_target(direction)
        return None if target is None else self.resolve_native_room(target)

    def resolve_entry(
        self, record: TableRecord, direction: int, state: TableRuntimeState | None = None
    ) -> tuple[TableRecord | None, bool]:
        """Resolve one exit and apply the GAME.000:215e..21a6 entry rules.

        Returns ``(target_record, entry_allowed)``. The slot is read at
        ``record[0x5 + direction]``; ids 0/1 mean "no exit", in which case
        ``(None, False)`` is returned. Otherwise the 1-based slot id resolves to
        the target room (type-2 index id-1) and ``entry_allowed`` mirrors the
        target's +0x24 aux-state gate.
        """

        target = self.resolve_native_direction(record, direction)
        if target is None:
            return None, False
        entry_allowed = (
            target.native_entry_allowed() if state is None else state.native_entry_allowed(target)
        )
        return target, entry_allowed

    def native_direction_availability(
        self, record: TableRecord, state: TableRuntimeState | None = None
    ) -> tuple[bool, bool, bool, bool, bool, bool]:
        """Evaluate all six slots using GAME.000:213B..21A9's gate.

        The native loop performs the same blocked-slot and target ``+0x24``
        checks for every direction before a movement command selects one. This
        exposes its raw availability result without rendering an exit list or
        claiming an unverified room description.
        """

        return tuple(
            self.resolve_entry(record, direction, state)[1]
            for direction in range(NATIVE_DIRECTION_SLOT_COUNT)
        )  # type: ignore[return-value]
