"""AsgGame: parsing, noun phrases, room descriptions and generic verb responses."""

from __future__ import annotations

import dataclasses
import re
from gameengine.parser import ParsedCommand


class NounMixin:
    """Parsing a command, naming objects and scenery, LOOK and verb responses."""

    def parse(self, command: str) -> ParsedCommand:
        parsed = self.parser.parse(command)
        table = self.vm.vocab_nodes
        if table is None:
            return parsed
        # The parser reads the runtime VOCAB nodes (DS:06B2): action 47h
        # turns a dead person's name into a kind-0 word for the body, so
        # EXAMINE ODDJOB describes the body afterwards (native endgame), and
        # the parser itself does the same to any other word for them.
        self.vm.name_dead_person_words(entry.index + 1 for entry in parsed.entries)
        table = self.vm.vocab_nodes
        changed = False
        entries = []
        for entry in parsed.entries:
            node = entry.index + 1
            if 0 <= node < len(table.metadata_by_node):
                meta = table.metadata_by_node[node]
                if len(meta) >= 4 and (meta[2], meta[3]) != (entry.value_a, entry.value_b):
                    entry = dataclasses.replace(
                        entry, metadata=bytes(meta), value_a=meta[2], value_b=meta[3]
                    )
                    changed = True
            entries.append(entry)
        return dataclasses.replace(parsed, entries=tuple(entries)) if changed else parsed

    def _direction_availability(self, room_index: int) -> tuple[bool, ...]:
        return tuple(
            self.vm.direction_available(room_index + 1, direction)
            for direction in range(6)
        )

    @staticmethod
    def _with_object_id(parsed: ParsedCommand) -> int | None:
        """The object after WITH (class 07h) -- sub_5992's noun."""

        entries = parsed.entries
        for index, entry in enumerate(entries):
            if entry.class_id != 0x07:
                continue
            for candidate in entries[index + 1 :]:
                if candidate.value_a == 0 and candidate.value_b:
                    return candidate.value_b
        return None

    def _parsed_indirect_object_id(self, parsed: ParsedCommand) -> int | None:
        markers = {"in", "into", "inside", "on", "onto"}
        entries = parsed.entries
        for index, entry in enumerate(entries):
            if entry.word not in markers:
                continue
            for candidate in entries[index + 1 :]:
                if candidate.group_id in (0x00, 0x01, 0x02) and candidate.value_a == 0 and candidate.value_b:
                    return candidate.value_b
        return None

    def _object_phrase(self, object_id: "int | None", word: str) -> str:
        """`%t`: "the <word>" -- or, for a body (a type-5 node), the listing's
        own phrase ("the body of Oddjob", native EXAMINE ODDJOB)."""

        if object_id is not None:
            node = self.vm.phase7_runtime.get(object_id)
            if node is not None and len(node) > 0x18 and self.vm.vocab_nodes is not None:
                word_index = node[0x0A] | node[0x0B] << 8
                if 0 <= word_index < len(self.vm.vocab_nodes.metadata_by_node):
                    meta = self.vm.vocab_nodes.metadata_by_node[word_index]
                    target = self.vm.phase7_runtime.get(meta[3]) if meta[2] == 0 else None
                    if target is not None and len(target) > 0x18 and target[0x18] == 5:
                        return self.vm._listing_item_text(object_id, article=1, contents=0)
        if not word and object_id is None:
            # No object: 1A4C is at its reset value 1, and the native prints
            # phase-7 node 1 -- its +0Ah word is node 0 (the pool head "!!")
            # and its +19h article flag is clear.
            return self._node_phrase(1)
        return ("the " + word) if word else ""

    def _node_phrase(self, index: int) -> str:
        node = self.vm.phase7_runtime.get(index)
        if node is None or len(node) <= 0x19 or self.vm.vocab_nodes is None:
            return ""
        word = self.vm.vocab_nodes.word_for_node(node[0x0A] | node[0x0B] << 8)
        return ("the " if node[0x19] else "") + word

    def _typed_object_word(self, parsed: ParsedCommand, object_id: int) -> str:
        node = self.vm.phase7_runtime.get(object_id)
        if node is not None and len(node) > 0x0B and self.vm.vocab_nodes is not None:
            # `%t` prints the object's own name word (phase-7 +0Ah), not the
            # alias typed: FLIP SWITCH answers "You turn the panel on."
            entry = self.vm.vocab_nodes.entry_for_message_symbol(node[0x0A] | node[0x0B] << 8)
            if entry is not None and entry.word:
                # With the VOCAB group's casing: The Mist's "the Raid".
                return self.vm.display_word(entry)
        typed = next(
            (
                entry.word
                for entry in parsed.entries
                if entry.group_id in (0x00, 0x01, 0x02) and entry.value_a == 0 and entry.value_b == object_id
            ),
            self.object_names.get(object_id, ""),
        )
        # A title may need a fuller display name than the bare VOCAB noun the
        # player typed (Goldfinger: "ball" -> "golf ball"). Data, not logic.
        overrides = self.config.object_display_names or {}
        override = overrides.get(object_id)
        if override is not None and typed in {"", override}:
            return override
        if override is not None and typed and override.endswith(typed):
            return override
        return typed

    def _resolve_current_scenery(self) -> None:
        """Resolve this turn's kind-2 noun against the room's scenery.

        Runs where the cursor nodes are chosen rather than inside
        ``_open_message_record``, because that is the record-open callback and
        fires *during* the render -- after the response's substitutions have
        already been built.
        """

        self._current_scenery_value_b = None
        self._current_scenery_absent = False
        if self._current_object_node is None or self.vm.vocab_nodes is None:
            return
        entry = self.vm.vocab_nodes.entries_by_node[self._current_object_node]
        if entry is None or entry.value_a != self.vm.SCENERY_CONTEXT_TYPE:
            return
        current = (
            None if self.state.current_room is None else self.state.current_room + 1
        )
        resolved = self.vm.resolve_scenery_noun(
            entry.value_b, entry.word, current_room=current
        )
        if resolved is None:
            self._current_scenery_absent = True
        else:
            self._current_scenery_value_b = resolved

    def _scenery_cursor_name(self, parsed: ParsedCommand) -> str:
        """Display name of the record the scenery cursor (byte_1A52) holds."""

        record = self.vm.action_state.byte_1a52
        if record in (0, 1):
            word = self._resolved_scenery_word(parsed)
            return ("the " + word) if word else ""
        # The record names itself (+2, as for %j): High Stakes' van door is
        # "the van's door", not its longer synonym "horse van".
        name = self._location_reference(record)
        if not name:
            word = self._resolved_scenery_word(parsed)
            return ("the " + word) if word else ""
        return name

    def _resolved_scenery_word(self, parsed: ParsedCommand) -> str:
        """The name of the scenery the typed noun actually resolved to.

        The player types "door"; the native answers about the barn door,
        because resolution happens against the room. So the response names the
        resolved record, not the typed word.
        """

        typed = self._typed_scenery_word(parsed)
        resolved = self._current_scenery_value_b
        if not typed or resolved is None or self.vm.vocab_nodes is None:
            return typed
        # A record answers to several words ("cover" and "manhole cover" both
        # reach 39); the response names the fullest one, as the native does.
        best = ""
        for entry in self.vm.vocab_nodes.entries_by_node:
            if (
                entry is not None
                and entry.value_a == self.vm.SCENERY_CONTEXT_TYPE
                and entry.value_b == resolved
                and len(entry.word) > len(best)
            ):
                best = entry.word
        return best or typed

    def _typed_scenery_word(self, parsed: ParsedCommand) -> str:
        """The typed word for a kind-2 (scenery/location) noun, else ``""``."""

        location_id = parsed.location_id()
        if location_id is None:
            return ""
        return next(
            (
                entry.word
                for entry in parsed.entries
                if entry.group_id in (0x00, 0x01, 0x02)
                and entry.value_a == self.vm.SCENERY_CONTEXT_TYPE
                and entry.value_b == location_id
            ),
            "",
        )

    def _article_phrase(self, word: str) -> str:
        if not word:
            return ""
        if word.startswith(("the ", "a ", "an ")):
            return word
        return f"the {word}"

    def _object_take_phrase(self, parsed: ParsedCommand, object_id: int) -> str:
        return self._article_phrase(self._typed_object_word(parsed, object_id))

    def _container_phrase(self, container_id: int) -> str:
        # `%b` names the node by its own word (phase-7 +0Ah), not by the
        # alias typed: A View to a Kill's TAKE CHECKBOOK "from the desk"
        # although the player says DRAWER.
        named = self.vm._listing_item_text(container_id, article=1, contents=0)
        if named:
            return named
        return self._article_phrase(self.object_names.get(container_id, "object"))

    def _is_carried(self, object_id: int) -> bool:
        return object_id in self.inventory_ids()

    def _render_arrival(self, target: int) -> str:
        """First-visit display: the configured arrival record, else the room."""

        record_index = self.config.arrival_record
        if record_index is None:
            return self.room_description()
        self._room_context_native = target
        try:
            text = self.engine.render_message_record(
                record_index,
                substitutions={"j": self._message_context_name("j")},
            )
        except (IndexError, ValueError, TypeError):
            text = ""
        text = text.strip()
        return text if text else self.room_description()

    def _render_look_record(self) -> str:
        """LOOK through its DS:05F0 verb record (Goldfinger: 1672).

        The record is the native room display: ``+@j`` points 1A52 at the
        room, ``=di`` prints its description and marks it, a mode-3 star picks
        per-room extras, ``\aic`` runs the listing program (record 270) and
        ``%l`` names the people present. Scenes that draw their own scenery
        (the chase, the helicopter) keep their override.
        """
        self._last_route = "verb"

        record_index = (self.verb_response_records or {}).get(0x05)
        if record_index is None:
            return self.room_description()
        try:
            text = self.engine.render_message_record(
                record_index,
                substitutions={"j": self._message_context_name("j")},
            )
        except (IndexError, ValueError, TypeError):
            text = ""
        text = text.strip()
        return text if text else self.room_description()

    def room_description(self) -> str:
        room = self.room
        if room is None or room.message_offset <= 0:
            return ""
        overrides = self.config.room_description_spans
        if overrides is not None and self.state.current_room is not None:
            native_id = self.state.current_room + 1
            span = overrides.get(native_id)
            if span is not None:
                rendered = self._render_native_span(span)
                if rendered:
                    return rendered
        native_id = self.state.current_room + 1
        message_index = self._resolve_room_message_index(native_id, room.message_offset)
        return self._render_room_message(message_index, native_room_id=native_id)

    def _render_generic_verb_response(
        self,
        action: int,
        parsed: ParsedCommand,
    ) -> str:
        """Render the data-driven DS:0x5F0 verb-response record for ``action``.

        Cursors and the DS:4AE9 parser work set are bound by
        ``_open_message_record`` (via ``record_open_callback``) before the
        MESSAGE renderer evaluates ``$``/``&``/``(`` controls. The structural
        span renderer is not used here -- it would retain every unresolved
        branch and expand mutually exclusive data as prose.
        """
        self._last_route = "verb"

        record_index = (self.verb_response_records or {}).get(action)
        if record_index is None:
            return ""
        verb_word = next(
            (e.word for e in parsed.entries
             if e.group_id == 0x02 and e.value_a == 0x06),
            "",
        )
        object_id = parsed.object_id()
        # Prefer the alias the player actually typed over whichever one the
        # name table happens to hold. Object 10 is reachable as "frame",
        # "photos" and "safe"; LOCK SAFE must answer about the safe.
        obj_word = (
            self._typed_object_word(parsed, object_id)
            if object_id is not None
            else ""
        )
        put_family = any(
            e.group_id == 0x02 and e.value_a == 0x06 and e.class_id in (0x24, 0x25)
            for e in parsed.entries
        )
        if not obj_word and not put_family:
            # (The PUT dispatcher 46FD takes objects only: PUT ON TOP FRONT
            # DOOR leaves the object cursor at 1, native "You can't put on
            # top! !!".)
            # A scenery noun (resolver kind 2 -- doors, windows, a trap door)
            # is a legitimate verb target: sub_D6FD answers its presence test
            # unconditionally true, and its name is simply the word the player
            # typed, since it has no object record to carry a display name.
            # Without this the composite's subject stayed empty and every such
            # command rendered its template with a hole in it (" Is not here.",
            # "You can't open !").
            obj_word = self._resolved_scenery_word(parsed)
        container_id = self._parsed_indirect_object_id(parsed)
        substitutions = {
            # `%i` names whatever the scenery cursor points at *when it is
            # rendered* -- after record 2203 has re-pointed it at the room's
            # own door -- so it is resolved lazily. Records 2308 ("%i is
            # latched tight.") and 321 (the name plus a possessive selector:
            # "the DB5's door") read it.
            "i": lambda: self._scenery_cursor_name(parsed),
            "e": verb_word,
            # `%t` is cursor 8Ah, byte_1A4C, read when printed: the typed
            # object's phrase while the cursor still holds it, the cursor's
            # own name once an action re-pointed it -- Indiana Jones' TAKE
            # CYLINDER: `(@ey %t tumbles out` names the pedestal.
            "t": self._cursor_t_phrase(self._object_phrase(object_id, obj_word)),
            # `%j` too: a record that walks the player (Voodoo Island's
            # penthouse door, `(m`) names the room the walk ended in.
            "j": lambda: self._message_context_name("j"),
            # `%b` names cursor 8Eh (byte_1A4F). The parser puts a typed
            # indirect object there; records also point it at a container
            # themselves (TAKE BALL: `$` 64h leaves the hole in 1A4F).
            "b": (
                self._container_phrase(container_id)
                if container_id is not None
                else (lambda: self._container_phrase(self.vm.action_state.byte_1a4f)
                      if self.vm.action_state.byte_1a4f > 1 else "")
            ),
        }
        try:
            with self._moves_allowed():
                text = self.engine.render_message_record(
                    record_index,
                    substitutions=substitutions,
                )
        except (IndexError, ValueError, TypeError):
            text = ""
        return text

    def _apply_open_close_side_effects(
        self, action: int, parsed: ParsedCommand
    ) -> None:
        """Mirror OPEN/CLOSE Phase-7 container state into ``state.opened``."""

        if action not in (0x11, 0x15):
            return
        open_object_id = parsed.object_id()
        node = (
            self.vm.phase7_runtime.get(open_object_id)
            if open_object_id is not None
            else None
        )
        if node is not None and len(node) > 0x1B and node[0x18] == 0:
            if node[0x1B]:
                self.state.opened.add(open_object_id)
            else:
                self.state.opened.discard(open_object_id)
