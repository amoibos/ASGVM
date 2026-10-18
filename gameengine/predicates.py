"""ASG scene predicate storage used by MESSAGE and rule dispatchers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .pascal_set import PascalSet
from .message import DEFAULT_SYMBOL_TABLE
from .vocab import VocabEntry


ASG_PREDICATE_BLOCK_SIZE = 8
ASG_PREDICATE_ADDRESSES = (0x671, 0x679, 0x681, 0x689, 0x691, 0x699, 0x6A1)

# Confirmed native set selection in msg_ctrl_star's mode!=1 tail.  The tuple
# is ``(native address, set width bytes, context byte offset)``.  Addresses are
# kept as native names because their semantic owners are still being decoded.
STAR_CONTEXT_SET_LAYOUTS: dict[int, tuple[int, int, int]] = {
    0: (0x4B81, 8, 3),
    1: (0x4B89, 4, 3),
    2: (0x4B8D, 15, 3),
    3: (0x4B9C, 2, 3),
    5: (0x4AE2, 7, 0),
    6: (0x4B9E, 8, 3),
    7: (0x4AE2, 7, 0),
    8: (0x4AE2, 7, 0),
    9: (0x4BB5, 1, 3),
    10: (0x4BA6, 15, 3),
}


@dataclass
class AsgPredicateState:
    """Mutable mirror of the traced DS:0670..06A8 predicate region.

    Each listed address is an eight-byte Turbo Pascal ``set of 0..63``.
    Keeping native addresses as keys makes MESSAGE opcode traces directly
    applicable across games without inventing game-specific field names.
    """

    byte_670: int = 0
    blocks: dict[int, PascalSet] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for address in ASG_PREDICATE_ADDRESSES:
            self.blocks.setdefault(address, PascalSet.empty(ASG_PREDICATE_BLOCK_SIZE))

    @classmethod
    def from_region(cls, region: bytes, base_address: int = 0x670) -> "AsgPredicateState":
        required = 0x6A9 - base_address
        if len(region) < required:
            raise ValueError(f"predicate region needs {required} bytes, got {len(region)}")
        state = cls(byte_670=region[0x670 - base_address])
        for address in ASG_PREDICATE_ADDRESSES:
            start = address - base_address
            state.blocks[address] = PascalSet.from_bytes(
                region[start:start + ASG_PREDICATE_BLOCK_SIZE]
            )
        return state

    def contains(self, address: int, element: int) -> bool:
        return element in self.blocks[address]

    def set(self, address: int, element: int, enabled: bool) -> None:
        block = self.blocks[address]
        if enabled:
            block.add(element)
        else:
            block.discard(element)

    def finalize_phase_7(self) -> None:
        """Apply the confirmed `sub_132B:loc_17F0` aggregate writes."""
        self.blocks[0x691] = self.blocks[0x681].union(self.blocks[0x689])
        self.blocks[0x6A1] = (
            self.blocks[0x6A1]
            .union(self.blocks[0x689])
            .union(self.blocks[0x699])
        )

    def region_bytes(self, base_address: int = 0x670, end_address: int = 0x6A9) -> bytes:
        raw = bytearray(end_address - base_address)
        raw[0x670 - base_address] = self.byte_670
        for address, block in self.blocks.items():
            start = address - base_address
            raw[start:start + ASG_PREDICATE_BLOCK_SIZE] = block.to_bytes()
        return bytes(raw)


@dataclass(frozen=True)
class RuntimeVocabCursor:
    """Ten-byte ``sub_33F6`` cursor projected without host far pointers."""

    node_index: int
    metadata: bytes


@dataclass(frozen=True)
class RuntimeVocabNodeTable:
    """The loader-built seven-byte node table's metadata projection.

    Node zero is the native header.  VOCAB records are inserted as nodes
    1..N, and node ``+6`` is the record's ``value_b`` byte consumed by
    ``sub_AE63``.
    """

    value_b_by_node: tuple[int, ...]
    entries_by_node: tuple[VocabEntry | None, ...]
    metadata_by_node: tuple[bytes, ...]
    raw_by_node: tuple[bytes, ...]

    @classmethod
    def from_entries(cls, entries: list[VocabEntry]) -> "RuntimeVocabNodeTable":
        pool_offset = 3
        raw_nodes = [bytes.fromhex("01 02 01 33 02 0A 01")]
        for entry in entries:
            length = entry.raw[0]
            raw_nodes.append(bytes((1, length, pool_offset & 0xFF)) + entry.metadata)
            pool_offset += length
        # MESSAGE controls address this array with a two-symbol 12-bit index
        # (``msg_ctrl_break(1)``), not merely with the populated VOCAB count.
        # The native region is zero-initialised before the loader writes its
        # sequential word nodes, so unused slots remain seven zero bytes.
        capacity = 0x1000
        if len(raw_nodes) > capacity:
            raise ValueError("runtime VOCAB exceeds 12-bit node table")
        padding = capacity - len(raw_nodes)
        return cls(
            (1,) + tuple(entry.value_b for entry in entries) + (0,) * padding,
            (None,) + tuple(entries) + (None,) * padding,
            (bytes.fromhex("33 02 0A 01"),)
            + tuple(entry.metadata for entry in entries)
            + (bytes(4),) * padding,
            tuple(raw_nodes) + (bytes(7),) * padding,
        )

    def cursor(self, node_index: int = 0) -> RuntimeVocabCursor:
        if not 0 <= node_index < len(self.metadata_by_node):
            raise IndexError(f"runtime VOCAB node {node_index} outside table")
        return RuntimeVocabCursor(node_index, self.raw_by_node[node_index][3:7])

    def value_b_for_message_symbol(self, symbol: int) -> int | None:
        if 0 <= symbol < len(self.value_b_by_node):
            return self.value_b_by_node[symbol]
        return None

    # The loader seeds the word pool (a Pascal string at DS:0F6F, overlay
    # IDA 06F3) with the literal '!!' before it appends the VOCAB words, and
    # header node 0 points at those two characters (pool offset 1, length 2).
    # Live memory after boot: FF 21 21 "AIRPORTAM I...".
    HEADER_WORD = "!!"

    def word_for_node(self, node_index: int) -> str:
        """The word a node's pool reference spells (node 0: the pool head)."""

        if node_index == 0:
            return self.HEADER_WORD
        entry = self.entry_for_message_symbol(node_index)
        return "" if entry is None else entry.word

    def entry_for_message_symbol(self, symbol: int) -> VocabEntry | None:
        if 0 <= symbol < len(self.entries_by_node):
            return self.entries_by_node[symbol]
        return None


