"""Shared primitive effects from the GAME.000 action-opcode dispatcher."""

from __future__ import annotations

from dataclasses import dataclass, field

from .tables import TableRecord, TableRuntimeState
from .predicates import AsgPredicateState
from .pascal_set import PascalSet


@dataclass
class AsgActionState:
    section_state: int = 0
    flag_4bcb: int = 0
    flag_4bcc: int = 0
    flag_1df7: int = 0
    byte_1a4c: int = 0
    byte_1a4d: int = 0
    byte_1a4e: int = 0
    byte_1a4f: int = 0
    byte_1a50: int = 0
    byte_1a51: int = 0
    byte_1a52: int = 0
    byte_1a53: int = 0
    block_1a44: bytes = bytes(8)
    byte_4add: int = 0
    byte_4ade: int = 0
    byte_4b7b: int = 0
    byte_1ab5: int = 0
    byte_1ab6: int = 0
    byte_1ab7: int = 0
    byte_1aeb: int = 0
    # The person the people update left in the player's room (1 = none).
    byte_4b62: int = 1
    byte_1aed: int = 0
    byte_1aee: int = 0
    byte_1aef: int = 0
    byte_1af0: int = 0
    byte_1af1: int = 0
    byte_1a8a: int = 0
    byte_1aec: int = 0
    byte_1ae3: int = 0
    byte_1ae4: int = 0
    byte_1ae5: int = 0
    byte_1a56: int = 0
    # The referent (67b6 / sub_3472): what the last sentence or display was
    # about -- 1A56 its kind, word 1A57 its index, 1A54 the move it was set.
    byte_1a57: int = 0
    word_1a54: int = 0
    byte_1a48: int = 0
    byte_1a59: int = 0
    byte_1a5a: int = 12
    byte_1a5b: int = 0
    byte_1a5c: int = 1
    word_1a5d: int = 0
    byte_4adc: int = 0
    last_target_room_value: int = 0
    word_6ad: int = 0
    byte_4adf: int = 0
    byte_4b7d: int = 0
    word_4b12: int = 0
    word_4b7f: int = 0
    byte_1b45: int = 0
    local_record_gates: tuple[int, ...] = (0,) * 8
    record_work_blocks: dict[int, bytes] = field(default_factory=dict)

    def load_phase4(self, phase4: bytes) -> None:
        """Load the action-visible subset of activation phase 4."""

        if len(phase4) < 14:
            raise ValueError("phase4 block must contain 14 bytes")
        self.byte_1aeb = phase4[7]
        self.byte_1aed = phase4[9]
        self.byte_1aee = phase4[10]
        self.byte_1aef = phase4[11]
        self.byte_1af0 = phase4[12]
        self.byte_1af1 = phase4[13]

    def initialize_dispatch_cursors(
        self,
        *,
        word_6ab: int = 0,
        word_1a54: int = 0,
    ) -> None:
        """Port complete ``sub_7BB7`` top-level MESSAGE-open reset.

        Its first statement is ``1A44 := 1A4C`` (8 bytes, destination pushed
        first): the previous record's cursors are kept for sub_35FB, not
        loaded. 1A51 -- the selected vehicle -- survives while the player
        sits in a closed one (1AEC == 1); measured 2 throughout the chase.
        """

        self.block_1a44 = bytes((
            self.byte_1a4c, self.byte_1a4d, self.byte_1a4e, self.byte_1a4f,
            self.byte_1a50, self.byte_1a51, self.byte_1a52, self.byte_1a53 & 0xFF,
        ))
        self.byte_1a4c = 1
        self.byte_1a4d = 1
        self.byte_1a4e = 1
        self.byte_1a4f = 1
        self.byte_1a50 = 1
        self.byte_1a52 = 1
        self.section_state = 0x0B
        if self.byte_1aec != 1:
            self.byte_1a51 = 1
        if (word_6ab & 0xFFFF) > ((word_1a54 + 2) & 0xFFFF):
            self.byte_1a56 = 6

        block_sizes = {
            0x4A58: 0x20, 0x4A78: 0x08, 0x49E0: 0x20,
            0x4A00: 0x08, 0x4A08: 0x20, 0x4A28: 0x08,
            # msg_ctrl_star mode 1 passes 0x28 bytes from 4AE9 to the
            # descriptor-membership helper (overlay loc_AAF).
            0x4A30: 0x20, 0x4A50: 0x08, 0x4AE9: 0x28,
            0x4B09: 0x08, 0x4AE2: 0x07, 0x4B73: 0x08,
            0x4B81: 0x08, 0x4B89: 0x04, 0x4B8D: 0x0F,
            0x4B9C: 0x02, 0x4B9E: 0x08, 0x4BA6: 0x0F,
            0x4BB5: 0x01,
        }
        self.record_work_blocks = {
            address: bytes(size) for address, size in block_sizes.items()
        }
        self.byte_4adc = 1
        self.byte_4add = 1
        self.byte_4ade = 1
        self.byte_4adf = 1
        self.word_4b12 = 0
        self.local_record_gates = (1,) * 8
        self.byte_4b7d = 1

    def seed_message_work_scratch(
        self,
        *,
        command_node: int,
        room_context: bytes | bytearray | None,
        vocab_raw_by_node: tuple[bytes, ...],
        predicates: AsgPredicateState,
    ) -> None:
        """Port ``sub_7DAC``'s ``loc_3C36`` scratch build into ``4B73``.

        Native sequence: command-node bytes from table ``6B2``, union carried
        set ``0671``, union current-room ``+18``, union ``0679``, then subtract
        ``0691``. Opcode ``46h`` tests ``byte_1A4C`` membership in this bank.
        """

        if 0 < command_node < len(vocab_raw_by_node):
            seed = vocab_raw_by_node[command_node].ljust(8, b"\x00")[:8]
            scratch = PascalSet.from_bytes(seed)
        else:
            scratch = PascalSet.empty(8)
        scratch = scratch.union(predicates.blocks[0x671])
        if room_context is not None and len(room_context) >= 0x20:
            scratch = scratch.union(
                PascalSet.from_bytes(room_context[0x18:0x20])
            )
        scratch = (
            scratch.union(predicates.blocks[0x679])
            .difference(predicates.blocks[0x691])
        )
        self.record_work_blocks[0x4B73] = scratch.to_bytes()

    def route_record_gate(self, value: int) -> None:
        """Port ``sub_7DB8``'s two-stage local `-2C/-2D` gate write."""

        gates = list(self.local_record_gates)
        target = 4 if gates[4] == 1 else 5
        gates[target] = value & 0xFF
        self.local_record_gates = tuple(gates)

    def evaluate_sub_4c44_prefix(
        self,
        descriptor: bytes | bytearray,
        *,
        phase9_records: tuple[bytes, ...] = (),
        current_room: int | None = None,
    ) -> bool | None:
        """Execute confirmed `sub_4C44..4D40` state/response selection."""

        if len(descriptor) <= 9:
            return None
        self.byte_1a52 = descriptor[9] if descriptor[8] == 2 else 1
        if self.byte_1a51 == self.local_record_gates[1]:
            self.byte_4adf = self.local_record_gates[0]
        if self.section_state == 7:
            return True
        if self.byte_1b45:
            self.section_state = 5
            return None
        selected = self.byte_1a51
        if not 1 <= selected <= len(phase9_records):
            return None
        record = phase9_records[selected - 1]
        # DS:5B0 points at the copied payload (TABLES type byte omitted), so
        # native pointer offsets remain payload offsets +0E/+2.
        if current_room is not None and len(record) > 0x0E and record[0x0E] != current_room:
            if len(phase9_records) < 2:
                return None
            record = phase9_records[1]  # native fallback pointer at DS:5B4
        if len(record) < 3:
            return None
        self.word_4b7f = record[2] | (record[3] << 8)
        self.section_state = 2
        return None

    def select_sub_3870_response(
        self,
        context_record: bytes | bytearray,
        runtime_records: tuple[bytes, ...],
    ) -> int | None:
        """Port the candidate-set selector in native ``sub_3870``.

        ``context_record`` is the in-memory room image (no TABLES type
        byte), the same layout the native reads: its people set is
        ``+14h..+17h`` (IDA 3895, ``add di, 14h``). Phase-6 records (the
        people table DS:0438) contribute their response word at ``+0A``.
        With nobody in the room record 1 answers -- Goldfinger's 6563, the
        talk record ("You're talking to air", the Auric Stud password).
        """

        if len(context_record) < 0x18:
            return None
        candidates = PascalSet.from_bytes(bytes(context_record[0x14:0x18]))
        selected = self.byte_1a50
        if selected not in candidates:
            selected = 1
        if selected == 1:
            values = candidates.values()
            if values:
                if self.byte_1a56 == 1 and self.byte_1a57 in candidates:
                    selected = self.byte_1a57
                elif self.byte_1a48 in candidates:
                    selected = self.byte_1a48
                else:
                    selected = next((value for value in values if value >= 1), 1)
        self.byte_1a50 = selected
        if not 0 <= selected < len(runtime_records):
            return None
        record = runtime_records[selected]
        if len(record) < 0x0C:
            return None
        self.word_4b7f = record[0x0A] | (record[0x0B] << 8)
        return self.word_4b7f

    def select_context_set_response(
        self,
        context_record: bytes | bytearray,
        runtime_records: tuple[bytes, ...],
        *,
        set_offset: int = 0x18,
        set_size: int = 8,
    ) -> int | None:
        """Select a runtime response from a context-record set.

        Several dispatcher paths use a room/context set to select a runtime
        record, then leave that runtime record's response word (`+0A`) in
        `word_4B7F`.  This is the data-side core: read the set, choose the
        first in-range non-sentinel runtime slot, and copy its response word.
        """

        if len(context_record) < set_offset + set_size:
            return None
        candidates = PascalSet.from_bytes(
            bytes(context_record[set_offset : set_offset + set_size])
        )
        for selected in candidates.values():
            if selected <= 1 or not 0 <= selected < len(runtime_records):
                continue
            record = runtime_records[selected]
            if len(record) < 0x0C:
                continue
            value = record[0x0A] | (record[0x0B] << 8)
            if value == 0:
                continue
            self.byte_1a50 = selected
            self.word_4b7f = value
            return value
        return None

    def advance_native_clock(self, amount: int) -> None:
        """Port ``sub_98FB`` calendar/clock arithmetic (EF31 opcode 49h)."""

        amount &= 0xFFFF
        week = 7 * 24 * 60
        self.word_1a5d = (self.word_1a5d + amount) % 0x10000
        hour = self.byte_1a5a
        if self.byte_1a5c:
            hour24 = 0 if hour == 12 else hour
        else:
            hour24 = 12 if hour == 12 else hour + 12
        total = (
            (self.byte_1a59 * 24 + hour24) * 60
            + self.byte_1a5b
            + amount
        ) % week
        self.byte_1a5b = total % 60
        total_hours = total // 60
        self.byte_1a59 = (total_hours // 24) % 7
        hour24 = total_hours % 24
        if hour24 < 12:
            self.byte_1a5c = 1
        else:
            hour24 -= 12
            self.byte_1a5c = 0
        self.byte_1a5a = 12 if hour24 == 0 else hour24


@dataclass
class AsgActionExecutor:
    table_state: TableRuntimeState
    state: AsgActionState
    predicates: AsgPredicateState | None = None
    auxiliary_4ab6: PascalSet | None = None

    def adjust_native_field(
        self,
        record: TableRecord | None,
        field_operand: int,
        amount: int,
        *,
        subtract: bool = False,
    ) -> int:
        """Port `sub_BF6B`: add or saturating-subtract a selected field."""
        current = self.table_state.read_native_field(record, field_operand)
        value = max(0, current - amount) if subtract else current + amount
        value = min(value, 0xFFFF)
        self.table_state.write_native_field(record, field_operand, value)
        return value

    def execute_direct(
        self,
        opcode: int,
        *,
        record: TableRecord | None = None,
        field_operand: int | None = None,
        amount: int = 1,
        random_value: int | None = None,
    ) -> int | None:
        """Execute action opcodes whose effects are fully decoded.

        5Ah/5Bh select the add/subtract modes 5Ch/5Dh with amount one.
        5Ch/5Dh use the supplied computed amount. 3Dh/3Eh/3Fh are direct
        global flag writes in `sub_EF31`.
        """
        if opcode in (0x5A, 0x5B, 0x5C, 0x5D):
            if field_operand is None:
                return None
            # Operands 0..5 address the active record (except global 1AE8 at
            # slot 5); operands >=6 address the shared VM arrays and do not
            # require a TABLES record pointer.
            if record is None and field_operand < 5:
                return None
            return self.adjust_native_field(
                record,
                field_operand,
                1 if opcode in (0x5A, 0x5B) else amount,
                subtract=opcode in (0x5B, 0x5D),
            )
        if opcode == 0x3D:
            self.state.section_state = 1
            return 1
        if opcode == 0x3E:
            self.state.flag_4bcb = 1
            return 1
        if opcode == 0x3F:
            self.state.flag_4bcc = 1
            return 1
        if opcode == 0x48:
            if self.predicates is None or random_value is None:
                return None
            element = random_value % 6
            self.predicates.byte_670 |= 1 << element
            return element
        if opcode == 0x55:
            self.state.flag_1df7 ^= 1
            return self.state.flag_1df7
        if opcode == 0x4A:
            if field_operand is None:
                return None
            index = field_operand - 0x10
            self.table_state.write_array_1a5f_secondary(index, amount)
            return amount & 0xFFFF
        if opcode in (0x4C, 0x4D):
            if field_operand is None:
                return None
            # GAME.000:EF343..F3C5 calls sub_BED2, subtracts 0x10 from the
            # operand, then toggles the sign of DS:1A5F[index]. Opcode 4Ch
            # forces the selected word negative when currently positive; 4Dh
            # forces it positive when currently negative.
            index = field_operand - 0x10
            current = self.table_state.read_array_1a5f_signed(index)
            if opcode == 0x4C and current > 0:
                current = -current
                self.table_state.write_array_1a5f_signed(index, current)
            elif opcode == 0x4D and current < 0:
                current = -current
                self.table_state.write_array_1a5f_signed(index, current)
            return current
        return None

    def execute_advance_phase7_cursor(
        self,
        *,
        cursor: int,
        phase7_runtime: dict[int, bytes],
        max_slot: int,
    ) -> int | None:
        """Port action opcode 0x51 (`sub_ACB6` -> `sub_ABE0`).

        Disassembly-confirmed (`goldfinger_overlay.asm`, live address
        `0815:75CC` via the shift formula): `sub_ACB6` reads the current
        `byte_1A4C` cursor and replaces it with `sub_ABE0(cursor)`'s
        result. `sub_ABE0` repeatedly advances the cursor (wrapping from
        `byte_19E9` back to `2`) while the `sub_4C44`/`sub_4CA8` shared
        tail's `byte_4B11==7` (`section_state`) test fails, then -- once
        that test passes -- looks up the Phase-7 node at the final cursor
        (same `DS:0x04B4` table `$k`/`$l`/`$m`/`$p` already read) and, if
        that node's `+0x18` byte (`node[0x18]`) is `3` (a "redirect"
        marker), recurses using the new cursor as the next starting
        point. Finally writes `byte_1A4C`/`byte_1A4D` and sets
        `byte_4B7B` to whether the cursor actually changed.

        **Not modeled** (unconfirmed): each retry iteration in the native
        code also re-runs `sub_4B93`'s gate routing (`byte_1A51` vs.
        `local_record_gates[1]`), which the disassembly shows is ALSO
        part of the exit condition in principle, but this port could not
        confirm whether/how it changes `section_state` itself -- without
        that, a literal retry-forever port could hang if `section_state`
        never reaches 7 by chance. So the retry loop here is bounded at
        `max_slot` iterations; if `section_state` isn't already 7 within
        that bound, this returns ``None`` (stays unresolved) rather than
        guessing. This is confirmed to cover the common case where
        `section_state` is already 7 when this opcode runs (the loop
        exits on the first check, no retries needed).
        """

        return self._advance_phase7_cursor(
            cursor=cursor,
            phase7_runtime=phase7_runtime,
            max_slot=max_slot,
            original=cursor,
            visited=set(),
        )

    def _advance_phase7_cursor(
        self,
        *,
        cursor: int,
        phase7_runtime: dict[int, bytes],
        max_slot: int,
        original: int,
        visited: set[int],
    ) -> int | None:
        if max_slot <= 0:
            return None
        next_cursor = cursor
        for _ in range(max_slot):
            if self.state.section_state == 7:
                break
            next_cursor = 2 if next_cursor == max_slot else next_cursor + 1
        else:
            return None
        node = phase7_runtime.get(next_cursor)
        if node is not None and len(node) > 0x18 and node[0x18] == 3:
            # A literal port would recurse using this same cursor as the
            # next starting point (confirmed from the disassembly), but
            # since `section_state` is loop-invariant in this port (see
            # the docstring), a node that redirects to itself would
            # recurse forever. Not confirmed whether real game data ever
            # hits this; guard against it rather than crash.
            if next_cursor in visited:
                return None
            visited.add(next_cursor)
            redirected = self._advance_phase7_cursor(
                cursor=next_cursor,
                phase7_runtime=phase7_runtime,
                max_slot=max_slot,
                original=original,
                visited=visited,
            )
            if redirected is None:
                return None
            next_cursor = redirected
        self.state.byte_1a4c = next_cursor
        self.state.byte_1a4d = next_cursor
        self.state.byte_4b7b = 1 if next_cursor != original else 0
        return next_cursor

    def execute_set_action(
        self,
        opcode: int,
        *,
        cursor: int,
        node: bytes,
        confirmed: bool = True,
        room_context: bytearray | None = None,
        nodes: "dict[int, bytearray] | None" = None,
    ) -> bool | None:
        """Port confirmed set-mutating handlers A49C/A56A/A099/A3C8.

        Each of these is also, structurally, one of the tiny action-VM
        programs a `(` composite-label span can encode (`msg_ctrl_section`
        falls through directly into `sub_EF31`). The disassembled bodies of
        `sub_A099`/opcode 0x34 and `sub_A3C8`/opcode 0x35 both write
        `byte_4B7B` from their success/failure result before returning, so
        the boolean this function returns is also that render/skip flag --
        set it on `self.state` so callers reached through the `(` path can
        read it via `AsgActionExecutor`'s gate accessor.
        """
        if opcode not in (0x32, 0x33, 0x34, 0x35) or self.predicates is None:
            return None
        if len(node) <= 0x18:
            self.state.byte_4b7b = 0
            return False
        values = PascalSet.from_bytes(node[0:8]).union(
            PascalSet.from_values([cursor], 8)
        )
        if opcode == 0x32:
            # sub_A49C, loc_A4C9: the gate is the node's container link
            # `+17h` (`cmp ax, 1`), not its type byte `+18h` -- the lighter's
            # +18h is 4, so the wrong field refused to take it out of the
            # pocket at walkthrough turn 41.
            if cursor not in self.predicates.blocks[0x679] or node[0x17] != 1:
                self.state.byte_4b7b = 0
                return False
            self.state.word_6ad += 1
            self.predicates.blocks[0x671] = self.predicates.blocks[0x671].union(values)
            self.predicates.blocks[0x679] = self.predicates.blocks[0x679].difference(values)
            self.state.byte_4b7b = 1
            return True
        if opcode == 0x34:
            return self._execute_take_action(cursor, node, room_context, nodes)
        if opcode == 0x33:
            return self._execute_drop_action(cursor, node, room_context)
        selectable = self.predicates.blocks[0x671].difference(
            self.predicates.blocks[0x699]
        )
        if not confirmed or len(selectable) == 0:
            self.state.byte_4b7b = 0
            return False
        self.state.word_6ad -= 1
        self.predicates.blocks[0x671] = self.predicates.blocks[0x671].difference(values)
        # 35h / A3C8
        self.predicates.blocks[0x679] = self.predicates.blocks[0x679].union(values)
        self.state.byte_4b7b = 1
        return True

    def _execute_take_action(
        self,
        cursor: int,
        node: bytes | bytearray,
        room_context: bytearray | None,
        nodes: "dict[int, bytearray] | None",
    ) -> bool:
        """Port opcode 34h, ``sub_A099 -> sub_A221/sub_A2F4``.

        ``room_context`` is the current room, ``025C[byte_6A9]``. The
        candidate set ``4B73 = (room+18 | 0671 | 0679) - 0691`` must hold the
        object: the call after ``push [19C7]`` (IDA 9642, an overlay-group-9
        address; runtime 0876:5F58) tests ``byte_1A4C in 4B73`` -- stepped
        live 2026-10-15 at TAKE BADGE (1A4C = 13, [19C7] = 6 is only its
        argument). The
        object and its contents move into ``0671``, leave the room, ``0679``
        and ``06A1``, and a contained object leaves its container chain
        (``sub_A0A5``): its link ``+17`` becomes 1 and it leaves ``0699``.
        """

        self.state.byte_4b7b = 0
        if room_context is None or len(room_context) < 0x20:
            return False
        context = PascalSet.from_bytes(bytes(room_context[0x18:0x20]))
        candidate = (
            context
            .union(self.predicates.blocks[0x671])
            .union(self.predicates.blocks[0x679])
            .difference(self.predicates.blocks[0x691])
        )
        self.state.record_work_blocks[0x4B73] = candidate.to_bytes()
        if cursor not in candidate:
            return False
        self.state.byte_4b7b = 1
        values = PascalSet.from_bytes(bytes(node[0:8])).union(
            PascalSet.from_values([cursor], 8)
        )
        self.state.word_6ad += 1
        self.predicates.blocks[0x671] = self.predicates.blocks[0x671].union(values)
        room_context[0x18:0x20] = context.difference(values).to_bytes()
        self.predicates.blocks[0x6A1].discard(cursor)
        self.predicates.blocks[0x679] = self.predicates.blocks[0x679].difference(values)
        link = node[0x17]
        if link != 1:
            if nodes is not None:
                self._detach_from_container(link, values, nodes)
            if isinstance(node, bytearray):
                node[0x17] = 1
            self.predicates.blocks[0x699].discard(cursor)
        return True

    def _detach_from_container(
        self, container: int, values: PascalSet, nodes: "dict[int, bytearray]"
    ) -> None:
        """Port ``sub_A0A5`` (first container) and ``sub_A0B4`` (its chain)."""

        first = True
        seen: set[int] = set()
        while container != 1 and container not in seen:
            seen.add(container)
            record = nodes.get(container)
            if record is None or len(record) <= 0x18:
                return
            remaining = PascalSet.from_bytes(bytes(record[0:8])).difference(values)
            record[0:8] = remaining.to_bytes()
            if first and record[0x18] == 2 and len(remaining) == 0:
                for address in (0x689, 0x691, 0x6A1):
                    self.predicates.blocks[address].discard(container)
            first = False
            container = record[0x17]

    def _execute_drop_action(
        self,
        cursor: int,
        node: bytes | bytearray,
        room_context: bytearray | None,
    ) -> bool:
        """Port opcode 33h, ``sub_A56A``.

        ``4B73 = 0671 - 0699`` must hold the object (the same IDA 9642
        test of ``byte_1A4C``, called with [19D1]), and it must not be inside a
        container (``+17 == 1``). It and its contents leave ``0671`` and join
        the current room ``025C[byte_6A9]``.
        """

        self.state.byte_4b7b = 0
        candidate = self.predicates.blocks[0x671].difference(self.predicates.blocks[0x699])
        self.state.record_work_blocks[0x4B73] = candidate.to_bytes()
        if cursor not in candidate or node[0x17] != 1:
            return False
        self.state.byte_4b7b = 1
        values = PascalSet.from_bytes(bytes(node[0:8])).union(
            PascalSet.from_values([cursor], 8)
        )
        self.predicates.blocks[0x671] = self.predicates.blocks[0x671].difference(values)
        self.state.word_6ad -= 1
        if room_context is not None and len(room_context) >= 0x20:
            context = PascalSet.from_bytes(bytes(room_context[0x18:0x20])).union(values)
            room_context[0x18:0x20] = context.to_bytes()
        return True

    def execute_context_transfer_action(
        self,
        *,
        nodes: dict[int, bytearray],
        current_room_context: bytearray,
    ) -> bool:
        """Port the set/link transfer performed by EF31 opcode ``46h``.

        This is native ``sub_E55B/sub_E5EF``: cursors ``1A4C`` and ``1A4F``
        select Phase-7 nodes, a work set is assembled from the current room,
        scratch ``4B73`` and predicate banks, linked nodes are folded into it,
        and ownership is transferred between the predicate/room sets.
        """

        self.state.byte_4b7b = 0
        if self.predicates is None or len(current_room_context) < 0x20:
            return False
        cursor = self.state.byte_1a4c
        target = self.state.byte_1a4f
        source_node = nodes.get(cursor)
        target_node = nodes.get(target)
        if source_node is None or target_node is None:
            return False
        if len(source_node) < 0x1C or len(target_node) < 0x1C:
            return False

        scratch = PascalSet.from_bytes(
            self.state.record_work_blocks.get(0x4B73, bytes(8))[:8]
        )
        room_set = PascalSet.from_bytes(bytes(current_room_context[0x18:0x20]))
        work = (
            room_set.union(scratch)
            .union(self.predicates.blocks[0x679])
            .difference(self.predicates.blocks[0x681])
        )
        if cursor not in scratch.difference(self.predicates.blocks[0x699]):
            return False
        if target not in work:
            return False
        if target_node[0x18] not in (0, 2) or target_node[0x1B] == 0:
            return False
        if target_node[0x0C] <= source_node[0x0C]:
            return False

        # E6E7: from here on the moved set is just the object and what it
        # holds; the reachability set above only gated the move.
        values = PascalSet.from_bytes(bytes(source_node[0:8])).union(
            PascalSet.from_values([cursor], 8)
        )
        target_node[0:8] = PascalSet.from_bytes(bytes(target_node[0:8])).union(values).to_bytes()
        self.predicates.blocks[0x6A1].add(cursor)
        # sub_E570: every container above the target holds them too.
        link = target_node[0x17]
        seen: set[int] = set()
        while link != 1 and link not in seen:
            seen.add(link)
            holder = nodes.get(link)
            if holder is None or len(holder) < 0x18:
                break
            holder[0:8] = PascalSet.from_bytes(bytes(holder[0:8])).union(values).to_bytes()
            link = holder[0x17]

        if target_node[0x18] == 2:
            for address in (0x689, 0x691, 0x6A1):
                self.predicates.blocks[address].add(target)
            if target in self.predicates.blocks[0x699]:
                self.predicates.blocks[0x699] = self.predicates.blocks[0x699].union(values)
        else:
            self.predicates.blocks[0x699] = self.predicates.blocks[0x699].union(values)

        if cursor in self.predicates.blocks[0x671]:
            self.state.word_6ad -= 1
            self.predicates.blocks[0x671] = self.predicates.blocks[0x671].difference(values)
        else:
            self.predicates.blocks[0x679] = self.predicates.blocks[0x679].difference(values)
            current_room_context[0x18:0x20] = room_set.difference(values).to_bytes()

        live_room = PascalSet.from_bytes(bytes(current_room_context[0x18:0x20]))
        if target in live_room:
            current_room_context[0x18:0x20] = live_room.union(values).to_bytes()
        elif target in self.predicates.blocks[0x671]:
            self.predicates.blocks[0x671] = self.predicates.blocks[0x671].union(values)
        elif target in self.predicates.blocks[0x679]:
            self.predicates.blocks[0x679] = self.predicates.blocks[0x679].union(values)

        source_node[0x17] = target
        self.state.byte_4b7b = 1
        return True

    def execute_room_state_action(
        self,
        opcode: int,
        *,
        target_context: bytearray,
        current_room: int | None = None,
        active_rooms: set[int] | None = None,
        phase9_records: tuple[bytes, ...] = (),
    ) -> bool:
        """Port the room-flag core of ``sub_E048/sub_E097``.

        Opcodes 44h/45h toggle room byte +24, while 39h/3Ah toggle +25.
        ``+23`` is the native eligibility gate. The 45h branch also restores
        ``1AEC`` and selects the matching kind-2 Phase-9 descriptor.
        """

        self.state.byte_4b7b = 0
        if opcode not in (0x39, 0x3A, 0x44, 0x45) or len(target_context) <= 0x25:
            return False
        if target_context[0x23] == 0:
            return False
        self.state.byte_4b7b = 1
        active = active_rooms is not None and current_room in active_rooms
        if opcode == 0x44:
            if target_context[0x24] or target_context[0x25]:
                self.state.byte_4b7b = 0
                return False
            target_context[0x24] = 1
            if active:
                self.state.byte_1aec = 0
            return True
        if opcode == 0x45:
            if target_context[0x24] == 0:
                self.state.byte_4b7b = 0
                return False
            target_context[0x24] = 0
            if active:
                self.state.byte_1aec = 1
                for index, record in enumerate(phase9_records, start=1):
                    if len(record) > 0x12 and record[0x11] == 2 and record[0x12] == current_room:
                        self.state.byte_1a51 = index
                        break
            return True
        if opcode == 0x39:
            if target_context[0x25]:
                self.state.byte_4b7b = 0
                return False
            target_context[0x25] = 1
            target_context[0x24] = 0
            return True
        if target_context[0x25] == 0:  # 3Ah
            self.state.byte_4b7b = 0
            return False
        target_context[0x25] = 0
        return True

    def _uncover(
        self,
        values: PascalSet,
        target_index: int,
        excluded_19ef: PascalSet | None,
        *,
        remove: bool,
    ) -> None:
        """OPEN/CLOSE bookkeeping on 0681, 0691 and (conditionally) 19EF."""

        for address in (0x681, 0x691):
            block = self.predicates.blocks[address]
            self.predicates.blocks[address] = (
                block.difference(values) if remove else block.union(values)
            )
        if excluded_19ef is not None and target_index in excluded_19ef:
            for value in values.values():
                if remove:
                    excluded_19ef.discard(value)
                else:
                    excluded_19ef.add(value)

    def execute_phase7_state_action(
        self,
        opcode: int,
        *,
        target_index: int,
        target_node: bytearray,
        current_room_context: bytes | bytearray,
        nodes: "dict[int, bytearray] | None" = None,
        excluded_19ef: PascalSet | None = None,
        phase7_count: int = 0,
    ) -> bool:
        """Port the ``sub_DCAD`` Phase-7 flag branches.

        OPEN (44h, DE1A..DEFF) also uncovers the contents: the node's set,
        minus what still sits in closed type-0 or in type-1 members
        (``sub_DCBF``), leaves ``0681`` and ``0691`` (and ``19EF`` when the
        opened node is in it). CLOSE (45h, DF39..DFC1) puts the node's whole
        set back into all three.
        """

        self.state.byte_4b7b = 0
        if self.predicates is None or opcode not in (0x39, 0x3A, 0x44, 0x45):
            return False
        if len(target_node) <= 0x1C or len(current_room_context) < 0x20:
            return False
        candidates = (
            self.predicates.blocks[0x671]
            .union(self.predicates.blocks[0x679])
            .union(PascalSet.from_bytes(bytes(current_room_context[0x18:0x20])))
            .difference(self.predicates.blocks[0x691])
        )
        if target_index not in candidates:
            return False
        self.state.byte_4b7b = 1
        if opcode == 0x44:
            if target_node[0x18] != 0 or target_node[0x1B] or target_node[0x1C]:
                self.state.byte_4b7b = 0
                return False
            target_node[0x1B] = 1
            local = PascalSet.from_bytes(bytes(target_node[0:8]), 8)
            if nodes is not None:
                for index in range(2, phase7_count + 1):
                    if index not in local:
                        continue
                    member = nodes.get(index)
                    if member is None or len(member) <= 0x1B:
                        continue
                    if (member[0x18] == 0 and member[0x1B] != 1) or member[0x18] == 1:
                        local = local.difference(PascalSet.from_bytes(bytes(member[0:8]), 8))
            self._uncover(local, target_index, excluded_19ef, remove=True)
            return True
        if opcode == 0x45:
            if target_node[0x18] != 0 or target_node[0x1B] == 0:
                self.state.byte_4b7b = 0
                return False
            target_node[0x1B] = 0
            self._uncover(
                PascalSet.from_bytes(bytes(target_node[0:8]), 8),
                target_index,
                excluded_19ef,
                remove=False,
            )
            return True
        if opcode == 0x39:
            if target_node[0x1B] or target_node[0x1C]:
                self.state.byte_4b7b = 0
                return False
            target_node[0x1C] = 1
            return True
        if target_node[0x1C] == 0:
            self.state.byte_4b7b = 0
            return False
        target_node[0x1C] = 0
        return True

    def execute_runtime_to_inventory_transfer(
        self,
        *,
        current_room_context: bytes | bytearray,
        runtime_rule_set: bytes,
        phase7_node: bytes | bytearray,
    ) -> tuple[bool, bytes]:
        """Port EF31 opcode 41h (`sub_A94D` + `sub_A797`)."""

        self.state.byte_4b7b = 0
        if self.predicates is None or len(current_room_context) < 0x17:
            return False, runtime_rule_set
        if len(runtime_rule_set) != 8 or len(phase7_node) < 8:
            return False, runtime_rule_set
        room_slots = PascalSet.from_bytes(bytes(current_room_context[0x14:0x18]))  # people set, +14h
        if self.state.byte_1a50 == 1 or self.state.byte_1a50 not in room_slots:
            return False, runtime_rule_set
        runtime_set = PascalSet.from_bytes(runtime_rule_set)
        target = self.state.byte_1a4f
        if target not in runtime_set.difference(self.predicates.blocks[0x6A1]):
            return False, runtime_rule_set
        moved = PascalSet.from_bytes(bytes(phase7_node[0:8])).union(
            PascalSet.from_values([target], 8)
        )
        runtime_set = runtime_set.difference(moved)
        self.predicates.blocks[0x671] = self.predicates.blocks[0x671].union(moved)
        self.state.word_6ad += 1
        self.state.byte_4b7b = 1
        return True, runtime_set.to_bytes()

    def execute_inventory_to_person_transfer(
        self,
        *,
        current_room_context: bytes | bytearray,
        runtime_rule_set: bytes,
        phase7_node: bytes | bytearray,
    ) -> tuple[bool, bytes]:
        """Port EF31 opcode 42h (``sub_A9CB`` -> ``sub_A901`` / ``sub_A84C``).

        The person 1A50 must be present (room people set +14h, not 1) and the
        object 1A4C in hand (0671 - 06A1); then byte_4B7B := 1 and the object
        with its contents leaves 0671 for the person's +0Ch set, word_6AD
        dropping by one. (A84C ends in a72e, which refreshes a frame set of
        what the person visibly holds; that set is not modelled.)
        """

        self.state.byte_4b7b = 0
        if self.predicates is None or len(current_room_context) < 0x18:
            return False, runtime_rule_set
        if len(runtime_rule_set) != 8 or len(phase7_node) < 8:
            return False, runtime_rule_set
        people = PascalSet.from_bytes(bytes(current_room_context[0x14:0x18]))
        if self.state.byte_1a50 == 1 or self.state.byte_1a50 not in people:
            return False, runtime_rule_set
        target = self.state.byte_1a4c
        if target not in self.predicates.blocks[0x671].difference(self.predicates.blocks[0x6A1]):
            return False, runtime_rule_set
        self.state.byte_4b7b = 1
        moved = PascalSet.from_bytes(bytes(phase7_node[0:8])).union(
            PascalSet.from_values([target], 8)
        )
        self.predicates.blocks[0x671] = self.predicates.blocks[0x671].difference(moved)
        self.state.word_6ad -= 1
        return True, PascalSet.from_bytes(runtime_rule_set).union(moved).to_bytes()

    def execute_descriptor_action(
        self,
        opcode: int,
        *,
        descriptor: bytes,
        resolved_aux: int | None = None,
    ) -> bool | None:
        """Execute descriptor-state actions from the EF31 dispatcher.

        Opcode 53h reads the seven-byte descriptor selected through
        ``msg_ctrl_break``.  The byte at ``+2`` chooses which VM cursor/global
        receives descriptor byte ``+3``:

        * 0 -> ``byte_1A4C``
        * 1 -> ``byte_1A50`` and then ``sub_A72E`` in the native runtime
        * 2 -> ``byte_1A52`` plus an optional auxiliary room lookup result
        * 3 -> ``byte_1A51``

        The heavy lookup behind the type-2 branch is supplied by the caller as
        ``resolved_aux`` because it depends on the command-local descriptor
        table that is still decoded separately from these primitive effects.
        """

        if opcode != 0x53:
            return None
        if len(descriptor) < 4:
            return False
        kind = descriptor[2]
        value = descriptor[3]
        if kind == 0:
            self.state.byte_1a4c = value
            return True
        if kind == 1:
            self.state.byte_1a50 = value
            return True
        if kind == 2:
            self.state.byte_1a52 = value
            if resolved_aux is not None:
                self.state.byte_4add = resolved_aux & 0xFF
            return True
        if kind == 3:
            self.state.byte_1a51 = value
            return True
        return False

    def execute_room_toggle_action(
        self,
        *,
        room_context: bytearray,
        value: int,
    ) -> bool:
        """Port ``sub_B74B``: toggle a light source's +1Ah and DS:4AB6.

        Despite the parameter name, the record is the phase-7 runtime record
        ``4B4[value]`` (``les di, [di+4B4h]``), not a room. The routine only
        acts when its type byte ``+18`` is ``4`` (a light source -- the
        lighter); it toggles ``+1A`` and inserts ``value`` into set ``4AB6``
        when that becomes one, removes it when it becomes zero.
        """

        if len(room_context) < 0x1B or room_context[0x18] != 4:
            return False
        room_context[0x1A] ^= 1
        if self.auxiliary_4ab6 is not None:
            if room_context[0x1A]:
                self.auxiliary_4ab6.add(value)
            else:
                self.auxiliary_4ab6.discard(value)
        return True

    def execute_target_room_action(
        self,
        *,
        target_context: bytearray,
        selected_room: int,
        target_value: int,
        current_room: int | None = None,
    ) -> bool:
        """Port the state write core of ``sub_BB10``.

        ``sub_BB10`` resolves ``selected_room`` via ``sub_B9E5`` and then
        checks the target context selected by its argument.  If byte ``+11`` is
        not ``2`` and ``selected_room`` is in the 15-byte set at ``+12``, the
        routine sets byte ``+0E`` to ``selected_room`` and marks
        ``byte_4B7B`` true.  When the selected room is the current room
        (`DS:06A9`), the native stack frame also remembers the action argument;
        this method exposes that as ``last_target_room_value``.
        """

        if len(target_context) < 0x21 or not 0 <= selected_room <= 0xFF:
            self.state.byte_4b7b = 0
            return False
        self.state.byte_4b7b = 0
        if target_context[0x11] == 2:
            return False
        if selected_room not in PascalSet.from_bytes(bytes(target_context[0x12:0x21]), 0x0F):
            return False
        target_context[0x0E] = selected_room
        self.state.byte_4b7b = 1
        if current_room is not None and selected_room == current_room:
            self.state.last_target_room_value = target_value & 0xFF
        return True

    def execute_link_marker_action(
        self,
        *,
        nodes: dict[int, bytearray],
        forward: bool,
    ) -> bool:
        """Port ``sub_EE18`` over the node table addressed from ``DS:25C``.

        The native routine keeps a current link cursor in ``byte_1AB7`` and
        uses ``byte_1AB6``/``byte_1AB5`` as forward/backward sentinels.  In the
        forward direction it advances to ``node[byte_1AB7][+13]`` and marks the
        new node's ``+22`` byte.  In the backward direction it clears the
        current node marker, then walks links from ``byte_1AB5`` until it finds
        the predecessor whose ``+13`` points at the current cursor.
        """

        current = self.state.byte_1ab7
        sentinel = self.state.byte_1ab6 if forward else self.state.byte_1ab5
        if current == sentinel:
            self.state.byte_4b7b = 0
            return False
        self.state.byte_4b7b = 1
        if forward:
            node = nodes.get(current)
            if node is None or len(node) <= 0x22:
                self.state.byte_4b7b = 0
                return False
            next_id = node[0x13]
            self.state.byte_1ab7 = next_id
            next_node = nodes.get(next_id)
            if next_node is not None and len(next_node) > 0x22:
                next_node[0x22] = 1
            return True

        node = nodes.get(current)
        if node is not None and len(node) > 0x22:
            node[0x22] = 0
        probe = self.state.byte_1ab5
        visited: set[int] = set()
        while probe != current and probe not in visited:
            visited.add(probe)
            probe_node = nodes.get(probe)
            if probe_node is None or len(probe_node) <= 0x13:
                break
            if probe_node[0x13] == current:
                self.state.byte_1ab7 = probe
                return True
            probe = probe_node[0x13]
        return True

    def execute_aux_selector_action(self, *, resolved_value: int | None = None) -> bool:
        """Port the isolated gate/write behaviour of ``sub_ADD8``.

        Native ``sub_ADD8`` checks ``byte_1A51``.  If it is ``1`` the action
        predicate ``byte_4B7B`` becomes false and no write happens. Otherwise
        it calls a resolver (`loc_8C64+1`) with ``byte_1A51`` and writes the
        returned byte into ``byte_1A52``.
        """

        if self.state.byte_1a51 == 1:
            self.state.byte_4b7b = 0
            return False
        self.state.byte_4b7b = 1
        if resolved_value is not None:
            self.state.byte_1a52 = resolved_value & 0xFF
        return True

    def execute_phase4_selector_write(
        self,
        *,
        argument: int,
        resolver_valid: bool,
        side_effect_flag: bool = False,
    ) -> bool:
        """Port the confirmed final write of ``sub_BA7D``.

        ``sub_BA7D`` first resolves a selector through ``sub_B9E5``.  If that
        resolution fails, ``byte_4B7B`` is false and no phase-4 write occurs.
        Otherwise the native routine writes ``byte_1AEB = argument`` when its
        local side-effect flag is set, and ``byte_1AEB = 1`` when it is clear.
        The side-effect flag itself is produced by deeper UI/target logic and
        is intentionally supplied by the caller here.
        """

        self.state.byte_4b7b = 1 if resolver_valid else 0
        if not resolver_valid:
            return False
        self.state.byte_1aeb = (argument if side_effect_flag else 1) & 0xFF
        return True

    def execute_plus_t_gate(self) -> bool:
        """Port the entry gate of ``sub_B805`` used by MESSAGE ``+T``.

        `sub_B805` begins by setting `byte_4B7B` to false when `byte_1A4C`
        equals one, and true otherwise.  The following set mutations are still
        decoded separately; this helper intentionally exposes only the
        confirmed gate.
        """

        self.state.byte_4b7b = 0 if self.state.byte_1a4c == 1 else 1
        return bool(self.state.byte_4b7b)

    def execute_plus_t_transfer(
        self,
        *,
        room_contexts: dict[int, bytearray],
        target_room: int,
        current_room: int | None = None,
    ) -> bool | None:
        """Port the decoded set mutation body of ``sub_B805``.

        ``+T`` first rejects cursor value ``1``.  It then finds the phase-8
        room whose context set at ``+18..1F`` contains ``byte_1A4C``; if none
        is found, the native fallback is the current room (`DS:06A9`).  The
        selected/source context loses the cursor, and the operand-selected
        target room gains it.  When the cursor was also in predicate set
        ``0671``, the native routine removes it from ``0671`` and decrements
        ``word_6AD``.

        The pre-mutation gate mirrors the native temporary set:

        ``((source_context union {cursor} union 0671) - 0691 - 06A1) != empty``.
        """

        if self.predicates is None:
            return None
        cursor = self.state.byte_1a4c
        if cursor == 1:
            self.state.byte_4b7b = 0
            return False
        self.state.byte_4b7b = 1

        source_room = None
        # sub_B814 scans rooms 2..byte_19EA; room 1 is never the source (the
        # 33h action can park the cursor there, see record 270).
        for room_id in sorted(r for r in room_contexts if r >= 2):
            room = room_contexts[room_id]
            if len(room) >= 0x20 and cursor in PascalSet.from_bytes(bytes(room[0x18:0x20]), 8):
                source_room = room_id
                break
        if source_room is None:
            source_room = current_room
        if source_room is None:
            self.state.byte_4b7b = 0
            return False
        source = room_contexts.get(source_room)
        target = room_contexts.get(target_room)
        if source is None or target is None or len(source) < 0x20 or len(target) < 0x20:
            self.state.byte_4b7b = 0
            return False

        singleton = PascalSet.from_values([cursor], 8)
        source_context = PascalSet.from_bytes(bytes(source[0x18:0x20]), 8)
        candidate = (
            source_context
            .union(singleton)
            .union(self.predicates.blocks[0x671])
            .difference(self.predicates.blocks[0x691])
            .difference(self.predicates.blocks[0x6A1])
        )
        if len(candidate) == 0:
            self.state.byte_4b7b = 0
            return False

        source[0x18:0x20] = source_context.difference(singleton).to_bytes()
        if cursor in self.predicates.blocks[0x671]:
            self.predicates.blocks[0x671] = self.predicates.blocks[0x671].difference(singleton)
            self.state.word_6ad -= 1
        target_context = PascalSet.from_bytes(bytes(target[0x18:0x20]), 8)
        target[0x18:0x20] = target_context.union(singleton).to_bytes()
        return True

    def execute_plus_v_context(
        self,
        secondary_opcode: int,
        *,
        parser_block_4b63: bytes,
        byte_4b7c: int | None = None,
    ) -> bool | None:
        """Port the confirmed ``+V`` parser-scratch cursor copies.

        The native helper at `loc_F565` switches on the secondary opcode and
        copies from the parser scratch block `DS:4B63..4B6A`:

        * `8Ah`: `4B63 -> byte_1A4C`
        * `8Bh`: `4B69 -> byte_1A52`
        * `8Ch`: `4B68 -> byte_1A51`
        * `8Dh`: `4B67 -> byte_1A50`
        * `8Eh`: `4B66 -> byte_1A4F`
        * `94h`: `byte_4B7C -> byte_4ADE`
        """

        if len(parser_block_4b63) < 7:
            return False
        if secondary_opcode == 0x8A:
            self.state.byte_1a4c = parser_block_4b63[0]
            return True
        if secondary_opcode == 0x8B:
            self.state.byte_1a52 = parser_block_4b63[6]
            return True
        if secondary_opcode == 0x8C:
            self.state.byte_1a51 = parser_block_4b63[5]
            return True
        if secondary_opcode == 0x8D:
            self.state.byte_1a50 = parser_block_4b63[4]
            return True
        if secondary_opcode == 0x8E:
            self.state.byte_1a4f = parser_block_4b63[3]
            return True
        if secondary_opcode == 0x94:
            if byte_4b7c is None:
                return None
            self.state.byte_4ade = byte_4b7c & 0xFF
            return True
        return False

    def execute_plus_control(
        self,
        opcode: int | str,
        *,
        secondary_opcode: int | None = None,
        descriptor_kind: int | None = None,
        parser_block_4b63: bytes | None = None,
        byte_4b7c: int | None = None,
        room_context: bytearray | None = None,
        target_context: bytearray | None = None,
        selected_room: int | None = None,
        current_room: int | None = None,
        value: int | None = None,
        resolved_aux: int | None = None,
        resolver_valid: bool | None = None,
        side_effect_flag: bool = False,
    ) -> bool | None:
        """Port confirmed side effects of MESSAGE ``+`` control.

        ``msg_ctrl_plus`` compares its first translated operand against ASCII
        opcodes.  The fully context-free branch decoded so far is ``N`` with
        secondary opcode ``8Fh``: it toggles global ``byte_1A8A``.  The other
        ``N`` branch delegates to ``sub_B74B`` and is safe when the caller
        supplies the resolved room context and value.  ``R`` delegates to
        `BA7D` when descriptor kind is one, otherwise to `BB10`.  ``S`` is the
        descriptor cursor writer also reached through action opcode ``53h``.
        """

        if isinstance(opcode, str):
            if len(opcode) != 1:
                return None
            opcode_value = ord(opcode.upper())
        else:
            opcode_value = opcode
        if opcode_value == 0x52:  # 'R'
            if descriptor_kind == 1:
                if value is None or resolver_valid is None:
                    return None
                return self.execute_phase4_selector_write(
                    argument=value,
                    resolver_valid=resolver_valid,
                    side_effect_flag=side_effect_flag,
                )
            if (
                target_context is None
                or selected_room is None
                or value is None
            ):
                return None
            return self.execute_target_room_action(
                target_context=target_context,
                selected_room=selected_room,
                target_value=value,
                current_room=current_room,
            )
        if opcode_value == 0x53:  # 'S'
            if descriptor_kind is None or value is None:
                return None
            descriptor = bytes((0, 0, descriptor_kind & 0xFF, value & 0xFF, 0, 0, 0))
            return self.execute_descriptor_action(
                0x53,
                descriptor=descriptor,
                resolved_aux=resolved_aux,
            )
        if opcode_value == 0x54:  # 'T'
            if target_context is not None and selected_room is not None:
                rooms = {selected_room: target_context}
                if room_context is not None and current_room is not None:
                    rooms[current_room] = room_context
                return self.execute_plus_t_transfer(
                    room_contexts=rooms,
                    target_room=selected_room,
                    current_room=current_room,
                )
            return self.execute_plus_t_gate()
        if opcode_value == 0x56:  # 'V'
            if secondary_opcode is None or parser_block_4b63 is None:
                return None
            return self.execute_plus_v_context(
                secondary_opcode,
                parser_block_4b63=parser_block_4b63,
                byte_4b7c=byte_4b7c,
            )
        if opcode_value != 0x4E:  # 'N'
            return None
        if secondary_opcode == 0x8F:
            self.state.byte_1a8a ^= 1
            return True
        if room_context is None or value is None:
            return None
        return self.execute_room_toggle_action(room_context=room_context, value=value)
