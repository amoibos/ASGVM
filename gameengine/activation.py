"""Shared ASG activation-table loader.

GAME.000 phases 6..9 repeatedly call the same TABLES iterator with record
types 0, 1, 2 and 3.  Each phase copies a type-specific payload into a freshly
allocated far-pointer table.  Python keeps the immutable payloads directly;
the tuple position is the native one-based table id minus one.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .predicates import AsgPhase7Node
from .tables import TableDecoder, TableRecord


@dataclass(frozen=True)
class AsgActivationState:
    """Direct globals written by activation phases 1..5."""

    byte_670: int
    set_671: bytes
    set_679: bytes
    native_room_id: int
    byte_6aa: int
    word_6ad: int
    block_1a4c: bytes
    block_4b63: bytes
    word_6ab: int
    block_1a54: bytes
    phase4: bytes
    phase5_header: bytes
    phase5_slots: bytes
    phase5_tail: bytes
    # DS:1A8D's ten 4-byte entries (value, MESSAGE record) -- None when the
    # title's layout has not been measured.
    block_1a8d: "bytes | None" = None

    @classmethod
    def from_tables(cls, tables: "AsgActivationTables") -> "AsgActivationState":
        p1, p2, p3, p4, p5 = (
            tables.phase1_record,
            tables.phase2_record,
            tables.phase3_record,
            tables.phase4_record,
            tables.phase5_record,
        )
        slots = bytes(p5[7:27])
        timers = slots + slots
        block_1a8d = None
        run = tables.phase5_run
        if len(run) == 4:
            # 40-byte layout: four type-6 records of five 4-byte entries
            # each (+7..+26). The first two are DS:1A5F[0..9] (the timers),
            # the last two DS:1A8D[0..9]. Measured 2026-10-14: the native
            # 1A8D after a new game holds records 3899, 2186, 2077 and 1893
            # in entries 1..4 -- record 6's words -- and the old reading
            # filled all ten timers from record 4 twice.
            timers = b"".join(bytes(r[7:27]) for r in run[:2])
            block_1a8d = b"".join(bytes(r[7:27]) for r in run[2:])
        elif len(run) == 2 and all(len(r) >= 47 for r in run):
            # 47-byte layout: one record holds all ten entries (+7..+46),
            # DS:1A5F first, then DS:1A8D (its words 1..4 are records, like
            # the 40-byte titles': A View to a Kill 2462/2420/2319/2198).
            timers = bytes(run[0][7:47])
            block_1a8d = bytes(run[1][7:47])
        return cls(
            byte_670=p1[1],
            set_671=bytes(p1[2:10]),
            set_679=bytes(p1[10:18]),
            native_room_id=p1[18],
            byte_6aa=p1[19],
            word_6ad=p1[20] | (p1[21] << 8),
            block_1a4c=bytes(p2[1:9]),
            block_4b63=bytes(p2[1:9]),
            word_6ab=p3[1] | (p3[2] << 8),
            block_1a54=bytes(p3[1:6]),
            phase4=bytes(p4[1:15]),
            phase5_header=bytes(p5[1:7]),
            phase5_slots=timers,
            phase5_tail=bytes(p5[27:31]),
            block_1a8d=block_1a8d,
        )


@dataclass(frozen=True)
class AsgActivationTables:
    phase1_record: bytes
    phase2_record: bytes
    phase3_record: bytes
    phase4_record: bytes
    phase5_record: bytes
    phase6_records: tuple[bytes, ...]
    phase7_nodes: tuple[AsgPhase7Node, ...]
    phase8_records: tuple[bytes, ...]
    room_records: tuple[TableRecord, ...]
    phase9_records: tuple[bytes, ...]
    # The whole leading run of type-6 records (phase 5).
    phase5_run: tuple[bytes, ...] = ()

    @classmethod
    def from_tables(cls, tables: TableDecoder) -> "AsgActivationTables":
        """Port the phase 6..9 activation-table builds.

        The assembly copies 0x1d, 0x1e, 0x27 and 0x21 bytes beginning at source
        offset +1.  Type 1's payload is the normalized phase-7 node format;
        type 2 records stay as TableRecords because movement also needs their
        remaining disk fields.
        """
        type0 = tables.records_by_type(0)
        type1 = tables.records_by_type(1)
        type2 = tables.records_by_type(2)
        type3 = tables.records_by_type(3)
        type6 = tables.records_by_type(6)
        if len(type6) < 2:
            raise ValueError("TABLES activation requires phase-5 and phase-6 type-6 records")
        records = tables.records()
        if len(records) < 5 or tuple(r.record_type for r in records[:5]) != (7, 4, 8, 9, 6):
            raise ValueError("unexpected TABLES activation prelude; expected types 7,4,8,9,6")
        return cls(
            phase1_record=records[0].raw,
            phase2_record=records[1].raw,
            phase3_record=records[2].raw,
            phase4_record=records[3].raw,
            phase5_record=records[4].raw,
            phase5_run=tuple(
                record.raw
                for record in records[4 : 4 + next(
                    (k for k, r in enumerate(records[4:]) if r.record_type != 6),
                    len(records) - 4,
                )]
            ),
            # The DS:0438 pointer table holds the type-0 records from slot 1.
            # Measured live 2026-10-13 after a new game: word_19E7 = 5,
            # 438[1] = the first (empty) type-0 record, 438[2..5] = Goldfinger,
            # Tilly, Oddjob, Pussy -- the VOCAB value_b of each name. An
            # earlier reading put the second type-6 record in slot 1, which
            # shifted every person by one.
            phase6_records=tuple(record.raw[1:0x1E] for record in type0),
            phase7_nodes=tuple(
                AsgPhase7Node(index=index, raw=record.raw[1:0x1F])
                for index, record in enumerate(type1, start=1)
            ),
            phase8_records=tuple(record.raw[1:0x28] for record in type2),
            room_records=type2,
            phase9_records=tuple(record.raw[1:0x22] for record in type3),
        )

    @property
    def word_19e7(self) -> int:
        """Native phase-6 pointer-table high-water mark."""
        return len(self.phase6_records)

    @property
    def initial_native_room_id(self) -> int:
        """Phase-1 ``sub_D61`` write to DS:06A9 from record +18."""
        return self.phase1_record[0x12]

    @property
    def byte_19e9(self) -> int:
        """Native phase-7 pointer-table high-water mark."""
        return len(self.phase7_nodes)

    @property
    def byte_19ea(self) -> int:
        """Native phase-8 pointer-table high-water mark."""
        return len(self.room_records)

    @property
    def byte_19eb(self) -> int:
        """Native phase-9 pointer-table high-water mark."""
        return len(self.phase9_records)

    def build_verb_response_records(self, engine) -> dict[int, int]:
        """Port of the DS:0x5F0 verb-to-record builder (GAME.000:2df3..2e51).

        The runtime verb-response table is NOT a static ``dw`` block; the
        overlay builds it at startup by reading, per verb id 0..63, three
        six-bit symbols from a packed MESSAGE record and folding them into a
        record index (``s0*0x1000 + s1*0x40 + s2``), storing it at
        ``DS:0x5F0[verb*2]``.  The source record is identified by a pointer the
        phase-1 activation record carries at ``+0x19`` (a MESSAGE record index
        in six-byte-block units); ``engine.record_symbols`` frames it exactly
        like any other record (its two-symbol length header is skipped).  A
        record value of 0 marks an unused verb slot (``byte_19EE`` tracks the
        highest populated id).

        Deriving this replaces the per-title frozen ``VERB_RESPONSE_RECORDS``
        captures: verified to reproduce all four exactly-captured titles and to
        recover one slot the hand-capture missed (The Mist verb 0x1E).
        """
        pointer = self.phase1_record[0x19] | (self.phase1_record[0x1A] << 8)
        symbols = engine.record_symbols(pointer)
        table: dict[int, int] = {}
        for verb in range(64):
            base = verb * 3
            if base + 3 > len(symbols):
                break
            record = (
                symbols[base] * 0x1000
                + symbols[base + 1] * 0x40
                + symbols[base + 2]
            )
            if record > 0:
                table[verb] = record
        return table


@dataclass
class AsgActivationRuntime:
    """Mutable phase-8 room images and confirmed phase-9 graph effects."""

    rooms: list[bytearray]
    active_rooms_4abe: set[int] = field(default_factory=set)
    bridge_rooms_1abc: set[int] = field(default_factory=set)

    @classmethod
    def from_tables(cls, tables: AsgActivationTables) -> "AsgActivationRuntime":
        return cls([bytearray(record) for record in tables.phase8_records])

    def room(self, native_id: int) -> "bytearray | None":
        if 1 <= native_id <= len(self.rooms):
            return self.rooms[native_id - 1]
        return None

    def apply_phase9(self, records: "tuple[bytes, ...]") -> None:
        """Execute the decoded type-3/kind-2 room-bridge operation.

        This is the common `loc_186D..1B52` body in the clean sibling
        disassembly.  Direction bytes are +4..+9 in normalized phase-8 room
        images (disk +5..+0a).
        """
        for record in records:
            if len(record) != 0x21 or record[0x11] != 2:
                continue
            source_id = record[0x0E]
            target_id = record[0x12]
            source = self.room(source_id)
            target = self.room(target_id)
            if source is None or target is None:
                continue
            self.active_rooms_4abe.add(target_id)
            bridge_id = target[0x08]
            if bridge_id == 1:
                bridge_id = target[0x04]
            bridge = self.room(bridge_id)
            if bridge is None:
                continue
            self.bridge_rooms_1abc.add(bridge_id)
            # The native body only splices records having a sentinel exit.
            if 1 not in source[0x04:0x0A]:
                continue
            # Only the first free slot the source's +10h direction mask
            # allows is spliced (the loop ends by forcing its counter to 5;
            # native room 15 keeps N/S/U free, its D leads to the DB5).
            for direction in range(6):
                offset = 0x04 + direction
                if not source[0x10] & (1 << direction) or source[offset] != 1:
                    continue
                source[offset] = bridge_id
                bridge[0x11] = source[0x11]
                bridge[offset] = target_id
                target[offset] = 1
                for sibling in range(6):
                    if sibling == direction:
                        continue
                    sibling_offset = 0x04 + sibling
                    bridge[sibling_offset] = source_id
                    target[sibling_offset] = bridge_id
                break

    def direction_target(self, native_room_id: int, direction: int) -> int | None:
        room = self.room(native_room_id)
        if room is None or not 0 <= direction < 6:
            return None
        target = room[0x04 + direction]
        return target if target > 1 and self.room(target) is not None else None
