"""Engine-base world dataclasses (Room, GameObject, base GameState).

Engine-generic structural types. Per-game extensions live in the
respective ``games/<title>/`` binding (e.g. Goldfinger's
``SceneGlobals`` lives in ``games.goldfinger.interpreter``).

These types are *structurally* invariant across the sibling
Mindscape titles -- every title has rooms with 6 direction slots,
objects with location + name, and the per-turn ``GameState`` carries
the same set of base fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .runtime_records import RuntimeRecordArray
from .tables import TableRecord


DIRECTION_NAMES = ("north", "south", "east", "west", "up", "down")
OPPOSITE_DIRECTIONS = (1, 0, 3, 2, 5, 4)


@dataclass(frozen=True)
class WorldGraph:
    """Complete authored six-direction graph derived from room records."""

    edges: dict[int, tuple[int | None, ...]]

    @classmethod
    def from_rooms(cls, rooms: dict[int, "Room"]) -> "WorldGraph":
        return cls({
            index + 1: tuple(target if target > 1 else None for target in room.exits)
            for index, room in rooms.items()
        })

    def destination(self, native_room: int, direction: int) -> int | None:
        exits = self.edges.get(native_room)
        return None if exits is None or not 0 <= direction < 6 else exits[direction]

    def non_reciprocal_edges(self) -> tuple[tuple[int, int, int], ...]:
        """Return authored one-way edges; useful, not an error condition."""

        result: list[tuple[int, int, int]] = []
        for source, exits in self.edges.items():
            for direction, target in enumerate(exits):
                if target is None:
                    continue
                reverse = self.destination(target, OPPOSITE_DIRECTIONS[direction])
                if reverse != source:
                    result.append((source, direction, target))
        return tuple(result)

    def available_exits(
        self,
        native_room: int,
        entry_allowed,
    ) -> tuple[tuple[int, int], ...]:
        """Return live ``(direction, target)`` edges passing an entry gate.

        ``entry_allowed`` reads the mutable target-room state (TABLES +0x24 in
        this engine). Consequently an action that opens or seals a target is
        reflected without rebuilding the authored graph.
        """

        exits = self.edges.get(native_room, ())
        return tuple(
            (direction, target)
            for direction, target in enumerate(exits)
            if target is not None and entry_allowed(target)
        )


@dataclass(frozen=True)
class VisibilityRules:
    """Resolve room/inventory/container visibility from native locations.

    Location values may name a room, the carried marker, or another object's
    VOCAB id. Contents of a closed container are not visible; nested open
    containers are followed recursively with cycle protection.
    """

    carried_marker: int = 0x53

    def visible_object_ids(
        self,
        locations: dict[int, int],
        *,
        native_room: int,
        open_containers: set[int],
        include_carried: bool = True,
    ) -> tuple[int, ...]:
        visible: set[int] = {
            obj_id for obj_id, location in locations.items()
            if location == native_room
            or (include_carried and location == self.carried_marker)
        }
        changed = True
        while changed:
            changed = False
            for obj_id, location in locations.items():
                if obj_id in visible or location not in visible:
                    continue
                if location in open_containers:
                    visible.add(obj_id)
                    changed = True
        return tuple(sorted(visible))


@dataclass
class Room:
    """A loaded type-0x02 room record with resolved direction slots.

    ``record`` is the on-disk TABLES record; ``exits`` are the six
    direction-slot values (N/S/E/W/U/D, 1-based native room ids;
    0 or 1 = blocked / null room).
    """

    room_index: int
    record: TableRecord
    message_offset: int
    exits: tuple[int, int, int, int, int, int]


@dataclass
class GameObject:
    """A loaded type-0x01 object record with parsed name and location.

    ``obj_id`` is the VOCAB ``value_b`` (1-based slot into the object
    record list). ``location`` is the per-game location byte position
    (game-specific interpretation; the engine just carries it).
    """

    obj_id: int
    name: str
    location: int
    record: TableRecord


@dataclass
class EngineGameState:
    """Engine-base per-turn state shared by every sibling game.

    Per-game extensions add fields (Goldfinger adds ``scene:
    SceneGlobals`` for its activation-chain ports). This base captures
    the truly engine-invariant fields:

      * ``current_room`` -- 0-based room index (None until a scene is
        activated).
      * ``entry_available`` -- result of the +0x24 aux-state gate from
        the last move resolution.
      * ``direction_available`` -- six-tuple of bool availability for
        each direction slot at the current room.
      * ``move_number`` -- count of turns processed.
      * ``inventory`` -- VOCAB ``value_b`` ids of carried objects
        (hypothesis-side; promotes to a native record byte when the
        native location bit is traced per game).
      * ``opened`` -- VOCAB ``value_b`` ids whose binary "open" state
        is set (same hypothesis-side pattern).
      * ``worn`` -- VOCAB ``value_b`` ids currently worn (same
        hypothesis-side pattern as ``opened``).
      * ``lit`` -- VOCAB ``value_b`` ids currently lit/on (same
        hypothesis-side pattern as ``opened``).
      * ``runtime_records`` -- the DS:0x4BE0 32-byte runtime record
        array (populated by the activation chain when a scene loads).
    """

    current_room: "int | None" = None
    entry_available: bool = False
    direction_available: "tuple[bool, bool, bool, bool, bool, bool] | None" = None
    move_number: int = 0
    inventory: "set[int]" = field(default_factory=set)
    opened: "set[int]" = field(default_factory=set)
    worn: "set[int]" = field(default_factory=set)
    lit: "set[int]" = field(default_factory=set)
    outcome: str = "playing"  # playing / won / lost
    runtime_records: RuntimeRecordArray = field(default_factory=RuntimeRecordArray)
