"""AsgVm: the action VM (record action blocks, moves, room transitions, field writes)."""

from __future__ import annotations

import dataclasses
from dataclasses import field
from typing import Callable, Iterable
from .pascal_set import PascalSet
from .runtime_records import RuntimeRecord


class ActionMixin:
    """Executing action blocks and their effects on rooms, people and fields."""

    def _execute_sub_4936(self, *, current_room: int) -> None:
        """Port the matching-room Phase-9 traversal used by ``$e``.

        Starting at ``room[1AE5].exit[6AA]``, the native loop follows the
        same direction until it reaches the mutable 4ACD frontier, revisits a
        room, or encounters the context seed/sentinel.  Only a frontier hit
        becomes the new 1A52 selector.
        """

        if not self.action_state.byte_1aec:
            return
        # The context is byte_6A9's record (the cockpit), whose first exit
        # (else its second) names the vehicle's bridge record.
        context = self.graph.room(current_room)
        origin = self.graph.room(self.action_state.byte_1ae5)
        direction = self.direction_cursor_6aa
        if context is None or origin is None or not 0 <= direction < 6:
            self.action_state.byte_1a52 = 1
            return
        seed = context[0x04]
        if seed == 1:
            seed = context[0x05]
        candidate = origin[0x04 + direction]
        visited = {current_room}
        while (
            candidate not in self.rewire_rooms_4acd
            and candidate not in visited
            and candidate not in {1, seed}
        ):
            visited.add(candidate)
            room = self.graph.room(candidate)
            if room is None:
                candidate = 1
                break
            candidate = room[0x04 + direction]
        self.action_state.byte_1a52 = (
            candidate if candidate in self.rewire_rooms_4acd else 1
        )

    def execute_action_block(
        self,
        symbols: tuple[int, ...],
        *,
        current_room: int | None = None,
        current_direction: int | None = None,
    ) -> tuple[int, ...]:
        """Execute context-free opcodes from a native ``(`` action block.

        ``msg_ctrl_section`` falls directly into ``sub_EF31``. Every action
        byte is decoded by ``sub_AE27(0x32)``, so its opcode is the MESSAGE
        symbol plus ``0x32``. Returned opcodes still require command-local
        descriptors or records and remain for the contextual dispatcher.
        """

        unresolved: list[int] = []
        executor = self.actions
        self.last_action_block_length = 0
        self.last_action_gate = None
        if not symbols:
            return ()
        index = 0
        wide = {0x39, 0x3A, 0x44, 0x45, 0x4E, 0x52, 0x53, 0x54}
        # One msg_ctrl_section invocation enters sub_EF31 exactly once.
        while index < len(symbols):
            symbol = symbols[index]
            opcode = (symbol + 0x32) & 0xFF
            operand_node: int | None = None
            field_operand: int | None = None
            arithmetic_amount = 1
            if opcode in wide:
                if index + 2 >= len(symbols):
                    unresolved.append(opcode)
                    self.last_action_block_length = len(symbols)
                    break
                operand_node = symbols[index + 1] * 0x40 + symbols[index + 2]
                index += 3
                if opcode == 0x52:
                    # sub_B9E5 reads the walk's destination right behind the
                    # walker: `%` + a two-symbol VOCAB descriptor (its +3 is
                    # the room) or `=` + a room cursor (`=j`, byte_6A9).
                    destination = None
                    by_cursor = False
                    if index < len(symbols) and symbols[index] == 0x20 and index + 2 < len(symbols):
                        node = symbols[index + 1] * 0x40 + symbols[index + 2]
                        if self.vocab_nodes is not None and 0 <= node < len(self.vocab_nodes.metadata_by_node):
                            destination = self.vocab_nodes.metadata_by_node[node][3]
                        index += 3
                    elif index + 1 < len(symbols) and symbols[index] == 0x2D:
                        selector = self.cursor_selector(symbols[index + 1])
                        kind = self.cursor_context_types.get(
                            selector, self.STATIC_CURSOR_KINDS.get(selector)
                        )
                        target = self.resolve_amp_operand(symbols[index + 1], current_room=current_room)
                        if kind == 2 or selector == 0x92:
                            destination = target
                            # sub_AE9E flags only selector 92h (byte_6A9) in
                            # [bx-12h]; sub_BA7D makes that walker follow.
                            by_cursor = selector == 0x92
                        index += 2
                    self._execute_walk_action(
                        operand_node, destination, current_room=current_room, follow=by_cursor
                    )
                    self.last_action_block_length = index
                    break
            elif opcode in (0x5A, 0x5B, 0x5C, 0x5D):
                # EF31 -> BF6B -> BF0D consumes the following value-source
                # selector through sub_83D0. A zero selector is followed by a
                # three-symbol msg_dict_index literal; a non-zero selector is
                # a BBC3 native-field operand. 5C/5D read an amount source
                # first, then a second source selecting the destination.
                cursor = index + 1

                def read_source(pos: int) -> tuple[int, int, int] | None:
                    if pos >= len(symbols):
                        return None
                    selector = symbols[pos]
                    if selector != 0:
                        value = self.read_native_value(selector)
                        return value, selector, pos + 1
                    if pos + 3 >= len(symbols):
                        return None
                    value = (
                        symbols[pos + 1] * 0x1000
                        + symbols[pos + 2] * 0x40
                        + symbols[pos + 3]
                    )
                    return value, selector, pos + 4

                if opcode in (0x5C, 0x5D):
                    amount_source = read_source(cursor)
                    if amount_source is None:
                        unresolved.append(opcode)
                        self.last_action_block_length = len(symbols)
                        break
                    arithmetic_amount, _amount_selector, cursor = amount_source
                target_source = read_source(cursor)
                if target_source is None:
                    unresolved.append(opcode)
                    self.last_action_block_length = len(symbols)
                    break
                _current_value, field_operand, index = target_source
                if field_operand == 0:
                    # A literal has no writable BBC3 destination.
                    unresolved.append(opcode)
            else:
                index += 1
            # Default: the base opcode width already computed above (1 for a
            # narrow opcode, 3 for a wide opcode + its node operand). The
            # 0x4B/0x4A/0x49 branches below read fixed-width operands
            # directly out of ``symbols`` instead of advancing ``index``, so
            # they override this with their own true consumed width.
            self.last_action_block_length = index
            if opcode in (0x32, 0x33, 0x34, 0x35):
                cursor = self.action_state.byte_1a4c
                node = self.phase7_runtime.get(cursor)
                # sub_A221 / sub_A56A work on 025C[byte_6A9], the room the
                # player stands in.
                room = None if current_room is None else self.graph.room(current_room)
                gate_result = None if node is None else executor.execute_set_action(
                    opcode,
                    cursor=cursor,
                    node=node,
                    room_context=room,
                    nodes=self.phase7_runtime,
                )
                if gate_result is None:
                    unresolved.append(opcode)
                else:
                    self.last_action_gate = gate_result
            elif opcode == 0x36:
                # loc_A670 (THROW): with 1A4C in 0671 - 0699 it is dropped by
                # A56A (33h, which writes byte_4B7B) and an object of type
                # 6/7/8 (+0Dh) counts the throw in +16h (below 9); otherwise
                # byte_4B7B := 0. THROW's record 2726 gates on it: `(i|ak`.
                cursor = self.action_state.byte_1a4c
                node = self.phase7_runtime.get(cursor)
                room = None if current_room is None else self.graph.room(current_room)
                held = self.predicates.blocks[0x671].difference(self.predicates.blocks[0x699])
                if node is None or cursor not in held:
                    self.action_state.byte_4b7b = 0
                    self.last_action_gate = False
                else:
                    executor.execute_set_action(
                        0x33, cursor=cursor, node=node, room_context=room,
                        nodes=self.phase7_runtime,
                    )
                    if len(node) > 0x16 and node[0x0D] in (6, 7, 8) and node[0x16] < 9:
                        node[0x16] += 1
                    self.last_action_gate = bool(self.action_state.byte_4b7b)
            elif opcode == 0x46:
                # sub_E5EF reads 025C[byte_6A9], the room the player is in.
                room = None if current_room is None else self.graph.room(current_room)
                if room is None:
                    unresolved.append(opcode)
                else:
                    # 1A4C (the object) goes into 1A4F (the container).
                    gate_result = executor.execute_context_transfer_action(
                        nodes=self.phase7_runtime,
                        current_room_context=room,
                    )
                    self.last_action_gate = gate_result
            elif opcode in (0x5A, 0x5B, 0x5C, 0x5D) and self._adjust_person_field(
                field_operand,
                1 if opcode in (0x5A, 0x5B) else arithmetic_amount,
                subtract=opcode in (0x5B, 0x5D),
            ):
                pass
            elif (
                opcode in (0x5A, 0x5B, 0x5C, 0x5D)
                and field_operand is not None
                and 2 <= field_operand <= 4
                and self.phase7_runtime.get(self.action_state.byte_1a4c) is not None
            ):
                # sub_BB65 -> sub_B863 (both builds): BBC3 selector 41h,
                # index 2/3/4 is the 1A4C node's +0Ch/+16h/+0Dh. 5Ah/5Ch
                # add (capped at 9 by sub_BC69), 5Bh/5Dh subtract down to
                # 0. A View to a Kill's TURN CALCULATOR ON is `(;t`: +16h + 1.
                node = self.phase7_runtime[self.action_state.byte_1a4c]
                offset = {2: 0x0C, 3: 0x16, 4: 0x0D}[field_operand]
                amount = 1 if opcode in (0x5A, 0x5B) else arithmetic_amount
                current = node[offset]
                if opcode in (0x5A, 0x5C):
                    updated = min(current + amount, 9)
                else:
                    updated = current - amount if current > amount else 0
                node[offset] = updated & 0xFF
            elif opcode in (0x5A, 0x5B, 0x5C, 0x5D):
                result = executor.execute_direct(
                    opcode,
                    field_operand=field_operand,
                    amount=arithmetic_amount,
                )
                if result is None:
                    unresolved.append(opcode)
            elif opcode in (0x39, 0x3A, 0x44, 0x45):
                # Native ``loc_F12B``: after reading the two-symbol operand,
                # the action VM indexes the seven-byte node table
                # (``mul 7; add di, 6B2h``) and branches on the node's
                # *context type* -- zero selects ``sub_DCAD`` (the phase-7
                # condition table at DS:04B4), non-zero ``sub_E048`` (the room
                # table at DS:025C) -- passing the node's record index on as
                # the callee's first argument.
                #
                # Those two fields are the VOCAB entry's ``value_a`` and
                # ``value_b``, the same pair ``sub_D814`` switches on when a
                # ``$f``/``$g``/``$i`` gate *reads* this state. They have to
                # agree: OPEN has to write the record the room description
                # reads back. Room 26's ``$g td|`` resolves to "trap door"
                # (value_a=2, value_b=35), so OPEN TRAP DOOR must set room
                # record 35's +24h -- which is what makes its description flip
                # from "A small closed trap door" to "A small open trap door".
                entry = (
                    None if self.vocab_nodes is None or operand_node is None
                    else self.vocab_nodes.entry_for_message_symbol(operand_node)
                )
                if entry is None:
                    unresolved.append(opcode)
                elif entry.value_a == self.OBJECT_CONTEXT_TYPE:
                    target_node = self.phase7_runtime.get(entry.value_b)
                    room = self.graph.room(current_room or 0)
                    if target_node is None or room is None:
                        unresolved.append(opcode)
                    else:
                        executor.execute_phase7_state_action(
                            opcode,
                            target_index=entry.value_b,
                            target_node=target_node,
                            current_room_context=room,
                            nodes=self.phase7_runtime,
                            excluded_19ef=self.excluded_19ef,
                            phase7_count=self.activation.byte_19e9,
                        )
                        self.last_action_gate = bool(self.action_state.byte_4b7b)
                else:
                    target = self.graph.room(entry.value_b)
                    if target is None:
                        unresolved.append(opcode)
                    else:
                        # sub_E048 writes byte_4B7B (1 on +23h, 0 again when
                        # the door is already open or locked), and the `|`
                        # after the action reads it: record 2281's
                        # `(ktt|a^%i opens` -- TYPE OPEN DOOR.
                        self.last_action_gate = (
                            executor.execute_room_state_action(
                                opcode,
                                target_context=target,
                                current_room=current_room,
                                active_rooms=self.graph.active_rooms_4abe,
                                phase9_records=self.activation.phase9_records,
                            )
                            if self._scenery_within_reach(entry.value_b, current_room)
                            else False
                        )
            elif opcode == 0x4B:
                if len(symbols) < 3:
                    unresolved.append(opcode)
                    self.last_action_block_length = len(symbols)
                else:
                    field_operand = symbols[1]
                    value_operand = symbols[2]
                    if value_operand == 0:
                        if len(symbols) < 6:
                            unresolved.append(opcode)
                            self.last_action_block_length = len(symbols)
                            break
                        value = (
                            symbols[3] * 0x1000
                            + symbols[4] * 0x40
                            + symbols[5]
                        )
                        self.last_action_block_length = 6
                    else:
                        value = self._read_runtime_action_field(
                            self.action_state.byte_1a50, value_operand
                        )
                        self.last_action_block_length = 3
                    if value is None or not self._write_runtime_action_field(
                        self.action_state.byte_1a50, field_operand, value
                    ):
                        unresolved.append(opcode)
            elif opcode == 0x47:
                self._kill_person(current_room)
            elif opcode == 0x42:
                room = self.graph.room(current_room or 0)
                runtime = self.runtime_records.get(self.action_state.byte_1a50)
                node = self.phase7_runtime.get(self.action_state.byte_1a4c)
                if room is None or runtime is None or node is None:
                    unresolved.append(opcode)
                else:
                    _ok, updated = executor.execute_inventory_to_person_transfer(
                        current_room_context=room,
                        runtime_rule_set=runtime.raw[0x0C:0x14],
                        phase7_node=node,
                    )
                    if updated != runtime.raw[0x0C:0x14]:
                        self.runtime_records.replace(
                            runtime.index, runtime.with_rule_set(updated)
                        )
                    # GIVE's record 7307 gates "Thanks" on it: `(g|aj`.
                    self.last_action_gate = bool(self.action_state.byte_4b7b)
            elif opcode == 0x37:
                self._pour_liquid(current_room)
                self.last_action_gate = bool(self.action_state.byte_4b7b)
            elif opcode == 0x43:
                self._trade_with_person(current_room)
                self.last_action_gate = bool(self.action_state.byte_4b7b)
            elif opcode == 0x3C:
                self._step_person_holding()
                self.last_action_gate = bool(self.action_state.byte_4b7b)
            elif opcode == 0x41:
                room = self.graph.room(current_room or 0)
                runtime = self.runtime_records.get(self.action_state.byte_1a50)
                node = self.phase7_runtime.get(self.action_state.byte_1a4f)
                if room is None or runtime is None or node is None:
                    unresolved.append(opcode)
                else:
                    _ok, updated = executor.execute_runtime_to_inventory_transfer(
                        current_room_context=room,
                        runtime_rule_set=runtime.raw[0x0C:0x14],
                        phase7_node=node,
                    )
                    # sub_A94D writes byte_4B7B; record 444's `(r|as` gates
                    # "here is %b" on it.
                    self.last_action_gate = bool(self.action_state.byte_4b7b)
                    if updated != runtime.raw[0x0C:0x14]:
                        self.runtime_records.replace(
                            runtime.index, runtime.with_rule_set(updated)
                        )
            elif opcode == 0x3B:
                # sub_ADD8: byte_4B7B := 1A51 <> 1; then 1A52 := 8c65(1A51),
                # the route's next stop -- where a ride goes (Voodoo Island's
                # record 7358 `(f \7358` after a first `(c` found no 1A52).
                selected = self.action_state.byte_1a51
                self.action_state.byte_4b7b = int(selected != 1)
                if selected != 1:
                    following = self.route_next_room(selected)
                    if following is not None:
                        self.action_state.byte_1a52 = following
                self.last_action_gate = bool(self.action_state.byte_4b7b)
            elif opcode == 0x40:
                self._execute_phase9_transition_action(current_room=current_room)
                # sub_9FBC leaves byte_4B7B for the `|` that follows:
                # Forbidden Castle's GET BOAT `(c|xu` crosses or refuses.
                self.last_action_gate = bool(self.action_state.byte_4b7b)
            elif opcode == 0x38:
                # sub_9AFF writes byte_4B7B (1 when the move happened), and
                # the `|` right after `(m` reads it: record 1818's
                # `(m|ea` would otherwise print its routing bytes.
                on_foot = self.action_state.byte_1aec != 1
                handled = self._execute_room_transition_action(
                    current_room=current_room,
                    current_direction=current_direction,
                )
                # On foot a blocked slot is handled too: the gate is 4B7B.
                self.last_action_gate = bool(handled) and (
                    not on_foot or bool(self.action_state.byte_4b7b)
                )
                if not handled:
                    unresolved.append(opcode)
            elif opcode == 0x4A:
                if len(symbols) < 5 or symbols[1] < 0x10:
                    unresolved.append(opcode)
                    self.last_action_block_length = len(symbols)
                else:
                    amount = symbols[2] * 0x1000 + symbols[3] * 0x40 + symbols[4]
                    executor.execute_direct(
                        0x4A, field_operand=symbols[1], amount=amount
                    )
                    self.last_action_block_length = 5
            elif opcode in (0x4C, 0x4D):
                # F34B/F38F: sub_BED2 reads the field symbol; 4Ch makes the
                # 1A5F word negative, 4Dh positive (the start program's
                # `( w` turns 1A5F[8] from 20 into -20, as measured).
                if len(symbols) < 2:
                    unresolved.append(opcode)
                    self.last_action_block_length = len(symbols)
                else:
                    executor.execute_direct(opcode, field_operand=symbols[1])
                    self.last_action_block_length = 2
            elif opcode == 0x48:
                # loc_F19A: sub_83D0 reads the next MESSAGE symbol -- an
                # operand, not a random number -- and its value mod 6 joins
                # the one-byte set DS:0670.
                if len(symbols) < 2:
                    unresolved.append(opcode)
                    self.last_action_block_length = len(symbols)
                else:
                    executor.execute_direct(0x48, random_value=symbols[1])
                    self.last_action_block_length = 2
            elif opcode == 0x49:
                if len(symbols) < 5:
                    unresolved.append(opcode)
                    self.last_action_block_length = len(symbols)
                else:
                    amount = symbols[2] * 0x1000 + symbols[3] * 0x40 + symbols[4]
                    self.action_state.advance_native_clock(amount)
                    self.last_action_block_length = 5
            elif opcode in (0x3D, 0x3E, 0x3F, 0x55):
                executor.execute_direct(opcode)
                if opcode == 0x3D and self.save_hook is not None:
                    # GAME.000's save routine runs inside the record: its
                    # dialog prints before "Now let's continue."
                    printed = self.save_hook()
                    if printed:
                        self.action_output.append(printed)
            elif opcode == 0x53:
                descriptor = (
                    None
                    if self.vocab_nodes is None or operand_node is None
                    or not 0 <= operand_node < len(self.vocab_nodes.metadata_by_node)
                    else self.vocab_nodes.metadata_by_node[operand_node]
                )
                if descriptor is None or not executor.execute_descriptor_action(
                    opcode, descriptor=descriptor
                ):
                    unresolved.append(opcode)
                elif descriptor[2] == 2:
                    self._select_bridge_vehicle(descriptor[3])
                    self._aim_at_room(descriptor[3], current_room)
                # 53h (F40D..F4F7) leaves byte_4B7B alone, but a `|` after it
                # is still a gate on it: Voodoo Island's monkeys,
                # `(@t?|p#$*e8...`, render "One monkey comes right up to you"
                # (native), not a line break and a stray "p".
                self.last_action_gate = bool(self.action_state.byte_4b7b)
            elif opcode == 0x54:
                # sub_EF31: sub_B805 with the descriptor's value_b (+6), the
                # room the object in byte_1A4C is moved into.
                if self.vocab_nodes is None or operand_node is None or not (
                    0 <= operand_node < len(self.vocab_nodes.value_b_by_node)
                ):
                    unresolved.append(opcode)
                else:
                    moved = executor.execute_plus_t_transfer(
                        room_contexts={
                            index: room for index, room in enumerate(self.graph.rooms, start=1)
                        },
                        target_room=self.vocab_nodes.value_b_by_node[operand_node],
                        current_room=current_room,
                    )
                    if moved is None:
                        unresolved.append(opcode)
            elif opcode == 0x51:
                # sub_ACB6: 1A4C := sub_ABE0 over what is in hand (0671 -
                # 06A1) -- the next member after 1A4C, 1 past the last --
                # 1A4D := 1A4C, byte_4B7B := 1A4C != 1. Indiana Jones'
                # record 128 walks the hand with it (`($|a?`).
                state = self.action_state
                hand = self.predicates.blocks[0x671].difference(self.predicates.blocks[0x6A1])
                following = [
                    member for member in hand.values()
                    if state.byte_1a4c < member <= self.activation.byte_19e9
                ]
                state.byte_1a4c = following[0] if following else 1
                state.byte_1a4d = state.byte_1a4c
                state.byte_4b7b = int(state.byte_1a4c != 1)
                self.last_action_gate = bool(state.byte_4b7b)
            else:
                unresolved.append(opcode)
            break
        return tuple(unresolved)

    def _execute_room_transition_action(
        self,
        *,
        current_room: int | None,
        current_direction: int | None,
    ) -> bool:
        """Execute the non-rewire branch of action 38h/``sub_9AFF``.

        With ``1AEC != 1`` the native routine resolves the directional slot
        at room ``+4+byte_6AA``.  Slot 1 is blocked; otherwise byte_4B7B is
        true and rooms carrying the +23 continuation flag advance 1A52.
        The separate ``1AEC == 1`` graph-rewire branch is deliberately not
        reported as handled here.
        """

        if current_room is None:
            return False
        if self.action_state.byte_1aec == 1:
            # In a vehicle the context is the room the player sits in -- the
            # cockpit, whose +4 names the bridge record (the DB5, 21). Measured
            # 2026-10-14: every drive re-points the bridge's exits at the new
            # scenery and parks the car in one of the scenery's exit slots.
            cockpit = self.graph.room(current_room)
            if cockpit is None:
                return False
            return self._execute_room_rewire_action(cockpit, current_room=current_room)
        # sub_9AFF reads byte_6AA itself: the typed direction, or wherever a
        # record aimed it (1893's `$*a'` points it at the DB5 for GET IN;
        # the start program steps the way phase-1 +13h points).
        current_direction = self.direction_cursor_6aa
        if self.move_hook is not None:
            # The player's own move (record 1893 -> 1712 `(m`): the game
            # carries it out, passages included, and reports success.
            if not 0 <= current_direction < 6:
                return False
            self.direction_cursor_6aa = current_direction
            moved = self.move_hook(current_direction)
            # A blocked slot is still a handled action: sub_9AFF clears
            # byte_4B7B and the record renders its refusal branch.
            self.action_state.byte_4b7b = int(moved)
            return True
        room = self.graph.room(current_room)
        if room is None:
            return False
        if not 0 <= current_direction < 6:
            return False
        self.direction_cursor_6aa = current_direction
        if current_room == self.action_state.byte_1a52:
            self.action_state.byte_4b7b = 1
        else:
            target = room[0x04 + current_direction]
            self.action_state.byte_4b7b = int(target != 1)
            if target != 1:
                self.action_state.last_target_room_value = target
                if room[0x23]:
                    if self.action_state.byte_1ae3 in self.graph.active_rooms_4abe:
                        self.action_state.byte_1ae3 = current_room
                    self.action_state.byte_1a52 = target
        if current_room in self.graph.active_rooms_4abe:
            self.action_state.byte_1ae5 = self.action_state.byte_1ae4
        else:
            self.action_state.byte_1ae5 = 1
        return True

    def _execute_walk_action(
        self,
        node: int,
        destination: int | None,
        *,
        current_room: int | None,
        follow: bool = False,
    ) -> None:
        """Action 52h (IDA F258): walk a person or a Phase-9 record.

        A kind-1 descriptor is a person (sub_BA7D): unless the destination is
        a scenery record, GAME.COM 55F6 carries them into it, and byte_1AEB
        (the person following the player) becomes 1. Any other kind indexes
        DS:05B0 (sub_BB10): a record that is not a vehicle moves when the
        destination lies in its 15-byte route set at +12h; byte_4B7B tells.
        Record 3240 brings Pussy into the barn with `(%e@=j`.
        """

        self.action_state.byte_4b7b = 0
        if self.vocab_nodes is None or not 0 <= node < len(self.vocab_nodes.metadata_by_node):
            return
        metadata = self.vocab_nodes.metadata_by_node[node]
        self._walk_resolved(
            metadata[2], metadata[3], destination, current_room=current_room, follow=follow
        )

    def _walk_resolved(
        self,
        kind: int,
        index: int,
        destination: int | None,
        *,
        current_room: int | None,
        follow: bool = False,
    ) -> None:
        """52h's body once the walker is known (descriptor or cursor form)."""

        self.action_state.byte_4b7b = 0
        if destination is None or destination == 1:
            return
        if kind == 1:
            self.action_state.byte_4b7b = 1
            room = self.graph.room(destination)
            raw = self._person(index)
            if room is not None and len(room) > 0x23 and room[0x23] == 0 and raw is not None:
                self._move_person(index, raw, destination)
                self._store_person(index, raw)
            # byte_1AEB, the person who follows the player: sub_BA7D writes
            # the walker when its frame flag [bx-12h] is set, else 1. Which
            # path sets the flag is not decoded; the native screens show
            # sub_BA7D: 1AEB := the person when the destination was `=j`
            # (sub_AE9E sets the frame flag [bx-12h] for selector 92h only),
            # else 1. Pussy -- walked to `=j` by 3240 -- follows from the barn.
            self.action_state.byte_1aeb = index if follow else 1
            return
        if not 1 <= index <= len(self.phase9_runtime):
            return
        record = self.phase9_runtime[index - 1]
        if len(record) < 0x21 or record[0x11] == 2:
            return
        if destination in PascalSet.from_bytes(bytes(record[0x12:0x21]), 15):
            self.action_state.byte_4b7b = 1
            record[0x0E] = destination

    def name_body(self, word: int, body: int) -> None:
        """Turn VOCAB node ``word`` into a kind-0 word for phase-7 ``body``
        (node +2 := 0, +3 := body in DS:06B2)."""

        table = self.vocab_nodes
        if table is None or not 0 <= word < len(table.metadata_by_node):
            return
        metadata = bytearray(table.metadata_by_node[word])
        metadata[2] = 0
        metadata[3] = body
        metadata_by_node = list(table.metadata_by_node)
        metadata_by_node[word] = bytes(metadata)
        value_b_by_node = list(table.value_b_by_node)
        value_b_by_node[word] = body
        self.vocab_nodes = dataclasses.replace(
            table,
            metadata_by_node=tuple(metadata_by_node),
            value_b_by_node=tuple(value_b_by_node),
        )

    def name_dead_person_words(self, words: Iterable[int]) -> None:
        """sub_7CA8 (overlay 7D91..7DE5): a typed word naming a person
        (node +2 == 1) whose +14h is 1 -- off the map, i.e. dead -- is
        rewritten into a word for the body (+19h). Action 47h renames only
        the person's own name word; this is how GET GIRL finds "the body of
        the island girl" (Voodoo Island, measured 2026-10-18: DS:06B2 node
        100 keeps 01 06 after the kill, GET GIRL still takes the body)."""

        table = self.vocab_nodes
        if table is None:
            return
        for word in words:
            if not 0 <= word < len(table.metadata_by_node):
                continue
            metadata = self.vocab_nodes.metadata_by_node[word]
            if len(metadata) < 4 or metadata[2] != 1:
                continue
            raw = self._person(metadata[3])
            if raw is None or len(raw) <= 0x19 or raw[0x14] != 1:
                continue
            self.name_body(word, raw[0x19])

    def _kill_person(self, current_room: int | None) -> None:
        """Action 47h (sub_E244 -> E2F5..E54E): byte_1A50 dies.

        Only a person in the player's room (+14h set). They leave the map
        (+14h = 1, into room 1's people set), their body (+19h) and what they
        carried (+0Ch, then emptied) land in the room's +18h set and are
        uncovered (0681/0689/0691 lose the body), 1A4C points at the body,
        the body takes the person's name word (+2 -> phase-7 +0Ah), and the
        person's VOCAB node becomes a kind-0 word for the body -- so after
        FLIP SWITCH "Oddjob" names an object (record 7873's `$hec`, 6Eh,
        asks for a body: phase-7 +18h == 5). A dead follower stops following.
        """

        person = self.action_state.byte_1a50
        room = None if current_room is None else self.graph.room(current_room)
        raw = self._person(person)
        if room is None or raw is None or len(raw) <= 0x19 or len(room) < 0x20:
            return
        if person not in PascalSet.from_bytes(bytes(room[0x14:0x18]), 4):
            return
        body = raw[0x19]
        raw[0x14] = 1
        self.action_state.byte_1a4c = body
        held = PascalSet.from_bytes(bytes(raw[0x0C:0x14]), 8)
        room[0x18:0x20] = (
            PascalSet.from_bytes(bytes(room[0x18:0x20]), 8)
            .union(PascalSet.from_values([body], 8))
            .union(held)
            .to_bytes()
        )
        raw[0x0C:0x14] = PascalSet.empty(8).to_bytes()
        for address in (0x681, 0x689, 0x691):
            self.predicates.blocks[address] = self.predicates.blocks[address].difference(
                PascalSet.from_values([body], 8)
            )
        room[0x14:0x18] = PascalSet.from_bytes(bytes(room[0x14:0x18]), 4).difference(
            PascalSet.from_values([person], 4)
        ).to_bytes()
        node = self.phase7_runtime.get(body)
        if node is not None and len(node) > 0x0B:
            node[0x0A] = raw[2]
            node[0x0B] = raw[3]
        limbo = self.graph.room(1)
        if limbo is not None and len(limbo) >= 0x20:
            limbo[0x18:0x20] = PascalSet.from_bytes(bytes(limbo[0x18:0x20]), 8).difference(
                PascalSet.from_values([body], 8)
            ).to_bytes()
            limbo[0x14:0x18] = PascalSet.from_bytes(bytes(limbo[0x14:0x18]), 4).union(
                PascalSet.from_values([person], 4)
            ).to_bytes()
        self.name_body(raw[2] | raw[3] << 8, body)
        self._store_person(person, raw)
        if self.action_state.byte_1aeb == person:
            self.action_state.byte_1aeb = 1

    def sub_665b(self, record_id: int, current_room: int | None) -> bool:
        """Port sub_665B(record, var direction) -- overlay group 0Fh.

        Dumped live at its runtime address 0876:2F71 (2026-10-15; the IDA
        body at 665B is another group's code). A room record is within
        reach when it is the player's room (byte_6A9) -- the direction
        stays byte_6AA -- or one of that room's six exits (+4..+9): then
        byte_6AA and the out parameter become the exit slot. Record 1 and
        anything else are out of reach. Every caller passes &byte_6AA.
        """

        if current_room is not None and record_id == current_room:
            return True
        if record_id == 1 or current_room is None:
            return False
        room = self.graph.room(current_room)
        if room is None:
            return False
        for direction in range(6):
            if room[0x04 + direction] == record_id:
                self.direction_cursor_6aa = direction
                return True
        return False

    def _scenery_within_reach(self, record_id: int, current_room: int | None) -> bool:
        """sub_E048's guard: sub_665B(record, &byte_6AA) must find it.

        Measured: Goldfinger's "(zen" (close the oak door, record 1340)
        leaves the door open natively while the player is on the porch.
        """

        if self.sub_665b(record_id, current_room):
            return True
        self.action_state.byte_4b7b = 0
        return False

    def _aim_at_room(self, room_id: int, current_room: int | None) -> None:
        """53h kind 2 calls sub_665B(1A52, &byte_6AA).

        Live trace of walkthrough turn 72: the guard's `(@` puts 1A52 on the
        driveway (43), room 40's N exit, and byte_6AA reads 0 when movement
        record 1712 runs next, though the player last moved S.
        """

        self.sub_665b(room_id, current_room)

    def _select_bridge_vehicle(self, room_id: int) -> None:
        """Action 53h's kind-2 tail (IDA F48A..F4BD) plus ``sub_974B``.

        A room cursor set onto a vehicle's bridge record (DS:1ABC) selects
        that vehicle: 1A51 becomes the kind-2 Phase-9 record whose cockpit's
        first exit (else its second) is the bridge -- the last match, 1 when
        none -- and 4ADD that record's cockpit (+12h).
        """

        if room_id not in self.graph.bridge_rooms_1abc:
            return
        selected = 1
        for index, record in enumerate(self.phase9_runtime, start=1):
            if index < 2 or len(record) <= 0x12 or record[0x11] != 2:
                continue
            cockpit = self.graph.room(record[0x12])
            if cockpit is None:
                continue
            bridge = cockpit[0x04] if cockpit[0x04] != 1 else cockpit[0x05]
            if bridge == room_id:
                selected = index
        self.action_state.byte_1a51 = selected
        if 1 <= selected <= len(self.phase9_runtime):
            self.action_state.byte_4add = self.phase9_runtime[selected - 1][0x12]

    def _execute_room_rewire_action(
        self, context: bytearray, *, current_room: int
    ) -> bool:
        """Port ``sub_9AFF``'s ``1AEC == 1`` graph-rewire body (IDA 9CB6..9FB2).

        ``context`` is the room the player sits in (byte_6A9, the cockpit);
        its first non-1 exit names the bridge room (the vehicle record).
        The bridge is unhooked from the previous scenery (1AE5), re-pointed
        at the destination (1A52), and parked in the destination's first
        free exit slot allowed by its +10h mask.  4ACD gains the previous
        scenery and loses the destination unless it keeps another free
        masked slot (resident sub_1592 = set union, sub_15A0 = difference).
        Measured against the native 2026-10-14.
        """

        bridge_id = context[0x04]
        if bridge_id == 1:
            bridge_id = context[0x05]
        destination = self.action_state.byte_1a52
        if destination == 1:
            self.action_state.byte_4b7b = 0
            return True
        self.action_state.byte_4b7b = 1
        bridge = self.graph.room(bridge_id)
        destination_room = self.graph.room(destination)
        previous_id = self.action_state.byte_1ae5
        previous = self.graph.room(previous_id)
        if bridge is None or destination_room is None or previous is None:
            return False
        slot = next(
            (index for index in range(6) if previous[0x04 + index] == bridge_id),
            None,
        )
        if slot is None:
            return False
        previous[0x04 + slot] = 1
        self.rewire_rooms_4acd.add(previous_id)
        context[0x04 + slot] = bridge_id
        for index in range(6):
            bridge[0x04 + index] = destination

        mask = destination_room[0x10]
        for index in range(6):
            if mask & (1 << index) and destination_room[0x04 + index] == 1:
                destination_room[0x04 + index] = bridge_id
                bridge[0x04 + index] = current_room
                context[0x04 + index] = 1
                break

        selector = self.action_state.byte_1a51
        if 1 <= selector <= len(self.phase9_runtime):
            self.phase9_runtime[selector - 1][0x0E] = destination
        self.action_state.byte_1ae5 = destination
        bridge[0x11] = destination_room[0x11]
        self.rewire_rooms_4acd.discard(destination)
        for index in range(6):
            if mask & (1 << index) and destination_room[0x04 + index] == 1:
                self.rewire_rooms_4acd.add(destination)
        return True

    def _walk_route_records(
        self,
        current_room: int,
        *,
        render: "Callable[[int], None] | None" = None,
    ) -> None:
        """IDA 11034..110DD: every fifth move the route records walk (ab7b).

        For Phase-9 records 2..byte_19EB, skipping vehicles (+11h == 2) and
        the record the player rode this turn (40h), ab7b runs
        aafe(i, &1A51, &4ADF), sets +0Eh to 8c65(i)'s room, then
        aafe(i, &4ADF, &1A51). 8c65 sits behind an overlay thunk; measured on
        the original (turns 1-30, DS:05B0[3]): the "tardis" record steps from
        22 to 23 on moves 5, 10, 15, 20, 25, 30 without a Random call (the
        seed matches the port's every turn) -- the next room of its route
        set, which the port takes.
        """

        for index in range(2, self.activation.byte_19eb + 1):
            if index == self.last_ridden_phase9 or not 1 <= index <= len(self.phase9_runtime):
                continue
            record = self.phase9_runtime[index - 1]
            if len(record) < 0x21 or record[0x11] == 2:
                continue
            state = self.action_state
            if (
                record[0x0E] == current_room
                and state.byte_1a56 == 3
                and state.byte_1a57 == index
                and (state.word_1a54 & 0xFFFF) == (self.move_counter & 0xFFFF)
            ):
                # HYPOTHESIS (measured on Forbidden Castle, NATIVE_FAR
                # 05B0:2-5:0E, 2026-10-18): a walker the player has just met
                # -- listed in the player's room this turn, so the referent
                # since this move -- stays for this walk. The dragon waits at
                # the gorge (turn 74) and moves on five moves later; Voodoo
                # Island's donkey, met on earlier turns, leaves.
                continue
            self._announce_route_record(index, current_room, leaving=True, render=render)
            following = self.route_next_room(index)
            if following is not None:
                record[0x0E] = following
            self._announce_route_record(index, current_room, leaving=False, render=render)
        self.last_ridden_phase9 = None

    def step_allowed(self, native_room_id: int) -> bool:
        """GAME.COM 5DA2's gate for a step into a room.

        The room's +11h names a power that must be in byte_670 (the bits
        granted so far -- bit 0 from the start; Forbidden Castle's mankin
        grants the griffin's cave, +11h = 1), and its +12h an object the
        player must hold or wear (0671 + 0679 + [1]: the cave wants the
        feather, Thorn Mountain the locket). A passage additionally has to
        be open (+24h), which direction_available already asks.
        """

        room = self.graph.room(native_room_id)
        if room is None or len(room) <= 0x12:
            return True
        power = room[0x11]
        if power > 7 or not (self.predicates.byte_670 >> power) & 1:
            return False
        needed = room[0x12]
        if needed != 1:
            carried = self.predicates.blocks[0x671].union(self.predicates.blocks[0x679])
            if needed not in carried:
                return False
        return True

    def route_next_room(self, index: int) -> "int | None":
        """8c65(i): the next room of a route record's +12h set after +0Eh."""

        if not 1 <= index <= len(self.phase9_runtime):
            return None
        record = self.phase9_runtime[index - 1]
        route = PascalSet.from_bytes(bytes(record[0x12:0x21]), 15).values()
        if len(record) < 0x21 or not route:
            return None
        later = [room for room in route if room > record[0x0E]]
        return later[0] if later else route[0]

    def set_referent(self, kind: int, index: int) -> None:
        """67b6(index, kind), overlay group 0Ah (dumped live 0876:30CC).

        1A56 := kind, word 1A57 := index, word 1A54 := word_6AB. Called for
        a passage room (sub_9AFF, kind 2), a walker in the room (aafe, 3), a
        person arriving or listed (FFF5 / FB2C, 1) and every thing a listing
        prints (C3F6..C52B: 0 / 1 / 3) -- OPEN DESK leaves the plans it
        listed (measured 2026-10-15).
        """

        state = self.action_state
        state.byte_1a56 = kind & 0xFF
        state.byte_1a57 = index & 0xFFFF
        state.word_1a54 = self.move_counter & 0xFFFF

    def _announce_route_record(
        self,
        index: int,
        current_room: int,
        *,
        leaving: bool,
        render: "Callable[[int], None] | None",
    ) -> None:
        """aafe(i, var a, var b): a route record in the player's room.

        When Phase-9 record i stands in byte_6A9's room: a := i, b := 1,
        then word_1A9B renders with 1A50 = 1 (restored afterwards) and i is
        marked described (67b6(i, 3)). ab7b passes (&1A51, &4ADF) before the
        step -- 4ADF names the walker leaving -- and (&4ADF, &1A51) after it,
        so 1A51 names one arriving.
        """

        record = self.phase9_runtime[index - 1]
        if record[0x0E] != current_room:
            return
        state = self.action_state
        if leaving:
            state.byte_4adf, state.byte_1a51 = index, 1
        else:
            state.byte_1a51, state.byte_4adf = index, 1
        saved = state.byte_1a50
        state.byte_1a50 = 1
        announcement = self.table_state.array_1a8d_secondary.get(3, 0)
        if announcement and render is not None:
            render(announcement)
        self.set_referent(3, index)
        state.byte_1a50 = saved

    def _execute_phase9_transition_action(self, *, current_room: int | None) -> bool:
        """Port action 40h, native ``sub_9FBC``.

        The selected DS:5B0 record is gated by its current room byte, the
        global 0671 prerequisite set and the 15-byte destination set at +12h.
        On success 1A52 becomes the record's new +0Eh room and byte_4B7B is
        true.  Selector/destination 1 are native sentinels.
        """

        self.action_state.byte_4b7b = 0
        selector = self.action_state.byte_1a51
        destination = self.action_state.byte_1a52
        if selector == 1 or destination == 1:
            return False
        if not 1 <= selector <= len(self.phase9_runtime):
            return False
        record = self.phase9_runtime[selector - 1]
        if len(record) < 0x21 or current_room is None or record[0x0E] != current_room:
            return False
        # A0 1D: 0671 * +06h must be [] -- the record names what the rider
        # may not hold (Forbidden Castle's dragon: the sword).
        forbidden = PascalSet.from_bytes(bytes(record[0x06:0x0E]))
        held = self.predicates.blocks.get(0x671, PascalSet.empty(8))
        if len(forbidden.intersection(held)):
            return False
        destinations = PascalSet.from_bytes(bytes(record[0x12:0x21]))
        if destination not in destinations:
            return False
        # loc_948B+1 = GAME.COM 5DA2: the player rides along to 1A52 (the
        # chase capture's "tardis" carries Bond to the laser room) -- and the
        # step's gate applies: Pegasus will not carry the unworthy to the
        # flat mountain (Forbidden Castle, "Pegasus avoids you").
        if not self.step_allowed(destination):
            # 5DA2 clears byte_4B7B; sub_9FBC still sends the walker on
            # ("Pegasus avoids you, and leaves").
            record[0x0E] = destination
            self.last_ridden_phase9 = selector
            return False
        self.action_state.byte_4b7b = 1
        if self.step_hook is not None:
            self.step_hook(destination)
        record[0x0E] = destination
        self.last_ridden_phase9 = selector  # A08F: [bp-5], skipped by ab7b
        return True

    def read_native_value(self, operand: int) -> int | None:
        """Port ``sub_BD67``'s field read (``sub_BBC3`` operand decoding).

        Selector 41h: index 1 is ``438[byte_1A50] + 15h``; indices 2/3/4 are
        the phase-7 node ``4B4[byte_1A4C]`` at ``+0Ch``/``+16h``/``+0Dh``;
        index 5 is ``word_1AE8``. Selectors 58h/54h are the word arrays
        DS:1A8D/1A5F.
        """

        return self._read_runtime_action_field(self.action_state.byte_1a50, operand)

    def _adjust_person_field(
        self, operand: int | None, amount: int, *, subtract: bool
    ) -> bool:
        """sub_BF6B on field 1: ``438[byte_1A50] + 15h`` (the person's state).

        The fights count on it: FLIP's pin (`('p`, 5Bh) takes Pussy's +15h
        from 2 to 1, which is what KISS asks (`$ppaaap`).
        """

        if operand is None:
            return False
        ref = self.table_state.decode_native_field_operand(operand)
        if ref.selector != 0x41 or ref.index != 1:
            return False
        raw = self._person(self.action_state.byte_1a50)
        if raw is None or len(raw) <= 0x15:
            return True
        value = max(0, raw[0x15] - amount) if subtract else min(raw[0x15] + amount, 0xFF)
        raw[0x15] = value
        self._store_person(self.action_state.byte_1a50, raw)
        return True

    def _read_runtime_action_field(self, slot: int, operand: int) -> int | None:
        ref = self.table_state.decode_native_field_operand(operand)
        if ref.selector == 0x41:
            if ref.index == 0:
                return 0
            if ref.index == 5:
                return self.table_state.word_1ae8
            if ref.index == 1:
                record = self.runtime_records.get(slot)
                return None if record is None else record.raw[0x15]
            offset = {2: 0x0C, 3: 0x16, 4: 0x0D}.get(ref.index)
            node = self.phase7_runtime.get(self.action_state.byte_1a4c)
            if offset is None or node is None or len(node) <= offset:
                return None
            return node[offset]
        # sub_BD67 (BE76..BE92) returns the word's absolute value: High
        # Stakes' record 770 takes the clock's -1001 in 1A5F[0] as 1001
        # (`(:gv`, then `$avaayy` asks 3120 - 1001 < 780), native 2026-10-18.
        if ref.selector == 0x58:
            return abs(self.table_state._signed_word(self.table_state.array_1a8d.get(ref.index, 0)))
        if ref.selector == 0x54:
            return abs(self.table_state._signed_word(self.table_state.array_1a5f.get(ref.index, 0)))
        return None

    def _phase7_linked_mode_match(self, start: int, desired_mode: int) -> bool:
        """Implement the shared Phase-7 chain predicate from ``sub_C7DC``."""

        self.action_state.byte_4b7b = 0
        node = self.phase7_runtime.get(start)
        if node is None or len(node) <= 0x18:
            return False
        if node[0x18] == 3 and desired_mode == 0:
            desired_mode = 1

        current = start
        visited: set[int] = set()
        while current not in visited:
            visited.add(current)
            node = self.phase7_runtime.get(current)
            if node is None or len(node) <= 0x18:
                return False
            target = node[0x17]
            if target in (0, 1):
                return False
            target_node = self.phase7_runtime.get(target)
            if target_node is None or len(target_node) <= 0x18:
                return False
            if target_node[0x18] == desired_mode:
                self.action_state.byte_4ade = start
                self.action_state.byte_1a4f = target
                self.action_state.byte_4b7b = 1
                return True
            current = target
        return False

    def _write_runtime_action_field(self, slot: int, operand: int, value: int) -> bool:
        value &= 0xFFFF
        ref = self.table_state.decode_native_field_operand(operand)
        if ref.selector == 0x41:
            if ref.index == 0:
                return True
            if ref.index == 5:
                self.table_state.word_1ae8 = value
                self.table_state.word_1ae8_dirty = True
                return True
            # sub_BC69: values above 9 are stored as 9 in these byte fields.
            if 1 <= ref.index <= 4 and value > 9:
                value = 9
            if ref.index == 1:
                record = self.runtime_records.get(slot)
                if record is None:
                    return False
                raw = bytearray(record.raw)
                raw[0x15] = value & 0xFF
                self.runtime_records.replace(slot, RuntimeRecord(slot, bytes(raw)))
                return True
            offset = {2: 0x0C, 3: 0x16, 4: 0x0D}.get(ref.index)
            node = self.phase7_runtime.get(self.action_state.byte_1a4c)
            if offset is None or node is None or len(node) <= offset:
                return False
            node[offset] = value & 0xFF
            return True
        if ref.selector == 0x58:
            self.table_state.array_1a8d[ref.index] = value
            return True
        if ref.selector == 0x54:
            self.table_state.array_1a5f[ref.index] = value
            return True
        return False

    # Resolver kind each sub_AE9E cursor selector produces (the sub_AEAD /
    # sub_B09C / sub_B110 / sub_B028 / sub_AF22 / loc_AFC4 call it makes).
    # 8Bh is byte_1A52 through sub_B110 (B36E), a room-table cursor.
    STATIC_CURSOR_KINDS = {
        0x87: 0, 0x8A: 0, 0x8E: 0, 0x94: 0,
        0x8D: 1, 0x95: 1,
        0x8B: 2, 0x92: 2, 0x93: 2, 0x97: 2, 0x98: 2, 0x99: 2,
        0x8C: 3, 0x96: 3,
        0x89: 6,
        0x9B: 9,
    }

    def _step_content_cursor(self, node_index: int) -> bool:
        """Port ``sub_C93C`` with ``sub_ABE0``'s plain member walk.

        ``sub_ABE0`` has a further recursive branch for type-3 members that
        is not ported; the walk below is its non-type-3 path.
        """

        node = self.phase7_runtime.get(node_index)
        if node is None or len(node) <= 0x18 or node[0x18] != 2:
            return False
        members = PascalSet.from_bytes(bytes(node[0:8]), 8)
        if len(members) == 0:
            return False
        candidates = members.difference(self.predicates.blocks[0x699])
        limit = self.activation.byte_19e9
        current = self.action_state.byte_4ade
        if len(candidates) > 0:
            for _ in range(limit + 1):
                current = 2 if current >= limit else current + 1
                if current in candidates:
                    break
            self.action_state.byte_4ade = current
        return True

    def _container_of_type(self, node_index: int, wanted_type: int) -> bool:
        """Port ``sub_C7DC``: walk the +17 chain for a container of a type."""

        node = self.phase7_runtime.get(node_index)
        if node is None:
            return False
        if node[0x18] == 3 and wanted_type == 0:
            wanted_type = 1
        current = node_index
        seen: set[int] = set()
        while current not in seen:
            seen.add(current)
            record = self.phase7_runtime.get(current)
            if record is None:
                return False
            container = record[0x17]
            holder = self.phase7_runtime.get(container)
            if holder is not None and holder[0x18] == wanted_type:
                # Variant A (Goldfinger C863) leaves the object in 4ADE; the
                # 47-byte titles (Voodoo Island C2D1) shift the previous
                # 1A4F into it instead -- measured on Voodoo Island's record
                # 149 (2026-10-18): 4ADE 21 -> 1 -> 9 over `$nak`, `$ne9`.
                self.action_state.byte_4ade = (
                    self.action_state.byte_1a4f
                    if self.tables.record_size == 47
                    else node_index
                )
                self.action_state.byte_1a4f = container
                return True
            current = container
            if current == 1:
                return False
        return False
