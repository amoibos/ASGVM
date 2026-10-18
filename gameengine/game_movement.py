"""AsgGame: walking between rooms, followers and arrival."""

from __future__ import annotations

from gameengine.parser import ParsedCommand


class MovementMixin:
    """Moving the player (and followers) through the room graph."""

    def _is_room_visited(self, native_room_id: int) -> bool:
        if native_room_id < 1 or (native_room_id - 1) not in self.rooms:
            return False
        record = self.rooms[native_room_id - 1].record
        return self.vm.table_state.read_byte(record, 0x22) != 0

    def _movement_transition_prefix(self, from_native: int, direction: int) -> str:
        transitions = self.config.movement_transition_records
        if transitions is None:
            return ""
        record_index = transitions.get((from_native, direction))
        if record_index is None:
            return ""
        try:
            text = self.engine.render_with_conditional_spans(
                record_index,
                evaluator=lambda span: span.kind == "^" and span.operand == "pb",
            )
        except (IndexError, ValueError, TypeError):
            return ""
        text = text.strip()
        if not text:
            return ""
        first = text.split("\n", 1)[0].strip()
        if first.lower().startswith("you lower yourself"):
            return first.rstrip(".") + "."
        return first

    def _is_passage(self, native_room_id: int) -> bool:
        """True for a scenery record: sub_9AFF passes straight through it."""

        record = self.vm.graph.room(native_room_id)
        return record is not None and len(record) > 0x23 and record[0x23] != 0

    def _record_step(self, origin: int, target: int) -> None:
        """GAME.COM 5DA2 (the step itself) and sub_9AFF 9C24's passage case.

        Every step shifts the previous-room pair: 1AE4 = 1AE3, 1AE3 = the
        room left. Stepping into a passage while 1AE3 is a vehicle cockpit
        (DS:4ABE) makes the passage itself the previous room -- leaving the
        DB5 through record 21 leaves 1AE3 = 1AE4 = 21 (measured 2026-10-14).
        """

        state = self.vm.action_state
        state.byte_1ae4 = state.byte_1ae3
        state.byte_1ae3 = origin
        self._move_follower(target)
        if self._is_passage(target) and origin in self.vm.graph.active_rooms_4abe:
            state.byte_1ae3 = target

    def _move_follower(self, target: int) -> None:
        """GAME.COM 5E4E..5F37: the person in byte_1AEB follows the step.

        With the player last turn: into the new room. Elsewhere (not already
        here): through 1AE4 when that is an open passage (a closed one loses
        them, 1AEB = 1), or onto 1AE3 when that is no passage.
        """

        state = self.vm.action_state
        follower = state.byte_1aeb
        if follower == 1:
            return
        raw = self.vm._person(follower)
        if raw is None or len(raw) <= 0x14:
            return
        destination = None
        if raw[0x14] == state.byte_1ae3:
            destination = target
        elif raw[0x14] != target:
            before = self.vm.graph.room(state.byte_1ae4)
            if before is not None and len(before) > 0x24 and before[0x23]:
                if before[0x24]:
                    destination = state.byte_1ae3
                else:
                    state.byte_1aeb = 1
            else:
                left = self.vm.graph.room(state.byte_1ae3)
                if left is not None and len(left) > 0x23 and not left[0x23]:
                    destination = state.byte_1ae3
        if destination is not None:
            self.vm._move_person(follower, raw, destination)
            self.vm._store_person(follower, raw)

    def _finish_move(self, final: int) -> None:
        """sub_9AFF 9C8A: 1AE5 = 1AE4 inside a vehicle cockpit, else 1."""

        state = self.vm.action_state
        if final in self.vm.graph.active_rooms_4abe:
            state.byte_1ae5 = state.byte_1ae4
        else:
            state.byte_1ae5 = 1

    def _arrive(
        self, target: int, from_native: int, direction: int, *, context: "int | None" = None
    ) -> str:
        """Enter ``target`` and return what the player sees there.

        The movement record decides between the first-visit description and
        the "still / back at" line itself (`&'j`, amp 80h); a title without
        one shows the arrival record.
        """

        prefix = self._movement_transition_prefix(from_native, direction)
        self._record_step(from_native, target)
        self.state.current_room = target - 1
        self.vm.mark_visited(target)
        self._session_visited_rooms.add(target)
        self.state.direction_available = self._direction_availability(target - 1)
        if context is not None:
            # A passage (sub_9AFF): only its own text, rendered with the
            # room context cursor on the room beyond it. It is not described
            # through the movement record, so it is not marked either.
            response = self._render_passage_text(target, context)
        else:
            response = self._render_movement_record(target)
            if response is None:
                response = self._render_arrival(target)
        if prefix:
            body = response.strip()
            response = f"{prefix}\n\n{body}" if body else prefix
        return response

    def _walk(self, origin: int, direction: int) -> "tuple[int, list[str]]":
        """sub_9AFF's walk: through passages to the room the move ends in.

        Returns the final room and the passages' own texts, each rendered
        with 1A52 on the room beyond it.
        """

        target = self.vm.direction_target(origin, direction)
        texts: list[str] = []
        passed = {origin}
        if target is not None and not self.vm.step_allowed(target):
            # GAME.COM 5DA2 refuses the step: the cave needs a power the
            # player has not been granted (Forbidden Castle's griffin).
            return None, texts
        if target is not None:
            self._record_step(origin, target)
        while (
            target is not None
            and self._is_passage(target)
            and target not in passed
        ):
            passed.add(target)
            onward = self.vm.direction_target(target, direction)
            if (
                onward is None
                or (onward - 1) not in self.rooms
                or not self.vm.direction_available(target, direction)
                or not self.vm.step_allowed(onward)
            ):
                break
            text = self._render_passage_text(target, onward)
            if text:
                texts.append(text)
            # sub_9AFF 9C44: the passage is the referent (67b6(6A9, 2)).
            self.vm.set_referent(2, target)
            self.vm.mark_visited(target)
            self._record_step(target, onward)
            target = onward
        if target is not None:
            self._finish_move(target)
        return target, texts

    def _move_to_named_place(self, parsed: ParsedCommand, place: int) -> "str | None":
        """GO / ENTER / CLIMB TO <place> on foot: sub_6D38 with a place.

        sub_6D38 asks sub_665B (as sub_FE5B) whether the place is the
        player's room or one of its exits. Within reach it leaves state 3 --
        byte_6AA on that exit (unchanged for the room itself), 1A52 on the
        place -- and 4A74 answers with record 1893. Out of reach on foot it
        is state 2 and 4B36 answers: record 7743's "You can't get there from
        here." (1A52 != 1).
        """

        here = self.state.current_room + 1
        room = self.vm.graph.room(here)
        if room is None:
            return None
        if place == here:
            direction = self.vm.direction_cursor_6aa
        elif place != 1 and place in room[0x04:0x0A]:
            direction = room[0x04:0x0A].index(place)
            self.vm.direction_cursor_6aa = direction
        else:
            return self._ride(parsed)
        return self._move_through_command_record(
            here, direction, context=place, refusal=True
        )

    def _move_through_command_record(
        self,
        origin: int,
        direction: int,
        *,
        context: "int | None" = None,
        refusal: bool = False,
    ) -> "str | None":
        """A move on foot as the native renders it: record 1893.

        The bewegungs-dispatcher (GAME.000 4AF4) makes word_1A9F -- 1893 --
        the response of a move on foot. Its first part is a star over the
        current room with that room's special cases ("You lower yourself down
        the cable ..."), and every branch ends in movement record 1712, whose
        `(m` (action 38h, sub_9AFF) performs the move. Here 38h calls back
        into this game to walk the passages and move; the record renders the
        rest. Returns None when the record never moved the player, so the
        caller can fall back -- unless ``refusal``: a blocked move renders
        1893 too (4AF4 makes it the answer of every move on foot), and 1712's
        refusal branch is the answer.
        """
        self._last_route = "move"

        state = {"moved": False, "pending": []}

        def hook(step_direction: int) -> bool:
            # `(m` walks along byte_6AA as it stands then -- 1893's `$*a'`
            # (sub_665B) aims it at the DB5 for GET IN.
            # The passages' own texts render actions of their own; the `(m`
            # that called us must still report its own width and gate.
            # sub_9AFF: with the context cursor 1A52 on the player's own room
            # (GO TO OFFICE in the office, sub_6D38) byte_4B7B is 1 and
            # nothing moves.
            # sub_9AFF starts from byte_6A9 as it stands: a record may move
            # the player twice (A View to a Kill's flight goes on to Paris).
            here = self.state.current_room + 1
            if self.vm.action_state.byte_1a52 == here:
                state["moved"] = True
                return True
            # sub_9AFF refuses a dead end or a closed passage (218D: the
            # target's +24h) and clears byte_4B7B.
            if not self.vm.direction_available(here, step_direction):
                return False
            saved = (self.vm.last_action_block_length, self.vm.last_action_gate)
            try:
                final, texts = self._walk(here, step_direction)
            finally:
                self.vm.last_action_block_length, self.vm.last_action_gate = saved
            if final is None or (final - 1) not in self.rooms:
                return False
            state["pending"] = texts
            state["moved"] = True
            self.state.current_room = final - 1
            self.vm.mark_visited(final)
            self._session_visited_rooms.add(final)
            self.state.direction_available = self._direction_availability(final - 1)
            self.vm.action_state.byte_1a52 = final
            return True

        def pending_text() -> "str | None":
            if not state["pending"]:
                return None
            text = " ".join(state["pending"])
            state["pending"] = []
            return text

        self.vm.move_hook = hook
        self.engine.action_text_reader = pending_text
        # 1893's inner star asks cursor i (1A52) which room the step leads
        # into -- "end of the cable" selects "You lower yourself down the
        # cable ...", "secret door" the bunker branch -- so the record opens
        # with 1A52 on the first room in that direction.
        self._room_context_native = (
            self.vm.direction_target(origin, direction) if context is None else context
        )
        try:
            text = self.engine.render_message_record(
                self.config.movement_command_record,
                substitutions=self._turn_tail_substitutions(),
            )
        except (IndexError, ValueError, TypeError):
            text = ""
        finally:
            self.vm.move_hook = None
            self.engine.action_text_reader = None
            self._room_context_native = None
        if not state["moved"] and not refusal:
            return None
        return text.strip()
