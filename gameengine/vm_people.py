"""AsgVm: Random, the people update, timers and the end-of-turn pass."""

from __future__ import annotations

from typing import Callable
from .dispatcher import (
    TABLE_CONTEXT_SET_OFFSET,
    AsgPerTurnDispatcher,
    DispatcherTransferResult,
)
from .pascal_set import PascalSet
from .runtime_records import RuntimeRecord


class PeopleMixin:
    """TP3 Random, what people do each turn, timers and start transfers."""

    def tp_random(self, limit: int) -> int:
        """Turbo Pascal 3's ``Random(limit)`` (GAME.COM 10BB / 10C7).

        ``Seed := Seed * 129 + 361962E9h`` (mod 2^32) -- the byte shuffle and
        ``rcr`` chain in 10C7 is ``Seed shl 7 + Seed`` -- and the result is
        the new seed's high word shifted right once, ``mod limit``.
        """

        self.rand_seed = (self.rand_seed * 129 + 0x361962E9) & 0xFFFFFFFF
        return ((self.rand_seed >> 16) >> 1) % limit

    def percent_chance(self, percent: int) -> bool:
        """GAME.COM 554B: ``percent > Random(101)``."""

        return percent > self.tp_random(101)

    # ---- the people update (GAME.COM 585F and its helpers) -------------

    def _person(self, index: int) -> "bytearray | None":
        record = self.runtime_records.get(index)
        return None if record is None else bytearray(record.raw)

    def _store_person(self, index: int, raw: bytearray) -> None:
        self.runtime_records.replace(index, RuntimeRecord(index, bytes(raw)))

    def _person_target(self, raw: bytearray) -> int:
        """GAME.COM 56A5: where heading +16h leads from the person's room.

        1 when there is no exit; a passage (+23h) is walked through when it is
        open (+24h), and is a dead end (1) when closed.
        """

        room = self.graph.room(raw[0x14])
        heading = raw[0x16]
        if room is None or not 0 <= heading < 6:
            return 1
        target = room[0x04 + heading]
        if target == 1:
            return 1
        passage = self.graph.room(target)
        if passage is None or len(passage) <= 0x24 or passage[0x23] == 0:
            return target
        if passage[0x24] == 0:
            return 1
        return passage[0x04 + heading]

    def _step_person_holding(self) -> None:
        """Action 3Ch (sub_AD12): step 1A4F over what person 1A50 holds.

        With 1A4F at 1 it starts at the cheapest held thing (GAME.COM 5764);
        otherwise sub_ABE0 moves it to the next index not yet visited (the
        caller's frame set). 1A4F = 1 ends the walk with byte_4B7B = 0. A
        View to a Kill's record 187 loops on it until 1A4F is the object
        asked for (`&:b&y`), which action 41h then hands over. Not ported:
        the sub_A72E call taken when the visited set is not empty.
        """

        state = self.action_state
        state.byte_4b7b = 1
        if state.byte_1a4f == 1:
            raw = self._person(state.byte_1a50)
            state.byte_1a4f = 1 if raw is None else self._cheapest_held(raw)
            self._holding_walk_visited = set()
        else:
            visited = getattr(self, "_holding_walk_visited", set())
            visited.add(state.byte_1a4f)
            self._holding_walk_visited = visited
            nxt = next(
                (i for i in range(state.byte_1a4f + 1, 64) if i not in visited), 1
            )
            state.byte_1a4f = nxt
        if state.byte_1a4f == 1:
            state.byte_4b7b = 0

    def _cheapest_held(self, raw: bytearray) -> int:
        """GAME.COM 5764: the held object (+0Ch minus 06A1) of lowest +0Dh
        that sits in no container (+17h == 1); 1 when there is none."""

        held = PascalSet.from_bytes(bytes(raw[0x0C:0x14])).difference(
            self.predicates.blocks[0x6A1]
        )
        pick, best = 1, 9
        if len(held) == 0:
            return pick
        for index in range(2, self.activation.byte_19e9 + 1):
            if index not in held:
                continue
            node = self.phase7_runtime.get(index)
            if node is None or len(node) <= 0x17 or node[0x17] != 1:
                continue
            if node[0x0D] <= best:
                pick, best = index, node[0x0D]
        return pick

    def _with_contents(self, values: PascalSet) -> PascalSet:
        """GAME.COM 54D4: add the contents (+0..7) of every object listed."""

        result = values
        for index in range(2, self.activation.byte_19e9 + 1):
            if index in result:
                node = self.phase7_runtime.get(index)
                if node is not None:
                    result = result.union(PascalSet.from_bytes(bytes(node[0:8])))
        return result

    def _pour_liquid(self, current_room: int | None) -> bool:
        """EF31 opcode 37h (GF ``sub_EA28`` -> ``loc_EC95``): pour 1A4C.

        byte_4B7B = 0. ``loc_EB62`` needs 1A4C to be a liquid (+18h == 3)
        whose container (+17h) is in hand (0671) or in the room (+18h).
        With no vessel to pour into (1A4F is 1, or not a type-1 node) it
        runs ``sub_EA3D``: byte_4B7B = 1 and the liquid leaves the world --
        into room 1's +18h set, out of its container and out of 0671, its
        +17h = 1. Rambo's GIVE WATER TO BANKS ("Lt. Banks drinks the
        water.").
        """

        state = self.action_state
        state.byte_4b7b = 0
        liquid = state.byte_1a4c
        node = self.phase7_runtime.get(liquid)
        room = self.graph.room(current_room or 0)
        if node is None or room is None or len(room) < 0x20:
            return True
        reachable = self.predicates.blocks[0x671].union(PascalSet.from_bytes(bytes(room[0x18:0x20])))
        if node[0x18] != 3 or node[0x17] not in reachable:
            return True
        vessel_index = state.byte_1a4f
        vessel = self.phase7_runtime.get(vessel_index)
        one = PascalSet.from_values([liquid], 8)
        if vessel_index != 1 and vessel is not None and vessel[0x18] == 1:
            # loc_E5D9 (Rambo's clean listing): the vessel is in hand, in the
            # room or 1, and empty; then loc_E652 pours: 4ADE := the old
            # container, which loses the liquid; the vessel holds it, its
            # +17h names the vessel, and it is in hand when the vessel is,
            # else in the room. The Mist's POUR PESTICIDE INTO SPRAYER.
            reach = reachable.union(PascalSet.from_values([1], 8))
            if vessel_index not in reach or len(PascalSet.from_bytes(bytes(vessel[0:8]))):
                return True
            state.byte_4b7b = 1
            state.byte_4ade = node[0x17]
            old = self.phase7_runtime.get(node[0x17])
            if old is not None:
                old[0:8] = PascalSet.from_bytes(bytes(old[0:8])).difference(one).to_bytes()
            vessel[0:8] = PascalSet.from_bytes(bytes(vessel[0:8])).union(one).to_bytes()
            node[0x17] = vessel_index
            hand = self.predicates.blocks[0x671].difference(one)
            room_set = PascalSet.from_bytes(bytes(room[0x18:0x20])).difference(one)
            if vessel_index in hand:
                hand = hand.union(one)
            else:
                room_set = room_set.union(one)
            self.predicates.blocks[0x671] = hand
            room[0x18:0x20] = room_set.to_bytes()
            return True
        state.byte_4b7b = 1
        limbo = self.graph.room(1)
        if limbo is not None and len(limbo) >= 0x20:
            limbo[0x18:0x20] = PascalSet.from_bytes(bytes(limbo[0x18:0x20])).union(
                PascalSet.from_values([liquid], 8)
            ).to_bytes()
        container = self.phase7_runtime.get(node[0x17])
        if container is not None:
            container[0:8] = PascalSet.from_bytes(bytes(container[0:8])).difference(
                PascalSet.from_values([liquid], 8)
            ).to_bytes()
        node[0x17] = 1
        self.predicates.blocks[0x671] = self.predicates.blocks[0x671].difference(
            PascalSet.from_values([liquid], 8)
        )
        return True

    def _trade_with_person(self, current_room: int | None) -> None:
        """EF31 opcode 43h, ``sub_AA46``: a trade.

        byte_4B7B = 0. With the person 1A50 present (``sub_A901``), holding
        1A4F (its +0Ch set - 06A1) while the player has 1A4D in hand
        (0671 - 06A1): byte_4B7B = 1, the person hands over 1A4F
        (``sub_A797``) and takes 1A4D (``sub_A84C``), each with what it
        contains. Rambo's KINH, TRADE CAMERA FOR CANTEEN.
        """

        state = self.action_state
        state.byte_4b7b = 0
        room = self.graph.room(current_room or 0)
        runtime = self.runtime_records.get(state.byte_1a50)
        if room is None or len(room) < 0x18 or runtime is None or state.byte_1a50 == 1:
            return
        if state.byte_1a50 not in PascalSet.from_bytes(bytes(room[0x14:0x18])):
            return
        held = PascalSet.from_bytes(runtime.raw[0x0C:0x14])
        hidden = self.predicates.blocks[0x6A1]
        wanted, offered = state.byte_1a4f, state.byte_1a4d
        if wanted not in held.difference(hidden):
            return
        if offered not in self.predicates.blocks[0x671].difference(hidden):
            return
        state.byte_4b7b = 1

        def with_contents(index: int) -> PascalSet:
            node = self.phase7_runtime.get(index)
            things = PascalSet.from_values([index], 8)
            return things if node is None else things.union(PascalSet.from_bytes(bytes(node[0:8])))

        got, given = with_contents(wanted), with_contents(offered)
        held = held.difference(got)
        self.predicates.blocks[0x671] = self.predicates.blocks[0x671].union(got).difference(given)
        held = held.union(given)
        self.runtime_records.replace(runtime.index, runtime.with_rule_set(held.to_bytes()))

    def _move_person(self, index: int, raw: bytearray, target: int) -> None:
        """GAME.COM 55F6: carry the person between the rooms' +14h sets."""

        old = self.graph.room(raw[0x14])
        if old is not None and len(old) >= 0x18:
            old[0x14:0x18] = PascalSet.from_bytes(bytes(old[0x14:0x18]), 4).difference(
                PascalSet.from_values([index], 4)
            ).to_bytes()
        new = self.graph.room(target)
        if new is not None and len(new) >= 0x18:
            new[0x14:0x18] = PascalSet.from_bytes(bytes(new[0x14:0x18]), 4).union(
                PascalSet.from_values([index], 4)
            ).to_bytes()
        raw[0x14] = target

    def people_update(self, index: int, *, current_room: int) -> None:
        """Port GAME.COM 585F for one person of the DS:0438 table.

        +1Bh set means the person stays this turn. In the player's room it is
        set; elsewhere it is re-rolled with the +18h chance (inverted when it
        was already set) -- one Random per absent person, which is exactly
        what walkthrough turn 2 measures (three rolls: Goldfinger, Oddjob,
        Pussy; Tilly rides with Bond). A person who does not stay may drop
        the cheapest thing they hold (+17h chance), turns to a random heading
        when the current one leads nowhere (Random(6), then up to five
        clockwise turns), moves, and below a +17h of 99 picks up what lies
        in the new room. byte_4B62 ends as the person's index when they end
        up in the player's room.
        """

        if index == self.action_state.byte_1aeb:
            return
        raw = self._person(index)
        if raw is None or len(raw) <= 0x1C:
            return
        self.action_state.byte_4b62 = 1
        if raw[0x14] == current_room:
            raw[0x1B] = 1
        elif raw[0x1B] != 0:
            raw[0x1B] = int(not self.percent_chance(raw[0x18]))
        else:
            raw[0x1B] = int(self.percent_chance(raw[0x18]))
        if raw[0x1B] == 1:
            self._store_person(index, raw)
            return
        held = PascalSet.from_bytes(bytes(raw[0x0C:0x14]))
        if len(held) and self.percent_chance(raw[0x17]):
            dropped = self._cheapest_held(raw)
            node = self.phase7_runtime.get(dropped)
            things = PascalSet.from_values([dropped], 8)
            if node is not None:
                things = things.union(PascalSet.from_bytes(bytes(node[0:8])))
            room = self.graph.room(raw[0x14])
            if room is not None and len(room) >= 0x20:
                room[0x18:0x20] = PascalSet.from_bytes(bytes(room[0x18:0x20])).union(things).to_bytes()
            raw[0x0C:0x14] = held.difference(things).to_bytes()
        target = self._person_target(raw)
        turns = 0
        if target == 1 and self.tables.record_size != 47:
            # The 40-byte build (Goldfinger, Indiana Jones) first turns to a
            # random heading; the 47-byte one (Rambo, The Mist -- read from
            # their GAME.COMs, 15A2D..15AAB) only turns clockwise.
            raw[0x16] = self.tp_random(6)
        while target == 1 and turns < 5:
            raw[0x16] = 0 if raw[0x16] == 5 else raw[0x16] + 1
            turns += 1
            target = self._person_target(raw)
        if target != 1:
            self._move_person(index, raw, target)
            self._person_picks_up(raw)
        if raw[0x14] == current_room:
            self.action_state.byte_4b62 = index
        self._store_person(index, raw)

    def _person_picks_up(self, raw: bytearray) -> None:
        """A person with +17h below 99 takes the loose things of their room.

        Loose: the room's +18h set without 19EF and 06A1, with whatever those
        things contain. They move from the room into the person's +0Ch.
        """

        if raw[0x17] >= 99:
            return
        room = self.graph.room(raw[0x14])
        if room is None or len(room) < 0x20:
            return
        loose = (
            PascalSet.from_bytes(bytes(room[0x18:0x20]))
            .difference(self.excluded_19ef)
            .difference(self.predicates.blocks[0x6A1])
        )
        loose = self._with_contents(loose)
        raw[0x0C:0x14] = PascalSet.from_bytes(bytes(raw[0x0C:0x14])).union(loose).to_bytes()
        room[0x18:0x20] = PascalSet.from_bytes(bytes(room[0x18:0x20])).difference(loose).to_bytes()

    def end_of_turn(
        self,
        *,
        current_room: int,
        render: "Callable[[int], None] | None" = None,
    ) -> list[int]:
        """The native end-of-turn sequence after a command (IDA 10F43..111AB).

        Ported so far: the people update for persons 2..word_19E7 once the
        move counter is above 1, and the timer pass. Returns the MESSAGE
        records to show, in order: an arrival (1A8D[3]'s record, word_1A9B)
        for each person who walked into the player's room, then the timers'.
        Not yet: call 17896, 1A97, the phase-9 walkers every fifth move, and
        the clock (one minute is assumed to pass).
        """

        records: list[int] = []
        if self.move_counter > 1:
            for person in range(2, self.activation.word_19e7 + 1):
                self.people_update(person, current_room=current_room)
                if self.action_state.byte_4b62 == person:
                    self.action_state.byte_1a50 = person
                    self.action_state.byte_4adf = 1
                    self.action_state.byte_1a51 = 1
                    arrival = self.table_state.array_1a8d_secondary.get(3, 0)
                    if arrival:
                        if render is not None:
                            render(arrival)
                        else:
                            records.append(arrival)
                    self.set_referent(1, person)
                    self._mark_described(1, person)
        if self.move_counter % 5 == 0:
            self._walk_route_records(current_room, render=render)
        # A08F's [bp-5] lives one turn: a ride on a turn without a route walk
        # does not hold the record back at the next walk (Forbidden Castle's
        # bridge goes up the turn after it was crossed).
        self.last_ridden_phase9 = None
        # 98b7(1): one more minute on the clock, added to whatever action 49h
        # advanced during the turn (WAIT); the timer pass counts minutes.
        self.action_state.advance_native_clock(1)
        records.extend(self.tick_timers(None, render=render))
        self.action_state.word_1a5d = 0
        return records

    # The native pass covers entries 0..9 (IDA 110FA: `mov ax, 9`).
    TIMER_COUNT = 10

    def tick_timers(
        self, elapsed: "int | None" = 1, render: "Callable[[int], None] | None" = None
    ) -> list[int]:
        """Run one turn of the timer array DS:1A5F; return the records fired.

        Each entry is two words: a signed countdown and a MESSAGE record
        (written by 4Bh and 4Ah respectively). Measured live 2026-10-14 with
        a write breakpoint on timer 2 during OPEN ARMREST: every positive
        countdown drops by one in index order (7 -> 6, 1 -> 0) while a
        negative one (timer 8, -20: the lighter's fuel before LIGHT) stays;
        a countdown that reaches 0 has its record word cleared and that
        record runs -- record 3511 then re-arms its own timer (1, 3511) and
        prints the chase's "gaining ground" line.
        """

        fired: list[int] = []
        state = self.table_state
        live = elapsed is None
        for index in range(self.TIMER_COUNT):
            value = state.read_array_1a5f_signed(index)
            if value <= 0:
                continue
            if live:
                # elapsed None: the pass reads word_1A5D for every entry, so
                # minutes a fired record adds (49h) count for the entries
                # after it. Rambo's junk: timer 5's record 3042 advances 59,
                # and timer 7 (the gunship) and the clock lose 64 that turn.
                elapsed = self.action_state.word_1a5d
            # IDA 110FA..: a countdown below the elapsed minutes becomes 0.
            value = 0 if value < elapsed else value - elapsed
            state.write_array_1a5f_signed(index, value)
            if value == 0:
                record = state.read_array_1a5f_secondary(index)
                if record:
                    state.write_array_1a5f_secondary(index, 0)
                    if render is not None:
                        # 970e renders it right here, so its actions (the
                        # chase capture disarming the other chase timers)
                        # take effect before the later entries are checked.
                        render(record)
                    else:
                        fired.append(record)
        return fired

    def execute_start_transfers(self) -> tuple[DispatcherTransferResult, ...]:
        if not self.activated:
            return ()
        # The native has one room image; the port keeps the live one in the
        # graph and the TABLES copy the dispatcher reads. Hand the transfer
        # the live +18h sets and take its result back.
        records = self.activation.room_records
        for native_id, record in enumerate(records, start=1):
            room = self.graph.room(native_id)
            if room is not None and len(room) >= 0x20:
                self.table_state.write_bytes(
                    record, TABLE_CONTEXT_SET_OFFSET, bytes(room[0x18:0x20])
                )
        results = AsgPerTurnDispatcher.execute_transfers(
            self.runtime_records,
            self.activation.word_19e7,
            records,
            self.table_state,
            self.excluded_19ef,
            self.predicates.blocks[0x6A1],
        )
        for native_id, record in enumerate(records, start=1):
            room = self.graph.room(native_id)
            if room is not None and len(room) >= 0x20:
                room[0x18:0x20] = self.table_state.read_bytes(
                    record, TABLE_CONTEXT_SET_OFFSET, 8
                )
        # A person holds what they took with its contents (GAME.COM 54D4),
        # and those leave the room too: The Mist's Ollie starts with the
        # pistol and the polished clip in it, room 4 empty (native after
        # turn 1, 2026-10-18) -- 06A1 kept the clip out of the transfer.
        for index in range(2, self.activation.word_19e7 + 1):
            raw = self._person(index)
            if raw is None or len(raw) <= 0x14:
                continue
            held = PascalSet.from_bytes(bytes(raw[0x0C:0x14]))
            extra = self._with_contents(held).difference(held)
            if not len(extra):
                continue
            raw[0x0C:0x14] = held.union(extra).to_bytes()
            self._store_person(index, raw)
            room = self.graph.room(raw[0x14])
            if room is not None and len(room) >= 0x20:
                room[0x18:0x20] = PascalSet.from_bytes(bytes(room[0x18:0x20])).difference(extra).to_bytes()
        return results
