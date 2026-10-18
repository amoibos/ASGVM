"""MESSAGE codec (paged 6-bit symbol records).

Engine-pure module — the 6-bit packing + paged file format is
identical across all 8 sibling Mindscape titles. Per-game symbol
tables can override ``DEFAULT_SYMBOL_TABLE`` (this is the table for
Goldfinger; identical across Variant A games per spot-checks).
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from .packing import unpack_6bit_stream, unpack_six_bytes


DEFAULT_SYMBOL_TABLE: dict[int, str] = {
    0x00: "a",
    0x01: "p",
    0x02: "e",
    0x03: "t",
    0x04: "i",
    0x05: "x",
    0x06: "m",
    0x07: "b",
    0x08: "q",
    0x09: "f",
    0x0A: "u",
    0x0B: "j",
    0x0C: "y",
    0x0D: "n",
    0x0E: "c",
    0x0F: "r",
    0x10: "g",
    0x11: "v",
    0x12: "k",
    0x13: "z",
    0x14: "o",
    0x15: "d",
    0x16: "s",
    0x17: "h",
    0x18: "w",
    0x19: "l",
    0x1A: " ",
    0x1B: "^",
    0x1C: "|",
    0x1D: "*",
    0x1E: "(",
    0x1F: "$",
    0x20: "%",
    0x21: "@",
    0x22: "#",
    0x23: ".",
    0x24: ",",
    0x25: "-",
    0x26: "?",
    0x27: '"',
    0x28: ";",
    0x29: "'",
    0x2A: "!",
    0x2B: ":",
    0x2C: "&",
    0x2D: "=",
    0x2E: "+",
    0x2F: "\\",
    0x34: "0",
    0x35: "1",
    0x36: "2",
    0x37: "3",
    0x38: "4",
    0x39: "5",
    0x3A: "6",
    0x3B: "7",
    0x3C: "8",
    0x3D: "9",
}

# These are direct prose symbols. The other mapped symbols are template and
# formatting controls emitted by the native MESSAGE renderer.
LITERAL_SYMBOLS = frozenset((*range(0x00, 0x1B), 0x23, 0x24, 0x25, 0x26, 0x27))

# MESSAGE on disk is a paged file: 94 fixed 512-byte pages, each carrying a
# two-byte page header followed by 85 six-byte symbol groups (510 data bytes).
# Confirmed via a live DOSBox-X trace of the record seek GAME.COM:4525 (it
# divides a record index by 0x55=85 and strides by 0x202=514 over a RAM block
# cache; the on-disk pages are 512 bytes). The record reader walks the depaged
# stream, so a logical record index N lives at depaged offset N*6.
MESSAGE_PAGE_SIZE = 512
MESSAGE_PAGE_HEADER = 2
MESSAGE_GROUPS_PER_PAGE = 85


def depage(data: bytes) -> bytes:
    """Concatenate each 512-byte page's 510-byte data region into one stream.

    Dropping the two-byte per-page header yields the contiguous symbol stream
    the native record reader sees; a record that is longer than one page then
    reads straight across what were page boundaries on disk.
    """

    out = bytearray()
    for start in range(0, len(data), MESSAGE_PAGE_SIZE):
        out += data[start + MESSAGE_PAGE_HEADER : start + MESSAGE_PAGE_SIZE]
    return bytes(out)


@dataclass(frozen=True)
class MessageAnalysis:
    size: int
    symbol_count: int
    first_symbols: list[int]


@dataclass(frozen=True)
class MessageRecord:
    offset: int
    byte_offset: int
    length: int
    symbols: list[int]


def decode_symbols(
    symbols: list[int],
    table: dict[int, str] | None = None,
    unknown: str = "?",
) -> str:
    table = DEFAULT_SYMBOL_TABLE if table is None else table
    return "".join(table.get(symbol, unknown) for symbol in symbols)


def normalize_text(text: str) -> str:
    """Make partially decoded game text readable at the console."""
    text = text.replace("\x02", "")  # the centring mark (gamecom.CENTER_MARK)

    text = text.replace("_", " ")
    text = text.replace(" .", ".").replace(" ,", ",")
    return " ".join(text.split())


def render_template(text: str) -> str:
    """Render the first recovered MESSAGE template control.

    GAME.000 emits `% x@` as a capitalized literal `X`; this is visible in the
    DOSBox-X prologue as `% b@ond` -> `Bond` and `% q@` -> `Q`.
    """

    text = re.sub(r"% ([a-z])@", lambda match: match.group(1).upper(), text)
    text = text.replace("@", "")
    text = re.sub(r"(?<=[.!?])(?=[a-z])", " ", text)
    text = re.sub(r"(?<=[.!?] )([a-z])", lambda match: match.group(1).upper(), text)
    text = normalize_text(text)
    return text[:1].upper() + text[1:]


class MessageDecoder:
    """Partial MESSAGE decoder.

    The 6-bit packing is known. The remaining unknown is the runtime
    translation table at DS:1DF8 used by GAME.COM:4D64-4D70. Until that table is
    reconstructed, this class exposes symbol streams for analysis rather than
    claiming to decode final prose.
    """

    def __init__(self, data: bytes) -> None:
        self.data = data
        # The native record reader / `\` dictionary walk the depaged stream
        # (see depage()); the older TABLES-offset room path still indexes the
        # raw file, so both are kept until that path is re-validated.
        self.depaged = depage(data)

    def symbols(self) -> list[int]:
        return unpack_6bit_stream(self.data)

    def record_at(self, offset: int) -> MessageRecord:
        """Read a MESSAGE record at a six-byte-group offset.

        The game routine at GAME.COM:4A89/4AB8 treats the first two unpacked
        symbols as a 12-bit symbol length. The remaining symbols are the record
        payload.
        """

        byte_offset = offset * 6
        if byte_offset + 6 > len(self.data):
            raise IndexError(f"message offset {offset} outside MESSAGE")
        first = unpack_six_bytes(self.data[byte_offset : byte_offset + 6])
        length = first[0] * 64 + first[1]
        if length == 0:
            return MessageRecord(offset, byte_offset, 0, [])

        needed_symbols = length + 2
        needed_groups = (needed_symbols + 7) // 8
        raw = self.data[byte_offset : byte_offset + needed_groups * 6]
        stream = unpack_6bit_stream(raw)
        return MessageRecord(
            offset=offset,
            byte_offset=byte_offset,
            length=length,
            symbols=stream[2 : 2 + length],
        )

    def record_by_index(self, index: int) -> MessageRecord:
        """Read MESSAGE record ``index`` from the depaged stream.

        This is the addressing the native record reader and the ``\\`` word
        dictionary use: record ``index`` starts at depaged group ``index`` (the
        first two symbols are a base-64 length). Records may span former page
        boundaries; depaging makes the payload contiguous. Confirmed by a live
        DOSBox-X trace (index 68 -> "Goldfinger", 3491 -> "Mercedes").
        """

        byte_offset = index * 6
        if index < 0 or byte_offset + 6 > len(self.depaged):
            raise IndexError(f"MESSAGE record {index} outside MESSAGE")
        first = unpack_six_bytes(self.depaged[byte_offset : byte_offset + 6])
        length = first[0] * 64 + first[1]
        if length == 0:
            return MessageRecord(index, byte_offset, 0, [])
        needed_groups = (length + 2 + 7) // 8
        stream = unpack_6bit_stream(self.depaged[byte_offset : byte_offset + needed_groups * 6])
        return MessageRecord(index, byte_offset, length, stream[2 : 2 + length])

    def decode_record(
        self,
        offset: int,
        table: dict[int, str] | None = None,
        unknown: str = "?",
    ) -> str:
        return decode_symbols(self.record_at(offset).symbols, table=table, unknown=unknown)

    def decode_text_at(self, offset: int, max_symbols: int = 512) -> str:
        """Decode the printable literal run beginning at a MESSAGE address.

        TABLES stores positions in six-byte blocks, not the synthetic length
        records used by :meth:`record_at`. The main game combines these runs
        with script-driven templates. Stop at the first non-printing control
        token so partially understood template data cannot spill into the
        terminal as prose.
        """

        if offset < 0:
            raise IndexError("message offset must not be negative")
        start = offset * 8
        stream = self.symbols()
        if start >= len(stream):
            raise IndexError(f"message offset {offset} outside MESSAGE")

        symbols: list[int] = []
        for symbol in stream[start : start + max_symbols]:
            if symbol not in LITERAL_SYMBOLS:
                break
            symbols.append(symbol)
        return normalize_text(decode_symbols(symbols, unknown=""))

    def plausible_records(self, max_length: int = 1024) -> list[MessageRecord]:
        records: list[MessageRecord] = []
        groups = len(self.data) // 6
        for offset in range(groups):
            record = self.record_at(offset)
            if 0 < record.length <= max_length:
                end_symbol = offset * 8 + 2 + record.length
                if end_symbol <= groups * 8:
                    records.append(record)
        return records

    def analyze(self, limit: int = 64) -> MessageAnalysis:
        symbols = self.symbols()
        return MessageAnalysis(
            size=len(self.data),
            symbol_count=len(symbols),
            first_symbols=symbols[:limit],
        )