@dataclass(frozen=True)
class AsgPredicateEvaluator:
    """Confirmed MESSAGE predicate opcode evaluator.

    Confirmed opcode forms:

    * ``q``: ``value_b in DS:0681`` (`loc_CDD9`)
    * ``u``: ``value_b in (DS:0679 - DS:0699)`` (`loc_CED7`)
    * ``;``: ``value_b in DS:0671`` (decoded opcode 0x81, `loc_CF34`)
    * ``y``: raw operand symbol in one-byte set DS:0670 (`loc_CE17`)
    * ``"``: no dedicated ``loc_CC86`` handler; the native dispatcher falls
      through without assigning ``byte_4B7B``. Structural EXAMINE evaluation
      has no prior live gate to carry, so this evaluates false.

    Unknown opcodes return ``None``.
    """

    state: AsgPredicateState
    nodes: RuntimeVocabNodeTable
    record_context_set: PascalSet | None = None
    local_set: PascalSet | None = None
    fg_context_type: int | None = None
    condition_records: dict[int, bytes] | None = None
    room_records: dict[int, bytes] | None = None
    t_record: bytes | None = None
    t_scene_value: int | None = None
    t_lookup_records: dict[int, bytes] | None = None
    t_type_2_4_test: Callable[[int], bool] | None = None
    x_lookup_records: dict[int, bytes] | None = None
    amp_node_records: dict[int, bytes] | None = None
    amp_cached_flag: bool | None = None
    h_cursor_advance: Callable[[PascalSet], None] | None = None
    w_room_index: int | None = None
    s_cursor_advance: Callable[[], None] | None = None
    z_candidate_set: PascalSet | None = None
    z_cursor_advance: Callable[[PascalSet], None] | None = None
    amp_global_1a8a: bool | None = None
    amp_current_command_value_b: int | None = None
    amp_node_cursor_1a4c: int | None = None
    amp_runtime_cursor_1a50: int | None = None
    amp_runtime_records: dict[int, bytes] | None = None
    amp_current_room: int | None = None
    amp_auxiliary_4ab6: PascalSet | None = None
    amp_link_match: Callable[[int, int], None] | None = None
    amp_context_type: int | None = None
    amp_set_1ab8: PascalSet | None = None
    amp_set_1acb: PascalSet | None = None
    dollar_context_record: bytes | bytearray | None = None

    def evaluate_dollar_a(self, node_index: int) -> bool | None:
        """Port `$a`/`loc_D463` against context record set ``+0x0C``."""

        if self.dollar_context_record is None:
            return None
        if not 0 <= node_index < len(self.nodes.value_b_by_node):
            return False
        if len(self.dollar_context_record) < 0x14:
            return False
        value_b = self.nodes.value_b_by_node[node_index]
        return value_b in PascalSet.from_bytes(self.dollar_context_record[0x0C:0x14])

    def evaluate(self, operand: str) -> bool | None:
        if not operand:
            return None
        if operand[0] == '"':
            return False
        if operand[0] == "r":
            if self.record_context_set is None:
                return None
            return len(self.record_context_set.difference(self.state.blocks[0x699])) != 0
        if operand[0] == "w":
            return self._evaluate_w(self.w_room_index)
        if operand[0] == "s":
            if self.s_cursor_advance is not None:
                self.s_cursor_advance()
            return True
        if operand[0] == "z":
            if self.z_candidate_set is None:
                return None
            if len(self.z_candidate_set) == 0:
                return False
            if self.z_cursor_advance is not None:
                self.z_cursor_advance(self.z_candidate_set)
            return True
        if len(operand) < 2 or operand[0] not in ("q", "u", ";", "y", "v", "f", "g", "i", "t", "x", "h"):
            return None
        reverse = {character: symbol for symbol, character in DEFAULT_SYMBOL_TABLE.items()}
        symbol = reverse.get(operand[1])
        if symbol is None:
            return None
        if operand[0] == "y":
            return self.evaluate_resolved(operand[0], raw_symbol=symbol)
        value_b = self.nodes.value_b_for_message_symbol(symbol)
        if value_b is None:
            return None
        return self.evaluate_resolved(
            operand[0], value_b=value_b,
            entry=self.nodes.entry_for_message_symbol(symbol),
        )

    def evaluate_resolved(
        self,
        opcode: str,
        *,
        value_b: int | None = None,
        raw_symbol: int | None = None,
        entry: VocabEntry | None = None,
    ) -> bool | None:
        """Evaluate the shared predicate after operand resolution.

        The native ``$`` dispatcher resolves a MESSAGE symbol through the
        seven-byte VOCAB node table.  Its ``&`` sibling caches that resolved
        operand in its frame.  Both therefore converge here.
        """
        if opcode == "y":
            if raw_symbol is None:
                return None
            return bool(self.state.byte_670 & (1 << raw_symbol)) if raw_symbol < 8 else False
        if opcode in ("f", "g", "i"):
            return self._evaluate_fgi_entry(opcode, entry)
        if value_b is None:
            return None
        if opcode == "t":
            return self._evaluate_t(value_b)
        if opcode == "x":
            return self._evaluate_x(value_b)
        if opcode == "h":
            return self._evaluate_h(value_b)
        if opcode == "v":
            return None if self.local_set is None else value_b in self.local_set
        if opcode == "q":
            return self.state.contains(0x681, value_b)
        if opcode == ";":
            return self.state.contains(0x671, value_b)
        if opcode != "u":
            return None
        container = self.state.blocks[0x679]
        excluded = self.state.blocks[0x699]
        return value_b in container.difference(excluded)

    def evaluate_amp_resolved(
        self, opcode: str, node_index: int, *, secondary_value: int | None = None
    ) -> bool | None:
        """Evaluate ``msg_ctrl_amp`` after its parser has cached the operand.

        Unlike ``$``, amp's ``sub_AE9E`` prologue has already produced the
        runtime node/table index.  The direct type opcodes are the native
        ``sub_D894`` cases at ``D894``/``DA43..DABB``.
        """
        if opcode == "}":
            return self.amp_cached_flag
        expected_types = {"j": 2, "k": 0, "l": 1, "p": 3, "m": 4, "n": 5}
        expected = expected_types.get(opcode)
        if expected is not None:
            if self.amp_node_records is None:
                return None
            record = self.amp_node_records.get(node_index)
            return record is not None and len(record) > 0x18 and record[0x18] == expected
        if opcode == "o":
            if self.room_records is None:
                return None
            record = self.room_records.get(node_index)
            return record is not None and len(record) > 0x23 and bool(record[0x23])
        if opcode == "w":
            return self._evaluate_w(node_index)
        if opcode == "_":
            if secondary_value == 0x8F:
                return self.amp_global_1a8a
            if self.amp_node_records is None:
                return None
            record = self.amp_node_records.get(node_index)
            return record is not None and len(record) > 0x1A and bool(record[0x1A])
        if opcode == "b":
            if (
                self.amp_node_records is None
                or self.amp_node_cursor_1a4c is None
                or self.amp_current_command_value_b is None
            ):
                return None
            record = self.amp_node_records.get(self.amp_node_cursor_1a4c)
            if record is None or len(record) < 0x16:
                return False
            return self.amp_current_command_value_b in PascalSet.from_bytes(record[0x0E:0x16])
        if opcode == "a":
            if self.amp_runtime_records is None or self.amp_runtime_cursor_1a50 is None:
                return None
            record = self.amp_runtime_records.get(self.amp_runtime_cursor_1a50)
            if record is None or len(record) < 0x14:
                return False
            return node_index in PascalSet.from_bytes(record[0x0C:0x14])
        if opcode == "^":
            if self.room_records is None:
                return None
            room = self.room_records.get(node_index)
            if room is None or len(room) <= 0x20:
                return False
            mode = room[0x20]
            if mode == 0:
                return False
            if mode == 1:
                enabled = True
            elif mode == 2:
                if self.amp_global_1a8a is None:
                    return None
                enabled = not self.amp_global_1a8a
            else:
                enabled = False
            if not enabled or self.amp_current_room != node_index:
                return enabled
            if self.amp_auxiliary_4ab6 is None:
                return None
            room_set = PascalSet.from_bytes(room[0x18:0x20])
            accepted = self.state.blocks[0x671].union(room_set)
            return len(self.amp_auxiliary_4ab6.intersection(accepted)) != 0
        if opcode == "`":
            if self.room_records is None:
                return None
            if node_index != 1:
                room = self.room_records.get(node_index)
                return room is not None and len(room) > 0x22 and bool(room[0x22])
            if self.amp_current_room is None:
                return None
            current = self.room_records.get(self.amp_current_room)
            if current is None or len(current) < 10:
                return False
            for target_index in current[4:10]:
                target = self.room_records.get(target_index)
                if target is not None and len(target) > 0x22 and target[0x22]:
                    return True
            return False
        if opcode in ("c", "d"):
            if self.amp_node_records is None:
                return None
            wanted = 2 if opcode == "c" else 0
            start = self.amp_node_records.get(node_index)
            if start is None or len(start) <= 0x18:
                return False
            if wanted == 0 and start[0x18] == 3:
                return True
            current = node_index
            seen: set[int] = set()
            while current not in seen:
                seen.add(current)
                record = self.amp_node_records.get(current)
                if record is None or len(record) <= 0x18:
                    return False
                linked = record[0x17]
                if linked == 1:
                    return False
                target = self.amp_node_records.get(linked)
                if target is None or len(target) <= 0x18:
                    return False
                if target[0x18] == wanted:
                    if self.amp_link_match is not None:
                        self.amp_link_match(node_index, linked)
                    return True
                current = linked
            return False
        if opcode == "\x80":
            if self.amp_context_type == 2:
                return None if self.amp_set_1acb is None else node_index not in self.amp_set_1acb
            if self.amp_context_type == 1:
                return None if self.amp_set_1ab8 is None else node_index not in self.amp_set_1ab8
            return False
        if opcode in ("q", "u", "v", ";", "t", "x", "h"):
            return self.evaluate_resolved(opcode, value_b=node_index)
        return None

    @staticmethod
    def evaluate_amp_context_compare(
        primary_value: int,
        comparison_value: int,
        *,
        context_type: int,
        cached_enabled: bool,
        comparison_room: bytes | bytearray | None = None,
        bridge_rooms_1abc: PascalSet | None = None,
        active_rooms_4abe: PascalSet | None = None,
    ) -> bool:
        """Port amp opcode 82h (`:`), native ``sub_D4C4``'s final gate.

        Context types 0/1/3/6 compare directly. Type 2 additionally scans
        active exits of a 1ABC bridge room when the direct comparison fails.
        """

        if not cached_enabled:
            return False
        primary_value &= 0xFFFF
        comparison_value &= 0xFFFF
        if context_type in (0, 1, 3, 6):
            return primary_value == comparison_value
        if context_type != 2:
            return False
        result = primary_value == comparison_value
        if result or bridge_rooms_1abc is None or comparison_value not in bridge_rooms_1abc:
            return result
        if comparison_room is None or active_rooms_4abe is None:
            return result
        # loc_D678..D6CF: the first exit of the comparison room that is in
        # the active set 4ABE decides -- `cmp ax, cx / mov ax, 1 / jz / dec
        # ax` is equality, and `mov [bp-0Dh], 5` ends the loop.
        for target in comparison_room[0x04:0x0A]:
            if target in active_rooms_4abe:
                return primary_value == target
        return result

    def eq_candidate_set(
        self,
        opcode: str | int,
        *,
        room_context: bytes | bytearray | None = None,
    ) -> PascalSet | None:
        """Build the confirmed temporary set for MESSAGE ``=`` control.

        The native ``msg_ctrl_eq`` first clears an eight-byte stack set and
        then selects a base set by its translated opcode:

        * ``u`` (`75h`) copies predicate set `0679`;
        * ``v`` (`76h`) unions `0679` and `0671`;
        * decoded semicolon (`81h`, represented as ``;`` here) copies `0671`;
        * ``t`` (`74h`) copies a caller-supplied room/context set at `+18`.

        Later branches use this temporary set for additional node scans and
        render/skip decisions; those effects stay outside this helper until the
        remaining control flow is fully decoded.
        """

        if isinstance(opcode, str):
            if len(opcode) != 1:
                return None
            opcode_value = 0x81 if opcode == ";" else ord(opcode)
        else:
            opcode_value = opcode
        if opcode_value == 0x75:  # 'u'
            return self.state.blocks[0x679]
        if opcode_value == 0x76:  # 'v'
            return self.state.blocks[0x679].union(self.state.blocks[0x671])
        if opcode_value == 0x81:  # decoded ';'
            return self.state.blocks[0x671]
        if opcode_value == 0x74:  # 't'
            if room_context is None or len(room_context) < 0x20:
                return None
            return PascalSet.from_bytes(bytes(room_context[0x18:0x20]))
        return None

    def eq_filter_candidate_for_context(
        self,
        candidate: PascalSet,
        context_record: bytes | bytearray,
    ) -> PascalSet | None:
        """Apply the confirmed `msg_ctrl_eq` context-type-2 filter.

        In the tail after the `8E/94/8A` selector path, the native code reads
        the selected context record's byte `+18`.  If it equals `2`, it returns
        `candidate - DS:0699`.  Other context types enter a longer node-scan
        loop and remain undecoded here.
        """

        if len(context_record) <= 0x18:
            return None
        if context_record[0x18] != 2:
            return None
        return candidate.difference(self.state.blocks[0x699])

    def eq_candidate_node_scan(self, candidate: PascalSet, phase7_count: int) -> tuple[int, ...]:
        """Return the confirmed node indices scanned by ``msg_ctrl_eq``.

        For non-type-2 contexts, the native tail loops from index `2` through
        `byte_19E9` and enters the per-node body only when the current index is
        a member of the temporary candidate set.  The body itself is decoded in
        smaller pieces; this helper exposes the loop selection without claiming
        those later effects.
        """

        if phase7_count < 2:
            return ()
        return tuple(
            index for index in range(2, phase7_count + 1)
            if index in candidate
        )

    def eq_apply_node_filter_body(
        self,
        candidate: PascalSet,
        *,
        phase7_records: dict[int, bytes | bytearray],
        phase7_count: int,
    ) -> PascalSet | None:
        """Apply the confirmed mutable per-node body of ``msg_ctrl_eq``.

        For non-type-2 contexts, the native loop walks indices
        `2..byte_19E9`.  The membership test is against the *current* mutable
        candidate set.  When the current index is still present and the
        corresponding phase-7 record has type byte `+18` equal to `0` or `1`,
        the record's leading eight-byte set is subtracted from the candidate.

        Missing records or short records are left unresolved so the caller does
        not silently treat incomplete runtime-table plumbing as a false
        predicate.
        """

        result = candidate
        if phase7_count < 2:
            return result
        for index in range(2, phase7_count + 1):
            if index not in result:
                continue
            record = phase7_records.get(index)
            if record is None or len(record) <= 0x18:
                return None
            if record[0x18] in (0, 1):
                result = result.difference(PascalSet.from_bytes(record[:8], 8))
        return result

    def eq_final_render_result(self, candidate: PascalSet) -> bool:
        """Return the confirmed final render decision for ``msg_ctrl_eq``.

        The tail subtracts singleton element `1` from the working set and then
        calls the shared set-output gate (`loc_C114`).  The gate writes
        `byte_4B7B = 1` only when no relevant elements remain; otherwise it
        writes `0`.
        """

        relevant = candidate.difference(PascalSet.from_values([1], candidate.width_bytes))
        return len(relevant) == 0

    def star_context_membership(
        self,
        context: bytes | bytearray,
        *,
        star_sets: dict[int, PascalSet],
    ) -> bool | None:
        """Evaluate the confirmed set-membership tail of ``msg_ctrl_star``.

        After mode-specific cursor work, the native handler switches on
        `context[+2]`.  Most cases test `context[+3]` against a fixed set
        address; context types `5`, `7` and `8` instead test `context[+0]`
        against set `4AE2`.  Missing sets or unsupported context types return
        ``None`` so callers do not confuse an unported path with a false
        predicate.
        """

        if len(context) < 4:
            return None
        layout = STAR_CONTEXT_SET_LAYOUTS.get(context[2])
        if layout is None:
            return None
        address, _width, value_offset = layout
        candidate = star_sets.get(address)
        if candidate is None:
            return None
        return context[value_offset] in candidate

    def star_mode3_target_match(
        self,
        context: bytes | bytearray,
        descriptor_kind: int,
        target_value: int,
        *,
        owner_value: int | None = None,
        table_4aa8: tuple[int, ...] | list[int] | None = None,
        type2_resolver: Callable[[int], int | None] | None = None,
        set_1abc: PascalSet | None = None,
        set_4abe: PascalSet | None = None,
        indirect_records_025c: dict[int, bytes | bytearray] | None = None,
    ) -> bool | None:
        """Evaluate confirmed direct target tests in ``msg_ctrl_star`` mode 3.

        The decoded middle of the native handler switches on the descriptor
        byte copied from the parser frame.  The fully direct cases are:

        * kind `0`: only context type `0` is accepted, then `context[+3]`
          is compared with the target value;
        * kinds `1`, `6`, `10`: compare `context[+3]` with the target value;
        * kind `3`: for context type `2`, compare `sub_974B(context[+3])`
          with the target; otherwise compare `context[+3]` directly;
        * kind `2`: compare `context[+3]` directly, then optionally walk six
          bytes from the indirect record table at `025C` when `context[+3]` is
          in set `1ABC`; candidates are filtered through set `4ABE`;
        * kind `9`: compare word-table `4AA8[context[+3]]` with the target;
        * kinds `5`, `7`, `8`: compare `context[+0]` with the owner value.

        The kind `2` walk writes the result for every qualifying candidate, so
        the last candidate that belongs to `4ABE` wins, matching the native
        loop rather than using an "any match" shortcut.
        """

        if len(context) < 4:
            return None
        if descriptor_kind == 0:
            return context[3] == target_value if context[2] == 0 else False
        if descriptor_kind in (1, 6, 10):
            return context[3] == target_value
        if descriptor_kind == 2:
            if context[3] == target_value:
                return True
            if set_1abc is None or set_4abe is None:
                return None
            if context[3] not in set_1abc:
                return False
            if indirect_records_025c is None:
                return None
            linked = indirect_records_025c.get(context[3])
            if linked is None or len(linked) < 10:
                return None
            matched = False
            for offset in range(4, 10):
                candidate = linked[offset]
                if candidate in set_4abe:
                    matched = candidate == target_value
            return matched
        if descriptor_kind == 3:
            if context[2] == 2:
                if type2_resolver is None:
                    return None
                resolved = type2_resolver(context[3])
                return None if resolved is None else resolved == target_value
            return context[3] == target_value
        if descriptor_kind == 9:
            if table_4aa8 is None or context[3] >= len(table_4aa8):
                return None
            return table_4aa8[context[3]] == target_value
        if descriptor_kind in (5, 7, 8):
            return None if owner_value is None else context[0] == owner_value
        return None

    def _evaluate_x(self, value_b: int) -> bool | None:
        """Port the record/set test in native ``sub_BFF3``."""
        if value_b == 1:
            return False
        if self.x_lookup_records is None or self.local_set is None:
            return None
        record = self.x_lookup_records.get(value_b)
        if record is None or len(record) <= 0x12:
            return False
        accepted = self.local_set.union(PascalSet.from_values([1], 8))
        return record[0x12] in accepted

    def _evaluate_h(self, node_index: int) -> bool | None:
        """Port ``sub_C93C``'s type/empty-set gate and cursor side effect."""
        if self.amp_node_records is None:
            return None
        record = self.amp_node_records.get(node_index)
        if record is None or len(record) <= 0x18 or record[0x18] != 2:
            return False
        node_set = PascalSet.from_bytes(record[0:8])
        if len(node_set) != 0:
            return False
        selectable = node_set.difference(self.state.blocks[0x699])
        if self.h_cursor_advance is not None:
            self.h_cursor_advance(selectable)
        return True

    def _evaluate_w(self, room_index: int | None) -> bool | None:
        if room_index is None or self.room_records is None:
            return None
        record = self.room_records.get(room_index)
        if record is None or len(record) <= 0x11:
            return False
        value = record[0x11]
        return value < 8 and bool(self.state.byte_670 & (1 << value))

    def _evaluate_fgi(self, opcode: str, symbol: int) -> bool | None:
        return self._evaluate_fgi_entry(opcode, self.nodes.entry_for_message_symbol(symbol))

    def _evaluate_fgi_entry(self, opcode: str, entry: VocabEntry | None) -> bool | None:
        if entry is None or self.fg_context_type is None:
            return None
        if self.fg_context_type == 0:
            if self.condition_records is None:
                return None
            record = self.condition_records.get(entry.class_id)
            if record is None or len(record) <= 0x1C or record[0x18] != 0:
                return False
            if opcode == "g":
                return bool(record[0x1B])
            if opcode == "i":
                return not bool(record[0x1B])
            return bool(record[0x1C])
        if self.fg_context_type == 2:
            if self.room_records is None:
                return None
            record = self.room_records.get(entry.class_id)
            if record is None or len(record) <= 0x25 or record[0x23] == 0:
                return False
            if opcode == "g":
                return bool(record[0x24])
            if opcode == "i":
                return not bool(record[0x24])
            return bool(record[0x25])
        return False

    def _evaluate_t(self, value_b: int) -> bool | None:
        if self.t_record is None or len(self.t_record) <= 0x18:
            return None
        kind = self.t_record[0x02]
        if kind == 0:
            record_set = PascalSet.from_bytes(self.t_record[0x18:0x20])
            if self.local_set is not None:
                record_set = record_set.union(self.local_set)
            return value_b in record_set
        if kind == 1:
            return value_b in PascalSet.from_bytes(self.t_record[0x14:0x18])
        if kind in (2, 4):
            # sub_665B is a shared parser-cursor chunk. Every one of its
            # internal paths joins loc_672A, which writes boolean 1. A
            # callback may mirror its pointer-copy side effects, but cannot
            # change the predicate result.
            if self.t_type_2_4_test is not None:
                self.t_type_2_4_test(value_b)
            return True
        if kind == 3:
            if self.t_lookup_records is None or self.t_scene_value is None:
                return None
            target = self.t_lookup_records.get(value_b)
            return target is not None and len(target) > 0x0E and target[0x0E] == self.t_scene_value
        if kind in (5, 6):
            return False
        return None


