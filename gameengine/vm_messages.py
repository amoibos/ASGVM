"""AsgVm: the MESSAGE record controls ($, &, %, cursors, scenery nouns)."""

from __future__ import annotations

from typing import Sequence
from .pascal_set import PascalSet
from .message import DEFAULT_SYMBOL_TABLE
from .predicates import AsgPredicateEvaluator


class MessageControlMixin:
    """Opening a MESSAGE record and evaluating its controls."""

    def open_message_record(self, *, word_6ab: int = 0, word_1a54: int = 0) -> None:
        """Run native top-level record setup ``sub_7BB7`` + ``sub_7DAC``."""

        self.action_state.initialize_dispatch_cursors(
            word_6ab=word_6ab, word_1a54=word_1a54
        )
        if self.vocab_nodes is not None:
            self.parser_cursor = self.vocab_nodes.cursor(0)

    def seed_message_work_scratch(self, *, current_room: int | None = None) -> None:
        """Rebuild DS:4B73 after ``sub_7BB7`` reset (``sub_7DAC`` / ``loc_3C36``)."""

        if self.vocab_nodes is None:
            return
        room = self.graph.room(
            current_room if current_room is not None else self.action_state.byte_1a50
        )
        self.action_state.seed_message_work_scratch(
            command_node=self.action_state.word_4b12,
            room_context=room,
            vocab_raw_by_node=self.vocab_nodes.raw_by_node,
            predicates=self.predicates,
        )

    def set_message_object_cursors(
        self,
        *,
        command_value_b: int | None,
        object_value_b: int | None,
        indirect_value_b: int | None = None,
        container_context: int | None = None,
        open_container_link: int | None = None,
        object_context_type: int = 0,
    ) -> None:
        """Bind ``byte_1A4C`` / ``byte_1A4D`` / ``byte_1A4F`` before a render.

        ``byte_1A4C`` is the direct object's ``value_b`` (live OPEN and PUT
        traces), ``byte_1A4F`` the indirect object's, and ``byte_1A4D``
        follows an open authored container (+0x18) when the object is visible
        inside it (PRESS buttons after OPEN armrest).
        """

        if object_value_b is None:
            return
        self.message_direct_object_value_b = object_value_b
        if object_context_type == self.SCENERY_CONTEXT_TYPE:
            # A kind-2 noun goes on byte_1A52 (amp selector 8Bh, the `i`
            # cursor); byte_1A4C is left at its reset value 1. Captured live
            # 2026-10-13 with a BPM on DS:4B7B during the native OPEN DOOR
            # render in native room 46:
            #
            #   hit 1: 1A4C=1  1A52=37  4B12=147
            #   hit 2: 1A4C=1  1A52=33  4B12=147
            #
            # 1A52 takes the typed word's value_b and the render's own
            # room->door table (record 2203) then re-points it at the room's
            # scenery. With 1A4C at 1, record 2315's object chain opens with
            # `&?t` ("cursor != 1") false and is skipped, so the render reaches
            # the scenery chain on `i` -- whose default branch is record 2311,
            # `+ki|ag you %e xp.`: OPEN on 1A52, then "you open <name>.".
            self.cursor_context_types[0x8B] = object_context_type
            self.action_state.byte_1a52 = object_value_b
            self.message_container_context = container_context
            return
        # Selector 8Ah is byte_1A4C, 8Eh byte_1A4F -- the two cursors a verb
        # response binds to its direct *object*.
        self.cursor_context_types[0x8A] = object_context_type
        self.cursor_context_types[0x8E] = object_context_type
        self.message_command_value_b = command_value_b
        self.message_container_context = container_context
        # The parser leaves the direct object in 1A4C and the indirect one in
        # 1A4F. Captured live 2026-10-13 during the native PUT PLANS IN DESK
        # render (BPM on DS:1A4C/1A4F): 1A4C=21 (plans), 1A4F=11 (desk),
        # 1A4D stays 1; all three return to 1 after the turn.
        if indirect_value_b is not None:
            self.action_state.byte_1a4f = indirect_value_b
        cursor = object_value_b
        context_cursor = object_value_b
        if open_container_link is not None:
            context_cursor = open_container_link
        self.action_state.byte_1a4c = cursor
        self.action_state.byte_1a4d = context_cursor

    def apply_message_continuation(self, continuation: str) -> bool:
        """Apply confirmed MESSAGE continuation descriptors to VM cursors.

        Conditional MESSAGE spans can carry a two-symbol continuation after
        ``|xx``.  The traced ``aX`` form feeds the native DS:1A4C cursor used
        by ampersand predicates such as ``&b``.  Keep unsupported forms inert
        until they are tied to a native cursor by trace/assembly evidence.
        """
        if len(continuation) < 2 or continuation[0] != "a":
            return False
        reverse = {character: symbol for symbol, character in DEFAULT_SYMBOL_TABLE.items()}
        node = reverse.get(continuation[1])
        if node is None:
            return False
        self.action_state.byte_1a4c = node
        return True

    def predicate_evaluator(
        self,
        *,
        current_room: int | None = None,
        current_command_value_b: int | None = None,
        local_set: PascalSet | None = None,
        t_record: bytes | bytearray | None = None,
    ) -> AsgPredicateEvaluator | None:
        if self.vocab_nodes is None:
            return None
        node_records = {
            index: bytes(raw) for index, raw in self.phase7_runtime.items()
        } or {node.index: node.raw for node in self.activation.phase7_nodes}
        room_records = {
            index: bytes(room) for index, room in enumerate(self.graph.rooms, start=1)
        }
        dollar_context = self.graph.room(self.action_state.byte_1a50)
        return AsgPredicateEvaluator(
            self.predicates,
            self.vocab_nodes,
            local_set=local_set,
            t_record=t_record,
            room_records=room_records,
            amp_node_records=node_records,
            x_lookup_records=node_records,
            # `$a` and `&a` index the phase-8 far-pointer table at DS:0438,
            # not the phase-6 runtime-record array.
            amp_runtime_records=room_records,
            amp_current_room=current_room,
            amp_auxiliary_4ab6=self.auxiliary_4ab6,
            amp_set_1ab8=self.set_1ab8,
            amp_set_1acb=self.set_1acb,
            dollar_context_record=dollar_context,
            amp_node_cursor_1a4c=self.action_state.byte_1a4c or None,
            amp_runtime_cursor_1a50=self.action_state.byte_1a50 or None,
            amp_current_command_value_b=current_command_value_b,
            amp_global_1a8a=bool(self.action_state.byte_1a8a),
        )

    def evaluate_message_predicate(
        self,
        kind: str,
        operand: str,
        *,
        current_room: int | None = None,
        current_command_value_b: int | None = None,
        continuation: str = "",
    ) -> bool | None:
        self.apply_message_continuation(continuation)
        evaluator = self.predicate_evaluator(
            current_room=current_room,
            current_command_value_b=current_command_value_b,
        )
        if evaluator is None:
            return None
        if kind == "&" and len(operand) >= 2:
            reverse = {character: symbol for symbol, character in DEFAULT_SYMBOL_TABLE.items()}
            node = reverse.get(operand[1])
            return None if node is None else evaluator.evaluate_amp_resolved(operand[0], node)
        return evaluator.evaluate(operand)

    def evaluate_message_control(
        self,
        kind: str,
        operands: tuple[int, ...],
        *,
        current_room: int | None = None,
        current_command_value_b: int | None = None,
        current_object_node: int | None = None,
        continuation: str = "",
        local_set: PascalSet | None = None,
    ) -> bool | None:
        """Evaluate a control while preserving its raw 6-bit operands."""

        self.apply_message_continuation(continuation)
        if local_set is None:
            local_set = self.predicates.blocks[0x679].union(
                self.predicates.blocks[0x671]
            )
        evaluator = self.predicate_evaluator(
            current_room=current_room,
            current_command_value_b=current_command_value_b,
            local_set=local_set,
        )
        if evaluator is None or not operands:
            return None
        opcode = DEFAULT_SYMBOL_TABLE.get(operands[0])
        if kind == "&" and opcode == ":" and len(operands) == 4 and operands[2] == 0x2C:
            # sub_D4C4's other operand form (loc_D595): `&:X&Y` compares two
            # cursors. It keeps X's value and enabled flag, reads Y through
            # sub_AE27(87h)/sub_AE9E -- which leaves Y's value, flag and
            # resolver kind in the frame -- and then runs the same final
            # gate: both flags set, equality, and for kind 2 the bridge walk
            # over 025C[X]. Movement record 1712 asks `&:j&g` ("is the room
            # the one the vehicle stands in?") to choose "you're still at"
            # over "you're back at".
            first = self.resolve_amp_operand(operands[1], current_room=current_room)
            second = self.resolve_amp_operand(operands[3], current_room=current_room)
            if first is None or second is None:
                return None
            selector = self.cursor_selector(operands[3])
            second_kind = self.cursor_context_types.get(
                selector, self.STATIC_CURSOR_KINDS.get(selector)
            )
            if first in (0, 1) or second in (0, 1):
                result = False
            elif second_kind == 2:
                result = AsgPredicateEvaluator.evaluate_amp_context_compare(
                    second,
                    first,
                    context_type=2,
                    cached_enabled=True,
                    comparison_room=self.graph.room(first),
                    bridge_rooms_1abc=PascalSet.from_values(
                        sorted(self.graph.bridge_rooms_1abc), 15
                    ),
                    active_rooms_4abe=PascalSet.from_values(
                        sorted(self.graph.active_rooms_4abe), 15
                    ),
                )
            else:
                result = first == second
            self.action_state.byte_4b7b = int(result)
            return result
        if kind == "&" and opcode == ":" and len(operands) >= 5:
            if self.vocab_nodes is None:
                return None
            comparison_index = operands[3] * 0x40 + operands[4]
            if not 0 <= comparison_index < len(self.vocab_nodes.raw_by_node):
                return False
            selector = self.cursor_selector(operands[1])
            primary = self.resolve_amp_operand(
                operands[1], current_room=current_room
            )
            if primary is None:
                return None
            comparison = self.vocab_nodes.metadata_by_node[comparison_index][3]
            # sub_D4C4 resolver kinds 0/1/3/6 all compare the resolved target
            # directly with candidate metadata +3.  Kind 2 adds the room
            # bridge walk below.
            enabled = primary != 1
            if selector == 0x89 and 0 <= primary < len(self.vocab_nodes.metadata_by_node):
                # word_4B12 holds the typed verb's VOCAB node; sub_AF22 makes
                # its value the node's +3 when it is a verb (kind 6, else 0)
                # and "enabled" the node index being non-zero -- so QUIT,
                # whose value is 1, still compares: `&:e$e"` in record 2167.
                # Oddjob's bowler (3300) asks `&:e$a0` -- did the player DUCK?
                enabled = primary != 0
                meta = self.vocab_nodes.metadata_by_node[primary]
                primary = meta[3] if meta[2] == 6 else 0
            if selector in (0x87, 0x89, 0x8A, 0x8C, 0x8D, 0x8E, 0x94, 0x95, 0x96):
                result = primary == comparison and enabled
                self.action_state.byte_4b7b = int(result)
                return result
            comparison_room = self.graph.room(comparison)
            result = AsgPredicateEvaluator.evaluate_amp_context_compare(
                primary,
                comparison,
                context_type=2,
                cached_enabled=primary != 1,
                comparison_room=comparison_room,
                bridge_rooms_1abc=PascalSet.from_values(
                    sorted(self.graph.bridge_rooms_1abc), 15
                ),
                active_rooms_4abe=PascalSet.from_values(
                    sorted(self.graph.active_rooms_4abe), 15
                ),
            )
            self.action_state.byte_4b7b = int(result)
            return result
        if kind == "&" and len(operands) >= 2:
            # msg_ctrl_amp reads its cached operand through sub_AE27(87h),
            # then sub_AE9E resolves the resulting selector into a runtime
            # node/context index.  The raw MESSAGE symbol is not itself a
            # Phase-7 index (the previous shortcut behind the composite-
            # response context bug).
            resolved_node = self.resolve_amp_operand(
                operands[1], current_room=current_room
            )
            if resolved_node is not None:
                decoded_opcode = 0x57 + operands[0]
                if decoded_opcode in (0x77, 0x78):
                    room = self.graph.room(resolved_node)
                    if decoded_opcode == 0x77:
                        # loc_DAD3: the room's +11h power is in byte_670.
                        result = room is not None and len(room) > 0x11 and room[0x11] <= 7 and bool(
                            (self.predicates.byte_670 >> room[0x11]) & 1
                        )
                    else:
                        # sub_BBE0: a room (not 1) whose +12h object the
                        # player holds or wears (or needs none) -- the second
                        # half of 5DA2's step gate.
                        carried = self.predicates.blocks[0x671].union(self.predicates.blocks[0x679])
                        result = (
                            resolved_node != 1
                            and room is not None
                            and len(room) > 0x12
                            and (room[0x12] == 1 or room[0x12] in carried)
                        )
                    self.action_state.byte_4b7b = int(result)
                    return result
                if decoded_opcode == 0x80:
                    # loc_DB85 -> sub_C8B6: has this thing NOT been described
                    # yet? (the membership test, inverted). Kind 2 asks 1ACB
                    # (rooms), kind 1 asks 1AB8 (people), kind 3 asks 1ADA.
                    # This is the first-visit question: `&'j` on the current
                    # room decides full description vs "You're back at %j."
                    amp_selector = self.cursor_selector(operands[1])
                    kind = self.cursor_context_types.get(
                        amp_selector, self.STATIC_CURSOR_KINDS.get(amp_selector)
                    )
                    sets = {2: self.set_1acb, 1: self.set_1ab8, 3: self.set_1ada}
                    described = sets.get(kind)
                    result = None if described is None else resolved_node not in described
                elif decoded_opcode == 0x5F:
                    # loc_DBC7: cursor 8Fh reads byte_1A8A, any other cursor
                    # the phase-7 record's +1Ah -- the flag sub_B74B flips,
                    # so `&qt` is "is it lit" (TURN OFF / LIGHT's record).
                    if self.cursor_selector(operands[1]) == 0x8F:
                        result = bool(self.action_state.byte_1a8a)
                    else:
                        record = self.phase7_runtime.get(resolved_node)
                        result = (
                            record is not None
                            and len(record) > 0x1A
                            and bool(record[0x1A])
                        )
                elif decoded_opcode == 0x75:
                    # loc_D959: the cursor's index is on the person (0679) --
                    # the same plain 8-byte membership as 81h one branch
                    # down. TAKE's record 1480 asks it (`&(t`) to tell
                    # "take it out of your pocket" (action 32h) from "take it
                    # from the room" (34h).
                    result = resolved_node in self.predicates.blocks[0x679]
                elif decoded_opcode == 0x76:
                    # loc_D97C: membership in the amp handler's own 8-byte
                    # frame set at `[bx-0Ch]`. sub_D6FD's kind-0 branch
                    # unions that same frame set with the room's +18, and the
                    # port resolves that union as (room+18) | 0671 | 0679, so
                    # the frame set is the carried set. Taken directly from
                    # the predicate banks rather than through ``local_set``,
                    # whose ``$v`` fallback invents members when nothing is
                    # carried. Record 1480 asks `&$t` right after 75h to tell
                    # "you already have it" from "you take it".
                    carried = self.predicates.blocks[0x679].union(
                        self.predicates.blocks[0x671]
                    )
                    result = resolved_node in carried
                elif decoded_opcode == 0x61:
                    # loc_DC7D: the cursor's index is something the person in
                    # 1A50 holds (438[1A50] +0Ch): The Mist's `&ub`, "Ollie:
                    # You bet." when he has the pistol asked for.
                    person = self._person(self.action_state.byte_1a50)
                    result = person is not None and resolved_node in PascalSet.from_bytes(
                        bytes(person[0x0C:0x14])
                    )
                elif decoded_opcode == 0x81:
                    # loc_D9A3: the cursor's index is in hand (0671).
                    result = resolved_node in self.predicates.blocks[0x671]
                elif decoded_opcode == 0x68:
                    # loc_DA23 -> sub_C93C: a type-2 node with something on
                    # it; the content cursor 4ADE steps to its next member
                    # (sub_ABE0 over node set - 0699).
                    result = self._step_content_cursor(resolved_node)
                elif decoded_opcode == 0x7D:
                    # loc_D92A: copy sub_AE9E's cached-enabled flag. The
                    # common AEAD/B110 resolvers define it as value != 1.
                    result = resolved_node != 1
                elif decoded_opcode == 0x6F:
                    # loc_DB61: the room record's +23h byte (scenery) of the
                    # cursor, as is: `&wi` in the door records.
                    room = self.graph.room(resolved_node)
                    result = room is not None and len(room) > 0x23 and room[0x23] != 0
                elif decoded_opcode == 0x74:
                    # sub_D6FD -- the "is this thing here" test -- switches on
                    # the cursor's resolver kind at ``ss:[bx-19h]``:
                    #
                    #   0     -> index in room[+18..+20] (8) u the local set
                    #   1     -> index in room[+14..+18] (4)
                    #   2 / 4 -> sub_665B: the player's room or one of its
                    #            exits (and byte_6AA aims there)
                    #   3     -> DS:05B0[index][+0Eh] == the room cursor
                    #   5 / 6 -> 0
                    selector = self.cursor_selector(operands[1])
                    result = self._amp_presence_test(
                        resolved_node,
                        self.cursor_context_types.get(
                            selector, self.STATIC_CURSOR_KINDS.get(selector, 0)
                        ),
                        current_room=current_room,
                    )
                elif decoded_opcode == 0x62:
                    # loc_DC44: current command VOCAB value_b is tested
                    # against set +0E of the Phase-7 node selected by 1A4C.
                    if self.vocab_nodes is None:
                        result = None
                    elif not 0 <= self.action_state.word_4b12 < len(
                        self.vocab_nodes.value_b_by_node
                    ):
                        result = False
                    else:
                        node = self.phase7_runtime.get(self.action_state.byte_1a4c)
                        if node is None or len(node) < 0x16:
                            result = False
                        else:
                            value_b = self.vocab_nodes.value_b_by_node[
                                self.action_state.word_4b12
                            ]
                            result = value_b in PascalSet.from_bytes(node[0x0E:0x16])
                elif decoded_opcode == 0x64:
                    # sub_C7DC(start, mode=0): follow the Phase-7 +17 link
                    # until the linked node's +18 mode matches. A mode-3
                    # starting node changes the requested mode from 0 to 1.
                    result = self._phase7_linked_mode_match(resolved_node, 0)
                elif decoded_opcode == 0x63:
                    # loc_DB41: the same sub_C7DC with mode 2 -- is the thing
                    # inside a (mode-2) holder? The holder goes to 1A4F, so
                    # A View to a Kill's TAKE (record 1913, `&yt`) can say
                    # "you take the watch from the corpse of 003".
                    result = self._phase7_linked_mode_match(resolved_node, 2)
                elif decoded_opcode in (0x6A, 0x6B, 0x6C, 0x6D, 0x6E, 0x70):
                    # loc_DA43/DA5B/DA73/DA8B/DAA3/DABB -> shared
                    # sub_D894(mode); 6Ah (mode 2) is PUT ... ON's "is %b a
                    # surface" test, 6Eh (mode 5, `&h`) "is it a body": GET
                    # on a killed person's body (Voodoo Island's record 728,
                    # `&ht` -> `(leaaai` makes it carriable, measured with a
                    # write breakpoint on the body's +0Ch, 2026-10-18).
                    mode = {0x6A: 2, 0x6B: 0, 0x6C: 1, 0x70: 3, 0x6D: 4, 0x6E: 5}[
                        decoded_opcode
                    ]
                    node = self.phase7_runtime.get(resolved_node)
                    result = (
                        False
                        if node is None or len(node) <= 0x18
                        else node[0x18] == mode
                    )
                elif decoded_opcode in (0x66, 0x67, 0x69):
                    # sub_C6BB: object condition-state opcodes. Guard
                    # node[+0x18]==0 (a stateful record); g(67h)=node[+0x1B],
                    # i(69h)=NOT node[+0x1B], f(66h)=node[+0x1C]. Used by EXAMINE
                    # composites for the object open/closed variant ("is open"/
                    # "is closed").
                    cond_node = resolved_node
                    # sub_D814 serves the amp form of these opcodes too, so a
                    # kind-2 cursor reads the room table, not the phase-7 one.
                    # Record 2315's scenery chain gates on `&ki` (69h) through
                    # selector 8Bh; against the phase-7 table that lands on a
                    # slot-1 alias and the whole chain goes unresolved.
                    if (
                        self.cursor_context_types.get(self.cursor_selector(operands[1]), 0)
                        == self.SCENERY_CONTEXT_TYPE
                    ):
                        result = self._fgi_state(
                            {0x67: "g", 0x69: "i", 0x66: "f"}[decoded_opcode],
                            self.graph.room(cond_node),
                            guard_offset=0x23,
                            guard_is_zero=False,
                            gi_offset=0x24,
                            f_offset=0x25,
                        )
                        if result is not None:
                            self.action_state.byte_4b7b = int(result)
                        return result
                    node = self.phase7_runtime.get(cond_node)
                    if node is None or len(node) <= 0x1C or node[0x18] != 0:
                        # Non-stateful/alias node: sub_C6BB exits without
                        # writing byte_4B7B (guard jnz). Return None so the
                        # fragment keeps its prior gate (no drop) instead of
                        # forcing False -- avoids regressing verb-response
                        # composites whose amp cursor resolves to a slot-1
                        # alias while still fixing the stateful EXAMINE case.
                        result = None
                    elif decoded_opcode == 0x67:
                        result = bool(node[0x1B])
                    elif decoded_opcode == 0x69:
                        result = not bool(node[0x1B])
                    else:  # 0x66
                        result = bool(node[0x1C])
                else:
                    result = evaluator.evaluate_amp_resolved(opcode, resolved_node)
                if result is not None:
                    self.action_state.byte_4b7b = int(result)
                return result
        # msg_ctrl_dollar decodes its opcode as symbol + 57h (sub_AE27(57h)).
        # An older reading took the ASCII code of the symbol's letter instead,
        # which agrees only for `g`: `$k` is 69h (the "not open" state test,
        # not a node-type test), `$p` is 58h (value comparison), and `$l` 70h,
        # `$m` 5Dh and `$i` 5Bh have no case at all -- the dispatcher falls
        # through and byte_4B7B keeps its value.
        decoded = (0x57 + operands[0]) & 0xFF
        if kind == "$" and decoded in (0x5B, 0x5D, 0x70):
            return bool(self.action_state.byte_4b7b)
        if kind == "$" and decoded == 0x60:
            # loc_B65D: not ported.
            return None
        if kind == "$" and decoded == 0x5E and len(operands) >= 3:
            # loc_D384 -> sub_B4EA: can the player see in the room the
            # descriptor names (its value_b, DS:6B5 + 7n)? The same test as
            # `&^` on a room cursor. High Stakes' WAIT (record 727) asks it.
            descriptor = operands[1] * 0x40 + operands[2]
            if self.vocab_nodes is None or not 0 <= descriptor < len(
                self.vocab_nodes.metadata_by_node
            ):
                return None
            evaluator = self.predicate_evaluator(
                current_room=current_room,
                current_command_value_b=current_command_value_b,
            )
            if evaluator is None:
                return None
            result = evaluator.evaluate_amp_resolved(
                "^", self.vocab_nodes.metadata_by_node[descriptor][3]
            )
            if result is not None:
                self.action_state.byte_4b7b = int(result)
            return result
        if kind == "$" and decoded == 0x85:
            # loc_D370 -> sub_B4AF: is somebody following (byte_1AEB != 1)?
            # Then that person becomes cursor 4ADC. A View to a Kill's person
            # block (record 138) asks it before Stacey's "follows you".
            follower = self.action_state.byte_1aeb
            self.action_state.byte_4b7b = int(follower != 1)
            if follower != 1:
                self.action_state.byte_4adc = follower
            return follower != 1
        if kind == "$":
            opcode = {0x66: "f", 0x67: "g", 0x69: "i"}.get(decoded, opcode)
            if decoded not in (0x66, 0x67, 0x69) and opcode in ("f", "g", "i"):
                opcode = None
        if kind == "$" and opcode in ("f", "g", "i") and len(operands) >= 1:
            # Native ``msg_ctrl_dollar`` opcodes 66h/67h/69h run
            # ``sub_469C(cx=0Eh)`` -- the two-symbol VOCAB node descriptor
            # reader -- and then ``sub_D814``, which switches on the resolved
            # entry's *context type* in its caller frame:
            #
            #   mov al, ss:[bx-19h]   ; context type
            #   cmp ax, 2  -> sub_C74C   ; room table  DS:025C
            #   cmp ax, 0  -> sub_C6BB   ; phase-7 table DS:04B4
            #   else          byte_4B7B = 0
            #
            # Both callees take the same two arguments (``ss:[bx-17h]`` =
            # record index, ``ss:[bx-9]`` = the opcode) and have the same
            # shape: a guard byte, then g/i on one state byte and f on the
            # next. ``sub_C6BB`` guards ``+18h == 0`` and reads ``+1Bh``/
            # ``+1Ch``; ``sub_C74C`` guards ``+23h != 0`` and reads ``+24h``/
            # ``+25h``. A failed guard writes byte_4B7B = 0 in both
            # (``loc_C73A`` / ``sub_C7CA``), i.e. False, not "unresolved".
            #
            # The descriptor is what makes a gate address a *specific* piece
            # of scenery rather than whatever the render cursor happens to
            # point at: room 26's ``$g td|af open ^ab closed`` resolves to
            # VOCAB node 213 = "trap door" (value_a=2, value_b=35), i.e. room
            # record 35's +24h -- and its siblings in the same room resolve to
            # "office door" (node 144, record 4) and "secret door" (node 183,
            # record 36). value_a is the context type, value_b the index.
            if len(operands) >= 3:
                resolved = self._dollar_fgi_descriptor(opcode, operands)
                if resolved is not None:
                    return resolved
            # Operand-less sibling form (``$g x$``): no descriptor to resolve,
            # so the record comes from the bound render cursor instead.
            node = self.phase7_runtime.get(self.action_state.byte_1a4c)
            if node is not None and len(node) > 0x18 and node[0x18] != 0:
                node = self.phase7_runtime.get(self.action_state.byte_1a4d)
            if node is None or len(node) <= 0x1C or node[0x18] != 0:
                return False
            if opcode == "g":
                return bool(node[0x1B])
            if opcode == "i":
                return not bool(node[0x1B])
            return bool(node[0x1C])
        if kind == "$" and 0x57 + operands[0] == 0x5F and len(operands) >= 3:
            # loc_D3A8: the two-symbol descriptor's VOCAB node gives value_b
            # (metadata +3), which indexes the phase-7 runtime table DS:04B4;
            # the gate is that record's byte `+1Ah`. Record 31 asks it about
            # the lighter (`$qp6`) right after `$!p6` ("is it carried"), i.e.
            # "is it lit" -- the dark corridor only shows the bunker door by
            # its flame.
            if self.vocab_nodes is None:
                return None
            node_index = operands[1] * 0x40 + operands[2]
            if not 0 <= node_index < len(self.vocab_nodes.metadata_by_node):
                return False
            index = self.vocab_nodes.metadata_by_node[node_index][3]
            record = self.phase7_runtime.get(index)
            if record is None or len(record) <= 0x1A:
                return False
            result = bool(record[0x1A])
            self.action_state.byte_4b7b = int(result)
            return result
        if kind == "$" and 0x57 + operands[0] == 0x74 and len(operands) >= 3:
            # loc_CB3B: the descriptor names a VOCAB entry whose value_a is the
            # resolver kind and value_b the index; the test is sub_D6FD's.
            # This is how each PRESS gadget record asks "is my effect the one
            # in play" (`$*tp|x.` -- spikes, `$*ev|t.` -- oil slick).
            # The kind and index come from the live node (DS:06B2), not the
            # shipped VOCAB entry: once the island girl is a body, Moma's
            # `$*p9` ("island girl") asks for the body (node +2 0, +3 25).
            if self.vocab_nodes is None:
                return None
            descriptor = operands[1] * 0x40 + operands[2]
            if self.vocab_nodes.entry_for_message_symbol(descriptor) is None:
                return False
            metadata = self.vocab_nodes.metadata_by_node[descriptor]
            result = self._amp_presence_test(
                metadata[3], metadata[2], current_room=current_room
            )
            if result is not None:
                self.action_state.byte_4b7b = int(result)
            return result
        if kind == "$" and 0x57 + operands[0] == 0x7E and len(operands) >= 3:
            descriptor = operands[1] * 0x40 + operands[2]
            parser_set = self.action_state.record_work_blocks.get(0x4AE9)
            return (
                None
                if parser_set is None
                else descriptor in PascalSet.from_bytes(parser_set)
            )
        if kind == "$" and 0x57 + operands[0] == 0x65:
            # loc_D211: does the current thing hold anything? Its contents
            # set ([bp-13h], the 1A4C node +0..+7) <> [] (GAME.COM 155A
            # returns 1 for unequal sets). EXAMINE SAFE: "It contains the
            # chart and the letter."
            node = self.phase7_runtime.get(self.action_state.byte_1a4c)
            result = node is not None and any(bytes(node[0:8]))
            self.action_state.byte_4b7b = int(result)
            return result
        if kind == "$" and 0x57 + operands[0] == 0x77 and len(operands) >= 3:
            # loc_CD7B: the descriptor's room (value_b) has its +11h power in
            # byte_670 -- the powers granted.
            if self.vocab_nodes is None:
                return None
            node = operands[1] * 0x40 + operands[2]
            if not 0 <= node < len(self.vocab_nodes.metadata_by_node):
                return None
            room = self.graph.room(self.vocab_nodes.metadata_by_node[node][3])
            result = room is not None and len(room) > 0x11 and room[0x11] <= 7 and bool(
                (self.predicates.byte_670 >> room[0x11]) & 1
            )
            self.action_state.byte_4b7b = int(result)
            return result
        if kind == "$" and 0x57 + operands[0] == 0x7B:
            # loc_D16C: msg_ctrl_break(0) reads one symbol, times 10 is a
            # percentage, and GAME.COM 554B answers ``percent > Random(101)``.
            # Resolved live 2026-10-14 by stepping the call (IDA's
            # "sub_8C35" is an overlay-relative address; the real callee is
            # resident GAME.COM code). All 15 uses in MESSAGE are `$,x`, a
            # coin flip: "lead car" / "lead Mercedes", "left" / "right",
            # "not here" / "not around".
            if len(operands) < 2:
                return None
            result = self.percent_chance(operands[1] * 10)
            self.action_state.byte_4b7b = int(result)
            return result
        if kind == "$" and 0x57 + operands[0] == 0x79 and len(operands) >= 2:
            result = evaluator.evaluate_resolved("y", raw_symbol=operands[1])
            if result is not None:
                self.action_state.byte_4b7b = int(result)
            return result
        if kind == "$" and 0x57 + operands[0] == 0x84 and len(operands) >= 2:
            # loc_D19B: is the carried-item count word_6AD at least the raw
            # operand symbol? (TAKE's "you're holding too much" test.)
            result = self.action_state.word_6ad >= operands[1]
            self.action_state.byte_4b7b = int(result)
            return result
        if kind == "$" and 0x57 + operands[0] == 0x7F and len(operands) >= 3:
            result = self._parser_context_member(operands[1] * 0x40 + operands[2])
            if result is not None:
                self.action_state.byte_4b7b = int(result)
            return result
        if kind == "$" and 0x57 + operands[0] == 0x81 and len(operands) >= 3:
            # loc_CF34: the descriptor's value_b is carried (0671).
            if self.vocab_nodes is None:
                return None
            node = operands[1] * 0x40 + operands[2]
            if not 0 <= node < len(self.vocab_nodes.value_b_by_node):
                return False
            result = self.vocab_nodes.value_b_by_node[node] in self.predicates.blocks[0x671]
            self.action_state.byte_4b7b = int(result)
            return result
        if kind == "$" and 0x57 + operands[0] in (0x63, 0x64) and len(operands) >= 3:
            # loc_D1C1 / loc_D1E9: sub_C7DC(value_b, 2 or 0) -- does the
            # described object sit (anywhere up its +17 chain) in a container
            # of that type? A hit also leaves the object in 4ADE and the
            # container in 1A4F (record 270 relies on that to put the golf
            # ball and the club back on the plaque).
            if self.vocab_nodes is None:
                return None
            node_index = operands[1] * 0x40 + operands[2]
            if not 0 <= node_index < len(self.vocab_nodes.value_b_by_node):
                return False
            result = self._container_of_type(
                self.vocab_nodes.value_b_by_node[node_index],
                2 if 0x57 + operands[0] == 0x63 else 0,
            )
            self.action_state.byte_4b7b = int(result)
            return result
        if kind == "$" and 0x57 + operands[0] == 0x6E and len(operands) >= 3:
            # loc_D2B4: is the descriptor a kind-0 word whose object is a
            # body (phase-7 +18h == 5)? A person's word turns into one when
            # they die (action 47h): record 7873 asks it of Oddjob for the
            # helicopter's lift-off.
            if self.vocab_nodes is None:
                return None
            node = operands[1] * 0x40 + operands[2]
            if not 0 <= node < len(self.vocab_nodes.metadata_by_node):
                return False
            metadata = self.vocab_nodes.metadata_by_node[node]
            record = self.phase7_runtime.get(metadata[3]) if metadata[2] == 0 else None
            result = record is not None and len(record) > 0x18 and record[0x18] == 5
            self.action_state.byte_4b7b = int(result)
            return result
        if kind == "$" and 0x57 + operands[0] == 0x80 and len(operands) >= 3:
            # loc_D22F -> sub_C8B6(value, kind): has the descriptor's thing
            # NOT been described yet? Kind 1 asks 1AB8 (people), 2 asks 1ACB
            # (rooms), 3 asks 1ADA. Pussy Galore's description asks it of
            # herself (`$'e@`) for "As she leaps into a judo fighting stance".
            if self.vocab_nodes is None:
                return None
            node = operands[1] * 0x40 + operands[2]
            if not 0 <= node < len(self.vocab_nodes.metadata_by_node):
                return None
            metadata = self.vocab_nodes.metadata_by_node[node]
            described = {1: self.set_1ab8, 2: self.set_1acb, 3: self.set_1ada}.get(metadata[2])
            if described is None:
                return None
            result = metadata[3] not in described
            self.action_state.byte_4b7b = int(result)
            return result
        if kind == "$" and 0x57 + operands[0] == 0x72:
            # loc_CD4D: (context room +18) - 0699 <> [] -- is there anything
            # to list? Record 270's default branch gates "You see ..." on it
            # (the DB5's cockpit: the car key and the armrest).
            room_index = self._context_room(current_room)
            room = None if room_index is None else self.graph.room(room_index)
            if room is None or len(room) < 0x20:
                return None
            visible = PascalSet.from_bytes(bytes(room[0x18:0x20]), 8).difference(
                self.predicates.blocks[0x699]
            )
            result = bool(visible.values())
            self.action_state.byte_4b7b = int(result)
            return result
        if kind == "$" and 0x57 + operands[0] == 0x73:
            # loc_CDFF -> GAME.COM 308A: DS:025C[byte_6A9] + 4 + byte_6AA == 1
            # -- the player's room has no exit along the move's direction.
            # Record 1712 asks it after a refused `(m` (`$|` then `|pk`): a
            # dead end gets the "can't go that way" selector, anything else
            # (a closed door) its "... is closed." branch.
            room = None if current_room is None else self.graph.room(current_room)
            direction = self.direction_cursor_6aa
            if room is None or not 0 <= direction < 6 or len(room) <= 4 + direction:
                return None
            result = room[4 + direction] == 1
            self.action_state.byte_4b7b = int(result)
            return result
        if kind == "$" and 0x57 + operands[0] == 0x61 and len(operands) >= 3:
            # loc_CEB3 (A View to a Kill; the same branch in both builds): the
            # descriptor's value_b is in the +0Ch set of person 1A50 -- does
            # the person carry it? M's "I happen to have a clip here." asks
            # it (`$ua2`) before handing the clip over with action 41h.
            if self.vocab_nodes is None:
                return None
            value_b = self.vocab_nodes.value_b_for_message_symbol(
                operands[1] * 0x40 + operands[2]
            )
            person = self._person(self.action_state.byte_1a50)
            if value_b is None or person is None or len(person) < 0x14:
                return None
            result = value_b in PascalSet.from_bytes(bytes(person[0x0C:0x14]), 8)
            self.action_state.byte_4b7b = int(result)
            return result
        if kind == "$" and 0x57 + operands[0] == 0x75 and len(operands) >= 3:
            # loc_CED7: sub_AE63's descriptor value_b in (0679 - 0699) -- on
            # the person and not stowed away. Record 911 asks it of the
            # badge (`$uah`): the Auric Stud guard only asks a man wearing
            # one for the password.
            if self.vocab_nodes is None:
                return None
            value_b = self.vocab_nodes.value_b_for_message_symbol(
                operands[1] * 0x40 + operands[2]
            )
            if value_b is None:
                return None
            result = value_b in self.predicates.blocks[0x679].difference(
                self.predicates.blocks[0x699]
            )
            self.action_state.byte_4b7b = int(result)
            return result
        if kind == "$" and 0x57 + operands[0] == 0x76 and len(operands) >= 3:
            # loc_CF0A: sub_AE63 reads a two-symbol descriptor
            # (msg_ctrl_break(1)) and returns that node's value_b (+6), which
            # is tested against the frame's local set.
            value_b = self.vocab_nodes.value_b_for_message_symbol(
                operands[1] * 0x40 + operands[2]
            )
            result = (
                None
                if value_b is None
                else evaluator.evaluate_resolved("v", value_b=value_b)
            )
            if result is not None:
                self.action_state.byte_4b7b = int(result)
            return result
        if kind == "$" and len(operands) == 1 and 0x57 + operands[0] == 0x5A:
            # msg_ctrl_dollar has no 5Ah case: the dispatcher falls through
            # without writing byte_4B7B, so the following `|` gate sees the
            # value the previous control left there.
            return bool(self.action_state.byte_4b7b)
        if kind == "$" and 0x57 + operands[0] == 0x74 and len(operands) >= 3:
            # loc_CDC1 -> loc_CB3B. sub_9711 returns byte_1A52 (falling back
            # to loc_6A7+2 only for sentinel 1); the result indexes the
            # DS:025C room/context pointer table. msg_ctrl_break(1) supplies
            # the two-symbol VOCAB descriptor whose +3 value is tested by the
            # shared type-dispatch (`t`) against that context record.
            descriptor = operands[1] * 0x40 + operands[2]
            if self.vocab_nodes is None or not 0 <= descriptor < len(
                self.vocab_nodes.metadata_by_node
            ):
                return False
            metadata = self.vocab_nodes.metadata_by_node[descriptor]
            if len(metadata) < 4:
                return False
            context_index = self.action_state.byte_1a52
            context = self.graph.room(context_index)
            if context is None:
                return None
            typed_evaluator = self.predicate_evaluator(
                current_room=current_room,
                current_command_value_b=current_command_value_b,
                t_record=bytes(context),
            )
            return (
                None
                if typed_evaluator is None
                else typed_evaluator.evaluate_resolved("t", value_b=metadata[3])
            )
        if kind == "$" and 0x57 + operands[0] in (0x57, 0x58, 0x59):
            cursor = 1

            def read_source() -> int | None:
                nonlocal cursor
                if cursor >= len(operands):
                    return None
                selector = operands[cursor]
                cursor += 1
                if selector != 0:
                    return self.read_native_value(selector)
                if cursor + 2 >= len(operands):
                    return None
                value = (
                    operands[cursor] * 0x1000
                    + operands[cursor + 1] * 0x40
                    + operands[cursor + 2]
                )
                cursor += 3
                return value

            left = read_source()
            right = read_source()
            if left is None or right is None:
                return None
            selector = 0x57 + operands[0]
            if selector == 0x57:
                return left < right
            if selector == 0x58:
                return left == right
            return left <= right
        if kind == "$" and opcode == "e":
            cursor = self.action_state.byte_1a4c
            descriptor = next(
                (node.raw for node in self.activation.phase7_nodes if node.index == cursor),
                None,
            )
            if descriptor is None:
                return None
            selected = self.action_state.byte_1a51
            matching_phase9_room = False
            if 1 <= selected <= len(self.phase9_runtime) and current_room is not None:
                record = self.phase9_runtime[selected - 1]
                matching_phase9_room = len(record) > 0x0E and record[0x0E] == current_room
            result = self.action_state.evaluate_sub_4c44_prefix(
                descriptor,
                phase9_records=tuple(bytes(record) for record in self.phase9_runtime),
                current_room=current_room,
            )
            if matching_phase9_room and current_room is not None:
                self._execute_sub_4936(current_room=current_room)
            if self.action_state.section_state == 5 and current_room is not None:
                context = self.graph.room(current_room)
                if context is not None:
                    self.action_state.select_sub_3870_response(
                        context,
                        tuple(record.raw for record in self.runtime_records.records),
                    )
            return result
        operand = "".join(DEFAULT_SYMBOL_TABLE.get(value, "?") for value in operands)
        return self.evaluate_message_predicate(
            kind,
            operand,
            current_room=current_room,
            current_command_value_b=current_command_value_b,
        )

    # Context types understood by native ``sub_D814``: 0 selects the phase-7
    # condition table at DS:04B4 (``sub_C6BB``), 2 the room table at DS:025C
    # (``sub_C74C``). Every other value falls through to byte_4B7B = 0.
    SCENERY_CONTEXT_TYPE = 2
    OBJECT_CONTEXT_TYPE = 0

    def _context_room(self, current_room: int | None) -> int | None:
        """Port ``sub_9711``: the room the presence tests run against.

        ``byte_1A52 == 1 ? byte_6A9 : byte_1A52`` -- the room-context cursor,
        falling back to the current room while that cursor is at its reset
        value. Composite records switch it on purpose: every PRESS gadget
        record runs ``(@pt`` (53h, kind 2 -> 1A52 = 22) right before asking
        ``$*`` whether its effect is present, so the question is put to record
        22, not to the room the player stands in.
        """

        value = self.action_state.byte_1a52
        return current_room if value in (0, 1) else value

    def _amp_presence_test(
        self, index: int, context_type: int, *, current_room: int | None
    ) -> "bool | None":
        """Port ``sub_D6FD`` / ``loc_CB3B``, the resolver-kind presence switch.

        Amp opcode 74h and dollar selector 74h (``$*``) run the same code; the
        dollar form only takes its kind and index from a two-symbol VOCAB
        descriptor instead of a cursor. Both read the room through
        ``sub_9711`` (see :meth:`_context_room`), and kind 3 compares against
        that same value.
        """

        room_index = self._context_room(current_room)

        if context_type in (2, 4):
            # IDA D799..D7B0: sub_665B(index, &byte_6AA) and nothing else.
            return self.sub_665b(index, current_room)
        if context_type in (5, 6):
            return False
        if context_type == 3:
            # 5B0[index] is phase9_runtime[index - 1], as everywhere else.
            if not 1 <= index <= len(self.phase9_runtime):
                return False
            record = self.phase9_runtime[index - 1]
            if len(record) <= 0x0E:
                return False
            return record[0x0E] == room_index
        room = None if room_index is None else self.graph.room(room_index)
        if room is None:
            return None
        if context_type == 1:
            if len(room) < 0x18:
                return None
            return index in PascalSet.from_bytes(bytes(room[0x14:0x18]))
        if len(room) < 0x20:
            return None
        accepted = (
            PascalSet.from_bytes(bytes(room[0x18:0x20]))
            .union(self.predicates.blocks[0x671])
            .union(self.predicates.blocks[0x679])
        )
        return index in accepted

    def scenery_record_candidates(
        self, typed_word: str, *, current_room: int | None
    ) -> "list[int]":
        """The current room's scenery whose name ends with ``typed_word``.

        Scenery records are room-table records carrying state (``+23 != 0``),
        and a room reaches its own scenery through its six exit bytes: native
        room 27's only scenery exit is 35 (the trap door), room 30's are
        4/36/35 (office door north, secret door east, trap door up -- exactly
        what its description lists), room 46's is 33 (the barn door).

        Matching is on the word, not on ``class_id``: all 66 scenery nouns
        share class 51, so the class cannot tell a door from a window. The
        word can, and the data says it is the discriminator -- see
        :meth:`resolve_scenery_noun` for the two live captures that pin this.
        """

        if current_room is None or self.vocab_nodes is None or not typed_word:
            return []
        room = self.graph.room(current_room)
        if room is None or len(room) < 0x0A:
            return []
        names: dict[int, str] = {}
        for entry in self.vocab_nodes.entries_by_node:
            if entry is None or entry.value_a != self.SCENERY_CONTEXT_TYPE:
                continue
            # Prefer the fuller name for a record addressed by several words
            # ("steel door" over the bare "door" for record 37).
            if len(entry.word) > len(names.get(entry.value_b, "")):
                names[entry.value_b] = entry.word
        candidates: list[int] = []
        for target in room[0x04:0x0A]:
            record = self.graph.room(target)
            if record is None or len(record) <= 0x23 or record[0x23] == 0:
                continue
            name = names.get(target, "")
            if name != typed_word and not name.endswith(" " + typed_word):
                continue
            if target not in candidates:
                candidates.append(target)
        return candidates

    def resolve_scenery_noun(
        self, value_b: int, typed_word: str, *, current_room: int | None
    ) -> "int | None":
        """Resolve a kind-2 noun against the room, the way the native does.

        Two live captures (DOSBox-X, 2026-10-13, SAVE2 -> N -> E, native room
        46 -- the yard, whose only scenery exit is 33, the barn door):

        * ``OPEN DOOR`` answers "You open the barn door." and sets **room
          record 33's** ``+24``, leaving record 37 -- the value_b of the word
          "door" the player typed, i.e. the steel door elsewhere -- untouched.
        * ``OPEN WINDOW`` in the same room answers "The french window is not
          around.", i.e. it stays on record 50, the value_b of "window".

        So a scenery noun is resolved against the room by *name*: the room's
        scenery that the typed word names. "barn door" answers to "door";
        nothing in that room answers to "window", so the subject stays the
        typed noun's own record and the response reports it as absent.

        A direct hit wins, which is what makes native room 32 answer "The
        steel door opens." for `door`: 37 is itself one of that room's scenery
        exits there. With no scenery exits at all the native says "There's no
        door here." (also captured live, in native room 45).

        Grade: *observed*. Inferred from the data rather than read from the
        disassembly, but consistent with five independent data points -- the
        two captures above plus the walkthrough's `OPEN DOOR` in native rooms
        27 ("you open the trap door.", exit 35), 32 ("The steel door opens.",
        direct hit 37) and 59 (the reinforced-door branch, exit 58).
        """

        candidates = self.scenery_record_candidates(
            typed_word, current_room=current_room
        )
        if value_b in candidates:
            return value_b
        if not candidates:
            return None
        # The native candidate loop writes its result for every qualifying
        # entry, so the last one wins (see
        # AsgPredicateEvaluator.star_mode3_target_match's kind-2 branch).
        return candidates[-1]

    def _dollar_fgi_descriptor(
        self, opcode: str, operands: "Sequence[int]"
    ) -> "bool | None":
        """Evaluate ``$f``/``$g``/``$i`` through their VOCAB node descriptor.

        Port of ``sub_D814``'s context switch plus both of its callees. The
        descriptor is a two-symbol 12-bit index into the runtime VOCAB node
        table; the entry's ``value_a`` is the context type ``sub_D814`` reads
        from ``ss:[bx-19h]`` and its ``value_b`` the record index it passes on
        as ``ss:[bx-17h]``.

        Returns ``None`` only when the descriptor cannot be resolved at all
        (no VOCAB table, or an index with no entry), so the caller can fall
        back to its cursor-based path. A resolved descriptor whose context
        type is neither 0 nor 2 is ``False``, matching ``loc_D887``.
        """

        if self.vocab_nodes is None:
            return None
        node_index = operands[1] * 0x40 + operands[2]
        entry = self.vocab_nodes.entry_for_message_symbol(node_index)
        if entry is None:
            return None
        if entry.value_a == self.SCENERY_CONTEXT_TYPE:
            return self._fgi_state(
                opcode,
                self.graph.room(entry.value_b),
                guard_offset=0x23,
                guard_is_zero=False,
                gi_offset=0x24,
                f_offset=0x25,
            )
        if entry.value_a == self.OBJECT_CONTEXT_TYPE:
            return self._fgi_state(
                opcode,
                self.phase7_runtime.get(entry.value_b),
                guard_offset=0x18,
                guard_is_zero=True,
                gi_offset=0x1B,
                f_offset=0x1C,
            )
        return False

    @staticmethod
    def _fgi_state(
        opcode: str,
        record: "bytes | bytearray | None",
        *,
        guard_offset: int,
        guard_is_zero: bool,
        gi_offset: int,
        f_offset: int,
    ) -> bool:
        """The shape shared by ``sub_C6BB`` and ``sub_C74C``.

        A guard byte decides whether the record carries state at all; a failed
        guard writes byte_4B7B = 0 in both callees rather than leaving the
        previous value, so this returns ``False``.
        """

        if record is None or len(record) <= max(gi_offset, f_offset):
            return False
        guarded = record[guard_offset] == 0
        if guarded is not guard_is_zero:
            return False
        if opcode == "g":
            return bool(record[gi_offset])
        if opcode == "i":
            return not bool(record[gi_offset])
        return bool(record[f_offset])

    def cursor_selector(self, symbol: int) -> int:
        """sub_AE27(87h): a cursor symbol's selector, in variant-A numbering.

        Both engine variants add 87h to the symbol, but their sub_AE9E
        tables differ from 91h on: the 40-byte titles (Goldfinger, Indiana
        Jones) map 92h..9Bh to 6A9, 4ADD, 4ADE, 4ADC, 4ADF, 1AE3, 1AE5,
        1AE4, -, 1A59; the 47-byte titles (A View to a Kill, Rambo, The
        Mist, Voodoo Island -- read from their disassemblies) map 91h..9Ah
        to the same globals. The port keeps the variant-A numbers, so a
        variant-B selector from 91h up moves one higher.
        """

        selector = 0x87 + (symbol & 0xFF)
        if self.tables.record_size == 47 and selector >= 0x91:
            selector += 1
        return selector

    def resolve_amp_operand(
        self, symbol: int, *, current_room: int | None = None
    ) -> int | None:
        """Port ``sub_AE27(87h)`` + ``sub_AE9E`` operand selection.

        ``msg_ctrl_amp`` does not use its second MESSAGE symbol as a direct
        node index. ``sub_AE27`` adds ``0x87`` and ``sub_AE9E`` maps the
        resulting selector to the active VM cursor/global. This mapping is
        part of the shared GAME.000 VM and is identical across sibling titles.
        Unhandled selector slots deliberately return ``None``; the native
        dispatcher has no branch for them either.
        """

        selector = self.cursor_selector((symbol & 0xFF))
        state = self.action_state
        if selector == 0x87:
            room = self.graph.room(state.byte_1a52)
            return None if room is None or len(room) <= 0x12 else room[0x12]
        direct = {
            0x89: state.word_4b12,
            0x8A: state.byte_1a4c,
            0x8B: state.byte_1a52,
            0x8C: state.byte_1a51,
            0x8D: state.byte_1a50,
            0x8E: state.byte_1a4f,
            0x92: current_room,
            0x93: state.byte_4add,
            0x94: state.byte_4ade,
            0x95: state.byte_4adc,
            0x96: state.byte_4adf,
            0x97: state.byte_1ae3,
            0x98: state.byte_1ae5,
            0x99: state.byte_1ae4,
            0x9B: state.byte_1a59,
        }
        return direct.get(selector)
