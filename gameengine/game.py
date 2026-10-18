"""Shared transitional binding for sibling titles using the same engine.

It intentionally implements only engine-invariant behavior: loading the five
native data files, VOCAB parsing, type-2 room records, the six native direction
slots, MESSAGE room rendering, LOOK and QUIT.  Title-specific action handlers
belong in each game's package as their overlays are recovered.
"""

from __future__ import annotations

import dataclasses
import os
import sys
import re

import argparse
from pathlib import Path
from typing import Callable

from gameengine.data import GameData
from gameengine import savegames
from gameengine.gamecom import GameComMessageEngine
from gameengine.parser import GoldfingerParser, ParsedCommand
from gameengine.grammar import route, take_or_ride_pattern, words_from_entries
from gameengine.paging import print_paged
from gameengine.tables import TableDecoder
from gameengine.vocab import VocabDecoder
from gameengine.world import EngineGameState, Room
from gameengine.vm import AsgVm


from gameengine.config import AsgConfig
from gameengine.game_messages import MessageMixin
from gameengine.game_movement import MovementMixin
from gameengine.game_talk import TalkMixin
from gameengine.game_vehicles import VehicleMixin
from gameengine.game_nouns import NounMixin


class AsgGame(MessageMixin, MovementMixin, TalkMixin, VehicleMixin, NounMixin):
    def __init__(self, data: GameData, config: AsgConfig) -> None:
        self.data = data
        self.config = config
        self.engine = GameComMessageEngine(data.message)
        self.vocab = VocabDecoder(data.vocab).entries()
        self.parser = GoldfingerParser(self.vocab)
        self.tables = TableDecoder(data.tables, record_size=config.table_record_size)
        self.vm = AsgVm.from_decoder(self.tables)
        self.engine.render_stop_check = lambda: bool(
            self.vm.action_state.flag_4bcb or self.vm.action_state.flag_4bcc
        )
        if config.table_record_size == 47:
            # The 47-byte engine build numbers msg_ctrl_eq's selectors one
            # lower: every title of that build lists with `=s` (9Dh) and
            # describes with `=o` (9Bh) where the 40-byte build has `=h`/`=d`
            # (inventory and LOOK records of all eight titles compared).
            self.vm.EQ_LIST_SELECTOR = 0x9D
            self.vm.EQ_MENTION_SELECTOR = 0x9B
            # sub_FF65 (`%`) is shifted the same way.
            self.engine.percent_variant_b = True
        self.vm.configure_vocab(self.vocab)
        self.vm.activate()
        # The set transfer (GAME.000 1F62, in the start-up chain after the
        # activation phases) runs once before the first prompt: in A View to
        # a Kill's memory after the opening every person with +17h below 99
        # holds their room's objects (M the clip he later hands over), and it
        # does not run again -- after turn 28 the calculator and wires Q left
        # still lie in M's office although M is "active".
        self.vm.execute_start_transfers()
        if self.config.movement_command_record is None:
            # GAME.000 4AF4 answers every move on foot with word_1A9F --
            # DS:1A8D's fourth secondary word (Goldfinger 1893, A View to a
            # Kill 2198), set up by the activation from the data.
            derived = self.vm.table_state.array_1a8d_secondary.get(4, 0)
            if derived:
                self.config = dataclasses.replace(
                    self.config, movement_command_record=derived
                )
        # Verb-to-MESSAGE-record table, built data-driven from the phase-1
        # activation pointer (port of the native DS:0x5F0 builder). This is the
        # authoritative source; no title wires a frozen capture anymore. The
        # optional ``config.verb_response_records`` override is only consulted if
        # the derivation yields nothing (defensive -- never happens for the
        # shipped titles: the derivation reproduces every captured table).
        self.verb_response_records = (
            self.vm.activation.build_verb_response_records(self.engine)
            or self.config.verb_response_records
        )
        self._current_command_value_b: int | None = None
        self._current_command_node: int | None = None
        self._current_object_node: int | None = None
        self._current_indirect_object_node: int | None = None
        self._current_modifier_nodes: tuple[int, ...] = ()
        # Set when a kind-2 noun resolved to no scenery in the current room.
        self._current_scenery_absent: bool = False
        # The scenery record a kind-2 noun resolved to this turn, if any.
        self._current_scenery_value_b: int | None = None
        self._current_place_value_b: int | None = None
        self._current_dispatcher: int | None = None
        self._current_parsed: "ParsedCommand | None" = None
        self._current_direction: int | None = None
        # When rendering a room DESCRIPTION, the native amp room-context cursor
        # ``byte_1A52`` (amp selector 8Bh) is the current room, so data-driven
        # ``&:i$YY`` room-id predicates (e.g. the shared manhole record 3863's
        # ``ground`` vs ``ceiling`` word) resolve. The top-level MESSAGE-open
        # reset (sub_7BB7) seeds it to 1; this holds the current native room so
        # the open callback can rebind it after that reset.
        self._room_context_native: int | None = None
        self._current_person_value: int | None = None
        self._rendering_turn_tail = False
        # The start record's text (the boot cutscene), set by _run_start_program.
        self.opening_text = ""
        self._session_visited_rooms: set[int] = set()
        # Per-game title scene state (Goldfinger chase/heli/fights). Built at
        # the end of __init__ once the game object is fully wired.
        self.engine.record_open_callback = self._open_message_record
        self.engine.control_evaluator = self._evaluate_message_control
        self.engine.control_text_evaluator = self._evaluate_message_control_text
        self.engine.star_candidate_matcher = self._evaluate_star_candidate
        self.engine.star_mode0_index_provider = self.vm.star_mode0_candidate_index
        self.engine.action_executor = self._execute_action_block
        self.engine.action_gate_reader = self._read_action_gate
        self.vm.save_hook = self._save_dialog
        self.engine.action_output_reader = self._read_action_output
        records = self.tables.records_by_type(0x02)
        self.object_records = self.tables.records_by_type(0x01)
        self.object_names: dict[int, str] = {}
        for entry in self.vocab:
            if entry.group_id in (0x00, 0x01, 0x02) and entry.value_a == 0 and entry.value_b:
                current = self.object_names.get(entry.value_b, "")
                if not current or len(entry.word) > len(current):
                    self.object_names[entry.value_b] = entry.word
        self.rooms = {}
        for index, record in enumerate(records):
            self.rooms[index] = Room(
                room_index=index,
                record=record,
                # The room's MESSAGE position is LE at +1 (raw[1] | raw[2]<<8)
                # for BOTH variants. The earlier Variant-A `be_word(2)` was a
                # decode error: it made 15 of 65 rooms render the same
                # "bluegrass" text (a shared-composite artifact) and only 24
                # distinct descriptions, whereas LE +1 yields 42 distinct and
                # only 2 bluegrass. Confirmed against the SAVE1 oracle (native
                # room 20 -> "The cockpit of the DB5...", which LE +1 renders
                # exactly and be_word(2) rendered empty) and the walkthrough
                # (LE +1's "checkerboard of interlocking runways" appears;
                # be_word(2)'s "blacktop road gives way" does not).
                message_offset=record.le_word(1),
                exits=record.native_direction_slots(),
            )
        initial_index = (
            (self.vm.initial_native_room_id - 1)
            if config.initial_native_room_id is None
            else config.initial_native_room_id - 1
        )
        if initial_index is not None and initial_index not in self.rooms:
            raise ValueError(
                f"initial native room {config.initial_native_room_id} is outside "
                f"the {len(self.rooms)} loaded rooms"
            )
        self.state = EngineGameState(current_room=initial_index)
        if initial_index is not None:
            self.state.direction_available = self._direction_availability(initial_index)

    def inventory_ids(self) -> list[int]:
        """Objects the player has: native sets 0671 (in hand) | 0679 (on person)."""

        carried = self.vm.predicates.blocks[0x671].union(self.vm.predicates.blocks[0x679])
        return [index for index in carried.values() if 1 <= index <= len(self.object_records)]

    @classmethod
    def load(cls, config: AsgConfig, root: Path | str | None = None) -> "AsgGame":
        data_root = config.root if root is None else Path(root)
        data = GameData.load(data_root, launcher_name=config.launcher_name)
        game = cls(data, config)
        game._run_start_program()
        return game

    def start_record(self) -> "int | None":
        """word_1A93 (DS:1A8D+6): the record the boot renders.

        The boot sets byte_1AE0, and the end-of-turn render (IDA 10EE4..)
        prints word_1A93 instead of word_4B7F while it is set. The word
        comes from the activation data like the rest of DS:1A8D
        (Goldfinger 3899, High Stakes 4702, Indiana Jones 4098).
        """

        if self.config.start_program_record is not None:
            return self.config.start_program_record
        block = None if self.vm.globals is None else self.vm.globals.block_1a8d
        if block is None or len(block) < 8:
            return None
        word = block[6] | (block[7] << 8)
        return word or None

    def _run_start_program(self, word: str = "open") -> None:
        record_index = self.start_record()
        if record_index is None:
            return
        start_room = self.state.current_room
        native_start = self.vm.initial_native_room_id
        if native_start >= 1 and (native_start - 1) in self.rooms:
            self.state.current_room = native_start - 1
            if word == "restore":
                # A restored game stays in the saved room (6A9): The Mist's
                # bakery, not the new game's checkout area (native, from a
                # STORAGE floppy, 2026-10-18).
                start_room = native_start - 1
        moved = {"room": None}

        def hook(direction: int) -> bool:
            # The program's `(m` steps from the activation room the way
            # byte_6AA points: Goldfinger's walks 15 -> DB5 (21) -> cockpit
            # 20, which leaves 1AE3/1AE4/1AE5 = 21/15/15 (measured).
            origin = self.state.current_room + 1
            final, _texts = self._walk(origin, direction)
            if final is None or (final - 1) not in self.rooms:
                return False
            self.state.current_room = final - 1
            moved["room"] = final - 1
            return True

        self.vm.move_hook = hook
        # sub_23AE (IDA 2A..): a new game starts with 1AE3 = 1AE4 = 1 (no
        # vehicle scenery yet) and nobody following (1AEB = 1). 1AE5 is 1 as
        # well -- measured on A View to a Kill's original after a new game
        # (1AE3..1AE5 = 01 01 01, 2026-10-15); its writer is not located.
        state = self.vm.action_state
        if word == "open":
            # A restored game keeps the saved ones (sub_10E loads the save
            # after sub_23AE).
            state.byte_1ae3 = state.byte_1ae4 = state.byte_1ae5 = state.byte_1aeb = 1
        self._open_message_record()
        # GAME.000 2C94: the boot types OPEN for a new game, RESTORE for a
        # restored one (sub_CE27 parses it, word_4B12 := word_1A0E) -- engine
        # code, the same for every title.
        self.vm.action_state.word_4b12 = next(
            (
                index
                for index, entry in enumerate(self.vm.vocab_nodes.entries_by_node)
                if entry is not None and entry.word == word
            ),
            0,
        ) if self.vm.vocab_nodes is not None else 0
        callback = self.engine.record_open_callback
        self.engine.record_open_callback = None
        try:
            self.opening_text = self.engine.render_message_record(
                record_index, substitutions=self._turn_tail_substitutions()
            ).strip()
        except (IndexError, ValueError, TypeError):
            pass
        finally:
            self.engine.record_open_callback = callback
            self.vm.move_hook = None
            self.state.current_room = (
                moved["room"] if moved["room"] is not None else start_room
            )
            # sub_7BB7 puts the cursors back to 1 before the next record
            # (measured after a new game: 1A4C..1A50 and 1A52 are 1).
            state = self.vm.action_state
            state.byte_1a4c = state.byte_1a4d = state.byte_1a4e = 1
            state.byte_1a4f = state.byte_1a50 = state.byte_1a52 = 1

    @classmethod
    def from_save(
        cls,
        config: AsgConfig,
        save: bytes,
        root: Path | str | None = None,
    ) -> "AsgGame":
        """A game restored from SAVE<n> bytes (see gameengine.savegames).

        The save replaces TABLES and the activation runs on it, as the
        original's boot does after "Which game would you like to resume";
        the globals the activation leaves to the boot (the move counter,
        the referent, the previous-room pair) come from their phase records,
        and the start record runs with RESTORE instead of OPEN.
        """

        import dataclasses

        data_root = config.root if root is None else Path(root)
        data = GameData.load(data_root, launcher_name=config.launcher_name)
        stride = config.table_record_size
        tables = savegames.restore_tables(data.tables, save, stride)
        game = cls(dataclasses.replace(data, tables=tables), config)
        state = game.vm.action_state
        p3 = tables[2 * stride : 3 * stride]
        p4 = tables[3 * stride : 4 * stride]
        p5 = tables[4 * stride : 5 * stride]
        moves = p3[1] | (p3[2] << 8)
        game.vm.move_counter = moves
        game.state.move_number = moves
        state.word_1a54 = moves
        state.byte_1a56 = p3[3]
        state.byte_1a57 = p3[4] | (p3[5] << 8)
        state.byte_1ae3, state.byte_1ae4, state.byte_1ae5 = p4[1], p4[2], p4[3]
        state.byte_1a59, state.byte_1a5a, state.byte_1a5b, state.byte_1a5c = p5[1], p5[2], p5[3], p5[4]
        state.word_1a5d = p5[5] | (p5[6] << 8)
        # The port mirrors open containers beside the phase-7 images.
        for index, node in game.vm.phase7_runtime.items():
            if 1 < index <= game.vm.activation.byte_19e9 and len(node) > 0x1B:
                if node[0x18] == 0 and node[0x1B]:
                    game.state.opened.add(index)
        game._run_start_program("restore")
        return game

    @classmethod
    def load_save(
        cls,
        config: AsgConfig,
        slot: int,
        root: Path | str | None = None,
    ) -> "AsgGame":
        """Restore SAVE<slot> from the title's directory."""

        data_root = config.root if root is None else Path(root)
        return cls.from_save(config, savegames.save_path(data_root, slot).read_bytes(), data_root)

    def save_image(self) -> bytes:
        """The SAVE<n> bytes of the current game, in the original's format."""

        return savegames.build_save_image(
            self.vm,
            self.data.tables,
            self.config.table_record_size,
            current_room=self.state.current_room + 1,
            move_counter=self.vm.move_counter,
        )

    # GAME.000's save routine behind opcode 3Dh: asks for the number (one
    # key), asks before overwriting, writes SAVE<n> where the game is, and
    # reports "Saving game #n...". slot_provider answers the number (None:
    # no save); save_directory overrides where the files go.
    slot_provider: "Callable[[str], str | None] | None" = None
    _saved_this_turn = False
    save_directory: "Path | None" = None

    def _read_action_output(self) -> "str | None":
        if not self.vm.action_output:
            return None
        text = "\n".join(self.vm.action_output)
        self.vm.action_output.clear()
        return text

    def _save_dialog(self) -> "str | None":
        if self.slot_provider is None:
            return None
        answer = self.slot_provider(savegames.ASK_SLOT)
        if not answer or not answer.strip()[:1].isdigit() or answer.strip()[:1] == "0":
            return None
        slot = int(answer.strip()[0])
        directory = self.save_directory or self.config.root
        path = savegames.save_path(directory, slot)
        # The printer drops the blank before "?"; the key echoes on its line.
        lines = [savegames.ASK_SLOT.replace(" ?", "?").strip(), str(slot)]
        if path.exists():
            question = savegames.ALREADY_SAVED.format(slot=slot)
            provider = self.engine.yes_no_provider
            if provider is not None and not provider(question + "\n" + savegames.TYPE_Y_OR_N_UPPER):
                return "\n".join(lines)
        path.write_bytes(self.save_image())
        self._saved_this_turn = True
        lines.append(savegames.SAVING.format(slot=slot))
        return "\n".join(lines)

    @property
    def room(self) -> Room | None:
        if self.state.current_room is None:
            return None
        return self.rooms.get(self.state.current_room)

    def handle(self, command: str) -> str:
        if not command.strip():
            # An empty line is no move: the native re-prompts with timers,
            # 1A8D and word_6AB untouched (measured 2026-10-14).
            return ""
        try:
            return self.screen_output(self._handle_turn(command))
        finally:
            # word_6AB: one more move after every command (1 after a new game).
            self.vm.move_counter += 1

    @staticmethod
    def screen_output(text: str) -> str:
        """GAME.COM's character output state machine (3DFB, state byte_1EBE).

        Decoded 2026-10-15. After ``.``/``!``/``?`` (state 2) -- or ``:``
        not followed by a digit (state 7, "10:30" stays) -- the next word
        starts after one space and its first letter is capitalised (states
        5 -> 3); ``..`` and a closing ``"`` continue the sentence end. After
        a space an ``i`` is held (state 4) and printed ``I`` when a space
        follows. The data relies on both: "the next time i get a chance"
        reads "I get" and the office's "...is closed. you see the desk"
        (a listing after an action) reads "You see" on the native screen.
        Line breaks come from a separate routine and count as the space.
        """

        return GameComMessageEngine._print_3dfb(text)

    def _turn_tail_substitutions(self) -> dict:
        """`%i` / `%j` for records rendered at the end of a turn.

        `%i` names whatever cursor 1A52 holds when the letter is reached --
        record 3511 points it at the road ahead before "you speed on toward
        %i." -- and `%j` the room the player is in.
        """

        current = None if self.state.current_room is None else self.state.current_room + 1
        return {
            "i": lambda: self._location_reference(self.vm.action_state.byte_1a52),
            "j": lambda: self._message_context_name("j"),
            "g": lambda: self._location_reference(self.vm.action_state.byte_1ae3),
            # `%v` (selector 98h, byte_1AE5): where the vehicle stands -- A
            # View to a Kill's "You drive to %g." (its own 97h).
            "v": lambda: self._location_reference(self.vm.action_state.byte_1ae5),
        }

    def _handle_turn(self, command: str) -> str:
        self._saved_this_turn = False
        response = self._handle_command(command)
        # The native per-turn timer pass (AsgVm.tick_timers) runs after the
        # command, and each record it fires prints after the response.
        parts = [response.strip()] if response.strip() else []
        if self._saved_this_turn:
            # The save routine ends with byte_1AE0 = 1 (overlay 2EE0), so the
            # driver renders word_1A93 -- the start record -- whose section
            # for the word typed (SAVE, in word_4B12) is "Now let's continue."
            record_index = self.start_record()
            callback = self.engine.record_open_callback
            self.engine.record_open_callback = None
            try:
                text = "" if record_index is None else self.engine.render_message_record(
                    record_index, substitutions=self._turn_tail_substitutions()
                )
            except (IndexError, ValueError, TypeError):
                text = ""
            finally:
                self.engine.record_open_callback = callback
            if text.strip():
                parts.append(text.strip())
            # ... and the turn ends there: no oath record, no timer pass.
            # Saving during Goldfinger's chase prints only "Now let's
            # continue."; the Mercedes catches up on the next turn (native,
            # 2026-10-18).
            return "\n\n".join(parts)
        state = self.vm.action_state
        if state.flag_4bcb or state.flag_4bcc:
            # IDA 10F2A: once `(y` (3Eh, game over) or `(n` (3Fh, a new
            # game) has run, the driver jumps to 11AA -- no oath record,
            # no timer pass.
            return "\n\n".join(parts)
        current = 0 if self.state.current_room is None else self.state.current_room + 1
        tail: list[int] = []
        # IDA 10F70..10F89: when the parser met a class-2Eh word (byte_4B7E,
        # msg_record_open loc_813B) the record in word_1A97 -- DS:1A8D[2]'s
        # second word, Goldfinger's 2186 -- follows the answer: "learned that
        # in the navy, Commander" / "giving vent to your frustrations".
        if any(entry.class_id == 0x2E for entry in self.parse(command).entries):
            swear = self.vm.table_state.array_1a8d_secondary.get(2, 0)
            if swear:
                tail.append(swear)
        def render(record: int) -> None:
            try:
                # Timer records move the player too (the chase capture
                # walks Bond out of the DB5).
                with self._moves_allowed():
                    text = self.engine.render_message_record(
                        record, substitutions=self._turn_tail_substitutions()
                    )
            except (IndexError, ValueError, TypeError):
                text = ""
            if text.strip():
                parts.append(text.strip())

        self._rendering_turn_tail = True
        try:
            for record in tail:
                render(record)
            # Route walkers announce themselves in place (970e), between
            # their steps; the other records render in the order returned.
            for record in self.vm.end_of_turn(current_room=current, render=render):
                render(record)
        finally:
            self._rendering_turn_tail = False
        return "\n\n".join(parts)

    def _handle_command(self, command: str) -> str:
        # Which native dispatcher family answered (talk / move / verb); the
        # grammar test checks it against gameengine.grammar.route.
        self._last_route = None
        normalized = " ".join(command.lower().split())
        if normalized in {"quit", "q", "bye"} and self.engine.yes_no_provider is None:
            # Nobody to answer QUIT's question: leave at once. With a
            # provider (the interactive loop) QUIT runs its record 2180.
            raise SystemExit
        parsed = self._resolve_pronoun(self.parse(command))
        dialogue = parsed.dialogue_request()
        movement = parsed.movement_verb_word()
        action = parsed.action_id()
        self._current_command_value_b = action
        self._current_scenery_absent = False
        self._current_scenery_value_b = None
        self._current_command_node = next(
            (
                entry.index + 1
                for entry in parsed.entries
                if entry.group_id == 0x02
                and entry.value_a == 0x06
                and entry.value_b == action
            ),
            None,
        )
        # The parser's word loop (IDA 8032) keeps the first place typed (a
        # kind-2 word) in frame byte [bp-2Eh], initialised to 1; every
        # dispatcher opens with byte_1A52 := that byte (sub_423E IDA 4360).
        self._current_place_value_b = next(
            (
                entry.value_b
                for entry in parsed.entries
                if entry.group_id in (0x00, 0x01, 0x02) and entry.value_a == 0x02
            ),
            None,
        )
        # sub_4857 (IDA 4857), 4B36 (loc_4B42) and sub_50D8 open with
        # byte_4ADE := frame slot -2Ch, the first object noun typed (1 when
        # none): A View to a Kill's UNLOCK 635CS WITH CAR KEY asks `&?y`
        # (4ADE) for the key.
        sentence = route(
            words_from_entries(parsed.entries),
            object_verbs_4b6b=self._object_verb_set().values(),
            referent_kind=self.vm.action_state.byte_1a56,
            byte_1aec=self.vm.action_state.byte_1aec,
        )
        self._current_4ade = None
        self._current_dispatcher = sentence.dispatcher
        self._current_parsed = parsed
        if sentence.dispatcher in (0x4857, 0x4B36, 0x50D8):
            typed_objects = parsed.object_ids()
            self._current_4ade = typed_objects[0] if typed_objects else 1
        object_id = parsed.object_id()
        if object_id is None:
            object_id = parsed.location_id()
        self._current_object_node = next(
            (
                entry.index + 1
                for entry in parsed.entries
                if entry.group_id in (0x00, 0x01, 0x02)  # group 1: proper nouns, the key
                and entry.value_a in (0, 0x02)
                and entry.value_b == object_id
            ),
            None,
        )
        # Every other word the player typed. That includes a second verb:
        # TYPE OPEN DOOR's "open" is a typed word like any other, and record
        # 2281 asks for it (`$;ez`, 7Fh: "was a word like OPEN typed?").
        self._current_person_value = self._loc_3548_person(parsed)
        # Parser frame slot -28h, the kind-3 noun (a vehicle, a beast): the
        # sentence dispatchers copy it into 4ADF (overlay 7806, 8206, ...).
        self._current_typed_person = next(
            (entry.value_b for entry in parsed.entries if entry.value_a == 0x01), None
        )
        self._current_beast_value = next(
            (entry.value_b for entry in parsed.entries if entry.value_a == 0x03), None
        )
        self._dispatch_referent(parsed, action)
        self._current_modifier_nodes = tuple(
            entry.index + 1
            for entry in parsed.entries
            if entry.group_id in (0x00, 0x01, 0x02)
            and (
                entry.value_a not in (0, 0x06)
                or (
                    entry.value_a == 0x06
                    and entry.index + 1 != self._current_command_node
                )
            )
        )
        if any(
            entry.value_a == 0x0A and entry.class_id == 0x12 for entry in parsed.entries
        ) or take_or_ride_pattern(
            words_from_entries(parsed.entries),
            referent_kind=self.vm.action_state.byte_1a56,
        ) is not None:
            # sub_68F8 (67DC): RIDE, or TAKE with a vehicle or a place (TAKE
            # DOOR on the porch) -- the vehicle dispatcher 4B36.
            ridden = self._ride(parsed)
            if ridden is not None:
                return ridden
        if (
            movement is not None
            and parsed.direction_id() is None
            and self._current_place_value_b is not None
            and self.vm.action_state.byte_1aec != 1
            and self.config.movement_command_record is not None
        ):
            gone = self._move_to_named_place(parsed, self._current_place_value_b)
            if gone is not None:
                return gone
        if movement is not None and parsed.direction_id() is None:
            if self.vm.action_state.byte_1ae5 != 1 and self.vm.action_state.byte_1aec == 1:
                # In a closed vehicle every move is the vehicle's own record
                # (GAME.000 4AF4), along byte_6AA as it stands: native DRIVE
                # CAR / ENTER CAR -> 7799 "You can't drive in that direction".
                driven = self._move_vehicle(self.vm.direction_cursor_6aa)
                if driven is not None:
                    return driven
            boarded = self._move_through_vehicle_exit()
            if boarded is not None:
                return boarded
            if (
                self.config.movement_command_record is not None
                and self.vm.action_state.byte_1aec != 1
                and 0 <= self.vm.direction_cursor_6aa < 6
            ):
                # sub_6D38 without a place or direction: state 3, 1A52 on
                # the exit along byte_6AA (loc_6E9E), and 4A74 answers with
                # 1893 along byte_6AA -- GO after U on the porch is refused.
                walked = self._move_through_command_record(
                    self.state.current_room + 1,
                    self.vm.direction_cursor_6aa,
                    refusal=True,
                )
                if walked:
                    return walked
        self._resolve_current_scenery()
        indirect_id = (
            # sub_3E2E (IN/INTO + noun, IDA 3ED0) puts the noun after INTO in
            # 1A4F whatever the verb: The Mist's POUR PESTICIDE INTO SPRAYER.
            self._parsed_indirect_object_id(parsed)
            if action == 0x12 or self._current_dispatcher == 0x3E2E
            # sub_423E puts the WITH noun in 1A4F too (sub_35FB, IDA 43F9):
            # A View to a Kill's UNLOCK DRAWER WITH KEY asks for it. So does
            # sub_3AD5 (IDA 3B6E): Rambo's CUT WIRE WITH KNIFE; and sub_3CCC,
            # KILL TAY WITH KNIFE.
            else self._with_object_id(parsed)
            if self._current_dispatcher in (0x423E, 0x3AD5, 0x3CCC)
            else None
        )
        self._current_indirect_object_node = (
            next(
                (
                    entry.index + 1
                    for entry in parsed.entries
                    if entry.group_id in (0x00, 0x01, 0x02)
                    and entry.value_a == 0
                    and entry.value_b == indirect_id
                ),
                None,
            )
            if indirect_id is not None
            else None
        )
        if action == 0x01 and self.engine.yes_no_provider is None:
            raise SystemExit
        if action == 0x05:
            # LOOK with a noun is the same verb record as plain LOOK: `=di`
            # describes whatever the parse bound to the `i` cursor (a piece of
            # scenery such as the trap door) and runs its program -- LOOK DOOR
            # on the chateau roof sets 1A8D[5] there (measured live), which
            # the office entry later tests.
            if parsed.object_id() is not None or self._current_scenery_value_b is not None:
                response = self._render_look_record()
                if response.strip():
                    return response
            if normalized in {"look", "l"}:
                response = self._render_look_record()
                return response
        if action in (0x03, 0x06, 0x0F):
            # INVENTORY / TAKE / DROP are their DS:05F0 verb records (309,
            # 1480, 1447): the 34h/33h/46h actions and the `=h!`/`=h(`
            # listings work on the native sets 0671 (in hand) and 0679 (on
            # your person), the same sets every predicate reads.
            response = self._render_generic_verb_response(action, parsed).strip()
            if response:
                return response
        direction = parsed.direction_id()
        self._current_direction = direction
        if direction is not None:
            self.vm.direction_cursor_6aa = direction
        if direction is not None and self.vm.action_state.byte_1aec == 1:
            driven = self._move_vehicle(direction)
            if driven is not None:
                return driven
        if direction is not None and self.room is not None:
            native_room = self.state.current_room + 1
            if not self.vm.direction_available(native_room, direction):
                if (
                    self.config.movement_command_record is not None
                    and self.vm.action_state.byte_1aec != 1
                ):
                    # GAME.000 4AF4: on foot the answer is record 1893 even
                    # when the exit is blocked; its `(m` refuses and 1712
                    # renders why ($| 73h: a dead end, or a closed door).
                    refused = self._move_through_command_record(
                        native_room, direction, refusal=True
                    )
                    if refused:
                        return refused
                self.vm.open_message_record()
                selected = self.vm.select_context_set_response(native_room)
                response = self._render_selected_vm_response(selected)
                return response
            target = self.vm.direction_target(native_room, direction)
            if target is None or (target - 1) not in self.rooms:
                return ""
            if self.config.movement_command_record is not None:
                # 4AF4: the record's answer is final, also when its `(m`
                # never ran (A View to a Kill's skis at the hatch: "CLANK!").
                moved = self._move_through_command_record(
                    native_room, direction, refusal=True
                )
                if moved is not None:
                    return moved
            # A passage's own text is rendered with the room context cursor
            # (1A52) on the room beyond it: record 41 asks `&:i$tk` -- is that
            # the top of the steps? -- for "you walk up / down the steps".
            onward_context = (
                self.vm.direction_target(target, direction)
                if self._is_passage(target)
                else None
            )
            response = self._arrive(target, native_room, direction, context=onward_context)
            # sub_9AFF (the move routine) checks the room it just entered: a
            # scenery record (+23h != 0, e.g. record 35, the trap door) is a
            # passage, not a place. It renders that record's own text ("You
            # pass through the trap door.") and calls itself again in the same
            # direction (byte_6AA) from there -- native room 27 goes down
            # into record 35 and on down into room 30, the office.
            passed: set[int] = {native_room}
            while self._is_passage(target) and target not in passed:
                passed.add(target)
                onward = self.vm.direction_target(target, direction)
                if (
                    onward is None
                    or (onward - 1) not in self.rooms
                    or not self.vm.direction_available(target, direction)
                ):
                    break
                next_context = (
                    self.vm.direction_target(onward, direction)
                    if self._is_passage(onward)
                    else None
                )
                body = self._arrive(onward, target, direction, context=next_context)
                head = response.strip()
                response = f"{head}\n\n{body.strip()}" if head and body.strip() else (head or body)
                target = onward
            self._finish_move(target)
            return response
        # Generic data-driven verb response: any verb with a native DS:0x5F0
        # record renders that MESSAGE composite through the live VM predicate
        # path (``_render_generic_verb_response``).
        records = self.verb_response_records
        if records and action in records:
            text = self._render_generic_verb_response(action, parsed)
            self._apply_open_close_side_effects(action, parsed)
            return text
        if action is None and normalized:
            talked = self._talk(parsed)
            if talked is not None:
                return talked
        return ""

    def present(self, text: str) -> str:
        return self.engine.layout_text(text)


