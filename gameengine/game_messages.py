"""AsgGame: opening and rendering MESSAGE records in the running game."""

from __future__ import annotations

from typing import Callable
from gameengine.gamecom import GameComMessageEngine
from gameengine.message_controls import ConditionalSpan
from gameengine.message import DEFAULT_SYMBOL_TABLE
from gameengine.message_controls import star_control_mode
from gameengine.pascal_set import PascalSet
from gameengine.tables import OBJECT_INITIAL_CONTAINER_OFFSET
from gameengine.world import Room
from gameengine.vm import AsgVm
from gameengine.config import NativeSpan


class MessageMixin:
    """Message records, their controls and spans, and the location/substitution texts."""

    def _open_message_record(self) -> None:
        """Run the native top-level MESSAGE record setup on the shared VM."""

        if self._rendering_turn_tail:
            # The end-of-turn records (timers, arrivals) are rendered by 970e
            # with the cursors and the parser scratch DS:4B63 as the command
            # left them -- record 3511 restores 1A52 from 4B69 (`+,i`, 56h)
            # and relies on getting the command's value back (measured: 16
            # after the drive west at walkthrough turn 2).
            return
        # sub_7BB7 expires the referent two moves after 67b6 / sub_3472 set
        # it; both run the native move counter word_6AB.
        word_6ab = self.vm.move_counter
        word_1a54 = self.vm.action_state.word_1a54
        self.vm.open_message_record(word_6ab=word_6ab, word_1a54=word_1a54)
        if self._current_person_value is not None:
            # loc_3548: the person the sentence is about goes to 4ADC,
            # cursor `c` -- Pussy's answer about Goldfinger is the `*tc`
            # candidate for person 2.
            self.vm.action_state.byte_4adc = self._current_person_value
        # Native ``word_4B12`` is copied from ``word_1A0E`` and addresses
        # the current command WORD (the verb), not its direct object.  The
        # two nodes happen to share value_b for commands such as
        # ``OPEN ARMREST``, which hid this binding error until the ``&:j``
        # predicate inspected the node's other metadata bytes.
        if self._current_typed_person is not None:
            # HYPOTHESIS: the sentence dispatchers put a typed person in
            # 1A50 (Voodoo Island's KILL BOB WITH STICK asks `&?m` and the
            # original answers "Bob isn't around.", 2026-10-18).
            self.vm.action_state.byte_1a50 = self._current_typed_person
        if self._current_beast_value is not None:
            # Voodoo Island's WAIT FOR TAXI: record 352 asks `&?c` (4ADF).
            self.vm.action_state.byte_4adf = self._current_beast_value
            # The object dispatcher (overlay 4F9B) puts a kind-3 noun in
            # 1A51 as it puts a kind-0 one in 1A4C: EXAMINE DONKEY's `&?x`.
            self.vm.action_state.byte_1a51 = self._current_beast_value
        if self._current_command_node is not None:
            self.vm.action_state.word_4b12 = self._current_command_node
        current_room = (
            None if self.state.current_room is None else self.state.current_room + 1
        )
        self.vm.seed_message_work_scratch(current_room=current_room)
        # The native plain-verb response emitter enters record 2315 with
        # byte_1A4C equal to the parsed direct object's value_b (live capture:
        # OPEN ARMREST -> 0x11).  Amp operand selector 8Ah then resolves to
        # this cursor; leaving the top-level reset value 1 here made every
        # object-sensitive amp predicate inspect the default Phase-7 node.
        if self._current_object_node is not None:
            object_entry = self.vm.vocab_nodes.entries_by_node[self._current_object_node]
            if object_entry is not None:
                container_context: int | None = None
                open_container_link: int | None = None
                # A kind-2 noun names a piece of the room, so it is resolved
                # against the room's scenery before it becomes a cursor; the
                # value_b of the word the player typed is only a candidate.
                # See AsgVm.resolve_scenery_noun for the live confirmation.
                object_value_b = (
                    # The live node value (a dead person's name now names the body).
                    self.vm.vocab_nodes.value_b_by_node[self._current_object_node]
                    if self._current_scenery_value_b is None
                    else self._current_scenery_value_b
                )
                record = self.object_record(object_value_b)
                if record is not None:
                    container = self._container_link(record)
                    if container is not None and container in self.state.opened:
                        open_container_link = container
                indirect_value_b: int | None = None
                if self._current_indirect_object_node is not None:
                    indirect_entry = self.vm.vocab_nodes.entries_by_node[
                        self._current_indirect_object_node
                    ]
                    if indirect_entry is not None:
                        indirect_value_b = self.vm.vocab_nodes.value_b_by_node[
                            self._current_indirect_object_node
                        ]
                        container_context = indirect_value_b
                self.vm.set_message_object_cursors(
                    command_value_b=self._current_command_value_b,
                    object_value_b=object_value_b,
                    indirect_value_b=indirect_value_b,
                    container_context=container_context,
                    open_container_link=open_container_link,
                    # The resolver kind that travels with the cursor: 0 for a
                    # real object, 2 for a noun that only exists as part of a
                    # room. See AsgVm.cursor_context_types.
                    object_context_type=self.vm.vocab_nodes.metadata_by_node[
                        self._current_object_node
                    ][2],
                )
        if getattr(self, "_current_4ade", None) is not None:
            # After the record-open reset, like 1A52 below.
            self.vm.action_state.byte_4ade = self._current_4ade
        elif (
            getattr(self, "_current_dispatcher", None) in (0x423E, 0x3AD5)
            and self._current_parsed is not None
        ):
            # sub_423E ends its cursor set-up with sub_37B9 (IDA 4404), and
            # so does sub_3AD5 (IDA 3CB1).
            self._select_typed_object_4ade(self._current_parsed)
        elif getattr(self, "_current_dispatcher", None) == 0x3E2E:
            # sub_3E2E's tail (IDA 3EE3..3F3B): with 4ADE still 1 it becomes
            # 1A4C's container (+17h); without a class-0Ch word typed (4AE2)
            # a 1A4F equal to it is cleared. POUR PESTICIDE INTO SPRAYER:
            # 4ADE is the bottle the pesticide stands in.
            state = self.vm.action_state
            if state.byte_4ade == 1:
                node = self.vm.phase7_runtime.get(state.byte_1a4c)
                if node is not None and len(node) > 0x17:
                    state.byte_4ade = node[0x17]
            typed_classes = PascalSet.from_bytes(
                bytes(state.record_work_blocks.get(0x4AE2, bytes(7)))[:7], 7
            )
            if 0x0C not in typed_classes and state.byte_4ade == state.byte_1a4f:
                state.byte_1a4f = 1
        elif getattr(self, "_current_dispatcher", None) == 0x3CCC:
            # sub_3CCC: 1A4F := the WITH noun (sub_35FB) -- its object is
            # a person, so the object-cursor set-up above did not run --
            # and at the end 4ADE := 1A4F (IDA 3DF5).
            if self._current_indirect_object_node is not None:
                self.vm.action_state.byte_1a4f = self.vm.vocab_nodes.value_b_by_node[
                    self._current_indirect_object_node
                ]
            self.vm.action_state.byte_4ade = self.vm.action_state.byte_1a4f
        object_is_place = (
            self._current_object_node is not None
            and self.vm.vocab_nodes.metadata_by_node[self._current_object_node][2] == 0x02
        )
        if self._current_place_value_b is not None and not object_is_place:
            # A place that is not the verb's own object still moves the
            # presence tests there (_context_room): TAKE BADGE TO AIRPORT
            # asks whether the badge is at the airport -- "not around".
            self.vm.action_state.byte_1a52 = self._current_place_value_b
        # DS:4AE9 parser work set for ``$0x7E`` / ``*`` mode-1 gates (see
        # ``_build_parser_work_set``).
        self.vm.action_state.record_work_blocks[0x4AE9] = self._build_parser_work_set()
        self.vm.build_parser_context_sets(
            PascalSet.from_bytes(self.vm.action_state.record_work_blocks[0x4AE9]).values()
        )
        # Room descriptions bind the amp room-context cursor (byte_1A52, amp
        # selector 8Bh) to the current room -- after sub_7BB7's reset-to-1 --
        # so the data's own ``&:i$YY`` room-id gate selects the right word
        # (e.g. record 3863 "In the ground/ceiling ... manhole cover").
        if self._room_context_native is not None and (
            self._current_scenery_value_b is None or self._passage_context
        ):
            # A passage's prose always sees the room beyond it, even when the
            # command typed the passage (Voodoo Island's OPEN GATE: record
            # 2570's `&:i$tn` asks for the shaft beyond the gate).
            self.vm.action_state.byte_1a52 = self._room_context_native
        self.vm.snapshot_parser_cursors()
        self._opened_1a4c = self.vm.action_state.byte_1a4c

    _opened_1a4c: "int | None" = None
    _passage_context = False
    _current_beast_value: "int | None" = None
    _current_typed_person: "int | None" = None

    def _cursor_t_phrase(self, typed: str) -> "Callable[[], str]":
        def phrase() -> str:
            moved = self.vm.action_state.byte_1a4c
            if self._opened_1a4c is None or moved == self._opened_1a4c or moved <= 1:
                return typed
            current = None if self.state.current_room is None else self.state.current_room + 1
            return self.vm.cursor_person_name(0x03, current_room=current) or typed

        return phrase

    def _build_parser_work_set(self) -> bytes:
        """Build DS:4AE9 -- the parsed-command VOCAB node set for ``$0x7E``/``*`` mode 1.

        Exactly the nodes the player typed, nothing more. This used to expand
        every noun to all lexical aliases sharing its ``(group_id, value_a,
        value_b)`` -- BUTTON/BUTTONS -- "so composites can pick the right
        agreement form". The data does the opposite: PRESS's record 3823 asks
        ``$"ad`` -- did the player type *buttons*? -- and sends a plural to
        the press-every-gadget path. With the alias added, PRESS WHITE BUTTON
        took that path, and two renderer workarounds (an output reset before
        ``^xx*`` and a skipped reference list) were added to compensate --
        which in turn swallowed OPEN's success text on scenery. Verbs had
        already been carved out of the expansion for the same reason (PUT
        also matching PUTT made record 2508's homonym gate fire).
        """

        parsed_indices = [
            index
            for index in (
                self._current_command_node,
                self._current_object_node,
                self._current_indirect_object_node,
                *self._current_modifier_nodes,
            )
            if index is not None
        ]
        if self._current_parsed is not None:
            # Every typed word: Rambo's FIRE GUN AT MINE has no WITH/IN, yet
            # record 2460's mode-2 star over the parser's word sets must see
            # MINE to choose "Your shot strikes home!".
            parsed_indices.extend(entry.index + 1 for entry in self._current_parsed.entries)
        return PascalSet.from_values(sorted(set(parsed_indices)), 0x28).to_bytes()

    def _message_local_set(self) -> PascalSet:
        """Build the caller-local set for ``$v`` during verb-response render."""

        carried = self.vm.predicates.blocks[0x679].union(
            self.vm.predicates.blocks[0x671]
        )
        if carried:
            return carried
        values = [1]
        for node_index in (
            self._current_command_node,
            self._current_object_node,
            self._current_indirect_object_node,
        ):
            if node_index is None:
                continue
            entry = self.vm.vocab_nodes.entries_by_node[node_index]
            if entry is not None and entry.value_b not in values:
                values.append(entry.value_b)
        return PascalSet.from_values(values, 8)

    def _evaluate_message_control(
        self, control: str, operands: tuple[int, ...], _position: int
    ) -> bool | None:
        """Bridge active MESSAGE controls into the engine-generic VM."""

        current = None if self.state.current_room is None else self.state.current_room + 1
        if control in {"$", "&"} and operands:
            return self.vm.evaluate_message_control(
                control,
                operands,
                current_room=current,
                current_command_value_b=self._current_command_value_b,
                current_object_node=self._current_object_node,
                local_set=self._message_local_set(),
            )
        if control == "=" and operands:
            listed = self.vm.eq_list_control(operands, current_room=current)
            if listed is not None:
                return listed[0]
            opcode = DEFAULT_SYMBOL_TABLE.get(operands[0])
            if opcode is None:
                return None
            context = self.vm.graph.room(self.vm.action_state.byte_1a50)
            return self.vm.evaluate_eq_control(
                opcode, current_room=current, context_record=context
            )
        if control == "*" and operands and star_control_mode(operands[0]) is not None:
            context = self.vm.graph.room(self.vm.action_state.byte_1a50)
            if context is None:
                return None
            return self.vm.evaluate_star_control(context_record=context)
        if control == "+" and operands:
            return self.vm.evaluate_plus_control(
                (operands[0] + 0x32) & 0xFF,
                operand_symbol=operands[1] if len(operands) > 1 else None,
                current_room=current,
                destination_symbols=tuple(operands[2:]),
            )
        return None

    def _apply_turn_section_state(self, section_state: int) -> None:
        """Mirror turn_resolve_text's section state into the shared VM."""

        self.vm.action_state.section_state = self.vm.merge_section_state(
            self.vm.action_state.section_state,
            section_state,
        )

    def _evaluate_star_candidate(
        self, mode: int, operand_symbol: int | None, descriptor: int
    ) -> bool | None:
        current = None if self.state.current_room is None else self.state.current_room + 1
        return self.vm.evaluate_star_candidate(
            mode, operand_symbol, descriptor, current_room=current
        )

    def _evaluate_message_control_text(
        self, control: str, operands: tuple[int, ...], _position: int
    ) -> str | None:
        """Render controls whose native result is prose, not only a gate."""

        current = None if self.state.current_room is None else self.state.current_room + 1
        if control == "%w":
            _listed, text = self.vm.phase9_listing(current_room=current)
            return text
        if control == "%name" and len(operands) == 1:
            return self.vm.cursor_person_name(operands[0], current_room=current)
        if control == "%" and len(operands) == 3 and operands[0] == 0x15:
            described = self.vm.describe_descriptor(operands[1] * 0x40 + operands[2])
            if described is None:
                return None
            kind, index, word = described
            if word is None:
                self.vm.mark_described(kind, index)
                return ""
            try:
                text = self.engine.render_message_record(word, _depth=1).strip()
            except (IndexError, ValueError, TypeError):
                text = ""
            # sub_FE5B marks only after msg_dict_expand returns.
            self.vm.mark_described(kind, index)
            return text
        if control == "%" and operands == (0x19,):
            listed = self.vm.people_listing(current_room=current)
            if listed is None:
                return None
            _gate, sentence, descriptions = listed
            parts = [sentence] if sentence else []
            for person, offset in descriptions:
                self.vm.describe_listed_person(person)
                try:
                    text = self.engine.render_message_record(offset, _depth=1)
                except (IndexError, ValueError, TypeError):
                    text = ""
                self.vm.finish_listed_person(person)
                if text.strip():
                    parts.append(text.strip())
            self.vm.absorb_listed_people([person for person, _offset in descriptions])
            # Each description starts a line of its own: The Mist's Ollie
            # Weeks description wraps after "star-" only from column 0.
            return "\n".join(parts)
        if control == "=" and operands:
            named = self.vm.eq_indefinite_name(operands, current_room=current)
            if named is not None:
                return named
            mention = self.vm.eq_mention_control(operands, current_room=current)
            if mention is not None:
                kind, index, word = mention
                if word is None:
                    self.vm.mark_described(kind, index)
                    return ""
                if kind == 2 and index == current:
                    # The room's +0 word points into a composite record whose
                    # section the validated room renderer selects; rendering
                    # the raw composite picks the wrong one. It is a nested
                    # expansion natively (msg_dict_expand): no record-open
                    # reset of the cursors -- LOOK WINDOW's `%l` still lists
                    # the porch's people afterwards, and the control room's
                    # own `(@p$` keeps 1A52 for the listing that follows.
                    callback = self.engine.record_open_callback
                    self.engine.record_open_callback = None
                    try:
                        text = self.room_description()
                    finally:
                        self.engine.record_open_callback = callback
                else:
                    try:
                        text = self.engine.render_message_record(
                            word,
                            _depth=1,
                            # A room's own prose names itself with %i/%j.
                            substitutions=(
                                self._message_substitutions(index) if kind == 2 else None
                            ),
                        ).strip()
                    except (IndexError, ValueError, TypeError):
                        text = ""
                # sub_FE5B renders first and writes +26h/1ACB afterwards, so
                # the prose can still ask `&'` about this very thing.
                self.vm.mark_described(kind, index)
                return text
        # msg_ctrl_eq selector 9Eh (``=h<source>``) prints the listed set
        # itself through loc_C114; see AsgVm.eq_list_control.
        if control != "=" or not operands:
            return None
        listed = self.vm.eq_list_control(operands, current_room=current)
        if listed is None or not listed[0]:
            return None
        return listed[1]

    def _evaluate_conditional_span(self, span: ConditionalSpan) -> bool:
        """Evaluate a structural span without losing raw 6-bit operands."""

        current = None if self.state.current_room is None else self.state.current_room + 1
        result = self.vm.evaluate_message_control(
            span.kind,
            span.raw_operand,
            current_room=current,
            current_command_value_b=self._current_command_value_b,
            current_object_node=self._current_object_node,
            continuation=span.continuation,
        )
        return result is not False

    def _execute_action_block(self, symbols: tuple[int, ...], _position: int) -> int:
        current = None if self.state.current_room is None else self.state.current_room + 1
        self.vm.execute_action_block(
            symbols,
            current_room=current,
            current_direction=self._current_direction,
        )
        return self.vm.last_action_block_length

    def _read_action_gate(self) -> bool | None:
        """Native byte_4B7B render/skip result of the last action block.

        ``None`` for any opcode this port hasn't confirmed sets it (see
        ``AsgVm.last_action_gate``), so an unconfirmed opcode never forces a
        render/skip decision the data doesn't support yet.
        """

        return self.vm.last_action_gate

    def object_record(self, vocab_id: int | None):
        if vocab_id is None or not 1 <= vocab_id <= len(self.object_records):
            return None
        return self.object_records[vocab_id - 1]

    def _container_link(self, record) -> int | None:
        """Authored initial-container VOCAB id (TABLES ``+0x18``), if any.

        ``0``/``1`` mean "no container" (confirmed by a survey of the
        shipped object records). Once the object's
        mutable ``+0x0C`` location has been explicitly set (carried, dropped,
        or PUT elsewhere), that field takes precedence over this authored
        link.
        """

        link = self.vm.table_state.read_byte(record, OBJECT_INITIAL_CONTAINER_OFFSET)
        return link if link not in (0, 1) else None

    def _render_static_span(
        self,
        symbol: int,
        length: int,
        substitutions: "dict[str, str] | None" = None,
    ) -> str:
        """Render a MESSAGE span without VM control-evaluator side effects."""

        engine = GameComMessageEngine(self.data.message)
        return engine.render_symbol_span(symbol, length, substitutions=substitutions)

    def _render_native_span(
        self, span, substitutions: "dict[str, str] | None" = None
    ) -> str:
        """Render a ``NativeSpan``, or ``""`` if not configured/resolvable."""

        if span is None:
            return ""
        if span.record is not None and span.record_start is not None:
            try:
                return self.engine.render_message_record_span(
                    span.record, span.record_start, span.length,
                    substitutions=substitutions,
                )
            except (IndexError, ValueError):
                return ""
        if span.record is not None:
            try:
                return self.engine.render_message_record(
                    span.record, substitutions=substitutions
                )
            except (IndexError, ValueError):
                return ""
        if span.symbol is not None:
            return self.engine.render_symbol_span(
                span.symbol, span.length, substitutions=substitutions
            )
        return ""

    def _render_turn_fragments(
        self,
        records: list,
        substitutions: "dict[str, str] | None" = None,
    ) -> str:
        """Render native sub_8628 fragments through the live VM context."""

        return self.engine.assemble_multi_fragment(
            records,
            substitutions=substitutions,
            on_section_state=self._apply_turn_section_state,
            control_evaluator=self._evaluate_message_control,
        )

    def _render_selected_vm_response(
        self,
        record_index: int | None,
        substitutions: "dict[str, str] | None" = None,
    ) -> str:
        if record_index is None:
            return ""
        try:
            text = self.engine.render_message_record(
                record_index,
                _depth=1,
                substitutions=substitutions,
                control_evaluator=self._evaluate_message_control,
            )
            if len(text.strip()) <= 1:
                text = self.engine.render_last_prose_fragment(
                    record_index,
                    substitutions=substitutions,
                )
            return "" if len(text.strip()) <= 1 else text
        except (IndexError, ValueError, TypeError):
            return ""

    def _location_entry(self, native_room_id: int):
        """The VOCAB noun that names a room: kind 2, value_b the room id.

        Group 1 holds the proper names (Trelex, D42, N5, S-curve, Fort Knox,
        Champagnole), group 2 the common nouns; the DB5 (record 21) is named
        by a group-0 word. The longest word wins for a room with several.
        """

        # The room record names itself: +2 is its VOCAB word (node). It
        # agrees with the search below for every named room and also names
        # the cockpits (20 -> "db5", 60 -> "helicopter"), which no kind-2
        # word points at -- "the back of the DB5" (%j in the cockpit).
        room = self.vm.graph.room(native_room_id)
        if room is not None and self.vm.vocab_nodes is not None:
            entry = self.vm.vocab_nodes.entry_for_message_symbol(room[2] | room[3] << 8)
            if entry is not None and entry.word:
                return entry
        candidates = [
            entry
            for entry in self.vocab
            if entry.group_id in (0x00, 0x01, 0x02)
            and entry.value_a == 0x02
            and entry.value_b == native_room_id
        ]
        return max(candidates, key=lambda entry: len(entry.word), default=None)

    def _location_name(self, native_room_id: int) -> str:
        """Longest VOCAB location noun for a native room id."""

        entry = self._location_entry(native_room_id)
        return "" if entry is None else entry.word

    def _location_reference(self, native_room_id: int) -> str:
        """The room as a noun phrase, the way ``%i``/``%j`` print it.

        Whether it takes "the" is the room record's byte ``+21h``: 1 for the
        sharp curve, the steep road, the airport, the side yard ...; 0 for
        lookout road, Trelex and D42, which the native prints bare in every
        place it names them (walkthrough turns 6, 12, 60, 65, 66). A group-1
        word is a proper name and keeps its capital mid-sentence.
        """

        entry = self._location_entry(native_room_id)
        if entry is None or not entry.word:
            return ""
        word = entry.word
        if entry.group_id == 0x00:
            word = word.upper()  # group 0: initialisms ("DB5")
        elif entry.group_id == 0x01:
            word = " ".join(part[:1].upper() + part[1:] for part in word.split(" "))
        room = self.vm.graph.room(native_room_id)
        takes_article = room is not None and len(room) > 0x21 and room[0x21] != 0
        return ("the " + word) if takes_article else word

    def _message_substitutions(self, native_room_id: int | None = None) -> dict[str, str]:
        """Fill %i/%j location placeholders for room-description MESSAGE records."""

        if native_room_id is None:
            if self.state.current_room is None:
                return {}
            native_room_id = self.state.current_room + 1
        reference = self._location_reference(native_room_id)
        if not reference:
            return {}
        # %g is cursor 97h, byte_1AE3 (the room just left): leaving the DB5
        # through its bridge record leaves 1AE3 on the DB5 itself, so record
        # 7789 reads "You step out of the DB5 at the steep road.".
        # %j is selector 92h, byte_6A9 -- the player's own room, which in a
        # vehicle is the vehicle: Indiana's "...splash into %v.%j makes it
        # about three-quarters" names the motorcycle, %v (1AE5) the pool.
        return {
            "i": reference,
            "j": lambda: self._location_reference(
                native_room_id if self.state.current_room is None else self.state.current_room + 1
            ),
            "g": lambda: self._location_reference(self.vm.action_state.byte_1ae3),
        }

    def _message_context_name(self, selector: str) -> str:
        """Resolve MESSAGE referent placeholders for verb-response templates."""

        if selector != "j":
            return ""
        if self.state.current_room is None:
            return ""
        return self._location_reference(self.state.current_room + 1)