@dataclass(frozen=True)
class AsgPhase7Node:
    """Normalized 30-byte node consumed by `sub_132B` / `sub_133A`."""

    index: int
    raw: bytes

    def __post_init__(self) -> None:
        if len(self.raw) != 30:
            raise ValueError(f"phase-7 node must be 30 bytes, got {len(self.raw)}")

    @property
    def predicate_set(self) -> PascalSet:
        return PascalSet.from_bytes(self.raw[0:8])

    @property
    def next_index(self) -> int:
        return self.raw[0x17]

    @property
    def rule_type(self) -> int:
        return self.raw[0x18]

    @property
    def flag_1a(self) -> int:
        return self.raw[0x1A]

    @property
    def flag_1b(self) -> int:
        return self.raw[0x1B]

    @property
    def runtime_record_indices(self) -> PascalSet:
        """Four-byte set at +0x14 used by the type-2 predicate."""
        return PascalSet.from_bytes(self.raw[0x14:0x18])

    @property
    def discriminator_0c(self) -> int:
        return self.raw[0x0C]


@dataclass
class AsgPhase7Evaluator:
    """Confirmed initial node pass from `sub_132B:1505..174B`."""

    state: AsgPredicateState
    auxiliary_4ab6: PascalSet = field(default_factory=lambda: PascalSet.empty(8))
    excluded_19ef: PascalSet = field(default_factory=lambda: PascalSet.empty(8))
    node_sets: dict[int, PascalSet] = field(default_factory=dict)

    def apply_node(
        self,
        node: AsgPhase7Node,
        type_2_enabled: bool = False,
    ) -> None:
        values = self.node_sets.setdefault(node.index, node.predicate_set)
        if node.discriminator_0c == 9:
            self.excluded_19ef.add(node.index)
        if node.rule_type == 0:
            self.state.blocks[0x699] = self.state.blocks[0x699].union(values)
            if node.flag_1b != 1 or node.index in self.state.blocks[0x681]:
                self.state.blocks[0x681] = self.state.blocks[0x681].union(values)
        elif node.rule_type == 2:
            if type_2_enabled:
                self.state.blocks[0x689].add(node.index)
                self.state.blocks[0x6A1] = self.state.blocks[0x6A1].union(values)
        elif node.rule_type == 3:
            self.state.blocks[0x681].add(node.index)
            self.state.blocks[0x699].add(node.index)
        elif node.rule_type == 4 and node.flag_1a != 0:
            self.auxiliary_4ab6.add(node.index)

    def apply_nodes(
        self,
        nodes: tuple[AsgPhase7Node, ...] | list[AsgPhase7Node],
        type_2_predicate: Callable[[AsgPhase7Node], bool] | None = None,
        runtime_rule_sets: dict[int, PascalSet] | None = None,
    ) -> None:
        node_map = {node.index: node for node in nodes}
        self.node_sets = {node.index: node.predicate_set for node in nodes}
        for node in nodes:
            if type_2_predicate is not None:
                enabled = bool(type_2_predicate(node))
            else:
                enabled = self.evaluate_type_2(node)
            self.apply_node(node, type_2_enabled=enabled)
        for node in nodes:
            self.apply_linked_closure(node.index, node_map)
        self.state.finalize_phase_7()

    def evaluate_type_2(self, node: AsgPhase7Node) -> bool:
        """Port `loc_15EA`: a type-2 node (a surface) with something on it.

        The native compares the node's own set (+0..7) with the empty set
        (`B5C2`, `B642`); a non-empty surface joins 0689 and its things 06A1.
        Read from A View to a Kill's memory after loading: the green chip
        with the tape on it is in 0689.
        """
        return len(self.node_sets.get(node.index, node.predicate_set)) != 0

    def apply_linked_closure(
        self,
        origin_index: int,
        nodes: dict[int, AsgPhase7Node],
    ) -> None:
        """Port `sub_133A`: follow +0x17 links up to 1; type-zero ones gain it.

        A link of another type (a surface, `loc_1376` -> `loc_1459`) adds
        nothing but the walk goes on: the tape on the green chip is also in
        the dome holding the chip (A View to a Kill's memory after loading).
        """
        current_index = origin_index
        visited: set[int] = set()
        while current_index not in visited:
            visited.add(current_index)
            current = nodes.get(current_index)
            if current is None or current.next_index == 1:
                return
            linked = nodes.get(current.next_index)
            if linked is None:
                return
            current_index = linked.index
            if linked.rule_type != 0:
                continue
            linked_set = self.node_sets.setdefault(linked.index, linked.predicate_set)
            linked_set.add(origin_index)
            self.state.blocks[0x699].add(origin_index)
            if linked.flag_1b != 1 or linked.index in self.state.blocks[0x681]:
                self.state.blocks[0x681].add(origin_index)