# CGA attribute colour (low nibble) -> ANSI foreground.
_ANSI_FOREGROUND = (30, 34, 32, 36, 31, 35, 33, 37, 90, 94, 92, 96, 91, 95, 93, 97)


def text_colour(attribute: int) -> str:
    """The ANSI sequence for a text-mode attribute's foreground colour."""

    return f"[{_ANSI_FOREGROUND[attribute & 0x0F]}m"


def _colour_enabled() -> bool:
    if os.environ.get("NO_COLOR") or not sys.stdout.isatty():
        return False
    if os.name == "nt":
        os.system("")  # switch the Windows console into VT mode
    return True


def run(config: AsgConfig, root: Path | str | None = None) -> None:
    colour = _colour_enabled()
    if colour:
        print(text_colour(config.text_attribute), end="", flush=True)
    try:
        while _play(config, root):
            pass  # `(n` (action 3Fh, byte_4BCC): a new game
    finally:
        if colour:
            print("[0m", end="", flush=True)


def _read_key(prompt: str = "-> ") -> "str | None":
    try:
        return input(prompt).strip()
    except EOFError:
        return None


def _boot(config: AsgConfig, root: Path | str | None) -> "AsgGame":
    """GAME.000 2BE5..2CA6: the resume question, then a new or saved game."""

    directory = config.root if root is None else Path(root)
    while True:
        print(savegames.RESUME_QUESTION)
        print(savegames.TYPE_Y_OR_N)
        answer = _read_key()
        if answer is None or answer.lower().startswith("n"):
            # No input left: a new game, as for N.
            return AsgGame.load(config, root)
        answer = answer.lower()
        if answer.startswith("n"):
            return AsgGame.load(config, root)
        if not answer.startswith("y"):
            continue
        print(savegames.ASK_RESUME_SLOT.replace(" ?", "?"))
        key = (_read_key() or "")[:1]
        if not key.isdigit() or key == "0":
            continue
        slot = int(key)
        path = savegames.save_path(directory, slot)
        if not path.is_file():
            print(savegames.missing_save_message(slot))
            continue
        print(savegames.RETRIEVING.format(slot=slot))
        try:
            return AsgGame.from_save(config, path.read_bytes(), root)
        except ValueError as error:
            print(error)


