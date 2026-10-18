"""Shared ASG per-turn dispatcher primitives.

This module ports GAME.000's ``sub_1DEB`` record loop: the rule frames, the
per-turn set transfers (``1F62..2019``) and the six-direction room pass.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .runtime_records import RuntimeRecord, RuntimeRecordArray
from .tables import TableRecord, TableRuntimeState
from .pascal_set import PascalSet


RUNTIME_RULE_SET_OFFSET = 0x0C
RUNTIME_RULE_SET_SIZE = 8
# The room image's +18h set; a TABLES record carries the family byte in
# front of that image, so in record coordinates it sits at +19h. (Reading
# +18h took the set one byte early -- every member 8 higher. Goldfinger's
# people never take part in the transfer, +17h = 99; A View to a Kill's do.)
TABLE_CONTEXT_SET_OFFSET = 0x19
TABLE_CONTEXT_SET_SIZE = 8


@dataclass(frozen=True)
class DispatcherRuleFrame:
    """Inputs prepared for one active rule at GAME.000:1F62..2019."""

    runtime_record: RuntimeRecord
    linked_record: TableRecord | None
    rule_set: bytes
    context_set: bytes


@dataclass(frozen=True)
class DispatcherTransferResult:
    """State produced by one confirmed ``1F62..2019`` transfer."""

    work_set: PascalSet
    runtime_rule_set: PascalSet
    linked_context_set: PascalSet


class AsgPerTurnDispatcher:
    """Engine-family implementation of the confirmed per-turn rule prelude."""

    @staticmethod
    def prepare_rule_frames(
        runtime_records: RuntimeRecordArray,
        loop_limit: int,
        pointer_table: tuple[TableRecord, ...],
        table_state: TableRuntimeState | None = None,
    ) -> tuple[DispatcherRuleFrame, ...]:
        """Apply the native loop bounds/gate and prepare rule operands.

        Native slots 0 and 1 are bookkeeping.  ``loop_limit`` mirrors
        ``word_19E7`` and is inclusive.  For every active runtime record,
        ``+0x14`` selects a 1-based TABLES pointer and the two 8-byte operands
        are exposed without assigning unverified semantics to their contents.
        """

        if loop_limit < 2:
            return ()
        frames: list[DispatcherRuleFrame] = []
        stop = min(loop_limit + 1, len(runtime_records))
        for slot in range(2, stop):
            runtime = runtime_records.get(slot)
            if runtime is None or not runtime.is_active:
                continue
            native_link = runtime.linked_native_id
            linked = (
                pointer_table[native_link - 1]
                if 1 <= native_link <= len(pointer_table)
                else None
            )
            context = b"\x00" * TABLE_CONTEXT_SET_SIZE
            if linked is not None:
                context = (
                    table_state.read_bytes(
                        linked, TABLE_CONTEXT_SET_OFFSET, TABLE_CONTEXT_SET_SIZE
                    )
                    if table_state is not None
                    else linked.raw[
                        TABLE_CONTEXT_SET_OFFSET:
                        TABLE_CONTEXT_SET_OFFSET + TABLE_CONTEXT_SET_SIZE
                    ]
                )
            frames.append(
                DispatcherRuleFrame(
                    runtime_record=runtime,
                    linked_record=linked,
                    rule_set=runtime.raw[
                        RUNTIME_RULE_SET_OFFSET:
                        RUNTIME_RULE_SET_OFFSET + RUNTIME_RULE_SET_SIZE
                    ],
                    context_set=context,
                )
            )
        return tuple(frames)

    @staticmethod
    def runtime_rule_sets(
        runtime_records: RuntimeRecordArray,
        loop_limit: int,
    ) -> dict[int, PascalSet]:
        """Expose slot -> runtime `+0x0C..13` sets for phase-7 type 2."""
        result: dict[int, PascalSet] = {}
        stop = min(loop_limit + 1, len(runtime_records))
        for slot in range(1, stop):
            record = runtime_records.get(slot)
            if record is None:
                continue
            result[slot] = PascalSet.from_bytes(
                record.raw[
                    RUNTIME_RULE_SET_OFFSET:
                    RUNTIME_RULE_SET_OFFSET + RUNTIME_RULE_SET_SIZE
                ]
            )
        return result

    @staticmethod
    def transfer_frame(
        frame: DispatcherRuleFrame,
        excluded_19ef: PascalSet,
        excluded_6a1: PascalSet,
        on_effect: "Callable[[PascalSet], None] | None" = None,
    ) -> DispatcherTransferResult:
        """Execute the native set transfer at ``GAME.000:1F62..2019``.

        Cross-game opcode alignment identifies the two adjacent TP3 set
        helpers: the Phase-7 add-element paths establish ``B710`` as union;
        ``B71E`` is the difference entry used three times here.
        """
        context = PascalSet.from_bytes(frame.context_set)
        work = context.difference(excluded_19ef).difference(excluded_6a1)
        if on_effect is not None:
            on_effect(work)
        runtime = PascalSet.from_bytes(frame.rule_set).union(work)
        linked = context.difference(work)
        return DispatcherTransferResult(work, runtime, linked)

    @classmethod
    def execute_transfers(
        cls,
        runtime_records: RuntimeRecordArray,
        loop_limit: int,
        pointer_table: tuple[TableRecord, ...],
        table_state: TableRuntimeState,
        excluded_19ef: PascalSet,
        excluded_6a1: PascalSet,
        on_effect: "Callable[[DispatcherRuleFrame, PascalSet], None] | None" = None,
    ) -> tuple[DispatcherTransferResult, ...]:
        """Execute and persist every active per-turn set transfer."""
        frames = cls.prepare_rule_frames(
            runtime_records, loop_limit, pointer_table, table_state
        )
        results: list[DispatcherTransferResult] = []
        for frame in frames:
            result = cls.transfer_frame(
                frame, excluded_19ef, excluded_6a1,
                None if on_effect is None else lambda work, f=frame: on_effect(f, work),
            )
            runtime_records.replace(
                frame.runtime_record.index,
                frame.runtime_record.with_rule_set(result.runtime_rule_set.to_bytes()),
            )
            if frame.linked_record is not None:
                table_state.write_bytes(
                    frame.linked_record,
                    TABLE_CONTEXT_SET_OFFSET,
                    result.linked_context_set.to_bytes(),
                )
            results.append(result)
        return tuple(results)

    @staticmethod
    def direction_matrix(
        pointer_table: tuple[TableRecord, ...],
        table_state: TableRuntimeState,
    ) -> dict[int, tuple[bool, bool, bool, bool, bool, bool]]:
        """Execute the six-slot room pass following the set transfers.

        Native room ids are 1-based. A slot id of 0/1 is blocked; otherwise
        target ``+24h == 0`` makes that direction available.
        """
        matrix: dict[int, tuple[bool, bool, bool, bool, bool, bool]] = {}
        for native_id, record in enumerate(pointer_table, start=1):
            available: list[bool] = []
            for target_id in record.native_direction_slots():
                if target_id <= 1 or target_id > len(pointer_table):
                    available.append(False)
                    continue
                available.append(
                    table_state.native_entry_allowed(pointer_table[target_id - 1])
                )
            matrix[native_id] = tuple(available)  # type: ignore[assignment]
        return matrix

    @staticmethod
    def mark_visited(
        native_room_id: int,
        pointer_table: tuple[TableRecord, ...],
        table_state: TableRuntimeState,
    ) -> None:
        """Port the tail write at ``21C3..21E1`` (id 1 is sentinel)."""
        if 1 < native_room_id <= len(pointer_table):
            table_state.mark_visited(pointer_table[native_room_id - 1])
