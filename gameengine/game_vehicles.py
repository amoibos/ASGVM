"""AsgGame: which moves are allowed, riding vehicles and passage texts."""

from __future__ import annotations

import re
import contextlib
from gameengine.parser import ParsedCommand


class VehicleMixin:
    """Allowed moves, vehicles and the movement/passage records."""

    @contextlib.contextmanager
    def _moves_allowed(self):
        """Let a record's `(m` (38h) really move the player while it renders.

        Talk records, verb records (OPEN DOOR's control room door) and timer
        records walk the player through movement record 1712; the hook walks
        the passages and moves, and their own texts are injected after the
        action (`action_text_reader`). An outer hook (the on-foot move) wins.
        """

        if self.vm.move_hook is not None:
            yield
            return
        pending: list[str] = []

        def hook(direction: int) -> bool:
            saved = (self.vm.last_action_block_length, self.vm.last_action_gate)
            try:
                final, texts = self._walk(self.state.current_room + 1, direction)
            finally:
                self.vm.last_action_block_length, self.vm.last_action_gate = saved
            if final is None or (final - 1) not in self.rooms:
                return False
            pending.extend(texts)
            self.state.current_room = final - 1
            self.vm.mark_visited(final)
            self._session_visited_rooms.add(final)
            self.state.direction_available = self._direction_availability(final - 1)
            self.vm.action_state.byte_1a52 = final
            return True

        def pending_text() -> "str | None":
            if not pending:
                return None
            text = " ".join(pending)
            pending.clear()
            return text

        def step(target: int) -> None:
            # 5DA2 alone: one step straight into the room, no passages.
            if (target - 1) not in self.rooms:
                return
            self._record_step(self.state.current_room + 1, target)
            self.state.current_room = target - 1
            self.vm.mark_visited(target)
            self._session_visited_rooms.add(target)
            self.state.direction_available = self._direction_availability(target - 1)

        self.vm.move_hook = hook
        self.vm.step_hook = step
        self.engine.action_text_reader = pending_text
        try:
            yield
        finally:
            self.vm.move_hook = None
            self.vm.step_hook = None
            self.engine.action_text_reader = None

    def _move_with_hook_render(self, record: int, extra_substitutions: "dict | None" = None) -> str:
        """Render a response record whose actions may move the player (`(m`)."""

        substitutions = self._turn_tail_substitutions()
        substitutions.update(extra_substitutions or {})
        with self._moves_allowed():
            try:
                text = self.engine.render_message_record(
                    record, substitutions=substitutions
                )
            except (IndexError, ValueError, TypeError):
                text = ""
        return text.strip()

    def _move_through_vehicle_exit(self) -> "str | None":
        """GET IN / GET OUT: a move verb without a direction, record 1893.

        Live-traced 2026-10-14 (walkthrough turns 10 and 63 natively): the
        command runs the on-foot movement record (word_4B7F = 1893), whose
        branches ask `$*a'` -- is the DB5 here? -- and sub_665B aims
        byte_6AA at the exit leading to it (slot 2 from the steep road, slot
        0 from the cockpit); 1712's `(m` then walks through the DB5 (21)
        into the cockpit or out onto the scenery.
        """

        if self.config.movement_command_record is None:
            return None
        origin = self.state.current_room + 1
        room = self.vm.graph.room(origin)
        if room is None:
            return None
        # 1893's inner star asks cursor i which room the step leads into.
        # Natively i is room(6A9)[old 6AA] here (measured 2 at the steep
        # road, 21 in the cockpit), not the DB5.
        current = self.vm.direction_cursor_6aa
        previous = room[0x04 + current] if 0 <= current < 6 else 1
        self._current_direction = current
        return self._move_through_command_record(origin, current, context=previous)

    def _ride(self, parsed: ParsedCommand) -> "str | None":
        """RIDE: the vehicle sentence dispatcher sub_4B36.

        While driving (1AE5 != 1) the selected vehicle 1A51 stays; otherwise
        a typed kind-3 noun selects it. word_4B7F is that Phase-9 record's
        +2 word when it stands in the player's room (+0Eh == byte_6A9),
        else record 1's (Goldfinger 7743: "There is nothing to %e here."),
        and section state 2 follows. Native RIDE CAR in the chase: 7743.
        """
        self._last_route = "move"

        state = self.vm.action_state
        if state.byte_1ae5 == 1:
            noun = next((e for e in parsed.entries if e.value_a == 3), None)
            if noun is not None:
                state.byte_1a51 = noun.value_b
        current = self.state.current_room + 1
        selected = state.byte_1a51
        records = self.vm.phase9_runtime
        if not 1 <= selected <= len(records) or not records:
            return None
        record = records[selected - 1]
        if len(record) > 0x0E and record[0x0E] == current:
            word = record[2] | record[3] << 8
        else:
            word = records[0][2] | records[0][3] << 8
        if not word:
            return None
        self._open_message_record()
        # sub_7BB7 cleared 1A51 on foot; the parser's kind-3 noun binds it
        # after that reset (Forbidden Castle's GET BOAT: sub_9FBC reads it).
        state.byte_1a51 = selected
        state.section_state = 2
        callback = self.engine.record_open_callback
        self.engine.record_open_callback = None
        try:
            return self._move_with_hook_render(word, extra_substitutions={
                "e": next((e.word for e in parsed.entries if e.value_a == 0x0A), ""),
            })
        finally:
            self.engine.record_open_callback = callback

    def _move_vehicle(self, direction: int) -> "str | None":
        """A move while sitting in a closed vehicle (byte_1AEC == 1).

        GAME.000 4AF4's other branch: word_4B7F is the selected vehicle's
        Phase-9 record +2 (the DB5's 7799, "You can't drive in that
        direction, 007." behind its gates) and sub_4936 walks from the
        vehicle's scenery (1AE5) along byte_6AA to the next room in the 4ACD
        frontier, leaving it in 1A52 (1 when there is none). The record's
        `(m` (38h with 1AEC == 1) then re-points the bridge. Live-traced
        2026-10-14: 4936 is entered once per drive with 6A9 = 20, 1A51 = 2.
        """
        self._last_route = "move"

        state = self.vm.action_state
        selected = state.byte_1a51
        if not 1 <= selected <= len(self.vm.phase9_runtime):
            return None
        record = self.vm.phase9_runtime[selected - 1]
        response_record = record[2] | (record[3] << 8)
        native_room = self.state.current_room + 1
        self.vm.direction_cursor_6aa = direction
        self.vm._execute_sub_4936(current_room=native_room)
        self._room_context_native = state.byte_1a52
        try:
            # The record may open the vehicle first (44h clears 1AEC): its
            # `(m` is then a step on foot -- Rambo's GET OUT of the Huey.
            with self._moves_allowed():
                text = self.engine.render_message_record(
                    response_record,
                    substitutions=self._turn_tail_substitutions(),
                )
        except (IndexError, ValueError, TypeError):
            text = ""
        finally:
            self._room_context_native = None
        return text.strip()

    # Movement record 1712 opens with `(m|e?`: action 38h (sub_9AFF, the
    # move itself) and the gate whose else-branch is the blocked-move text.
    # The port has already moved the player when it gets here, so it renders
    # the success branch -- from just after that gate up to the `^` at 192
    # that ends it -- which asks `&'j` and either runs 1669 (` x`, the
    # first visit) or "you're still / back at %j." plus the listing.
    MOVEMENT_SUCCESS_SPAN = (5, 195)

    def _render_movement_record(self, target: int) -> "str | None":
        record_index = self.config.movement_record
        if record_index is None:
            return None
        self._room_context_native = target
        try:
            text = self.engine.render_message_record(
                record_index,
                substitutions=self._message_substitutions(target),
                span=self.MOVEMENT_SUCCESS_SPAN,
            )
        except (IndexError, ValueError, TypeError):
            return None
        finally:
            self._room_context_native = None
        text = text.strip()
        return text or None

    def _render_passage_text(self, passage: int, onward: int) -> str:
        """A passage record's own prose, with 1A52 on the room beyond it."""

        room = self.rooms.get(passage - 1)
        if room is None or room.message_offset <= 0:
            return ""
        self._room_context_native = onward
        self._passage_context = True
        try:
            # The %-letters are cursors: i is 1A52 (the room beyond), j the
            # room the walk stands in (the passage), g 1AE3 (the room left).
            text = self.engine.render_message_record(
                room.message_offset,
                substitutions={
                    "i": lambda: self._location_reference(self.vm.action_state.byte_1a52),
                    "j": lambda: self._location_reference(passage),
                    "g": lambda: self._location_reference(self.vm.action_state.byte_1ae3),
                },
                control_evaluator=self._evaluate_message_control,
            )
        except (IndexError, ValueError, TypeError):
            text = ""
        finally:
            self._room_context_native = None
            self._passage_context = False
        return text.strip()

    def _resolve_room_message_index(self, native_room_id: int, default: int) -> int:
        return default

    def _render_room_message(
        self, message_index: int, *, native_room_id: int | None = None
    ) -> str:
        substitutions = self._message_substitutions(native_room_id)
        self._room_context_native = native_room_id
        try:
            text = self.engine.render_message_record(
                message_index,
                substitutions=substitutions,
                control_evaluator=self._evaluate_message_control,
            )
        except (IndexError, ValueError, TypeError):
            return ""
        finally:
            self._room_context_native = None
        if text.strip():
            return text
        return self.engine.render_room_segment(message_index)