def _play(config: AsgConfig, root: Path | str | None) -> bool:
    """One game; True when its records asked for a restart (byte_4BCC)."""

    game = _boot(config, root)
    asked = {"last": ""}

    def slot(prompt: str) -> "str | None":
        print(prompt.replace(" ?", "?").strip())
        key = (_read_key("") or "")[:1]
        # Shown already: the turn's output resumes after the echoed key.
        asked["last"] = prompt.replace(" ?", "?").strip() + "\n" + key
        return key

    game.slot_provider = slot

    def ask(text_so_far: str) -> bool:
        # A `$-` question: show what the turn printed up to it, then read
        # the answer at the prompt like the original ("-> No.").
        text = game.screen_output(text_so_far).strip()
        last = asked["last"]
        if last and last in text:
            text = text[text.rindex(last) + len(last):].strip()
        if text:
            print(game.present(text))
        asked["last"] = text.split("\n")[-1] if text else last
        try:
            answer = input("-> ").strip().lower()
        except EOFError:
            answer = "n"
        return answer.startswith("y")

    game.engine.yes_no_provider = ask
    # Native boot: the start record's text (Goldfinger's chase cutscene)
    # instead of a room description before the first prompt.
    opening = game.screen_output(game.opening_text or game.room_description())
    if opening:
        print_paged(
            config.display_name
            + "\n"
            + game.engine.status_line(game.state.move_number)
            + "\n"
            + game.present(opening)
        )
    else:
        print(config.display_name)
        print(game.engine.status_line(game.state.move_number))
    print()
    while True:
        try:
            command = input(game.engine.status_separator() + "\n-> ")
            asked["last"] = ""
            response = game.handle(command)
            game.state.move_number += 1
            last = asked["last"]
            if last and last in response:
                # Shown already, question by question.
                response = response[response.rindex(last) + len(last):].strip()
            if response:
                print_paged(
                    game.engine.status_line(game.state.move_number)
                    + "\n"
                    + game.present(response)
                )
            else:
                print(game.engine.status_line(game.state.move_number))
            state = game.vm.action_state
            if getattr(state, "flag_4bcc", 0):
                return True  # restart
            if getattr(state, "flag_4bcb", 0):
                return False  # `(y` (3Eh): the game is over
        except (EOFError, KeyboardInterrupt, SystemExit):
            print("\nGoodbye.")
            return False


def module_main(config: AsgConfig) -> None:
    parser = argparse.ArgumentParser(prog=config.key)
    parser.add_argument("--root", type=Path, default=config.root)
    args = parser.parse_args()
    run(config, args.root)
