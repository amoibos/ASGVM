"""High-level port of the confirmed GAME.COM MESSAGE runtime.

This module intentionally models the original data path, not an 8086 machine.
Addresses in comments refer to the IDA export in ``goldfinger.asm``.
"""

from __future__ import annotations

import re
from typing import Callable

from .message import DEFAULT_SYMBOL_TABLE, depage
from .packing import unpack_6bit_stream
from .gamecom_conditionals import ConditionalMixin
from .gamecom_render import SymbolRenderMixin


from .message_controls import (
    MESSAGE_TERMINATOR,
    CONTROL_CHARS,
    UNMAPPED_TEMPLATE_SYMBOLS,
    MessageCursor,
)


class GameComMessageEngine(ConditionalMixin, SymbolRenderMixin):
    """Pure-Python port of confirmed GAME.COM MESSAGE functions.

    ``next_character`` mirrors ``sub_4D3A``.  ``render_record`` models the
    bounded record reader initialized by ``sub_4A89`` and consumed by
    ``sub_4CE6``/``sub_4D3A``.  Template controls are deliberately returned as
    characters; the VM's control evaluator (``AsgVm``) interprets them.
    """

    def __init__(self, message_data: bytes) -> None:
        self.message_data = message_data
        self.symbols = unpack_6bit_stream(message_data)
        # The `\` word dictionary / record reader index the *depaged* stream:
        # the native reader strides over each 512-byte page's two-byte header,
        # so a flat unpack would corrupt any record crossing a page boundary.
        self.dict_symbols = unpack_6bit_stream(depage(message_data))
        self.translation_table = self._build_translation_table()
        self._record_stack: list[int] = []
        # 47-byte titles number their `%` selectors one lower (see the
        # render loop); the game loop sets this from the TABLES stride.
        self.percent_variant_b = False
        # Answers `$-` questions (QUIT / SAVE / play again); None = "no".
        self.yes_no_provider: "Callable[[str], bool] | None" = None
        # The native `\` control (IDA 10E1D) ends the render loop after an
        # expansion once 4BCB/4BCC is set -- the game is over or restarts.
        self.render_stop_check: "Callable[[], bool] | None" = None
        self._substitution_stack: list[dict] = []
        self.control_evaluator: Callable[[str, tuple[int, ...], int], bool | None] | None = None
        self.control_text_evaluator: Callable[[str, tuple[int, ...], int], str | None] | None = None
        self.action_text_reader: Callable[[], str | None] | None = None
        # Text a GAME.000 routine prints from inside an action (SAVE's
        # dialog, opcode 3Dh) -- read after every action block.
        self.action_output_reader: Callable[[], str | None] | None = None
        # ``msg_ctrl_star`` is a candidate selector, not an ordinary boolean
        # control.  The callback receives mode, the optional mode-3 operand,
        # and the two-symbol VOCAB descriptor index for one candidate.
        self.star_candidate_matcher: Callable[[int, int | None, int], bool | None] | None = None
        self.star_mode0_index_provider: Callable[[int], int | None] | None = None
        # Return value: the number of symbols consumed out of the action
        # tuple passed in (sub_EF31 executes exactly one opcode and returns;
        # see execute_action_block). ``None`` means "unknown" -- the caller
        # then falls back to skipping only the detected label, matching the
        # historical/conservative behaviour for callers that don't track it.
        self.action_executor: Callable[[tuple[int, ...], int], int | None] | None = None
        # Optional: read the native byte_4B7B render/skip flag left behind by
        # the action block ``action_executor`` just ran (confirmed native
        # opcodes 0x32-0x35/0x46/etc. write it; the ``|`` control consumes it).
        # ``None`` means "unknown", so the caller leaves any following ``|``
        # gate untouched rather than guessing a render/skip decision.
        self.action_gate_reader: Callable[[], bool | None] | None = None
        self.record_open_callback: Callable[[], None] | None = None

    @staticmethod
    def _build_translation_table() -> list[int]:
        """Rebuild the 64-entry table initialized by GAME.000:23BA..2706."""

        table = [ord("?")] * 64
        for symbol, character in DEFAULT_SYMBOL_TABLE.items():
            table[symbol] = ord(character)
        return table

    def next_symbol(self, cursor: MessageCursor) -> int | None:
        """Port GAME.COM:4CE6/4C91/4721 for one symbol window."""

        byte_offset = cursor.group_index * 6
        if byte_offset + 6 > len(self.message_data):
            return None
        symbol_offset = cursor.group_index * 8 + cursor.symbol_index
        if symbol_offset >= len(self.symbols):
            return None
        symbol = self.symbols[symbol_offset]
        cursor.symbol_index += 1
        if cursor.symbol_index == 8:
            cursor.symbol_index = 0
            cursor.group_index += 1
        return symbol

    def seek(self, symbol_offset: int) -> MessageCursor:
        """Port GAME.COM:4D81 address-to-window calculation.

        GAME.COM stores a one-based symbol position internally, divides it by
        eight to select a six-byte MESSAGE window, and keeps the remainder as
        the active symbol slot. Python exposes the same state as a zero-based
        cursor.
        """

        if symbol_offset < 0:
            raise ValueError("MESSAGE symbol offset must not be negative")
        return MessageCursor(symbol_offset // 8, symbol_offset % 8)

    def next_character(self, cursor: MessageCursor) -> int:
        """Port the table lookup in GAME.COM:4D3A for one packed symbol."""

        symbol = self.next_symbol(cursor)
        if symbol is None:
            return MESSAGE_TERMINATOR
        return self.translation_table[symbol]

    def record_length(self, group_index: int) -> int:
        """Read the 12-bit length header used by GAME.COM:4A89..4B14.

        A MESSAGE *record* starts with two packed symbols.  They are a base-64
        length, not printable text.  This API is deliberately separate from
        table references: not every word pointing into MESSAGE names a record.
        """

        start = group_index * 8
        if group_index < 0 or start + 2 > len(self.symbols):
            raise IndexError(f"MESSAGE group {group_index} outside MESSAGE")
        return self.symbols[start] * 64 + self.symbols[start + 1]

    def render_run(self, symbol_offset: int, max_symbols: int = 600) -> str:
        """Render the literal MESSAGE prose beginning at a symbol position.

        This ports the *confirmed* pieces of the GAME.COM text path:

        * ``% x@`` capitalises the following literal (the outer ``%`` control
          plus the ``0x40`` ('@') segment terminator handled by
          ``render_segment``): ``% s@wiss`` -> ``Swiss``.
        * ``sub_3DFB`` auto-capitalises the first letter and the first letter
          after a sentence end (``.``/``!``/``?``) and collapses runs of spaces.

        It stops at the first control symbol it cannot yet resolve, so it emits
        decoded prose only -- never raw template/control bytes. The native
        dispatcher that assembles a full multi-fragment room description from
        several offsets and substitutions is not ported yet, so some rooms whose
        offset points mid-fragment yield only a partial run.
        """

        symbols = self.symbols
        end = min(len(symbols), symbol_offset + max_symbols)
        chars: list[str] = []
        index = symbol_offset
        while index < end:
            symbol = symbols[index]
            if symbol == 0x20:  # '%' capitalize-next control
                cursor = index + 1
                if cursor < end and symbols[cursor] == 0x1A:  # skip the space
                    cursor += 1
                if cursor < end and 0x61 <= self.translation_table[symbols[cursor]] <= 0x7A:
                    chars.append(chr(self.translation_table[symbols[cursor]] - 0x20))
                    cursor += 1
                    if cursor < end and symbols[cursor] == 0x21:  # skip segment '@'
                        cursor += 1
                    index = cursor
                    continue
                break
            if symbol == 0x21:  # '@' segment terminator
                break
            if symbol in UNMAPPED_TEMPLATE_SYMBOLS:
                break
            char = chr(self.translation_table[symbol])
            if char in CONTROL_CHARS:
                break
            chars.append(char)
            index += 1

        out: list[str] = []
        capitalize_next = True
        previous = ""
        for char in "".join(chars):
            if char.isalpha():
                # sub_3DFB inserts a break after sentence/clause punctuation;
                # surface it as a single space so words do not run together.
                if previous in ".!?,:;":
                    out.append(" ")
                out.append(char.upper() if capitalize_next else char)
                capitalize_next = False
            else:
                out.append(char)
                if char in ".!?":
                    capitalize_next = True
            previous = char
        return " ".join("".join(out).split())

    def record_symbols(self, index: int) -> list[int]:
        """Return the payload symbols of MESSAGE record ``index``.

        Ports GAME.COM:4A89/4AB8: the record starts at depaged group ``index``;
        the first two symbols are a base-64 length and the next ``length``
        symbols are the payload.
        """

        start = index * 8
        if index < 0 or start + 2 > len(self.dict_symbols):
            raise IndexError(f"MESSAGE record {index} outside MESSAGE")
        length = self.dict_symbols[start] * 64 + self.dict_symbols[start + 1]
        payload_start = start + 2
        return self.dict_symbols[payload_start : payload_start + length]

    # Screen width / wrap column confirmed from the GAME.COM layout routine
    # (loc_3662..loc_38D1): a printed column counter is compared to 0x4F (79)
    # and the line wraps when it is reached; rows advance/scroll at 0x18 (24).
    SCREEN_WIDTH = 79

    # GAME.COM status header. ``aMove db 6,'MOVE #'`` (near loc_521B) prints the
    # label and then the move number via the numeric routine (sub_2835).
    # ``sub_41F2`` prints a 10-dash rule (``db 10,'----------'``) positioned at
    # column ``(0x4F - 0x0A) // 2`` == 34, i.e. centred on the 79-column screen.
    STATUS_RULE_LENGTH = 10

    def status_line(self, move_number: int) -> str:
        return f"MOVE #{move_number}"

    def status_separator(self, width: int | None = None) -> str:
        if width is None:
            width = self.SCREEN_WIDTH
        indent = (width - self.STATUS_RULE_LENGTH) // 2
        return " " * indent + "-" * self.STATUS_RULE_LENGTH

    def layout_text(self, text: str, width: int | None = None) -> str:
        """Port the GAME.COM text-layout routine's *visible* behaviour.

        The original (loc_3662..loc_38D1, live-confirmed: word separator
        ``byte_1BE8``, soft break ``byte_48F3``->``byte_1AF6``, wrap column
        ``0x4F``) buffers each word, normalises the inter-word separators, and
        breaks the line so a word that would pass column 79 moves whole to the
        next line. This reproduces that layout: per paragraph it runs the
        printer ``sub_3DFB`` (:meth:`_print_3dfb`: blanks, marks, capitals),
        then greedily wraps at ``width`` columns. Paragraph breaks (``|`` -> newline) become a
        blank line, matching the DOSBox-X prologue screen exactly.
        """

        if width is None:
            width = self.SCREEN_WIDTH
        # Collapse runs of '\n' to a single paragraph boundary so handlers
        # that already use '\n\n' to join sub-fragments do not get a
        # 4-newline gap after layout. The native engine emits ONE break
        # byte (0x0D from msg_ctrl_break) per paragraph; multiple breaks
        # collapse the same way they do on the original screen.
        import re as _re
        text = _re.sub(r"\n\s*\n+", "\n", text)
        wrapped = []
        for paragraph in text.split("\n"):
            centred = self.CENTER_MARK in paragraph
            paragraph = self._print_3dfb(paragraph.replace(self.CENTER_MARK, ""))
            lines = self._wrap_words(paragraph, width) if paragraph else ""
            if centred and lines:
                lines = "\n".join(
                    " " * max(0, (width - len(line)) // 2) + line for line in lines.split("\n")
                )
            wrapped.append(lines)
        return "\n\n".join(wrapped)

    # Marks a line the `%` centring selector (A2h) starts.
    CENTER_MARK = "\x02"  # dropped by every normalize()

    # GAME.COM init: DS:1BC8, the marks that end a word's run in state 0.
    _PRINTER_MARKS = ",.;?:!"

    @staticmethod
    def _print_3dfb(paragraph: str) -> str:
        """Port of the printer ``sub_3DFB``: every character through byte_1EBE.

        States (raw byte_1EBE values): 0 inside a word; 1 a blank is pending;
        2 after a sentence mark (``. ! ?``); 5 a sentence ended, a blank and
        a capital follow; 3 capitalise the next letter (paragraph start,
        sub_41AC); 4 a pending lone ``i`` (printed ``I`` when a blank
        follows); 6 after ``, ;`` (a blank follows, a quote closes); 7 after
        ``:`` (a digit continues the word: "9:00"). A mark after a pending
        blank attaches to the word (state 1 drops the blank), which is why a
        raw ". . ." prints ".. .". Each paragraph starts in state 3, and a
        ``\n`` inside the text is one (state 3 again).
        """

        out: list[str] = []
        state = 3
        marks = GameComMessageEngine._PRINTER_MARKS

        def put(ch: str) -> None:
            nonlocal state
            while True:
                if state == 0:
                    if ch == " ":
                        state = 1
                        return
                    out.append(ch)
                    if ch in marks:
                        state = 2 if ch in ".!?" else 7 if ch == ":" else 6
                    return
                if state == 4:
                    if ch == " ":
                        out.append("I")
                        state = 1
                        return
                    out.append("i")
                    state = 0
                    continue
                if state == 1:
                    if ch == " ":
                        return
                    if ch in ".?!,":
                        out.append(ch)
                        state = 0 if ch == "," else 2
                        return
                    out.append(" ")
                    if ch == "i":
                        state = 4
                        return
                    out.append(ch)
                    state = 0
                    return
                if state == 5:
                    out.append(" ")
                    state = 3
                    continue
                if state == 6:
                    if ch == '"':
                        state = 0
                        out.append(" ")
                        out.append('"')
                        return
                    state = 1
                    continue
                if state == 3:
                    if ch == " ":
                        return
                    if "a" <= ch <= "z":
                        ch = ch.upper()
                    out.append(ch)
                    state = 0
                    return
                if state == 2:
                    if ch == ".":
                        out.append(".")
                        return
                    state = 5
                    if ch == '"':
                        out.append('"')
                        return
                    continue
                if state == 7:
                    if "0" <= ch <= "9":
                        out.append(ch)
                        state = 0
                        return
                    state = 5
                    if ch == '"':
                        out.append('"')
                        return
                    continue
                return

        for ch in paragraph:
            if ch == "\n":
                # A paragraph (sub_41AC): the line ends, state 3.
                while out and out[-1] == " ":
                    out.pop()
                out.append("\n")
                state = 3
                continue
            put(" " if ch.isspace() else ch)
        return "".join(out).strip(" ")

    @staticmethod
    def _wrap_words(paragraph: str, width: int) -> str:
        """Greedy word wrap: a word that would pass column ``width`` wraps whole."""

        lines: list[str] = []
        current = ""
        for word in paragraph.split(" "):
            if not current:
                current = word
            elif len(current) + 1 + len(word) <= width:
                current += " " + word
            else:
                # The native wrap also breaks after a hyphen inside a word: A
                # View to a Kill's "earthquake--" ends a line, "killing" opens
                # the next.
                cut = max(
                    (k + 1 for k, c in enumerate(word[:-1]) if c == "-" and word[k + 1] != "-"
                     and len(current) + 1 + k + 1 <= width),
                    default=0,
                )
                if cut:
                    lines.append(current + " " + word[:cut])
                    current = word[cut:]
                else:
                    lines.append(current)
                    current = word
        if current:
            lines.append(current)
        return "\n".join(lines)

    def render_segment(self, cursor: MessageCursor, capitalize: bool = False) -> str:
        """Port the terminator-bounded renderer at GAME.COM:4ECC..4F35.

        Reads translated characters from ``cursor`` via ``next_character``
        (GAME.COM:4D3A) and stops at the ``0x40`` (``'@'``) terminator
        (GAME.COM:4ED7..4EE1) -- so ``'@'`` is a control, not a literal. While
        ``capitalize`` is set, a lowercase letter (``0x61..0x7a``) is
        upper-cased by subtracting ``0x20`` (GAME.COM:4F0B, gated by the
        ``'a'..'z'`` range test at GAME.COM:4EFD..4F08). End-of-data also stops
        the loop. The outer control dispatcher (``%`` capitalize, ``\\`` and the
        other template tokens) that decides when to call this with
        ``capitalize=True`` is not yet ported.
        """

        result: list[str] = []
        character = self.next_character(cursor)
        while character not in (0x40, MESSAGE_TERMINATOR):
            if capitalize and 0x61 <= character <= 0x7A:
                character -= 0x20
            result.append(chr(character))
            character = self.next_character(cursor)
        return "".join(result)

    def render_record(self, group_index: int, capitalize_first: bool = False) -> str:
        """Port the length-bounded record reader (GAME.COM:4A89/4B14).

        The native loop advances from packed symbol 3 and stops after the
        record length.  It does not use symbol ``0x3f`` as an end marker. This
        is distinct from the ``0x40``-terminated :meth:`render_segment` path.
        """

        length = self.record_length(group_index)
        start = group_index * 8 + 2
        end = start + length
        if end > len(self.symbols):
            raise IndexError(f"MESSAGE record {group_index} exceeds MESSAGE")

        result: list[str] = []
        for index, symbol in enumerate(self.symbols[start:end]):
            character = chr(self.translation_table[symbol])
            if capitalize_first and index == 0 and "a" <= character <= "z":
                character = character.upper()
            result.append(character)
        return "".join(result)
