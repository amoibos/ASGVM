"""AsgVm: parser context sets, descriptions and listings (=, * and + controls)."""

from __future__ import annotations

from typing import Sequence
from .actions import AsgActionExecutor
from .pascal_set import PascalSet
from .predicates import STAR_CONTEXT_SET_LAYOUTS
from .message_controls import star_should_skip_after_membership
from .runtime_records import RuntimeRecord


class ListingMixin:
    """Context sets, object and person listings, and the =, * and + controls."""

    def build_parser_context_sets(self, typed_nodes: Sequence[int]) -> None:
        """Port the parser's per-kind word sets (cleared each turn, 7E6F..).

        For every typed VOCAB node the parser adds its class byte (``+0`` of
        the 6B2 metadata, unless 33h) to 4AE2 and its value_b to the set its
        kind selects: 0 -> 4B81, 1 -> 4B89, 2 -> 4B8D, 3 -> 4B9C, 6 -> 4B9E,
        9 -> 4BB5, 10 -> 4BA6. ``$`` opcode 7Fh and the star selector read
        them. The kind-1 branch's ``+14`` redirection (7EA6..7F26) is not
        ported; the plain value_b is used.
        """

        if self.vocab_nodes is None:
            return
        sets = {
            address: PascalSet.empty(width)
            for address, width, _offset in set(STAR_CONTEXT_SET_LAYOUTS.values())
        }
        for node in typed_nodes:
            if not 0 <= node < len(self.vocab_nodes.metadata_by_node):
                continue
            metadata = self.vocab_nodes.metadata_by_node[node]
            if metadata[0] != 0x33:
                try:
                    sets[0x4AE2].add(metadata[0])
                except ValueError:
                    pass
            layout = STAR_CONTEXT_SET_LAYOUTS.get(metadata[2])
            if layout is not None and layout[0] != 0x4AE2:
                try:
                    sets[layout[0]].add(metadata[3])
                except ValueError:
                    pass
        for address, value in sets.items():
            self.action_state.record_work_blocks[address] = value.to_bytes()

    def _parser_context_member(self, node: int) -> bool | None:
        """``$`` opcode 7Fh (D018..D15E): was a word like this one typed?"""

        if self.vocab_nodes is None or not 0 <= node < len(self.vocab_nodes.metadata_by_node):
            return None
        metadata = self.vocab_nodes.metadata_by_node[node]
        layout = STAR_CONTEXT_SET_LAYOUTS.get(metadata[2])
        if layout is None:
            return None
        address, width, offset = layout
        raw = self.action_state.record_work_blocks.get(address)
        if raw is None:
            return False
        return metadata[offset] in PascalSet.from_bytes(bytes(raw[:width]), width)

    def snapshot_parser_cursors(self) -> None:
        """Keep the parser's cursor results in the scratch block DS:4B63.

        The native parser leaves the cursors it resolved in 4B63..4B6A
        (4B63 -> 1A4C, 4B66 -> 1A4F, 4B67 -> 1A50, 4B68 -> 1A51,
        4B69 -> 1A52); ``+V`` (56h, loc_F565) copies them back after a record
        has moved a cursor -- record 270 ends with ``+,i`` to restore 1A52.
        This port binds the cursors when a message record opens, so that is
        where the block is taken.
        """

        state = self.action_state
        self.action_state.record_work_blocks[0x4B63] = bytes(
            (
                state.byte_1a4c & 0xFF, 0, 0,
                state.byte_1a4f & 0xFF, state.byte_1a50 & 0xFF,
                state.byte_1a51 & 0xFF, state.byte_1a52 & 0xFF, 0,
            )
        )
        # byte_4B7C, +V's source for 4ADE (`+,y`), holds 4ADE as the
        # dispatcher left it. Measured in The Mist after POUR INSECTICIDE
        # FROM SPRAYER (11, the sprayer, sub_37B9) and POUR PESTICIDE INTO
        # SPRAYER (13, the bottle, sub_3E2E's tail).
        self.action_state.record_work_blocks[0x4B7C] = bytes((state.byte_4ade & 0xFF,))

    def describe_descriptor(self, node: int) -> "tuple[int, int, int | None] | None":
        """Port ``%d<descriptor>`` (sub_FF65 selector 9Ch -> sub_FDC9/sub_FE5B).

        The two-symbol descriptor names a VOCAB node whose kind/index pick the
        record: kind 2 a room (+0 word), kind 1 a person (phase-6 +0 word),
        kind 0 an object (phase-7 +8 word).

        Returns ``(kind, index, message word or None)``. It does **not** mark
        the thing described: ``sub_FE5B`` calls ``msg_dict_expand`` on the
        word first and writes ``+26h``/``1ACB`` only afterwards, and the text
        it renders asks ``&'`` about that very thing (room 25's prose opens
        with ``&'j``). The caller renders the word and then calls
        ``mark_described``.
        """

        if self.vocab_nodes is None or not 0 <= node < len(self.vocab_nodes.metadata_by_node):
            return None
        metadata = self.vocab_nodes.metadata_by_node[node]
        kind, index = metadata[2], metadata[3]
        word = None
        if kind == 2:
            room = self.graph.room(index)
            if room is not None and len(room) >= 2:
                word = room[0] | room[1] << 8
        elif kind == 1:
            record = self.runtime_records.get(index)
            if record is not None:
                word = record.raw[0] | record.raw[1] << 8
        elif kind == 0:
            phase7 = self.phase7_runtime.get(index)
            if phase7 is not None and len(phase7) >= 0x0A:
                word = phase7[8] | phase7[9] << 8
        return kind, index, word

    def mark_described(self, kind: int, index: int) -> None:
        """Mark a thing described exactly as ``=d``/``%d`` do.

        Public because a display path that does not itself run the native
        record carrying the ``=d`` (the chase, which shows a scenery room
        without rendering movement record 1712) still has to leave the same
        trace in ``1ACB``/``1AB8``/``1ADA`` -- the sets the first-visit
        question ``&'`` (80h) reads back.
        """

        self._mark_described(kind, index)

    def _mark_described(self, kind: int, index: int) -> None:
        if kind == 2:
            self.set_1acb.add(index)
            room = self.graph.room(index)
            if room is not None and len(room) > 0x26:
                room[0x26] = 0
        elif kind == 1:
            self.set_1ab8.add(index)
            record = self.runtime_records.get(index)
            if record is not None:
                raw = bytearray(record.raw)
                raw[0x1C] = 0
                self.runtime_records.replace(index, RuntimeRecord(index, bytes(raw)))
        elif kind == 3:
            self.set_1ada.add(index)
            if 0 <= index < len(self.phase9_runtime) and len(self.phase9_runtime[index]) > 0x10:
                self.phase9_runtime[index][0x10] = 0

    EQ_MENTION_SELECTOR = 0x9C

    def eq_indefinite_name(
        self, operands: Sequence[int], *, current_room: int | None
    ) -> "str | None":
        """HYPOTHESIS: the msg_ctrl_eq selector after the mention one (9Ch in
        the 47-byte build) prints the cursor's thing by its +0Ah name with
        "a"/"an" -- Voodoo Island's "You're not wearing =dt." reads "You're
        not wearing a necklace." on the original (2026-10-18). Only objects
        (kind 0) are covered."""

        if len(operands) < 2 or (operands[0] + 0x87) & 0xFF != self.EQ_MENTION_SELECTOR + 1:
            return None
        if self.EQ_MENTION_SELECTOR + 1 == self.EQ_LIST_SELECTOR:
            return None
        selector = self.cursor_selector(operands[1])
        kind = self.cursor_context_types.get(selector, self.STATIC_CURSOR_KINDS.get(selector))
        index = self.resolve_amp_operand(operands[1], current_room=current_room)
        if kind != 0 or index is None or index <= 1:
            return None
        node = self.phase7_runtime.get(index)
        if node is None or self.vocab_nodes is None or len(node) < 0x0C:
            return None
        entry = self.vocab_nodes.entry_for_message_symbol(node[0x0A] | node[0x0B] << 8)
        if entry is None or not entry.word:
            return None
        name = self.display_word(entry)
        return ("an " if name[:1].lower() in "aeiou" else "a ") + name

    def eq_mention_control(
        self, operands: Sequence[int], *, current_room: int | None
    ) -> "tuple[int, int, int | None] | None":
        """Port ``=d<cursor>`` (selector 9Ch, overlay 0x5C2..0x6DA).

        The second operand is a ``sub_AE9E`` cursor (AE27(87h)). When the
        resolved index is not 1 the native renders the cursor's message word
        through ``msg_dict_expand`` and marks the thing described only
        **after** that call returns (``sub_FE5B``: ``push ax`` /
        ``call msg_dict_expand`` / ``mov es:[di+26h], al`` / 1ACB union) --
        kind 2 -> ``1ACB`` and room ``+26h`` = 0, kind 1 -> ``1AB8`` and
        phase-6 ``+1Ch`` = 0, kind 3 -> ``1ADA`` and phase-9 ``+10h`` = 0.
        The order matters: a room's own prose asks ``&'j`` about itself.

        Returns ``(kind, index, message word or None)``; the word is the
        room's ``+0`` (sub_B110) or the node's ``+8`` (sub_AEAD). Rendering
        and the subsequent ``mark_described`` are the caller's.
        """

        if len(operands) < 2 or (operands[0] + 0x87) & 0xFF != self.EQ_MENTION_SELECTOR:
            return None
        selector = self.cursor_selector(operands[1])
        index = self.resolve_amp_operand(operands[1], current_room=current_room)
        kind = self.cursor_context_types.get(selector, self.STATIC_CURSOR_KINDS.get(selector))
        if index is None or kind is None:
            return None
        word = None
        if index != 1:
            if kind == 2:
                room = self.graph.room(index)
                if room is not None and len(room) >= 2:
                    word = room[0] | room[1] << 8
            elif kind == 0:
                node = self.phase7_runtime.get(index)
                if node is not None and len(node) >= 0x0A:
                    word = node[8] | node[9] << 8
            elif kind == 1:
                # sub_B09C: a person's description is its phase-6 record's
                # +0 word (+2 is the name). EXAMINE TILLY describes her.
                person = self.runtime_records.get(index)
                if person is not None and len(person.raw) >= 2:
                    word = person.raw[0] | person.raw[1] << 8
            elif kind == 3:
                # sub_B028: a Phase-9 record (vehicle, walker) is described
                # by its +0 word (+4 is the name): EXAMINE HELICOPTER.
                if 1 <= index <= len(self.phase9_runtime):
                    record = self.phase9_runtime[index - 1]
                    if len(record) >= 2:
                        word = record[0] | record[1] << 8
        return kind, index, word

    def cursor_person_name(self, symbol: int, *, current_room: int | None) -> str | None:
        """``%<cursor>`` for a person cursor (sub_FF65's non-special path).

        Outside its special selector set ``%`` resolves the operand as a
        cursor (``sub_AE9E``) and prints that thing's name. For a kind-1
        cursor (1A50, 4ADC) the name is the phase-6 record's ``+2`` VOCAB
        word; people's names print capitalised ("Goldfinger is here.",
        measured). Other kinds stay with the caller's substitutions.
        """

        selector = self.cursor_selector(symbol)
        kind = self.cursor_context_types.get(selector, self.STATIC_CURSOR_KINDS.get(selector))
        if kind == 0 and self.vocab_nodes is not None:
            # An object cursor prints the thing as the listing names it: High
            # Stakes' record 3370 points 1A4C at the tire iron (`(@tl`), then
            # "%t flies through the door" -- "The tire iron flies ...".
            index = self.resolve_amp_operand(symbol, current_room=current_room)
            if index is None or index <= 1 or index not in self.phase7_runtime:
                return None
            return self._listing_item_text(index, article=1, contents=0) or None
        if kind == 3 and self.vocab_nodes is not None:
            # A vehicle or beast (the 5B0h table): its +4 word, "the" when
            # +0Fh is set (overlay F8C8..) -- Forbidden Castle's "the small
            # boat", "Pegasus".
            index = self.resolve_amp_operand(symbol, current_room=current_room)
            if index is None or not 1 <= index <= len(self.phase9_runtime):
                return None
            raw = self.phase9_runtime[index - 1]
            if len(raw) <= 0x0F:
                return None
            entry = self.vocab_nodes.entry_for_message_symbol(raw[4] | raw[5] << 8)
            if entry is None or not entry.word:
                return None
            return ("the " if raw[0x0F] else "") + self.display_word(entry)
        if kind != 1 or self.vocab_nodes is None:
            return None
        index = self.resolve_amp_operand(symbol, current_room=current_room)
        record = None if index is None else self.runtime_records.get(index)
        if record is None:
            return None
        entry = self.vocab_nodes.entry_for_message_symbol(record.raw[2] | record.raw[3] << 8)
        if entry is None or not entry.word:
            return None
        # The +1Ah article flag as in the people listing: "the bartender".
        article = "the " if len(record.raw) > 0x1A and record.raw[0x1A] else ""
        return article + self.display_word(entry)

    def people_listing(
        self, *, current_room: int | None
    ) -> "tuple[bool, str, list[int]] | None":
        """Port ``%l`` (selector A0h, ``loc_F915``) without the rendering.

        The context room's (``sub_9711``) people set ``+14`` loses element 1
        (written back), and its being non-empty is ``byte_4B7B``. The people
        are listed in record order ``2..word_19E7`` as "<names> is/are
        here."; each one not yet in ``1AB8`` then gets its description record
        (phase-6 ``+0``) rendered by the caller, its ``+1C`` cleared, and
        ``1AB8`` absorbs them. Returns ``(byte_4B7B, the list sentence,
        description message offsets)``.
        """

        room_index = self._context_room(current_room)
        room = None if room_index is None else self.graph.room(room_index)
        if room is None or len(room) < 0x18 or self.vocab_nodes is None:
            return None
        people = PascalSet.from_bytes(bytes(room[0x14:0x18]), 4).difference(
            PascalSet.from_values([1], 4)
        )
        room[0x14:0x18] = people.to_bytes()
        if len(people) == 0:
            return False, "", []
        names: list[str] = []
        for index in range(2, self.activation.word_19e7 + 1):
            record = self.runtime_records.get(index)
            if index not in people or record is None:
                continue
            word = record.raw[2] | record.raw[3] << 8
            entry = self.vocab_nodes.entry_for_message_symbol(word)
            if entry is None:
                continue
            word = self.display_word(entry)
            names.append(("the " if record.raw[0x1A] else "") + word)
        if not names:
            return False, "", []
        listed = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
        sentence = listed + (" is here." if len(names) == 1 else " are here.")
        for index in people.values():
            self.set_referent(1, index)  # FB2C: each person listed
        new = people.difference(self.set_1ab8)
        descriptions: list[tuple[int, int]] = []
        for index in range(2, self.activation.word_19e7 + 1):
            record = self.runtime_records.get(index)
            if index not in new or record is None:
                continue
            descriptions.append((index, record.raw[0] | record.raw[1] << 8))
        return True, sentence, descriptions

    def describe_listed_person(self, index: int) -> None:
        """FB2C..FB6E before a description: sub_67B6(1, p). 1AB8 takes the
        people only after the loop, so a description still finds itself and
        the others undescribed (High Stakes' `&'m$'aj`: "your two friends
        blurt out")."""

        self.set_referent(1, index)

    def finish_listed_person(self, index: int) -> None:
        """FB64: +1Ch := 0 once the description is out."""

        record = self.runtime_records.get(index)
        if record is not None:
            raw = bytearray(record.raw)
            raw[0x1C] = 0
            self.runtime_records.replace(index, RuntimeRecord(index, bytes(raw)))

    def absorb_listed_people(self, people: "list[int]") -> None:
        """FB7B: 1AB8 takes the described people after the loop."""

        for index in people:
            self.set_1ab8.add(index)

    # ``msg_ctrl_eq`` (overlay 0x278 -> 0x52A) reads its first operand with
    # ``sub_AE27(87h)``. Selector 9Eh (MESSAGE ``h``) enters ``sub_028A``,
    # which reads a second operand with ``sub_AE27(57h)`` naming the set to
    # list, then hands the filtered set to the shared output ``loc_C114``.
    EQ_LIST_SELECTOR = 0x9E
    # The three cursor selectors ``sub_028A`` resolves through ``sub_AE9E``
    # (each a ``sub_AEAD`` phase-7 node cursor).
    EQ_LIST_CURSOR_SELECTORS = {0x8A: "byte_1a4c", 0x8E: "byte_1a4f", 0x94: "byte_4ade"}

    def eq_list_set(
        self, source_selector: int, *, current_room: int | None
    ) -> PascalSet | None:
        """Port ``sub_028A`` (overlay 0x28A..0x51D): the set ``=h`` lists.

        Sources: 74h the context room's ``+18`` set (room from ``sub_9711``),
        75h ``0679``, 76h ``0679 | 0671``, 81h ``0671``, and the cursor
        selectors 8Ah/8Eh/94h the cursor node's own leading set. Any other
        selector leaves the cleared temporary set. Cursor sources whose node
        is type 2 lose ``0699``; other cursor nodes lose the sets of every
        type-0/1 node they hold (0x435..0x4C4); every non-cursor source loses
        ``0699``. Element 1 is always removed before ``loc_C114``.
        """

        candidate = PascalSet.empty(8)
        cursor_node = None
        if source_selector == 0x74:
            room_index = self._context_room(current_room)
            room = None if room_index is None else self.graph.room(room_index)
            if room is None or len(room) < 0x20:
                return None
            candidate = PascalSet.from_bytes(bytes(room[0x18:0x20]), 8)
        elif source_selector == 0x75:
            candidate = self.predicates.blocks[0x679]
        elif source_selector == 0x76:
            candidate = self.predicates.blocks[0x679].union(self.predicates.blocks[0x671])
        elif source_selector == 0x81:
            candidate = self.predicates.blocks[0x671]
        elif source_selector in self.EQ_LIST_CURSOR_SELECTORS:
            cursor_node = getattr(
                self.action_state, self.EQ_LIST_CURSOR_SELECTORS[source_selector]
            )
            node = self.phase7_runtime.get(cursor_node)
            if node is None:
                return None
            candidate = PascalSet.from_bytes(bytes(node[0:8]), 8)
        if cursor_node is not None:
            if self.phase7_runtime[cursor_node][0x18] == 2:
                candidate = candidate.difference(self.predicates.blocks[0x699])
            else:
                for index in range(2, self.activation.byte_19e9 + 1):
                    if index not in candidate:
                        continue
                    member = self.phase7_runtime.get(index)
                    if member is not None and member[0x18] in (0, 1):
                        candidate = candidate.difference(
                            PascalSet.from_bytes(bytes(member[0:8]), 8)
                        )
        else:
            candidate = candidate.difference(self.predicates.blocks[0x699])
        return candidate.difference(PascalSet.from_values([1], 8))

    def set_listing_nodes(self, candidate: PascalSet) -> list[int]:
        """Port the two node loops of ``loc_C114``.

        First every type-2 node still in the set gives up its contents (the
        membership test reads the set as it shrinks), then the remaining
        nodes ``2..byte_19E9`` are listed in index order. An empty result is
        ``byte_4B7B = 0``; anything listed is ``byte_4B7B = 1``.
        """

        work = candidate
        for index in range(2, self.activation.byte_19e9 + 1):
            if index not in work:
                continue
            node = self.phase7_runtime.get(index)
            if node is not None and node[0x18] == 2:
                work = work.difference(PascalSet.from_bytes(bytes(node[0:8]), 8))
        return [index for index in range(2, self.activation.byte_19e9 + 1) if index in work]

    def _node_contents_for_listing(self, index: int, acc: PascalSet) -> PascalSet:
        """Port ``sub_C28C``: a type-2 node's contents minus ``0681``, recursively."""

        node = self.phase7_runtime.get(index)
        if node is None:
            return acc
        contents = PascalSet.from_bytes(bytes(node[0:8]), 8)
        if len(contents) == 0:
            return acc
        local = contents.difference(self.predicates.blocks[0x681])
        acc = acc.union(local)
        for child in range(2, self.activation.byte_19e9 + 1):
            if child in local:
                member = self.phase7_runtime.get(child)
                if member is not None and member[0x18] == 2:
                    acc = self._node_contents_for_listing(child, acc)
        return acc

    @staticmethod
    def display_word(entry) -> str:
        """A VOCAB word as the printer shows it: group 0 in capitals (DB5,
        ARR, M), group 1 capitalised (Goldfinger, Zorin), group 2 as it is
        (A View to a Kill's "the bartender")."""

        word = entry.word
        if not word:
            return word
        if entry.group_id == 0x00:
            return word.upper()
        if entry.group_id == 0x01:
            # Every word of a name: "May Day".
            return " ".join(part[:1].upper() + part[1:] for part in word.split(" "))
        return word

    def _listing_item_text(self, index: int, *, article: int, contents: int) -> str:
        """Port ``loc_C37F``: one list item.

        The item carries the node's ``+0A`` VOCAB word and ``+19`` article
        flag. A kind-0 word whose node is type 5 reads "the body of", type 3
        drops the caller's article request, and type 2 (when the caller asks
        for contents) appends "with ... on it". The ``sub_67B6`` bookkeeping
        call each item makes is not ported.
        """

        node = self.phase7_runtime.get(index)
        if node is None or self.vocab_nodes is None:
            return ""
        word_index = node[0x0A] | node[0x0B] << 8
        entry = self.vocab_nodes.entry_for_message_symbol(word_index)
        if entry is None:
            return ""
        metadata = self.vocab_nodes.metadata_by_node[word_index]
        body_of = False
        nested = ""
        if metadata[2] == 0:
            target = self.phase7_runtime.get(metadata[3])
            target_type = None if target is None else target[0x18]
            if target_type == 5:
                body_of = True
            elif target_type == 3:
                article = 0
            elif target_type == 2 and contents:
                held = self._node_contents_for_listing(metadata[3], PascalSet.empty(8))
                held_nodes = [
                    child for child in range(2, self.activation.byte_19e9 + 1)
                    if child in held
                ]
                if held_nodes:
                    nested = " with " + self.render_node_list(
                        held_nodes, article=0, contents=0
                    ) + " on it"
        text = ""
        if body_of:
            text = "the body of "
            article = 0
        if article or node[0x19]:
            text += "the "
        # Group 1 names print capitalised word by word ("the body of
        # Oddjob", High Stakes' "the Racing Calendar"), group 0 initialisms
        # in capitals ("the ARR").
        return text + self.display_word(entry) + nested

    def phase9_listing(self, *, current_room: int | None) -> "tuple[bool, str]":
        """Port ``%w`` (sub_FF65 selector 9Fh -> sub_FBA7).

        Phase-9 records 2..byte_19EB whose room ``+0Eh`` is the context room
        (sub_9711) go into a list of (``+04h`` VOCAB word, ``+0Fh`` article
        flag), which sub_C111 prints as "A", "A and B", ...; byte_4B7B is
        whether the list is non-empty. Movement record 1712 ends its revisit
        line with it, so a room holding nothing of the kind adds nothing.
        """

        room = self._context_room(current_room)
        words: list[str] = []
        listed: list[int] = []
        if room is not None and self.vocab_nodes is not None:
            for index in range(2, self.activation.byte_19eb + 1):
                if not 0 <= index - 1 < len(self.phase9_runtime):
                    continue
                record = self.phase9_runtime[index - 1]
                if len(record) <= 0x0F or record[0x0E] != room:
                    continue
                entry = self.vocab_nodes.entry_for_message_symbol(record[4] | record[5] << 8)
                if entry is None or not entry.word:
                    continue
                # Group 0 in capitals ("DB5"), group 1 word by word ("the
                # White Dragon").
                word = self.display_word(entry)
                words.append(("the " if record[0x0F] else "") + word)
                listed.append(index)
        # HYPOTHESIS (as FB2C does for people): each listed walker becomes
        # the referent (67b6(3, i)).
        for index in listed:
            self.set_referent(3, index)
        self.action_state.byte_4b7b = int(bool(words))
        if not words:
            return False, ""
        parts: list[str] = []
        for position, word in enumerate(words):
            if position:
                parts.append(" and " if position == len(words) - 1 else ", ")
            parts.append(word)
        # FC7F..FCF0: sub_C111 prints the list, then "is" for a single entry
        # (the list's next pointer is nil) or "are", then "here.".
        sentence = "".join(parts)
        sentence = sentence[:1].upper() + sentence[1:]
        return True, sentence + (" is here." if len(words) == 1 else " are here.")

    def render_node_list(self, nodes: Sequence[int], *, article: int, contents: int) -> str:
        """Port ``sub_C111``/``loc_C626``: "A", "A and B", "A, B and C"."""

        parts: list[str] = []
        for position, index in enumerate(nodes):
            if position:
                parts.append(" and " if position == len(nodes) - 1 else ", ")
            parts.append(self._listing_item_text(index, article=article, contents=contents))
            # C3F6: every thing the list prints becomes the referent.
            self.set_referent(0, index)
        return "".join(parts)

    def eq_list_control(
        self, operands: Sequence[int], *, current_room: int | None
    ) -> "tuple[bool, str] | None":
        """``=h<source>``: ``(byte_4B7B, listed text)``, or ``None`` if unported.

        ``loc_C114`` calls the list output with article request 0 and
        contents request 1.
        """

        if len(operands) < 2 or (operands[0] + 0x87) & 0xFF != self.EQ_LIST_SELECTOR:
            return None
        candidate = self.eq_list_set((operands[1] + 0x57) & 0xFF, current_room=current_room)
        if candidate is None:
            return None
        nodes = self.set_listing_nodes(candidate)
        if not nodes:
            return False, ""
        return True, self.render_node_list(nodes, article=0, contents=1)

    def evaluate_eq_control(
        self,
        opcode: str | int,
        *,
        current_room: int | None = None,
        context_record: bytes | bytearray | None = None,
    ) -> bool | None:
        """Evaluate the live MESSAGE ``=`` control into byte_4B7B semantics."""

        evaluator = self.predicate_evaluator(current_room=current_room)
        if evaluator is None:
            return None
        room_context = None
        if current_room is not None:
            room = self.tables.resolve_native_room(current_room)
            if room is not None:
                room_context = room.raw
        candidate = evaluator.eq_candidate_set(opcode, room_context=room_context)
        if candidate is None:
            return None
        if context_record is not None:
            filtered = evaluator.eq_filter_candidate_for_context(candidate, context_record)
            if filtered is not None:
                return evaluator.eq_final_render_result(filtered)
            phase7_records = {
                node.index: node.raw for node in self.activation.phase7_nodes
            }
            filtered = evaluator.eq_apply_node_filter_body(
                candidate,
                phase7_records=phase7_records,
                phase7_count=self.activation.byte_19e9,
            )
            if filtered is None:
                return None
            return evaluator.eq_final_render_result(filtered)
        # Non-selector opcodes reach the common tail, subtracting 0699 before
        # the final singleton-1 render gate.
        return evaluator.eq_final_render_result(candidate.difference(self.predicates.blocks[0x699]))

    def evaluate_star_control(
        self,
        *,
        context_record: bytes | bytearray,
        star_sets: dict[int, PascalSet] | None = None,
    ) -> bool | None:
        """Evaluate the confirmed ``*`` membership tail into render semantics."""

        evaluator = self.predicate_evaluator()
        if evaluator is None:
            return None
        if star_sets is None:
            star_sets = self.star_context_sets()
        membership = evaluator.star_context_membership(context_record, star_sets=star_sets)
        should_skip = star_should_skip_after_membership(membership)
        return None if should_skip is None else not should_skip

    def evaluate_star_candidate(
        self,
        mode: int,
        operand_symbol: int | None,
        descriptor: int,
        *,
        current_room: int | None = None,
    ) -> bool | None:
        """Evaluate one ``msg_ctrl_star`` candidate from its VOCAB metadata.

        Mode 3 resolves its operand through the same ``AE27(87h)`` selector
        family as ampersand controls, then dispatches on the resolver kind
        against the candidate's four metadata bytes at runtime table ``6B2``.
        """

        if mode == 1:
            raw = self.action_state.record_work_blocks.get(0x4AE9)
            if raw is None:
                return None
            return descriptor in PascalSet.from_bytes(raw)
        if mode == 2:
            # The command-local 40-byte candidate set is populated by the
            # parser before MESSAGE dispatch. Mode-2 selectors use it for
            # adjective-qualified alternatives (the candidate descriptors
            # are the actual VOCAB node ids). The broader context-set test
            # remains the fallback for selectors driven by world state.
            parser_candidates = self.action_state.record_work_blocks.get(0x4AE9)
            if (
                parser_candidates is not None
                and descriptor in PascalSet.from_bytes(parser_candidates)
            ):
                return True
            if self.vocab_nodes is None or not 0 <= descriptor < len(
                self.vocab_nodes.entries_by_node
            ):
                return False
            if self.vocab_nodes.entries_by_node[descriptor] is None:
                return False
            evaluator = self.predicate_evaluator()
            if evaluator is None:
                return None
            # The membership tail reads the parser's per-kind word sets
            # (4B81/4B89/4B8D/..., built by build_parser_context_sets from
            # what the player typed): TYPE OPEN DOOR puts value_b 37 into
            # 4B8D, so record 2281's "steel door" candidate (node 195, kind 2,
            # value_b 37) is chosen. The room-derived sets are only a
            # fallback for a turn whose parse built none.
            parser_sets = {
                address: PascalSet.from_bytes(self.action_state.record_work_blocks[address])
                for address, _width, _offset in set(STAR_CONTEXT_SET_LAYOUTS.values())
                if address in self.action_state.record_work_blocks
            }
            return evaluator.star_context_membership(
                self.vocab_nodes.metadata_by_node[descriptor],
                star_sets=parser_sets or self.star_context_sets(),
            )
        if mode != 3 or operand_symbol is None or self.vocab_nodes is None:
            return None
        if not 0 <= descriptor < len(self.vocab_nodes.metadata_by_node):
            return False
        selector = self.cursor_selector(operand_symbol)
        target = self.resolve_amp_operand(operand_symbol, current_room=current_room)
        if target is None:
            return None
        kind_by_selector = self.STATIC_CURSOR_KINDS
        # The table above is the *static* kind of each global cursor (the
        # current-room selectors are naturally kind 2, and so on). The two
        # object cursors, 8Ah and 8Eh, carry whatever kind the parsed noun
        # had, so a recorded kind overrides the static entry. This is what
        # lets mode 3's kind-2 branch run for a scenery noun: that branch
        # walks the six exit bytes of the room record at 025C[context+3]
        # (filtered through the active-room set 4ABE), which is where a
        # room's scenery lives -- native room 27's only scenery exit is
        # record 35, the trap door, so the generic noun "door" resolves
        # there, and the walkthrough's "you open the trap door." is a
        # candidate selection, not a synonym lookup.
        kind = self.cursor_context_types.get(selector, kind_by_selector.get(selector))
        if kind is None:
            return None
        owner_value = 0x33
        if selector == 0x89:
            node_index = self.action_state.word_4b12
            if not 0 <= node_index < len(self.vocab_nodes.metadata_by_node):
                return False
            source = self.vocab_nodes.metadata_by_node[node_index]
            owner_value = source[0]
            target = source[3] if source[2] == 6 else 0
        elif selector == 0x9B:
            # AFC4 resolves through the still-unported word table 4AA8;
            # byte_1A59 itself is only its index, not the comparison value.
            return None
        evaluator = self.predicate_evaluator()
        if evaluator is None:
            return None
        metadata = self.vocab_nodes.metadata_by_node[descriptor]
        return evaluator.star_mode3_target_match(
            metadata,
            kind,
            target,
            owner_value=owner_value,
            set_1abc=PascalSet.from_values(sorted(self.graph.bridge_rooms_1abc), 15),
            set_4abe=PascalSet.from_values(sorted(self.graph.active_rooms_4abe), 15),
            indirect_records_025c={
                index: room for index, room in enumerate(self.graph.rooms, start=1)
            },
        )

    def star_mode0_candidate_index(self, candidate_count: int) -> int | None:
        """Port mode 0's ``word_6AB mod candidate_count`` selection."""

        if candidate_count <= 0:
            return None
        # The live move counter: record 3511's `*aee` picks "Tilly's grip
        # seems to soften" at move 3 and "Tilly relaxes slightly" at move 6.
        return self.move_counter % candidate_count

    def star_context_sets(self) -> dict[int, PascalSet]:
        """Build the native ``msg_ctrl_star`` context sets from live rooms."""

        sets: dict[int, PascalSet] = {
            address: PascalSet.empty(width)
            for address, width, _offset in set(STAR_CONTEXT_SET_LAYOUTS.values())
        }
        for room in self.graph.rooms:
            if len(room) < 4:
                continue
            layout = STAR_CONTEXT_SET_LAYOUTS.get(room[2])
            if layout is None:
                continue
            address, _width, value_offset = layout
            if value_offset < len(room):
                try:
                    sets[address].add(room[value_offset])
                except ValueError:
                    pass
        return sets

    def evaluate_plus_control(
        self,
        opcode: str | int,
        *,
        target_room: int | None = None,
        operand_symbol: int | None = None,
        current_room: int | None = None,
        destination_symbols: "tuple[int, ...] | None" = None,
    ) -> bool | None:
        """Evaluate confirmed live MESSAGE ``+`` controls.

        This currently executes the fully decoded ``+T``/``sub_B805`` body and
        delegates other already-isolated ``+`` primitives to
        :class:`AsgActionExecutor` when they do not require unresolved parser
        frame data.
        """

        if isinstance(opcode, str):
            if len(opcode) != 1:
                return None
            opcode_value = ord(opcode.upper())
        else:
            opcode_value = opcode
        executor = AsgActionExecutor(
            self.table_state,
            self.action_state,
            self.predicates,
            auxiliary_4ab6=self.auxiliary_4ab6,
        )
        if opcode_value == 0x52 and operand_symbol is not None:
            # `+%<cursor><destination>`: the walk with the walker in a cursor
            # (the chase capture's `+%x=j` moves the "tardis" record that
            # 1A51 selects to the player's room).
            selector = self.cursor_selector(operand_symbol)
            kind = self.cursor_context_types.get(selector, self.STATIC_CURSOR_KINDS.get(selector))
            walker = self.resolve_amp_operand(operand_symbol, current_room=current_room)
            extra = tuple(destination_symbols or ())
            destination = None
            by_cursor = False
            if len(extra) >= 3 and extra[0] == 0x20 and self.vocab_nodes is not None:
                node = extra[1] * 0x40 + extra[2]
                if 0 <= node < len(self.vocab_nodes.metadata_by_node):
                    destination = self.vocab_nodes.metadata_by_node[node][3]
            elif len(extra) >= 2 and extra[0] == 0x2D:
                destination = self.resolve_amp_operand(extra[1], current_room=current_room)
                by_cursor = self.cursor_selector(extra[1]) == 0x92
            if walker is None or kind is None:
                return None
            self._walk_resolved(
                kind, walker, destination, current_room=current_room, follow=by_cursor
            )
            return bool(self.action_state.byte_4b7b)
        if operand_symbol is not None and opcode_value in (0x39, 0x3A, 0x44, 0x45):
            selector = self.cursor_selector(operand_symbol)
            target = self.resolve_amp_operand(
                operand_symbol, current_room=current_room
            )
            # 8Bh (byte_1A52) is the scenery cursor: record 2315's scenery
            # branch opens with `+ki`, action opcode 44h on that cursor.
            # Any cursor: Indiana Jones' capture closes and locks the cage
            # door behind the player through `+zg` / `+bg` (97h, 1AE3).
            kind = self.cursor_context_types.get(
                selector, self.STATIC_CURSOR_KINDS.get(selector)
            )
            if kind is not None and target is not None:
                # Same fork as the descriptor form in execute_action_block:
                # the cursor's resolver kind decides which table the write
                # lands in (sub_DCAD vs sub_E048). A kind-2 cursor names a
                # room-table record, so sending it to the phase-7 table wrote
                # whichever object happened to share the index -- i.e. the
                # OPEN never reached the scenery whose description reads it.
                if kind != self.OBJECT_CONTEXT_TYPE:
                    room_record = self.graph.room(target)
                    if room_record is None or not self._scenery_within_reach(target, current_room):
                        return False
                    return executor.execute_room_state_action(
                        opcode_value,
                        target_context=room_record,
                        current_room=current_room,
                        active_rooms=self.graph.active_rooms_4abe,
                        phase9_records=self.activation.phase9_records,
                    )
                node = self.phase7_runtime.get(target)
                room = self.graph.room(current_room or 0)
                if node is None or room is None:
                    return False
                return executor.execute_phase7_state_action(
                    opcode_value,
                    target_index=target,
                    target_node=node,
                    current_room_context=room,
                    nodes=self.phase7_runtime,
                    excluded_19ef=self.excluded_19ef,
                    phase7_count=self.activation.byte_19e9,
                )
        if opcode_value == 0x53 and operand_symbol is not None:
            # sub_F5F9 F6E2..F7A5: the cursor's kind picks the global that
            # receives its index -- the same body as the ``(`` form's
            # descriptor (execute_descriptor_action).
            selector = self.cursor_selector(operand_symbol)
            target = self.resolve_amp_operand(operand_symbol, current_room=current_room)
            kind = self.cursor_context_types.get(
                selector, self.STATIC_CURSOR_KINDS.get(selector)
            )
            if target is None or kind is None:
                return None
            done = executor.execute_descriptor_action(
                0x53, descriptor=bytes((0, 0, kind, target & 0xFF))
            )
            if done and kind == 2:
                self._select_bridge_vehicle(target & 0xFF)
                self._aim_at_room(target & 0xFF, current_room)
            return done
        if opcode_value == 0x56 and operand_symbol is not None:
            block = self.action_state.record_work_blocks.get(0x4B63)
            if block is None:
                return None
            saved_4ade = self.action_state.record_work_blocks.get(0x4B7C)
            return executor.execute_plus_v_context(
                self.cursor_selector(operand_symbol),
                parser_block_4b63=block,
                byte_4b7c=None if saved_4ade is None else saved_4ade[0],
            )
        if opcode_value == 0x54:  # 'T'
            if target_room is None and operand_symbol is not None:
                # sub_F5F9 F7B0: sub_B805 with the resolved cursor index.
                target_room = self.resolve_amp_operand(
                    operand_symbol, current_room=current_room
                )
            if target_room is None:
                return executor.execute_plus_t_gate()
            rooms = {
                index: room
                for index, room in enumerate(self.graph.rooms, start=1)
            }
            return executor.execute_plus_t_transfer(
                room_contexts=rooms,
                target_room=target_room,
                current_room=current_room,
            )
        if opcode_value == 0x4E and operand_symbol is not None:
            # sub_F5F9 loc_F667: cursor 8Fh toggles byte_1A8A; any other
            # cursor calls sub_B74B(index) on the phase-7 record DS:04B4 --
            # a light source (+18h == 4) has its +1Ah flipped and joins or
            # leaves DS:4AB6. LIGHT's record 2754 runs `+|t` on the lighter,
            # and record 31's `$qp6` then reads that +1Ah back.
            selector = self.cursor_selector(operand_symbol)
            if selector == 0x8F:
                self.action_state.byte_1a8a ^= 1
                return True
            index = self.resolve_amp_operand(operand_symbol, current_room=current_room)
            node = None if index is None else self.phase7_runtime.get(index)
            if node is None or len(node) <= 0x1A or node[0x18] != 4:
                self.action_state.byte_4b7b = 0
                return False
            self.action_state.byte_4b7b = 1
            return executor.execute_room_toggle_action(room_context=node, value=index)
        return None
