"""The MESSAGE renderer's control alphabet, selector sets and cursor types (GAME.COM)."""

from __future__ import annotations

from dataclasses import dataclass


MESSAGE_TERMINATOR = -1

# The confirmed template-control alphabet built by GAME.COM at DS:0x1b68
# (GAME.COM:5160..5171): ^ | ( + % = $ & * \. Only these characters are
# controls; everything else that the symbol table maps -- letters, digits, and
# in-sentence punctuation (. , - " ; ' ! : ?) -- is literal prose. ``%`` is the
# capitalize control (handled inline) and ``@`` (symbol 0x21) is the segment
# terminator; the rest stop the literal run because they need the native
# template dispatcher. This replaces the earlier symbol-range guess, which wrongly
# treated literal digits and ``?`` as controls and truncated descriptions early.
CONTROL_CHARS = frozenset(("^", "|", "(", "+", "=", "$", "&", "*", "\\"))

# ``msg_ctrl_dollar`` decodes its opcode as ``raw_symbol + 0x57`` via
# sub_AE27. Before the opcode-specific chain, selectors in this native set
# consume a two-symbol ``msg_ctrl_break(1)`` operand. Comparing printable
# translations here is wrong: raw `"` is symbol 0x27 and therefore selector
# 0x7E, which live tracing confirms consumes two further symbols.
DOLLAR_TWO_SYMBOL_SELECTORS = frozenset(
    (0x5E, 0x5F, 0x60, 0x61, 0x62, 0x63, 0x64, 0x6E,
     0x75, 0x77, 0x78, 0x7E, 0x7F, 0x80, 0x81)
)

# Object condition-state opcodes ``$f``/``$g``/``$i`` (selectors 0x66/0x67/0x69,
# sub_C6BB).  In gate position they carry a two-symbol node descriptor before the
# ``|`` render/skip gate (e.g. the room-description ``$g td|`` trap-door state);
# that descriptor is dispatcher metadata, not prose, and must be consumed so it
# does not leak as literal text.  Consumed only when two non-control symbols
# follow, so the rarer ``$g x$`` sibling form (operand-less) is left intact.
DOLLAR_FGI_SELECTORS = frozenset((0x66, 0x67, 0x69))

# Selectors whose dispatch branch reads exactly one raw symbol after the opcode
# through sub_AE27.  Confirmed 0x79 / loc_CE17 tests that raw symbol against
# the one-byte predicate set at DS:0670.
# 0x7B (``$,``) joins this class on data evidence: all 15 occurrences in
# MESSAGE have the identical shape ``$ , x | a f`` -- opcode, exactly ONE
# operand symbol, then the ``|`` gate and its two-symbol descriptor. Leaving
# it at zero operands let that operand leak into the prose as a stray "x"
# ("The letter is not xhere.").
DOLLAR_ONE_SYMBOL_SELECTORS = frozenset((0x79, 0x7B, 0x84))

# 0x72 (``$^``, loc_CD4D) reads no operand: is anything left to list in the
# context room's +18 set once 0699 is taken out? 0x73 (``$|``, loc_CDFF,
# GAME.COM 308A) reads none either: is the current room's exit along
# byte_6AA a dead end (slot value 1)?
DOLLAR_ZERO_SYMBOL_SELECTORS = frozenset((0x65, 0x72, 0x73))

# 0x76 (``$v``): the opcode byte is raw symbol 0x1F, so a ``$v`` gate is encoded
# as ``$$<value>`` (two consecutive ``$`` symbols, then the value operand).  The
# operand runs up to the next control symbol -- one symbol in the ``$$a@`` form
# (terminated by ``@``), two in the ``$$aq|`` form (terminated by ``|``, e.g. the
# office trap-door gate in record 5007).  ``evaluate_message_control``'s 0x76
# branch reads only the first value symbol (``operands[1]`` ->
# ``value_b_for_message_symbol``); any further descriptor symbols are dispatcher
# metadata that must be consumed here so they don't leak as prose (the ``Qa``
# leak before "small trap door").  Consuming to the next control matches both
# forms and leaves the handler semantics unchanged.
DOLLAR_V_SELECTOR = 0x76
DOLLAR_OPERAND_CONTROLS = (
    0x1C, 0x1F, 0x1B, 0x1E, 0x1D, 0x21, 0x2C, 0x2F, 0x20
)

