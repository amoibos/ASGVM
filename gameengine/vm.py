"""Executable common ASG runtime assembled from the recovered VM layers."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Callable

from .activation import AsgActivationRuntime, AsgActivationState, AsgActivationTables
from .actions import AsgActionExecutor, AsgActionState
from .dispatcher import AsgPerTurnDispatcher
from .pascal_set import PascalSet
from .predicates import (
    AsgPhase7Evaluator,
    AsgPredicateState,
    RuntimeVocabNodeTable,
    RuntimeVocabCursor,
)
from .vocab import VocabEntry
from .runtime_records import RuntimeRecordArray
from .tables import TableDecoder, TableRuntimeState
from .vm_messages import MessageControlMixin
from .vm_actions import ActionMixin
from .vm_listing import ListingMixin
from .vm_people import PeopleMixin


@dataclass
class AsgVm(MessageControlMixin, ActionMixin, ListingMixin, PeopleMixin):
    tables: TableDecoder
    activation: AsgActivationTables
    graph: AsgActivationRuntime
    table_state: TableRuntimeState = field(default_factory=TableRuntimeState)
    predicates: AsgPredicateState = field(default_factory=AsgPredicateState)
    runtime_records: RuntimeRecordArray = field(default_factory=RuntimeRecordArray)
    excluded_19ef: PascalSet = field(default_factory=lambda: PascalSet.empty(8))
    auxiliary_4ab6: PascalSet = field(default_factory=lambda: PascalSet.empty(8))
    # DS:1AB8 (4 bytes): people already described ("mentioned"), written by
    # the `%l` people listing (loc_F915) and the `=d` mark (kind 1).
    set_1ab8: PascalSet = field(default_factory=lambda: PascalSet.empty(4))
    # DS:1ACB (15 bytes): rooms already described, written by `=d` (kind 2).
    set_1acb: PascalSet = field(default_factory=lambda: PascalSet.empty(15))
    # DS:1ADA (2 bytes): phase-9 records already described (`=d`, kind 3).
    set_1ada: PascalSet = field(default_factory=lambda: PascalSet.empty(2))
    globals: AsgActivationState | None = None
    activated: bool = False
    vocab_nodes: RuntimeVocabNodeTable | None = None
    action_state: AsgActionState = field(default_factory=AsgActionState)
    parser_cursor: RuntimeVocabCursor | None = None
    phase7_runtime: dict[int, bytearray] = field(default_factory=dict)
    # ``sub_AE9E`` hands msg_ctrl_amp a resolved cursor *and* that cursor's
    # resolver kind, which the render frame keeps at ``ss:[bx-19h]`` while the
    # value sits at ``ss:[bx-17h]``. Every context-switching callee reads the
    # pair together: sub_D814 (f/g/i state), sub_D6FD (the `*` presence test),
    # sub_EF31's 39h/3Ah/44h/45h action dispatch. For the cursors bound from a
    # parsed noun the kind is that VOCAB entry's ``value_a``; nouns the player
    # can only refer to as part of a room (doors, windows, scenery) carry
    # kind 2 and therefore resolve against the room table, not the object one.
    # Keyed by amp selector (0x87 + operand symbol); absent means kind 0.
    cursor_context_types: dict[int, int] = field(default_factory=dict)
    phase9_runtime: list[bytearray] = field(default_factory=list)
    rewire_rooms_4acd: PascalSet = field(
        default_factory=lambda: PascalSet.empty(15)
    )
    direction_cursor_6aa: int = 0
    # Turbo Pascal 3's RandSeed (DS:01FC, 32 bits). The game never calls
    # Randomize, so it starts at 0 in every session -- measured live
    # 2026-10-14, together with one generator step per Random call. Saved with the game state.
    rand_seed: int = 0
    # word_6AB, the move counter ("MOVE #8" on the ending screen): 1 after a
    # new game (measured), +1 per turn. The end-of-turn routine runs the
    # people update only once it is above 1 and the phase-9 walkers every
    # fifth move.
    move_counter: int = 1
    # Set while the player's move command renders its record: action 38h
    # calls it with the direction and it performs the move.
    move_hook: "Callable[[int], bool] | None" = None
    last_ridden_phase9: "int | None" = None
    # GAME.COM 5DA2, a single step to a room (action 40h); set by the game.
    step_hook: "Callable[[int], None] | None" = None
    # Symbols consumed by the most recent execute_action_block() call, in the
    # caller's original coordinate space. sub_EF31 (the native `(` handler,
    # confirmed via both the static disassembly and a live capstone
    # disassembly of the resident renderer segment) executes exactly one
    # opcode and returns -- it never loops over further opcodes itself. The
    # MESSAGE render loop must therefore resume literal prose right after
    # this many symbols, not after a mis-detected "label"; exposed here
    # rather than as a return value so the existing unresolved-opcode tuple
    # contract stays unchanged.
    last_action_block_length: int = 0
    # Native byte_4B7B render/skip result of the just-executed action block,
    # ONLY for opcodes this port has confirmed set it as their real native
    # effect (currently 0x32-0x35 -- see execute_set_action). ``None`` for
    # every other opcode means "unknown", so a caller gating a `(` composite
    # label's render/skip decision on this must leave its own state alone
    # rather than guess. Reset at the top of each execute_action_block call.
    last_action_gate: bool | None = None
    # Direct-object value_b preserved while ``byte_1A4C`` points at a PUT
    # container or open-container context for amp/dollar predicates.
    # SAVE (opcode 3Dh): the title's save dialog, and what actions printed.
    save_hook: "Callable[[], str | None] | None" = None
    action_output: list = field(default_factory=list)
    message_direct_object_value_b: int | None = None
    message_command_value_b: int | None = None
    message_container_context: int | None = None

    @classmethod
    def from_decoder(cls, tables: TableDecoder) -> "AsgVm":
        activation = AsgActivationTables.from_tables(tables)
        graph = AsgActivationRuntime.from_tables(activation)
        # Phase 9's type-3 graph splice is deterministic and movement may be
        # entered from a restored/pre-scene state before the full rule-bank
        # activation runs.
        graph.apply_phase9(activation.phase9_records)
        return cls(tables=tables, activation=activation, graph=graph)

    @staticmethod
    def merge_section_state(current: int, resolved_type: int) -> int:
        """Apply the section-selector's protected-state assignment.

        In both branches at captured ``rt_paren.bin`` offsets 0x143..0x165
        and 0x1DB..0x1F0, the resolved local type replaces ``DS:4B11`` unless
        its current value is 5. State 5 is therefore a protected dispatcher
        state, not an ordinary MESSAGE label id.
        """

        return 5 if (current & 0xFF) == 5 else (resolved_type & 0xFF)

    def activate(self) -> None:
        """Run the decoded phase 6..9 TABLES activation chain."""
        phase1 = self.activation.phase1_record
        self.globals = AsgActivationState.from_tables(self.activation)
        self.action_state.word_6ad = self.globals.word_6ad
        self.direction_cursor_6aa = self.globals.byte_6aa
        p4 = self.globals.phase4
        self.action_state.load_phase4(p4)
        if len(self.globals.phase5_tail) >= 4:
            self.action_state.byte_1a8a = self.globals.phase5_tail[3]
        # FB8: the phase-5 header is the clock -- 1A59 (day), 1A5A (hour),
        # 1A5B (minute), 1A5C (AM), word 1A5D. Goldfinger's 00 0C 00 00 is
        # 12 PM: the native SAVE files hold 1A5C = 0 (2026-10-17).
        header = self.globals.phase5_header
        if len(header) >= 6:
            state = self.action_state
            state.byte_1a59, state.byte_1a5a, state.byte_1a5b, state.byte_1a5c = header[0:4]
            state.word_1a5d = header[4] | (header[5] << 8)
        self.table_state.word_1ae8 = p4[4] | (p4[5] << 8)
        self.table_state.word_1ae8_dirty = False
        self.table_state.array_1a5f = {
            slot: self.globals.phase5_slots[slot * 4]
            | (self.globals.phase5_slots[slot * 4 + 1] << 8)
            for slot in range(10)
        }
        self.table_state.array_1a5f_secondary = {
            slot: self.globals.phase5_slots[slot * 4 + 2]
            | (self.globals.phase5_slots[slot * 4 + 3] << 8)
            for slot in range(10)
        }
        block = self.globals.block_1a8d
        if block is not None:
            self.table_state.array_1a8d = {
                slot: int.from_bytes(block[slot * 4 : slot * 4 + 2], "little")
                for slot in range(len(block) // 4)
            }
            self.table_state.array_1a8d_secondary = {
                slot: int.from_bytes(block[slot * 4 + 2 : slot * 4 + 4], "little")
                for slot in range(len(block) // 4)
            }
        self.predicates.byte_670 = phase1[1]
        self.predicates.blocks[0x671] = PascalSet.from_bytes(phase1[2:10])
        self.predicates.blocks[0x679] = PascalSet.from_bytes(phase1[10:18])
        self.runtime_records.populate_from_phase6_payloads(
            self.activation.phase6_records
        )
        # sub_11C6 (1290..12BC): a person whose +1Ch is not 1 is described
        # already and joins 1AB8 -- after a restore The Mist's greeting
        # lists Mrs. Carmody without her description (native, 2026-10-18).
        for record in self.runtime_records.records:
            if len(record.raw) > 0x1C and record.raw[0x1C] != 1:
                self.set_1ab8.add(record.index)
        phase7 = AsgPhase7Evaluator(self.predicates)
        self.phase7_runtime = {
            node.index: bytearray(node.raw) for node in self.activation.phase7_nodes
        }
        # Native ``sub_132B`` keeps the first type-1 image as slot 1, loads
        # the remaining images into slots 2..byte_19E9, then fills every
        # unused far-pointer slot through 63 with an alias of slot 1
        # (loc_179B..17F0).  These are real, addressable descriptor cursors:
        # MESSAGE continuations can select e.g. slot 57.  Preserve pointer
        # aliasing rather than manufacturing independent zero records.
        default_phase7 = self.phase7_runtime.get(1)
        if default_phase7 is not None:
            for index in range(self.activation.byte_19e9 + 1, 0x40):
                self.phase7_runtime[index] = default_phase7
        phase7.apply_nodes(
            self.activation.phase7_nodes,
            runtime_rule_sets=AsgPerTurnDispatcher.runtime_rule_sets(
                self.runtime_records, self.activation.word_19e7
            ),
        )
        # sub_133A adds to the linked node's own set (+0..7) through its far
        # pointer: the dome's image holds the tape on its green chip.
        for index, members in phase7.node_sets.items():
            raw = self.phase7_runtime.get(index)
            if raw is not None and index <= self.activation.byte_19e9:
                raw[0:8] = members.to_bytes()
        self.excluded_19ef = phase7.excluded_19ef
        self.auxiliary_4ab6 = phase7.auxiliary_4ab6
        # DS:5B0 is a mutable far-pointer table.  In particular sub_9FBC
        # rewrites byte +0Eh of the selected Phase-9 image.
        self.phase9_runtime = [
            bytearray(record) for record in self.activation.phase9_records
        ]
        # Rebuild from immutable phase-8 images so reactivation is idempotent.
        self.graph = AsgActivationRuntime.from_tables(self.activation)
        self.graph.apply_phase9(self.activation.phase9_records)
        self.rewire_rooms_4acd = PascalSet.empty(15)
        for native_id, room in enumerate(self.graph.rooms, start=1):
            if native_id < 2:
                continue
            direction_mask = room[0x10]
            if any(
                direction_mask & (1 << direction) and room[0x04 + direction] == 1
                for direction in range(6)
            ):
                self.rewire_rooms_4acd.add(native_id)
        self.activated = True

    def configure_vocab(self, entries: list[VocabEntry]) -> None:
        self.vocab_nodes = RuntimeVocabNodeTable.from_entries(entries)

    def direction_target(self, native_room_id: int, direction: int) -> int | None:
        return self.graph.direction_target(native_room_id, direction)

    @property
    def initial_native_room_id(self) -> int:
        return self.activation.initial_native_room_id

    def direction_available(self, native_room_id: int, direction: int) -> bool:
        target = self.direction_target(native_room_id, direction)
        if target is None:
            return False
        # GAME.000:218d reads the *live* in-memory record -- the same image
        # OPEN/CLOSE write (sub_E048) -- so an opened door becomes passable
        # the moment it is opened. byte_1AEC = (+24h == 0) is "blocked".
        record = self.graph.room(target)
        if record is None or len(record) <= 0x24:
            return False
        # Only a passage (+23h) can be shut: Voodoo Island's rooms carry
        # +24h = 0 (the other titles' rooms 1), and they are walked into all
        # the same (sub_95F9 tests +23h before +24h).
        return record[0x23] == 0 or record[0x24] != 0

    def road_available(self, native_room_id: int, direction: int) -> bool:
        """Exit test for driving/flying the vehicle scene's scenery cursor.

        Driving moves byte_1AE5 over road rooms only. In the chase, the exits
        that point at a scenery record -- the DB5 itself (record 21) from
        scenery 15 -- are the "You can't drive in that direction, 007."
        directions (oracle-measured). That record's +24h is the *car door's*
        state, so the on-foot gate (:meth:`direction_available`, 218d) would
        call it passable. The native drive routine has not been traced; this
        keeps the measured behaviour: a road exit must lead to a non-scenery
        record.
        """

        target = self.direction_target(native_room_id, direction)
        if target is None:
            return False
        record = self.graph.room(target)
        return record is not None and len(record) > 0x23 and record[0x23] == 0

    def select_context_set_response(self, native_room_id: int) -> int | None:
        context = self.graph.room(native_room_id)
        if context is None:
            return None
        # The people present (room +14, four bytes) index the DS:0438 table;
        # in the chase that is Tilly (438[3]), who answers a blocked move.
        return self.action_state.select_context_set_response(
            context,
            tuple(record.raw for record in self.runtime_records.records),
            set_offset=0x14,
            set_size=4,
        )

    def mark_visited(self, native_room_id: int) -> None:
        AsgPerTurnDispatcher.mark_visited(
            native_room_id, self.activation.room_records, self.table_state
        )

    @property
    def actions(self) -> AsgActionExecutor:
        return AsgActionExecutor(
            self.table_state,
            self.action_state,
            self.predicates,
            self.auxiliary_4ab6,
        )
