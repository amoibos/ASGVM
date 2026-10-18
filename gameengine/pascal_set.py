"""Turbo Pascal 3 set primitives.

Turbo Pascal 3 represents `set of T` as a packed bit-array. For
``set of byte`` (the common case), the set is a 32-byte bitfield where
bit ``v`` is 1 iff value ``v`` is in the set. Smaller subranges use
proportionally smaller bitfields.

The TP3 runtime library exposes these operations via call helpers:

  * `sub_4B93` family (set source-loader + comparator) -- loads a set
    from a runtime address into a working buffer, then applies a
    comparison against another set or value.
  * `sub_4C44` (set membership test) -- returns ZF=0 when a value is
    a member of the set on the stack.
  * `sub_4CA8` (set in-set membership) -- tests if one set is a
    subset of another.
  * `loc_4BC2` thunks -- variants for different set widths.

These intrinsics are USED across GAME.000 (the per-turn record-eval
loop, the activation-chain phases, the verb handlers) but the exact
calling convention is multi-step (byte_1A4F as scratch, byte_1A4B as
source pointer, the [bp-14h] / [bp-0Ch] frame slots as work buffers).

This module provides the data-side foundation: a `PascalSet` class
that can be populated, tested, unioned, and compared, plus parsers
that read TP3-format set bytes. It does NOT port the GAME.000-specific
call wrappers -- those are caller-side recipes that need a live trace
to map cleanly.
"""

from __future__ import annotations

from dataclasses import dataclass


# TP3's `set of byte` is 256 bits = 32 bytes; smaller sets use fewer.
TP3_BYTE_SET_BYTES = 32


@dataclass
class PascalSet:
    """A TP3 packed-bit set of byte/small-ordinal values.

    The native bit layout is little-endian: ``data[v >> 3] & (1 << (v & 7))``
    is non-zero iff ``v`` is in the set. ``width_bytes`` is the
    declared set width (typically 32 for ``set of byte``; can be less
    for subrange sets).
    """

    data: bytearray
    width_bytes: int

    @classmethod
    def empty(cls, width_bytes: int = TP3_BYTE_SET_BYTES) -> "PascalSet":
        return cls(data=bytearray(width_bytes), width_bytes=width_bytes)

    @classmethod
    def from_bytes(cls, raw: bytes, width_bytes: int | None = None) -> "PascalSet":
        if width_bytes is None:
            width_bytes = len(raw)
        if len(raw) > width_bytes:
            raise ValueError(
                f"bit data {len(raw)} bytes exceeds declared width {width_bytes}"
            )
        data = bytearray(width_bytes)
        data[: len(raw)] = raw
        return cls(data=data, width_bytes=width_bytes)

    @classmethod
    def from_values(cls, values: "list[int] | set[int] | tuple[int, ...]",
                    width_bytes: int = TP3_BYTE_SET_BYTES) -> "PascalSet":
        s = cls.empty(width_bytes)
        for v in values:
            s.add(v)
        return s

    def __contains__(self, value: int) -> bool:
        """Native bit test: ``data[v >> 3] & (1 << (v & 7))``."""
        if not 0 <= value < self.width_bytes * 8:
            return False
        return bool(self.data[value >> 3] & (1 << (value & 7)))

    def add(self, value: int) -> None:
        if not 0 <= value < self.width_bytes * 8:
            raise ValueError(
                f"value {value} out of set range 0..{self.width_bytes * 8 - 1}"
            )
        self.data[value >> 3] |= 1 << (value & 7)

    def discard(self, value: int) -> None:
        if 0 <= value < self.width_bytes * 8:
            self.data[value >> 3] &= ~(1 << (value & 7)) & 0xFF

    def values(self) -> "list[int]":
        """Enumerate the set's members in ascending order."""
        out: list[int] = []
        for byte_idx in range(self.width_bytes):
            byte = self.data[byte_idx]
            if byte == 0:
                continue
            for bit in range(8):
                if byte & (1 << bit):
                    out.append(byte_idx * 8 + bit)
        return out

    def union(self, other: "PascalSet") -> "PascalSet":
        width = max(self.width_bytes, other.width_bytes)
        result = PascalSet.empty(width)
        for i in range(width):
            a = self.data[i] if i < self.width_bytes else 0
            b = other.data[i] if i < other.width_bytes else 0
            result.data[i] = a | b
        return result

    def intersection(self, other: "PascalSet") -> "PascalSet":
        width = max(self.width_bytes, other.width_bytes)
        result = PascalSet.empty(width)
        for i in range(width):
            a = self.data[i] if i < self.width_bytes else 0
            b = other.data[i] if i < other.width_bytes else 0
            result.data[i] = a & b
        return result

    def difference(self, other: "PascalSet") -> "PascalSet":
        """Return the native set subtraction ``self - other``."""
        width = max(self.width_bytes, other.width_bytes)
        result = PascalSet.empty(width)
        for i in range(width):
            a = self.data[i] if i < self.width_bytes else 0
            b = other.data[i] if i < other.width_bytes else 0
            result.data[i] = a & (~b & 0xFF)
        return result

    def is_subset_of(self, other: "PascalSet") -> bool:
        """Native equivalent of `sub_4CA8` set-in-set test."""
        for i in range(self.width_bytes):
            a = self.data[i]
            b = other.data[i] if i < other.width_bytes else 0
            if (a & ~b) & 0xFF:
                return False
        return True

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PascalSet):
            return NotImplemented
        width = max(self.width_bytes, other.width_bytes)
        for i in range(width):
            a = self.data[i] if i < self.width_bytes else 0
            b = other.data[i] if i < other.width_bytes else 0
            if a != b:
                return False
        return True

    def __hash__(self) -> int:
        return hash(bytes(self.data))

    def __len__(self) -> int:
        return sum(bin(b).count("1") for b in self.data)

    def to_bytes(self) -> bytes:
        return bytes(self.data)
