"""AsgGame: pronouns, referents, talking to people and speech."""

from __future__ import annotations

import dataclasses
from gameengine.parser import ParsedCommand
from gameengine.grammar import words_from_entries
from gameengine.pascal_set import PascalSet


class TalkMixin:
    """Resolving referents and dispatching talk and speech."""

    # sub_6F97: a sentence opening with a class 19h ("do you have", "have
    # you") or 17h word is a question put to whoever is present.
    QUESTION_CLASSES = frozenset((0x17, 0x19))

    def _resolve_pronoun(self, parsed: ParsedCommand) -> ParsedCommand:
        """sub_35FB's class-0Bh case: "it" / "them" in an object slot.

        The pronoun becomes byte_1A44 -- the previous command's 1A4C, which
        sub_7BB7 saves -- when that is not 1; otherwise, when the referent
        is an object (1A56 = 0), 1A57, named with that object's own word
        (sub_35B8). Measured 2026-10-15 after TAKE BADGE: EXAMINE IT, DROP IT
        and TAKE IT act on the badge although DROP's listing had left the
        lighter in 1A57; OPEN IT answers "You can't open the badge!".
        """

        if not any(entry.class_id == 0x0B for entry in parsed.entries):
            return parsed
        state = self.vm.action_state
        target = state.byte_1a4c if state.byte_1a4c != 1 else (
            state.byte_1a57 if state.byte_1a56 == 0 else 1
        )
        if target in (0, 1):
            return parsed
        node = self.vm.phase7_runtime.get(target)
        replacement = None
        if node is not None and len(node) > 0x0B and self.vm.vocab_nodes is not None:
            replacement = self.vm.vocab_nodes.entry_for_message_symbol(node[0x0A] | node[0x0B] << 8)
        if replacement is None or replacement.value_a != 0 or replacement.value_b != target:
            replacement = next(
                (e for e in self.vocab if e.value_a == 0 and e.value_b == target), None
            )
        if replacement is None:
            return parsed
        entries = tuple(replacement if e.class_id == 0x0B else e for e in parsed.entries)
        return dataclasses.replace(parsed, entries=entries)

    def _dispatch_referent(self, parsed: ParsedCommand, action: "int | None") -> None:
        """sub_3472 on the one-object command path (sub_6F8B -> sub_423E).

        The grammar sends verb + object to sub_423E when the verb's value
        is in DS:4B6B -- the union of every object's +0Eh verb set, built at
        load (IDA 2790) -- and that dispatcher ends with sub_3472(object):
        1A56/1A57 := its kind/value, 1A54 := word_6AB. Other verbs take the
        no-object dispatcher 4857, and a two-object sentence another pattern
        (5F66 -> 3FDA). Measured 2026-10-15: TAKE, OPEN, CLOSE, EXAMINE,
        READ, WEAR and PRESS write it; FLIP and KISS (not in 4B6B) and PUT X
        IN Y do not. It runs before the response renders, so a listing in it
        (67b6) has the last word: DROP BADGE leaves the lighter.
        """

        if action is None:
            return
        if any(entry.value_a == 0x08 for entry in parsed.entries):
            return  # a preposition: the two-object pattern
        verb = next((e for e in parsed.entries if e.value_a == 0x06), None)
        noun = next((e for e in parsed.entries if e.value_a in (0, 1, 2, 3)), None)
        if verb is None or noun is None:
            return
        if verb.value_b not in self._object_verb_set():
            return
        self.vm.set_referent(noun.value_a, noun.value_b)

    def _object_verb_set(self) -> PascalSet:
        """DS:4B6B: the union of the phase-7 nodes' +0Eh verb sets."""

        cached = getattr(self, "_object_verbs_4b6b", None)
        if cached is None:
            cached = PascalSet.empty(8)
            for node in self.vm.phase7_runtime.values():
                if len(node) >= 0x16:
                    cached = cached.union(PascalSet.from_bytes(bytes(node[0x0E:0x16])))
            self._object_verbs_4b6b = cached
        return cached

    @staticmethod
    def _loc_3548_person(parsed: ParsedCommand) -> "int | None":
        """loc_3548(p): byte_4ADC from the persons the parser recorded.

        The parser (loc_7F26) keeps the first kind-1 noun's value in frame
        slot -2Ah and every later one in -2Bh (both 1 after sub_7BB7);
        loc_3548 makes 4ADC -2Ah when -2Bh is 1 or p, else -2Bh. Measured
        2026-10-15 (TILLY, TELL ME ABOUT GOLDFINGER at a new game): p = 3,
        the person addressed, -2Ah = 3, -2Bh = 2, 4ADC = 2. The port takes
        p as the first person typed (the addressee in every traced case).
        """

        persons = [entry.value_b for entry in parsed.entries if entry.value_a == 0x01]
        if not persons:
            return None
        first = persons[0]
        later = persons[-1] if len(persons) > 1 else 1
        addressee = first
        return first if later in (1, addressee) else later

    def _talk(self, parsed: ParsedCommand) -> "str | None":
        """The talk dispatch (IDA 4D93 via sub_6F8B): sub_3870 response.

        sub_3870 picks a person from the room's people set (+14h) and leaves
        that person's +0Ah record in word_4B7F, with section state 5; nobody
        present leaves person 1, whose record (Goldfinger: 6563) holds the
        generic answers and the Auric Stud password. Live-traced at walkthrough
        turn 72 (records 6563 -> 222 -> 6563 -> 1712). The rest of
        sub_6F8B's sentence grammar is not ported.
        """
        self._last_route = "talk"

        native_room = self.state.current_room + 1
        context = self.vm.graph.room(native_room)
        if context is None:
            return None
        self._open_message_record()
        words = words_from_entries(parsed.entries)
        if True:
            # sub_410C (a person first: ZORIN, ... / ASK ZORIN ...) hands
            # the typed person to the selection through &byte_1A50, so the
            # one asked answers, not the last one talked to (the referent).
            person = next((w.value for w in words if w.kind == 1), None)
            if person is not None and person in PascalSet.from_bytes(bytes(context[0x14:0x18])):
                self.vm.action_state.byte_1a50 = person
        record = self.vm.action_state.select_sub_3870_response(
            context,
            tuple(record.raw for record in self.vm.runtime_records.records),
        )
        if not record:
            return None
        record = self._speech_dispatch(parsed, record)
        self._select_typed_object_4ade(parsed)
        # 4B7C, `+,y`'s source, holds 4ADE as the talk entry left it (sub_4999
        # sets 4ADE before the response renders): Voodoo Island's record 149
        # moves 4ADE and ends with `+,y`, and Moma's answer then asks `&?y`
        # about the doll (native control trace, 2026-10-18).
        self.vm.action_state.record_work_blocks[0x4B7C] = bytes(
            (self.vm.action_state.byte_4ade & 0xFF,)
        )
        # The cursors were set up above (sub_7BB7 runs once per command);
        # the record open itself does not reset them again.
        callback = self.engine.record_open_callback
        self.engine.record_open_callback = None
        try:
            return self._move_with_hook_render(record, extra_substitutions={
                # `%b` names cursor 1A4F as the verb records do ("Here is
                # the lighter." when Tilly trades it back).
                "b": lambda: (
                    self._container_phrase(self.vm.action_state.byte_1a4f)
                    if self.vm.action_state.byte_1a4f > 1 else ""
                ),
                # `%t` names 1A4C the same way: Rambo's trade "He grabs the
                # camera and shoves the canteen into your hands."
                "t": lambda: (
                    self._container_phrase(self.vm.action_state.byte_1a4c)
                    if self.vm.action_state.byte_1a4c > 1 else ""
                ),
            })
        finally:
            self.engine.record_open_callback = callback

    def _speech_dispatch(self, parsed: ParsedCommand, record: int) -> int:
        """IDA 4E1E..50B3: the speech word picks the person's record.

        sub_3870 left the person in 1A50 and its +0Ah talk record in
        word_4B7F. A sentence with a kind-10 speech word switches on that
        word's class (person record 438[p]: +04h trade, +06h greeting,
        +08h give, +0Ah talk, +0Ch what the person has):

        * 11h trade: section 6; 1A4C := the object offered, 1A4F := the one
          wanted (1 when the same); with the wanted one carried (0671 - {1})
          they swap unless the offered one is carried too, otherwise they
          swap when the person has the offered one; record +04h, 1A4D := 1A4C.
        * 16h give: section 6; 1A4C = 1A4F := the object; record +08h.
        * 1Ch hello: section 7; record +06h.
        * 17h where: section 5, 4ADC := 1; the thing asked about lands by
          kind (0 -> 1A4C, 1 -> 4ADC, 2 -> 1A52, 3 -> 1A51, 7 -> the referent).
        * 19h question: section 5, 1A4C := the object.
        * no speech word: section 5.

        17h and 19h also take 4ADE into 1A4F when the person has it. The tail
        (loc_50B3) makes the object node the referent (sub_3472).
        Measured 2026-10-15 with Tilly: GIVE LIGHTER TO TILLY -> "Thanks."
        (record 7307 = +08h), TRADE LIGHTER FOR KEY -> "Here is the
        lighter.", HELLO TILLY -> "Hello.".
        """

        state = self.vm.action_state
        state.section_state = 5
        speech = next((entry for entry in parsed.entries if entry.value_a == 0x0A), None)
        nouns = [
            entry for entry in parsed.entries
            # The parser only looks at the kind byte (+8): the car key is a
            # group-1 word.
            if entry.value_a in (0, 1, 2, 3, 7) and entry is not speech
        ]
        objects = [entry.value_b for entry in nouns if entry.value_a == 0]
        first = objects[0] if objects else 1
        second = objects[1] if len(objects) > 1 else 1
        if nouns and nouns[0].value_a <= 3:
            self.vm.set_referent(nouns[0].value_a, nouns[0].value_b)
        if speech is None:
            return record
        person = self.vm.runtime_records.get(state.byte_1a50)
        raw = bytes(person.raw) if person is not None else b""
        if len(raw) < 0x14:
            return record

        def word(offset: int) -> int:
            return raw[offset] | (raw[offset + 1] << 8)

        possessions = PascalSet.from_bytes(raw[0x0C:0x14])
        word_class = speech.class_id
        if word_class == 0x11:
            state.section_state = 6
            carried = self.vm.predicates.blocks[0x671].difference(PascalSet.from_values([1], 8))
            state.byte_1a4c = first
            state.byte_1a4f = 1 if second == first else second
            if state.byte_1a4f in carried:
                swap = state.byte_1a4c not in carried
            else:
                swap = state.byte_1a4c in possessions
            if swap:
                state.byte_1a4c, state.byte_1a4f = state.byte_1a4f, state.byte_1a4c
            state.byte_1a4d = state.byte_1a4c
            return word(0x04) or record
        if word_class == 0x16:
            state.section_state = 6
            state.byte_1a4c = state.byte_1a4f = first
            return word(0x08) or record
        if word_class == 0x1C:
            state.section_state = 7
            return word(0x06) or record
        if word_class == 0x17:
            state.byte_4adc = 1
            if state.byte_4ade in possessions:
                state.byte_1a4f = state.byte_4ade
            # The noun loc_73C4 hands over ([bp+0Ch]) follows the speech
            # word: BANKS, WHERE ARE PRISONERS? asks about the prisoners,
            # not Banks (Rambo, "They should be at the rice paddies.").
            asked = parsed.entries[parsed.entries.index(speech) + 1:]
            after = [entry for entry in nouns if entry in asked] or nouns
            if after:
                kind, value = after[0].value_a, after[0].value_b
                if kind == 7:
                    kind, value = state.byte_1a56, state.byte_1a57
                target = {0: "byte_1a4c", 1: "byte_4adc", 2: "byte_1a52", 3: "byte_1a51"}.get(kind)
                if target is not None:
                    setattr(state, target, value)
            return record
        if word_class == 0x19:
            state.byte_1a4c = first
            # 4ADE holds the parser's first kind-0 noun (frame -2Ch, as
            # sub_50D8 copies it): OLLIE, DO YOU HAVE A GUN? -> the pistol
            # Ollie holds goes to 1A4F, "Ollie: You bet." (The Mist).
            state.byte_4ade = first
            if state.byte_4ade in possessions:
                state.byte_1a4f = state.byte_4ade
        return record

    def _select_typed_object_4ade(self, parsed: ParsedCommand) -> None:
        """sub_37B9 (the talk path's tail, loc_50B3): 4ADE := a typed object.

        The parser (sub_7DB8) keeps the first kind-0 noun's value in frame
        slot -2Ch and every later one in -2Dh (both 1 after sub_7BB7).
        sub_37B9 takes the smallest of those not already 1A4C/1A4F/1;
        with none left, 1A4F (or 1A4C when 1A4F is 1). Record 6563's
        `&?n` then asks whether that object is here.
        """

        values = list(parsed.object_ids())
        slot_2c = values[0] if values else 1
        slot_2d = values[-1] if len(values) > 1 else 1
        state = self.vm.action_state
        typed = {slot_2c, slot_2d} - {state.byte_1a4c, state.byte_1a4f, 1}
        if typed:
            state.byte_4ade = min(typed)
        else:
            state.byte_4ade = state.byte_1a4f if state.byte_1a4f != 1 else state.byte_1a4c
