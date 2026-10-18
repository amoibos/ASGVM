"""ASCII-to-symbol conversion used before the original VOCAB matcher."""

from __future__ import annotations

from .message import DEFAULT_SYMBOL_TABLE


def build_ascii_symbol_table() -> list[int]:
    """Port GAME.000:23BA..2706's DS:1E38 initialization.

    The native routine clears 128 entries, maps both ASCII letter cases to the
    same six-bit symbol, then adds digits, space, and punctuation. Unmapped
    ASCII values retain the cleared value ``0``.
    """

    table = [0] * 128
    for symbol, character in DEFAULT_SYMBOL_TABLE.items():
        if len(character) != 1:
            continue
        codepoint = ord(character)
        if codepoint < len(table):
            table[codepoint] = symbol
        if "a" <= character <= "z":
            table[ord(character.upper())] = symbol
    return table


ASCII_TO_SYMBOL = build_ascii_symbol_table()


def encode_input(text: str) -> tuple[int, ...]:
    """Encode text exactly as the 7-bit native input table does.

    The original table is only 128 bytes wide. Python input outside that range
    is rejected rather than silently normalised into a different command.
    """

    encoded: list[int] = []
    for character in text:
        codepoint = ord(character)
        if codepoint >= len(ASCII_TO_SYMBOL):
            raise ValueError("Goldfinger input is limited to 7-bit ASCII")
        encoded.append(ASCII_TO_SYMBOL[codepoint])
    return tuple(encoded)