# Symbols 0x30..0x33 and 0x3E..0x3F have no entry in the symbol table; they are
# native template markers (very frequent in template regions, absent from clean
# prose), so a literal run ends when one appears.
UNMAPPED_TEMPLATE_SYMBOLS = frozenset((0x30, 0x31, 0x32, 0x33, 0x3E, 0x3F))


def star_control_mode(selector: int) -> int | None:
    """Return the confirmed ``msg_ctrl_star`` mode selected by ``sub_83D0``.

    The native handler's first branch chain accepts selector values 0, 1, 2
    and 3 and stores the same byte in its local mode slot.  The later branches
    are mode-specific and still being decoded, so values outside this range are
    intentionally left unresolved.
    """

    return selector if 0 <= selector <= 3 else None


def star_initial_break_count(mode: int, break_value: int, modulo_base: int | None = None) -> int | None:
    """Port the confirmed first-count setup in ``msg_ctrl_star``.

    After selecting mode 0..3, the handler consumes a ``msg_ctrl_break(0)``
    value.  Mode 0 reduces it modulo the native word at `loc_6A7+4`; modes
    1..3 keep it unchanged.  Invalid modes or an unusable modulo base are left
    unresolved rather than guessing.
    """

    if star_control_mode(mode) is None or break_value < 0:
        return None
    if mode == 0:
        if modulo_base is None or modulo_base <= 0:
            return None
        return break_value % modulo_base
    return break_value


def star_should_skip_after_membership(membership: bool | None) -> bool | None:
    """Return the confirmed post-membership ``break(1)`` skip decision.

    The tail stores the context-membership result in its local flag and then
    XORs that flag with one.  A false membership therefore consumes a
    two-symbol skip target via ``msg_ctrl_break(1)``/``sub_846B``; a true
    membership lets rendering continue.  ``None`` preserves unknown paths.
    """

    if membership is None:
        return None
    return not membership


def msg_ctrl_break_target(first_symbol: int, second_symbol: int) -> int:
    """Decode ``msg_ctrl_break(1)``'s two-symbol relative distance.

    The native routine reads two raw MESSAGE symbols and returns
    ``first*0x40 + second``. Its caller passes that value to the live-resolved
    ``sub_846B``, which adds it to the already-advanced MESSAGE cursor.  It is
    therefore a forward distance from just after the two descriptor symbols,
    not an absolute position in the current record.
    """

    return first_symbol * 0x40 + second_symbol


@dataclass
class MessageCursor:
    """State held by GAME.COM while consuming a packed MESSAGE stream.

    ``group_index`` mirrors the six-byte window selected by GAME.COM, while
    ``symbol_index`` mirrors the 1..8 selector passed to ``loc_4721``.
    """

    group_index: int = 0
    symbol_index: int = 0


@dataclass(frozen=True)
class ConditionalSpan:
    """Decoded structural span for MESSAGE predicate controls.

    ``continuation`` is the optional two-symbol descriptor following a ``|``
    operand terminator.  Native GAME.000 uses this descriptor to route the
    command-local cursor; older callers only need the tuple-compatible
    ``kind/operand/op_end/frag_end`` view exposed by
    :meth:`parse_conditional_operands`.
    """

    kind: str
    pos: int
    operand: str
    op_end: int
    frag_start: int
    frag_end: int
    continuation: str = ""
    jump_target: int | None = None
    raw_operand: tuple[int, ...] = ()
