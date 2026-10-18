"""VOCAB codec — 26-byte Pascal-string + 4-byte parser metadata records.

Engine-pure: every sibling title uses the same 26-byte record layout
(content count varies). Game-specific verb/noun id constants live with
the game binding, not here.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from .message import DEFAULT_SYMBOL_TABLE


VOCAB_RECORD_SIZE = 26
VOCAB_TEXT_SIZE = 22

# The value_a byte (record +0x18) acts as a part-of-speech discriminator.
# Confirmed by full coverage in the shipped VOCAB: every value_a == 5 entry is
# a direction word and its value_b is the direction id 0..5 (12/12 entries,
# matching the direction table in docs/file-formats.md). The verb (0x06) and
# noun (0x00) groupings are strongly indicated by the same data but their
# native use still needs the parse-token trace at GAME.000:1368/0x4b4.
VOCAB_VALUE_A_DIRECTION = 0x05
VOCAB_VALUE_A_VERB = 0x06
VOCAB_VALUE_A_NOUN = 0x00


@dataclass(frozen=True)
class VocabAnalysis:
    size: int
    unique_values: int
    min_value: int
    max_value: int
    top_values: list[tuple[int, int]]
    first_values: list[int]


@dataclass(frozen=True)
class VocabEntry:
    index: int
    offset: int
    word: str
    raw: bytes
    metadata: bytes
    class_id: int
    group_id: int
    value_a: int
    value_b: int

    @property
    def is_direction(self) -> bool:
        """True when value_a marks this word as a movement direction."""

        return self.value_a == VOCAB_VALUE_A_DIRECTION

    @property
    def direction_id(self) -> int | None:
        """Direction id 0..5 (value_b) for direction words, else None.

        The id matches the slot order consumed by the dispatcher direction
        loop (north=0, south=1, east=2, west=3, up=4, down=5), so it can be
        passed straight to ``TableDecoder.resolve_entry``.
        """

        return self.value_b if self.is_direction else None


def decode_vocab_chars(values: bytes) -> str:
    return "".join(DEFAULT_SYMBOL_TABLE.get(value, f"[{value:02x}]") for value in values)


class VocabDecoder:
    """VOCAB decoder.

    GAME.000:068B opens VOCAB as a fixed-record file. Each entry is 26 bytes:
    a Pascal-style string field (1 byte length + 21 bytes of symbol text) and
    four parser metadata bytes.
    """

    def __init__(self, data: bytes) -> None:
        self.data = data

    def entries(self) -> list[VocabEntry]:
        entries: list[VocabEntry] = []
        for offset in range(0, len(self.data) - VOCAB_RECORD_SIZE + 1, VOCAB_RECORD_SIZE):
            raw = self.data[offset : offset + VOCAB_RECORD_SIZE]
            length = raw[0]
            if length > VOCAB_TEXT_SIZE - 1:
                continue
            word_bytes = raw[1 : 1 + length]
            metadata = raw[VOCAB_TEXT_SIZE:VOCAB_RECORD_SIZE]
            entries.append(
                VocabEntry(
                    index=len(entries),
                    offset=offset,
                    word=decode_vocab_chars(word_bytes),
                    raw=raw,
                    metadata=metadata,
                    class_id=metadata[0],
                    group_id=metadata[1],
                    value_a=metadata[2],
                    value_b=metadata[3],
                )
            )
        return entries

    def directions(self) -> dict[str, int]:
        """Map every direction word (incl. synonyms) to its direction id."""

        result: dict[str, int] = {}
        for entry in self.entries():
            if entry.is_direction and entry.word:
                result[entry.word] = entry.value_b
        return result

    def analyze(self, limit: int = 64) -> VocabAnalysis:
        counts = Counter(self.data)
        return VocabAnalysis(
            size=len(self.data),
            unique_values=len(counts),
            min_value=min(self.data) if self.data else 0,
            max_value=max(self.data) if self.data else 0,
            top_values=counts.most_common(16),
            first_values=list(self.data[:limit]),
        )
