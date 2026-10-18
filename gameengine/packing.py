"""6-bit symbol packing used by MESSAGE and VOCAB text streams.

The same codec is shared across all 8 sibling Mindscape titles; the
``xtrnip`` routine in their respective COM launchers is byte-identical
where decompiled. Engine-pure module — no game-specific constants.
"""

from __future__ import annotations

from collections.abc import Iterable


def xtrnip(part: int, value: int) -> int:
    """Reproduce GAME.COM:46AC, the 6-bit symbol extractor.

    The DOS routine names its error message "error in xtrnip". It extracts
    one of six bit windows from a byte and returns the window aligned as a
    6-bit value. Consecutive calls combine these windows into packed symbols.
    """

    value &= 0xFF
    if part == 1:
        return (value & 0xFC) >> 2
    if part == 2:
        return (value & 0x03) << 4
    if part == 3:
        return (value & 0xF0) >> 4
    if part == 4:
        return (value & 0x0F) << 2
    if part == 5:
        return (value & 0xC0) >> 6
    if part == 6:
        return value & 0x3F
    raise ValueError(f"invalid xtrnip part {part}")


def unpack_six_bytes(chunk: bytes) -> list[int]:
    """Unpack six source bytes into the eight 6-bit symbols used by MESSAGE."""

    if len(chunk) != 6:
        raise ValueError("exactly six bytes are required")
    b0, b1, b2, b3, b4, b5 = chunk
    return [
        xtrnip(1, b0),
        xtrnip(2, b0) + xtrnip(3, b1),
        xtrnip(4, b1) + xtrnip(5, b2),
        xtrnip(6, b2),
        xtrnip(1, b3),
        xtrnip(2, b3) + xtrnip(3, b4),
        xtrnip(4, b4) + xtrnip(5, b5),
        xtrnip(6, b5),
    ]


def unpack_6bit_stream(data: bytes) -> list[int]:
    """Unpack a byte stream in six-byte groups.

    Partial trailing groups are ignored, matching the fixed block access
    pattern observed around GAME.COM:4721.
    """

    symbols: list[int] = []
    usable = len(data) - (len(data) % 6)
    for offset in range(0, usable, 6):
        symbols.extend(unpack_six_bytes(data[offset : offset + 6]))
    return symbols


def chunks(values: Iterable[int], width: int) -> Iterable[list[int]]:
    row: list[int] = []
    for value in values:
        row.append(value)
        if len(row) == width:
            yield row
            row = []
    if row:
        yield row
