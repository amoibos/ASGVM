"""A title's binding: what the shared engine needs to know about one game."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class NativeSpan:
    """A trace/static-confirmed native MESSAGE location for a short,
    state-driven acknowledgement (e.g. "You already have X.").

    Captured one of three ways, whichever the coordinate was originally
    traced as -- set only the matching fields:

    * a raw symbol span (``symbol``/``length``, read via
      ``render_symbol_span``);
    * a whole length-prefixed record (``record``, read via
      ``render_message_record``);
    * a bounded slice within a record (``record``+``record_start``+
      ``length``, read via ``render_message_record_span`` -- used when only
      part of a record is the confirmed response, e.g. READ CHART).
    """

    symbol: "int | None" = None
    length: int = 0
    record: "int | None" = None
    record_start: "int | None" = None


@dataclass(frozen=True)
class AsgConfig:
    key: str
    display_name: str
    root: Path
    launcher_name: str = "GAME.COM"
    table_record_size: int = 40
    # Must be supplied only after the title's GAME.000 startup write has been
    # traced.  Guessing room 2 produced unrelated action text in several games.
    initial_native_room_id: int | None = None
    # Optional OVERRIDE for the native verb-value_b -> MESSAGE-record index table
    # (the DS:0x5F0 table the GAME.COM loader builds). Normally ``None``: the VM
    # derives this table from the phase-1 activation pointer at load time
    # (``AsgActivationTables.build_verb_response_records``), so it is data, not a
    # per-title capture. This field only exists as an escape hatch if a title's
    # derivation ever needs to be forced; the shipped titles all leave it unset.
    verb_response_records: "dict[int, int] | None" = None
    # Per-room description overrides, keyed by NATIVE room id, for rooms whose
    # ``message_offset`` lands mid-composite where the structural
    # ``render_room_segment`` gap-scanner can't resolve the right segment (it
    # needs the still-unported state-based section selector). Each value is a
    # confirmed MESSAGE ``NativeSpan`` (a captured pointer, NOT prose),
    # oracle-validated
    # against the real game. ``None``/missing = use ``render_room_segment``.
    room_description_spans: "dict[int, NativeSpan] | None" = None
    # The 1A8D slot the pursuit approximation reads as the pursuer count.
    pursuit_counter_slot: int = 2
    # The text-mode attribute the original prints the game in (B800 read on
    # DOSBox-X after a new game, 2026-10-17): 0x0E yellow for Goldfinger,
    # Indiana Jones and High Stakes, 0x0F bright white for the 47-byte
    # titles. The restore question before it is 0x0F everywhere.
    text_attribute: int = 0x0F
    # MESSAGE record the movement record renders on a first visit (Goldfinger:
    # 1669, reached from movement record 1712 through `` x``):
    # ``%| =di ic %l`` -- the room description, the listing program and
    # the people present. ``None`` keeps the bare room description.
    arrival_record: "int | None" = None
    # Override for the record the boot renders after the restore prompt;
    # ``None`` takes word_1A93 from the activation data (Goldfinger: 3899,
    # the first text record the boot opens; traced live 2026-10-15). The boot (GAME.000 2C67..2CB2) parses the word OPEN --
    # RESTORE for a restored game -- and leaves its node in word_4B12; the
    # record's leading `*` (mode 3 on cursor e) and its `&:e$ez` pick the
    # new-game section, whose actions pocket the lighter, set the 1A5F/1A8D
    # fields and walk into the cockpit, and whose text is the opening.
    start_program_record: "int | None" = None
    # The movement record (Goldfinger: 1712, DS:05F0's entry for a move).
    movement_record: "int | None" = None
    # The response of a move on foot (Goldfinger: 1893 = DS:1A8D[4]'s record,
    # word_1A9F): room-specific move texts, then 1712.
    movement_command_record: "int | None" = None
    # (from_native_room_id, direction_slot) -> MESSAGE record index whose
    # ``^pb`` span is rendered as a movement-transition prefix.
    movement_transition_records: "dict[tuple[int, int], int] | None" = None
    # Fuller display names for objects whose bare VOCAB noun reads wrong in
    # generated sentences (Goldfinger: object 6 "ball" -> "golf ball").
    object_display_names: "dict[int, str] | None" = None
