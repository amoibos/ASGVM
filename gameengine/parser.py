"""Data-driven command tokenization over the original VOCAB records.

This is intentionally only the lexical layer. The dispatcher (per game)
decides what a parsed command means in the current state.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from .input_encoding import encode_input
from .vocab import VocabEntry


# The entries for N/S/E/W/U/D have this raw metadata shape in VOCAB.  Keep the
# values named as raw parser fields until the surrounding GAME.000 parser code
# has been fully recovered.
DIRECTION_VALUE_A = 0x05
ACTION_VALUE_A = 0x06
OBJECT_VALUE_A = 0x00
LOCATION_VALUE_A = 0x02
DIRECTION_COUNT = 6
SPACE_SYMBOL = 0x1A


@dataclass(frozen=True)
class ParsedCommand:
    """Original VOCAB entries matched from one input line."""

    raw: str
    symbols: tuple[int, ...]
    entries: tuple[VocabEntry, ...]
    unknown_words: tuple[str, ...]

    def object_ids(self) -> tuple[int, ...]:
        """Return all distinct object-noun candidates in input order."""

        return tuple(dict.fromkeys(
            entry.value_b for entry in self.entries
            if entry.class_id == 0x33
            # Group 1 holds the proper nouns -- and the car key; the native
            # parser only looks at the kind byte.
            and entry.group_id in (0x00, 0x01, 0x02)
            and entry.value_a == OBJECT_VALUE_A
        ))

    def direct_object_ids(self) -> tuple[int, ...]:
        """Return direct-object candidates before an indirect-object phrase.

        Some connector words (notably ``out of``) are deliberately absent
        from Goldfinger's VOCAB.  The native parser nevertheless treats the
        noun following them as an indirect/container object, so retain that
        boundary even when no :class:`VocabEntry` was emitted for it.
        """

        candidates: list[int] = []
        for entry in self.entries:
            if entry.group_id == 0x02 and entry.value_a == 0x08:
                break
            if (
                entry.class_id == 0x33
                and entry.group_id in (0x00, 0x01, 0x02)
                and entry.value_a == OBJECT_VALUE_A
                and entry.value_b not in candidates
            ):
                candidates.append(entry.value_b)
        words = re.findall(r"[a-z0-9']+", self.raw.lower())
        indirect_markers = {"in", "into", "inside", "on", "onto", "from", "of", "out", "through", "under"}
        if len(candidates) > 1 and indirect_markers.intersection(words):
            return (candidates[0],)
        return tuple(candidates)

    def direction_id(self) -> int | None:
        """Return the raw native direction id, when one was parsed."""

        for entry in self.entries:
            if entry.value_a == DIRECTION_VALUE_A and 0 <= entry.value_b < DIRECTION_COUNT:
                return entry.value_b
        return None

    def action_id(self) -> int | None:
        """Return the raw action-verb id carried by original VOCAB metadata.

        Most action verbs live in group=0x02 with value_a=0x06. One special
        case is ``wait`` (group=0x00 value_a=0x06 value_b=0x1B) -- it shares
        the value_a tag but lives in its own group. We accept either group
        for the action-id lookup so ``wait`` parses as an action.
        """

        for entry in self.entries:
            if entry.value_a == ACTION_VALUE_A and entry.group_id in (0x00, 0x02):
                return entry.value_b
        return None

    def movement_verb_word(self) -> str | None:
        """Return the canonical movement-verb phrase if one was parsed.

        VOCAB entries with ``group_id=0x02`` ``value_a=0x0a`` ``class_id=0x13``
        are the "movement-action" class -- ``go``, ``drive``, ``climb``,
        ``enter``, ``get in``, ``get out`` (all share ``value_b=0x0d``
        except ``enter``=0x05, ``exit``=0x10). These don't fall under the
        normal ``action_id`` (value_a=0x06) namespace; the native engine
        dispatches them via a separate movement path. The Python port
        surfaces the matched phrase here so per-game bindings can route
        by exact word.
        """

        for entry in self.entries:
            if (
                entry.group_id == 0x02
                and entry.value_a == 0x0A
                # go/drive/climb/get in/get out (13h), enter (0Dh), exit
                # (10h): native ENTER CAR moves like DRIVE CAR (record 7799).
                and entry.class_id in (0x0D, 0x10, 0x13)
            ):
                return entry.word
        return None

    def object_id(self) -> int | None:
        """Return the first original object-noun id, if present."""

        candidates = self.direct_object_ids()
        return candidates[0] if candidates else None

    def is_question(self) -> bool:
        """Whether the original input used an explicit question form."""

        return self.raw.rstrip().endswith("?")

    def addressed_name(self) -> str | None:
        """Return the addressee before a comma, if the command has one."""

        if "," not in self.raw:
            return None
        name = self.raw.split(",", 1)[0].strip().lower()
        return name or None

    def tell_about_topic(self) -> str | None:
        """Parse ``<npc>, tell [me] about <topic>`` without VOCAB hacks."""

        if "," not in self.raw:
            return None
        tail = self.raw.split(",", 1)[1].strip().lower().rstrip("?.!")
        words = tail.split()
        if not words or words[0] != "tell":
            return None
        try:
            about = words.index("about", 1)
        except ValueError:
            return None
        topic = " ".join(words[about + 1:]).strip()
        return topic or None

    def dialogue_request(self) -> tuple[str, str] | None:
        """Return addressee/topic for the native free-form dialogue shapes.

        Dialogue connector words are absent from VOCAB and therefore must be
        recognised from the raw line.  Keep this lexical: scene presence and
        available replies remain responsibilities of the game binding.
        """

        raw = self.raw.strip().lower().rstrip("?.!")
        patterns = (
            r"^([^,]+),\s*tell(?:\s+me)?\s+about\s+(.+)$",
            r"^ask\s+(.+?)\s+about\s+(.+)$",
            r"^([^,]+),\s*what\s+do\s+you\s+know\s+about\s+(.+)$",
        )
        for pattern in patterns:
            match = re.match(pattern, raw)
            if match is not None:
                addressee = match.group(1).strip()
                topic = match.group(2).strip()
                if addressee and topic:
                    return addressee, topic
        return None

    def location_id(self) -> int | None:
        """Return the first original location-noun id, if present."""

        for entry in self.entries:
            if (
                entry.class_id == 0x33
                and entry.group_id == 0x02
                and entry.value_a == LOCATION_VALUE_A
            ):
                return entry.value_b
        return None


class GoldfingerParser:
    """Match input using longest VOCAB phrases before individual words."""

    def __init__(self, entries: list[VocabEntry]) -> None:
        self.entries = tuple(entries)
        self._phrases: dict[tuple[int, ...], VocabEntry] = {}
        for entry in self.entries:
            phrase = tuple(entry.raw[1 : 1 + entry.raw[0]])
            if not phrase:
                continue
            # A duplicate spelling is an original synonym; retain file order.
            self._phrases.setdefault(phrase, entry)
        self._max_symbols = max((len(phrase) for phrase in self._phrases), default=0)

    def parse(self, raw: str) -> ParsedCommand:
        # The native input table has punctuation symbols, but player commands
        # commonly use sentence punctuation as soft separators -- commas for
        # address forms ("TILLY, ..."), the trailing "?" on questions ("DO
        # YOU HAVE AN INGOT?"). Strip them from the lex stream while
        # preserving the raw command for diagnostics.
        lex_raw = raw.replace(",", " ").replace("?", " ").replace(".", " ").replace("!", " ")
        symbols = encode_input(lex_raw)
        words = tuple(lex_raw.lower().split())
        matched: list[VocabEntry] = []
        unknown: list[str] = []
        position = 0
        word_position = 0
        while position < len(symbols):
            if symbols[position] == SPACE_SYMBOL:
                position += 1
                continue
            entry: VocabEntry | None = None
            width = 0
            for candidate_width in range(min(self._max_symbols, len(symbols) - position), 0, -1):
                candidate = symbols[position : position + candidate_width]
                candidate_entry = self._phrases.get(candidate)
                end = position + candidate_width
                if candidate_entry is not None and (
                    end == len(symbols) or symbols[end] == SPACE_SYMBOL
                ):
                    entry = candidate_entry
                    width = candidate_width
                    break
            if entry is None:
                end = position
                while end < len(symbols) and symbols[end] != SPACE_SYMBOL:
                    end += 1
                if word_position < len(words):
                    unknown.append(words[word_position])
                word_position += 1
                position = end
                continue
            matched.append(entry)
            word_position += len(entry.word.split())
            position += width
        return ParsedCommand(
            raw=raw,
            symbols=symbols,
            entries=tuple(matched),
            unknown_words=tuple(unknown),
        )
