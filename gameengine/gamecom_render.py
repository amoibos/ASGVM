"""GameComMessageEngine: the symbol-list renderer and room segments."""

from __future__ import annotations

import re
from typing import Callable
from .message_controls import (
    CONTROL_CHARS,
    UNMAPPED_TEMPLATE_SYMBOLS,
    star_control_mode,
    msg_ctrl_break_target,
)


class SymbolRenderMixin:
    """Rendering symbol lists (the control interpreter) and room-description segments."""

    # Confirmed prose controls (ASCII after table translation): '%'=capitalize
    # next letter, '@'=segment terminator (no output), '|'=line break, '\\'=word
    # dictionary expansion. The rest of the DS:0x1b68 control set is not traced.
    #
    # HYPOTHESIS substitution: short verb-response templates contain
    # ``%<letter>`` sequences that render to a single capitalised letter
    # (T/J/E/h) that visibly stands in for an object/location/verb name.
    # Examples found in MESSAGE:
    #   Record 374: "you don't have %t."   -> "You don't have T."
    #   Record 461: "you pass through %j." -> "You pass through J."
    #   Record 394: "you can't %e that."   -> "You can't E that."
    # The native dispatcher must substitute these letters with the current
    # command's target/location/verb. The %-handler at GAME.000:0x14369 is
    # documented as "capitalize-next" only, so the actual substitution
    # almost certainly happens via a *different* control we haven't traced
    # yet (likely the ``&`` handler at 0x11F01 read in tandem). This port
    # exposes a ``substitutions={'t': 'armrest', 'j': 'door', ...}`` opt-in
    # that callers (verb handlers) provide; when a key matches, the rendered
    # substitution replaces the would-be capitalised letter and the
    # capitalisation flag is consumed. With substitutions=None (default) the
    # behaviour is unchanged.
    def _render_symbol_list(
        self,
        symbols: list[int],
        depth: int = 0,
        substitutions: "dict[str, str] | None" = None,
        expand_conditionals: bool = False,
        control_evaluator: "Callable[[str, tuple[int, ...], int], bool | None] | None" = None,
        symbol_origin: int = 0,
        dict_expand_hook: "Callable[[int], str] | None" = None,
        sentence_start: bool = True,
        capitalize_next: bool = False,
        line_has_text: bool = False,
    ) -> str:
        """Render a symbol list through the native control dispatcher.

        Operand metadata is ALWAYS skipped regardless of mode -- the
        operand bytes after ``$`` / ``&`` and the section label after
        ``(`` are dispatcher metadata, never prose, and would leak as
        literal letters if rendered. ``^`` is always a paragraph break
        (``msg_ctrl_break``, the only confirmed semantics for
        non-operand-bearing ``^``).

        ``expand_conditionals`` only changes how ``$`` *fragments* are
        treated:

        * ``False`` (default, matches the native dispatcher's behaviour
          when the state evaluator returns false): skip the operand and
          the following fragment text up to the next ``$`` / ``(``.
          Honours the project rule "an empty response is correct when the
          dispatcher has not resolved a reference; gibberish is not."
        * ``True``: skip only the operand, keep the fragment text -- the
          "render every branch concatenated" behaviour used by data-presence
          tests and by the ``render_with_conditionals`` keep-all evaluator.

        See ``render_with_conditionals`` for the proper state-driven path
        that selects which branches to render.
        """
        out: list[str] = []
        active_control_evaluator = (
            control_evaluator if control_evaluator is not None else self.control_evaluator
        )
        # ``capitalize_next`` is set by the explicit '%' control (proper
        # nouns) and ``sentence_start`` by sub_3DFB's auto-capitalisation of
        # the first letter of each sentence (start of stream and after
        # '.'/'!'/'?' or a line break). Confirmed controls; render_run
        # applies the same rule to literal prose. Both arrive as arguments
        # because msg_dict_expand renders the referenced record into the SAME
        # output stream, so an expansion inherits the casing context it is
        # inserted into.
        pending_gate: bool | None = None
        i = 0
        n = len(symbols)
        percent_translated: set[int] = set()
        while i < n:
            if self.render_stop_check is not None and self.render_stop_check():
                # `(y` / `(n` ran (game over, new game): every render level
                # leaves its loop, a star's chosen body included -- Rambo's
                # ending must not go on to list the people in the Huey.
                break
            sym = symbols[i]
            if (
                sym == 0x20
                and self.percent_variant_b
                and i + 1 < n
                and i not in percent_translated
                and 0x08 <= symbols[i + 1] <= 0x1C
            ):
                # sub_FF65's selector table in the 47-byte titles numbers
                # every entry from 8Fh on one lower than Goldfinger's (read
                # from both disassemblies): their `%u` is the room name
                # (`%j`), `%l` the caps run (`% `), `%h` the "is here"
                # phrase (`%w`). Read the selector in variant-A terms.
                if not percent_translated:
                    symbols = list(symbols)
                symbols[i + 1] += 1
                percent_translated.add(i)
            if sym == 0x2F:  # '\\' word-dictionary expansion
                # Native: `\` always renders the referenced record. (A former
                # port rule skipped a run of references sitting just before
                # `^xx*`, treating them as the selector's payload; in PRESS's
                # record 3823 they are the four gadget records, each gated on
                # its own effect, and `^p0` jumps over the selector after them.)
                if i + 3 < n and depth < 8:
                    index = symbols[i + 1] * 4096 + symbols[i + 2] * 64 + symbols[i + 3]
                    if 0 <= index * 8 + 2 <= len(self.dict_symbols):
                        # Dictionary words are PROSE substituted inline -
                        # they MUST inherit the parent's expand_conditionals
                        # so that an EXAMINE rendered with keep-all gets
                        # the full dict word (e.g. 7121 -> "Oddjob"), and
                        # a conservative render still keeps the dict-spine
                        # text (operand metadata stripped either way).
                        nested_syms = self.record_symbols(index)
                        if self._record_stack.count(index) >= 3:
                            word = ""
                        elif dict_expand_hook is not None:
                            # A conditional-filtering caller (see
                            # render_with_conditional_spans) must apply its
                            # own drop/keep decision inside every dictionary-
                            # referenced record too, not just the top-level
                            # one -- otherwise every branch of every nested
                            # record renders unconditionally, which explodes
                            # combinatorially for large composite verb
                            # records that reference many other composite
                            # records.
                            word = dict_expand_hook(index)
                            # That hook caches per record index and so cannot
                            # take the parent's casing context; it renders in
                            # isolation, with its own sentence start. Undo
                            # that when the word lands mid-sentence and the
                            # record's first symbol is plain prose (a proper
                            # noun opens with its own `% x@` instead).
                            if (
                                word
                                and nested_syms
                                and (0 <= nested_syms[0] <= 0x19 or nested_syms[0] == 0x1D)
                                and not sentence_start
                                and not capitalize_next
                            ):
                                word = word[0].lower() + word[1:]
                        else:
                            self._record_stack.append(index)
                            try:
                                word = self._render_symbol_list(
                                    nested_syms,
                                    depth=depth + 1,
                                    substitutions=substitutions,
                                    expand_conditionals=expand_conditionals,
                                    control_evaluator=active_control_evaluator,
                                    # Dictionary expansion opens a distinct MESSAGE
                                    # record and therefore has its own cursor origin.
                                    symbol_origin=0,
                                    # ... but not its own sentence: the native
                                    # renders it into the same buffer, so a word
                                    # inserted mid-sentence is not sentence-cased
                                    # and a proper noun keeps the capital its own
                                    # `% x@` control gives it.
                                    sentence_start=sentence_start,
                                    capitalize_next=capitalize_next,
                                    # The expansion continues the current
                                    # line (a speaker tag in it breaks it).
                                    line_has_text=(
                                        bool("".join(out).strip(" "))
                                        and not "".join(out).endswith(chr(10))
                                    ) or (line_has_text and not "".join(out)),
                                )
                            finally:
                                self._record_stack.pop()
                        if word and capitalize_next and word[0].isalpha():
                            word = word[0].upper() + word[1:]
                            capitalize_next = False
                        if word and word[0].isalpha() and out and out[-1].endswith(tuple(".!?,:;")):
                            out.append(" ")
                        if any(c.isalpha() for c in word):
                            sentence_start = False
                        if out and out[-1].endswith(" ") and word.startswith(" "):
                            word = word.lstrip(" ")
                        if out and word.startswith(chr(10)):
                            out[-1] = out[-1].rstrip(" ")
                        out.append(word)
                        if self.render_stop_check is not None and self.render_stop_check():
                            # The expanded record ended the game (`(y`) or
                            # started a new one (`(n`): msg_ctrl_backslash
                            # leaves the render loop, so does every caller.
                            break
                i += 4
                continue
            if sym == 0x20 and i + 1 < n and symbols[i + 1] == 0x18:
                # `%w` (selector 9Fh, sub_FBA7): no operand; lists the
                # phase-9 things in the context room. Text comes from the
                # control_text_evaluator; nothing here means nothing to list.
                listed = (
                    self.control_text_evaluator("%w", (), i)
                    if self.control_text_evaluator is not None
                    else None
                )
                if listed:
                    if out and not out[-1].endswith(" "):
                        out.append(" ")
                    out.append(listed)
                    sentence_start = False
                i += 2
                continue
            if sym == 0x20 and i + 1 < n and symbols[i + 1] == 0x00:
                # `%a`: selector 87h is outside sub_FF65's special set, so it
                # takes the generic path (loc_132) -- print the name of what
                # cursor 87h holds (sub_AE9E: room[1A52]+12h). A name only a
                # person cursor has today; anything else prints nothing
                # rather than the letter. Its 5 occurrences in MESSAGE all
                # follow the route walk 52h (`(%pz%a#`, `(%ec%a#`), where no
                # native screen shows a name.
                named = (
                    self.control_text_evaluator("%name", (0x00,), i)
                    if self.control_text_evaluator is not None
                    else None
                )
                if named:
                    if capitalize_next and named[0].isalpha():
                        named = named[0].upper() + named[1:]  # "The bartender"
                    if out and not out[-1].endswith((" ", chr(10))):
                        out.append(" ")
                    out.append(named)
                    sentence_start = False
                capitalize_next = False
                i += 2
                continue
            if sym == 0x22:
                # Symbol 22h ('#') occurs only in operand positions in
                # MESSAGE (after `(`, `\`, `$`, `^`, `%a`), never as prose.
                i += 1
                continue
            if sym == 0x20 and i + 2 < n and symbols[i + 1] == 0x01:
                # `%p<source>`: sub_FF65 selector 88h -> sub_BE9E reads one
                # native value source (sub_83D0 + sub_BD67) and loc_B384
                # prints it in decimal -- the ending's "MOVE #8". Both operand
                # symbols are consumed. The digits are NOT emitted yet: in
                # movement record 1712 it follows the unported route walk 52h
                # (`(%ty`, sub_BB10), and no native move ever shows a number,
                # so printing a value here would be invented output.
                i += 3
                continue
            if sym == 0x20 and i + 1 < n and symbols[i + 1] == 0x1D:
                # `%*<run>@`: a speaker tag -- "%*pussy:@" prints "Pussy:",
                # "%*goldfinger:@" "Goldfinger:"; the empty "%*@" in 1712
                # prints nothing. (Without this the `*` was taken for a star
                # selector and swallowed the speech after it.)
                j = i + 2
                run: list[str] = []
                while j < n and symbols[j] not in (0x1B, 0x1C, 0x1D, 0x1E, 0x1F, 0x20, 0x21, 0x2C, 0x2D, 0x2E, 0x2F) and symbols[j] < 0x30:
                    run.append(chr(self.translation_table[symbols[j]]))
                    j += 1
                if j < n and symbols[j] == 0x21:
                    word = "".join(run)
                    # A speaker tag opens a new line when the line already
                    # holds text: native TRADE LIGHTER FOR KEY prints
                    # "Tilly:" / "Tilly: Here is the lighter." on two lines.
                    text_so_far = "".join(out)
                    if (
                        (text_so_far.strip(" ") and not text_so_far.endswith(chr(10)))
                        or (line_has_text and not text_so_far)
                    ):
                        out.append(chr(10))
                    if word:
                        out.append(word[:1].upper() + word[1:] + " ")
                        # The speech that follows starts a sentence.
                        sentence_start = True
                        capitalize_next = True
                    i = j + 1
                    continue
            if sym == 0x20 and i + 1 < n and symbols[i + 1] in (0x1B, 0x1C):
                # `%^`: a line break (selector A2h), not a `^` jump -- the
                # letter's address block: "%^% auric stud@%^% n@elson ...".
                # `%|` (A3h) likewise: `%` reads its selector itself, so the
                # `|` is never a pending gate's pipe (the opening narrative's
                # "Goldfinger.%|@the aristocratic" follows a `(` action).
                # A2h also centres the line it starts (native screens: the
                # letterhead "AURIC STUD" at column 34, The Mist's restore
                # greeting at 24 and 33 -- (79 - length) // 2; "Nelson
                # County, Kentucky" stands at 29, one right of that).
                out.append(chr(10))
                if symbols[i + 1] == 0x1B:
                    out.append(self.CENTER_MARK)
                sentence_start = True
                i += 2
                continue
            if sym == 0x20:  # '%' capitalize-next control (and substitution gate)
                # ``%d<descriptor>`` is sub_FF65 selector 9Ch ('d' 15h + 87h):
                # describe the node the two-symbol descriptor names.
                if (
                    self.control_text_evaluator is not None
                    and i + 3 < n
                    and symbols[i + 1] == 0x15
                ):
                    injected = self.control_text_evaluator(
                        "%", (0x15, symbols[i + 2], symbols[i + 3]), i
                    )
                    if injected is not None:
                        if injected:
                            if out and not out[-1].endswith((" ", chr(10))):
                                out.append(" ")
                            out.append(injected)
                            sentence_start = injected.rstrip().endswith((".", "!", "?"))
                        capitalize_next = False
                        i += 4
                        continue
                # A person cursor (``%m`` = 1A50, ...) prints that person's
                # name -- unless the caller substitutes the letter itself.
                if (
                    self.control_text_evaluator is not None
                    and i + 1 < n
                    and not (
                        substitutions
                        and chr(self.translation_table[symbols[i + 1]]) in substitutions
                    )
                ):
                    # The cursor path (sub_AE9E) has its own variant-B
                    # numbering (AsgVm.cursor_selector): hand it the symbol
                    # as written, not the selector-translated one -- The
                    # Mist's `%n` is 4ADC ("Ollie Weeks is not here.").
                    raw_symbol = symbols[i + 1] - (1 if i in percent_translated else 0)
                    named = self.control_text_evaluator("%name", (raw_symbol,), i)
                    if named:
                        if capitalize_next and named[0].isalpha():
                            named = named[0].upper() + named[1:]  # "The bartender"
                        if out and not out[-1].endswith((" ", chr(10))):
                            out.append(" ")
                        out.append(named)
                        sentence_start = False
                        capitalize_next = False
                        i += 2
                        continue
                # ``%l`` is sub_FF65 selector A0h ('l' 19h + 87h): the people
                # listing (loc_F915), which prints its own sentence.
                if (
                    self.control_text_evaluator is not None
                    and i + 1 < n
                    and symbols[i + 1] == 0x19
                ):
                    injected = self.control_text_evaluator("%", (0x19,), i)
                    if injected is not None:
                        if injected:
                            if out and not out[-1].endswith((" ", chr(10))):
                                out.append(" ")
                            out.append(injected)
                            sentence_start = injected.rstrip().endswith((".", "!", "?"))
                        capitalize_next = False
                        i += 2
                        continue
                # If a substitution table is provided and the next symbol is a
                # single letter that maps to a substitution value, render the
                # value instead of just capitalising the letter. This is the
                # hypothesis port: the native ``%`` handler does
                # capitalize-next only, but verb-response templates contain
                # ``%t``/``%j``/``%e`` placeholders where the letter is meant
                # to be substituted with the current command's target/location/
                # verb (likely via the un-traced ``&`` handler running in
                # tandem). When no substitution is supplied, behaviour is
                # unchanged: the letter is just capitalised.
                if (
                    substitutions
                    and i + 1 < n
                    and not (i + 1 < n and symbols[i + 1] == 0x1A)
                ):
                    next_sym = symbols[i + 1]
                    next_char = chr(self.translation_table[next_sym])
                    if next_char in substitutions:
                        sub_value = substitutions[next_char]
                        # A callable is resolved at the moment of insertion:
                        # some referents move during the render (the scenery
                        # cursor is re-pointed by record 2203's room->door
                        # table between the record opening and `%i`).
                        if callable(sub_value):
                            sub_value = sub_value()
                        if sub_value and capitalize_next and sub_value[0].isalpha():
                            sub_value = sub_value[0].upper() + sub_value[1:]
                        if (
                            sub_value
                            and sub_value[0].isalpha()
                            and out
                            and out[-1].endswith(tuple(".!?,:;"))
                        ):
                            out.append(" ")
                        capitalize_next = False
                        if any(c.isalpha() for c in sub_value):
                            sentence_start = False
                        out.append(sub_value)
                        i += 2
                        continue
                # ``% [letters]@`` is the all-caps initialism pattern
                # (304 occurrences in MESSAGE, e.g. ``% pg@`` -> "PG",
                # ``% in@`` -> "IN"). When ``%`` is followed by a space
                # and then a run of letters terminated by ``@``, uppercase
                # every letter in the run.
                if (
                    i + 3 < n
                    and symbols[i + 1] == 0x1A  # space
                    and (
                        0x00 <= symbols[i + 2] <= 0x19  # at least one letter
                        # or a space first: A View to a Kill's "% place
                        # explosives here.@" -> " PLACE EXPLOSIVES HERE."
                        or (symbols[i + 2] == 0x1A and 0x00 <= symbols[i + 3] <= 0x19)
                        # or punctuation first: Voodoo Island's headline
                        # `%l"shipwrecked ... search!"@` prints all in capitals
                        # (native, the winning turn).
                        or (0x22 <= symbols[i + 2] <= 0x2B and 0x00 <= symbols[i + 3] <= 0x19)
                    )
                ):
                    j = i + 2
                    letters: list[str] = []
                    # The run may hold spaces: "% auric stud@" -> "AURIC
                    # STUD" (the letter's letterhead, READ LETTER).
                    # Digits belong to the run too: "% mi6@" -> "MI6" (native),
                    # and so does punctuation (22h..2Bh): A View to a Kill's
                    # badge reads "ZORIN'S CHATEAU--MR. JAMES ST. JOHN-SMYTHE".
                    while j < n and (
                        0x00 <= symbols[j] <= 0x1A
                        or 0x22 <= symbols[j] <= 0x2B
                        or symbols[j] >= 0x30
                    ):
                        letters.append(chr(self.translation_table[symbols[j]]))
                        j += 1
                    if j < n and symbols[j] == 0x21:  # terminating @
                        word = "".join(letters).upper()
                        if out and out[-1].endswith(" ") and word.startswith(" "):
                            word = word.lstrip(" ")
                        out.append(word)
                        sentence_start = False
                        capitalize_next = False
                        i = j + 1
                        continue
                capitalize_next = True
                if i + 1 < n and symbols[i + 1] == 0x1A:  # skip a following space
                    i += 1
                i += 1
                continue
            if sym == 0x21:  # '@' segment terminator (no output)
                # The `%` segment ends here: 4ECC capitalises only inside it
                # (Voodoo Island's "%|@ . . . you" keeps the lower case).
                capitalize_next = False
                i += 1
                continue
            if sym == 0x1C:  # '|' line break
                if pending_gate is not None:
                    # Native `|` is the render/skip gate after a predicate
                    # control has written byte_4B7B. Both render and skip
                    # paths consume the two-symbol descriptor following `|`;
                    # the skip path treats it as an absolute symbol target.
                    render_fragment = pending_gate
                    pending_gate = None
                    if i + 2 < n:
                        target = msg_ctrl_break_target(symbols[i + 1], symbols[i + 2])
                        # Live record-2315 trace: msg_ctrl_break consumes the
                        # two descriptor symbols, then sub_846B applies
                        # ``cursor += target - 1``. Projected onto this local
                        # zero-based slice, the next symbol is i+2+target.
                        next_index = i + 2 + target
                        if not render_fragment and next_index > i:
                            i = min(next_index, n)
                            continue
                        i += 3
                        continue
                    i += 1
                    continue
                # ``|X|`` is the dispatcher label-separator pattern (only 4
                # occurrences in MESSAGE, e.g. room 68 ``ze3|a|the secret
                # door closes``). The middle byte is dispatcher metadata,
                # not literal prose -- collapse it into a single line
                # break so the bare ``a`` does not surface as ``A``.
                if (
                    i + 2 < n
                    and 0x00 <= symbols[i + 1] <= 0x19
                    and symbols[i + 2] == 0x1C
                ):
                    out.append("\n")
                    sentence_start = True
                    i += 3
                    continue
                out.append("\n")
                sentence_start = True
                i += 1
                continue
            if sym == 0x1B:  # '^' paragraph break / conditional opcode
                if not expand_conditionals and i + 2 < n:
                    # Native render driver (0D02..0D23): `^` is an
                    # unconditional jump -- sub_846B(msg_ctrl_break(1)) -- with
                    # no special case before a `*` selector. (A former port rule
                    # cleared the output and ran the following selector instead;
                    # it compensated for the parser work set's alias expansion
                    # and swallowed OPEN's success text on scenery.)
                    target = msg_ctrl_break_target(symbols[i + 1], symbols[i + 2])
                    next_index = i + 2 + target
                    if next_index > i:
                        i = min(next_index, n)
                        continue
                # The dispatcher (overlay loc_D0A) calls ``msg_ctrl_break``,
                # which can read either ZERO or ONE+ operand bytes depending
                # on the caller's arg (sub_FF65 vs. the section-state path).
                # Empirically, ``^`` carries a two-symbol opcode operand
                # when both following symbols are non-controls (e.g.
                # ``^ac`` closed-state, ``^a:`` cable-loose-not-descended,
                # ``^if`` plans-readable, ``^ef`` plaque-default). When the
                # next byte is a control (``%``, ``|`` etc.) -- as in READ
                # LETTER's ``^% n`` -- there is no operand and ``^`` is a
                # bare paragraph break.
                op_controls = (0x1C, 0x1F, 0x1B, 0x1E, 0x21, 0x2C, 0x2F, 0x20)
                if (
                    i + 2 < n
                    and symbols[i + 1] not in op_controls
                    and symbols[i + 2] not in op_controls
                ):
                    # Consume ``^`` + 2 operand bytes silently. The
                    # fragment that follows is itself rendered by the
                    # normal loop; ``render_with_conditionals`` can drop
                    # it via the evaluator (see parse_conditional_operands).
                    i += 3
                    continue
                # ``^a`` (2 bytes) when the byte after the operand is a
                # control is the inter-alternative separator pattern used
                # by composites with multiple ``$xxx`` branches (e.g.
                # PLAQUE: ``$ypo ... ^au ... ^a^$ypo ...``). Consume both
                # bytes silently -- the bare ``a`` here is dispatcher
                # metadata, not literal prose.
                if (
                    i + 2 < n
                    and symbols[i + 1] == 0x00  # literal 'a' = the separator opcode
                    and symbols[i + 2] in op_controls
                ):
                    i += 2
                    continue
                out.append("\n")
                sentence_start = True
                i += 1
                continue
            if sym == 0x1E:  # '(' section selector (msg_ctrl_section)
                # Static msg_ctrl_section is only a Pascal-frame wrapper and
                # then jumps directly to sub_EF31. It executes exactly one
                # action opcode beginning at the symbol after `(`. In
                # particular `(@pt` means opcode 53h (`@` + 32h) with wide
                # descriptor `pt`; `@` is not a section-label prefix.
                action_start = i + 1
                consumed = (
                    self.action_executor(tuple(symbols[action_start:]), i)
                    if self.action_executor is not None and action_start < n
                    else None
                )
                if consumed is not None:
                    j = action_start + consumed
                    if self.action_text_reader is not None:
                        # An action that prints (sub_9AFF renders a passage's
                        # own text while it walks through it).
                        injected = self.action_text_reader()
                        if injected:
                            if out and not out[-1].endswith((" ", chr(10))):
                                out.append(" ")
                            out.append(injected)
                    if self.action_output_reader is not None:
                        printed = self.action_output_reader()
                        if printed:
                            if out and not out[-1].endswith(chr(10)):
                                out.append(chr(10))
                            out.append(printed + chr(10))
                    if self.action_gate_reader is not None:
                        # Only for opcodes the VM has confirmed write
                        # byte_4B7B (currently 0x32-0x35); the reader
                        # returns None for anything else, leaving any
                        # existing pending_gate (e.g. from a still-open `$`)
                        # untouched rather than guessing.
                        gate = self.action_gate_reader()
                        if gate is not None:
                            pending_gate = gate
                else:
                    j = action_start + 1
                # An action prints nothing and leaves the casing alone: native
                # "You take the car key and turn off the DB5." (`(liaaaa and`).
                i = j
                continue
            if sym == 0x2C:  # '&' second predicate dispatcher (msg_ctrl_amp)
                # Overlay loc_D8DB: consumes two operand bytes via two
                # ``sub_AE27`` reads (one opcode, one operand-2) then
                # dispatches on the opcode to write byte_4B7B, exactly like
                # msg_ctrl_dollar. When a live evaluator is available, feed
                # the confirmed two-symbol operand into the same pending
                # byte_4B7B/`|` gate used by `$`; otherwise retain the legacy
                # metadata-only skip so unresolved composites never leak
                # operand bytes as prose.
                j = i + 1
                # Opcode ':' (translated native 82h) embeds a second `$`
                # expression: ``&:X$YY|zz``. sub_D4C4 consumes that nested
                # control itself and leaves the cursor on the ordinary pipe
                # render/skip gate. Treating `$YY` as a sibling predicate
                # loses the comparison value and renders unrelated branches.
                if (
                    i + 5 < n
                    and symbols[i + 1] == 0x2B  # ':'
                    and symbols[i + 3] == 0x2C  # nested '&': a second cursor
                    and symbols[i + 5] == 0x1C  # gate pipe
                ):
                    # ``&:X&Y|zz`` -- sub_D4C4 loc_D595 reads Y with
                    # sub_AE27(87h), one symbol, instead of a descriptor.
                    if active_control_evaluator is not None:
                        result = active_control_evaluator(
                            "&", tuple(symbols[i + 1 : i + 5]), i
                        )
                        pending_gate = False if result is None else result
                    i += 5
                    continue
                if (
                    i + 6 < n
                    and symbols[i + 1] == 0x2B  # ':'
                    and symbols[i + 3] == 0x1F  # nested '$'
                    and symbols[i + 6] == 0x1C  # gate pipe
                ):
                    if active_control_evaluator is not None:
                        result = active_control_evaluator(
                            "&", tuple(symbols[i + 1 : i + 6]), i
                        )
                        pending_gate = False if result is None else result
                    i += 6
                    continue
                # Two operand symbols, read whatever they are: msg_ctrl_amp
                # takes both through sub_AE27, exactly like msg_ctrl_eq and
                # msg_ctrl_plus, so an opcode symbol that happens to collide
                # with a top-level control is still an operand. Stopping at
                # those controls dropped every amp whose opcode is one of
                # them -- `&(t` (75h) in TAKE's record 1480 -- and then ran
                # its `(` as an action block, which swallowed the 34h take.
                op_consumed = min(2, n - j)
                j += op_consumed
                if active_control_evaluator is not None and op_consumed == 2:
                    result = active_control_evaluator("&", tuple(symbols[i + 1 : j]), i)
                    if result is not None:
                        pending_gate = result
                # Like the `$` predicate dispatcher, amp substitutions may
                # carry ``|`` plus a two-symbol continuation descriptor
                # after their opcode operands (e.g. ``&'j|pa``).  Those
                # routing bytes must not become visible ``Pa``/``Ai`` text.
                if j < n and symbols[j] == 0x1C and pending_gate is None:
                    j = min(n, j + 3)
                i = j
                continue
            if sym == 0x1F and i + 1 < n and (0x57 + symbols[i + 1]) & 0xFF == 0x7C:
                # `$-<question>@` (loc_CFC4): render the question, print "?"
                # (sub_74E5(3Fh)) and read a yes/no answer into byte_4B7B --
                # QUIT, SAVE and "play again". The run to the closing `@`
                # may hold a caps run (`% quit@`), whose own `@` ends it.
                j = i + 2
                while j < n and symbols[j] != 0x21:
                    # A caps run (`% quit@`) or a capitalised word (`%lsave@`,
                    # Rambo's "Save this game?") ends with its own `@`.
                    if symbols[j] == 0x20 and j + 1 < n and symbols[j + 1] in (0x1A, 0x19):
                        j += 2
                        while j < n and symbols[j] != 0x21:
                            j += 1
                    j += 1
                question = self._render_symbol_list(
                    list(symbols[i + 2:j]),
                    depth=depth,
                    substitutions=substitutions,
                    control_evaluator=active_control_evaluator,
                    sentence_start=False,
                )
                if out and not out[-1].endswith((" ", chr(10))) and question and not question.startswith(" "):
                    out.append(" ")
                # The answer is read on its own prompt line ("-> No."), so
                # what follows starts a new line.
                out.append(question.strip() + "?" + chr(10))
                answer = (
                    self.yes_no_provider(self._print_3dfb("".join(out)))
                    if self.yes_no_provider is not None
                    else False
                )
                pending_gate = bool(answer)
                i = min(j + 1, n)
                continue
            if sym == 0x1F:  # '$' conditional (msg_ctrl_dollar)
                native_end = self._native_dollar_operand_end(symbols, i)
                if native_end is not None and active_control_evaluator is not None:
                    result = active_control_evaluator("$", tuple(symbols[i + 1 : native_end]), i)
                    if result is not None:
                        pending_gate = result
                        i = native_end
                        continue
                # Native handler reads an opcode byte + 0..N operand bytes
                # via sub_AE27, evaluates the state predicate against
                # byte_4B7B-driven node fields, then either renders the
                # following fragment or skips it by calling msg_ctrl_break
                # with skip=1. Without the per-opcode state evaluator
                # (loc_CC86 multi-way switch on the opcode byte) the
                # operand bytes (always metadata, never prose) are always
                # skipped to avoid leaking as literal letters. The fragment
                # is also skipped when ``expand_conditionals=False`` (the
                # native default behaviour: "empty is correct when
                # unresolved"); ``expand_conditionals=True`` keeps the
                # fragment prose so tests/debug paths can verify every
                # branch's content is present in the data.
                # The native dispatcher reads exactly one opcode byte
                # (sub_AE27 with mode 0x57) and per-opcode multi-way
                # dispatches; some opcodes then consume additional operand
                # bytes terminated by '|' (0x1C), others (e.g. 'n' = the
                # distance-status "now" opcode at record 3637 idx 98)
                # take zero operand bytes. Without the per-opcode table
                # ported, the safe rule is: look ahead up to 6 bytes for
                # '|'. If found, all bytes between the opcode and '|' are
                # the operand and '|' is consumed. If not found, the
                # opcode reads zero operand bytes -- consume only the
                # opcode byte itself so we do not eat fragment prose.
                opcode_pos = i + 1
                # ``@`` (0x21) is NOT a probe terminator -- some operand
                # patterns interleave it with ``|`` (e.g. ``$'e@|a!`` in the
                # PUSSY_AUBURN span). Only sibling conditionals (``$``,
                # ``^``), section selectors (``(``) and amp/star/eq controls
                # genuinely end the probe.
                op_terminators = (0x1F, 0x1B, 0x1E, 0x2C)
                # Look for '|' (0x1C) within 6 bytes after the opcode,
                # bailing on any other top-level control (means there is
                # no operand here).
                pipe_at = -1
                probe = opcode_pos + 1
                probe_end = min(n, opcode_pos + 1 + 6)
                while probe < probe_end:
                    if symbols[probe] == 0x1C:
                        pipe_at = probe
                        break
                    if symbols[probe] in op_terminators:
                        break
                    probe += 1
                if pipe_at >= 0:
                    # The native stream carries a two-symbol continuation
                    # descriptor immediately after the ``|`` operand
                    # terminator.  It is dispatcher metadata, not prose.
                    # Examples in the original MESSAGE data are
                    # ``$#e|bz`` before the Scenic Lookout description and
                    # ``$;al|a5`` before "one end of the cable ...".  Letting
                    # those two symbols reach the text loop produced the
                    # visible artefacts ``bz``/``A5``/``Tpp4``.
                    j = min(n, pipe_at + 3)
                else:
                    # No '|' visible -> the data does not encode an
                    # opcode/operand here for this '$'; consume only the
                    # '$' marker itself so the next byte renders as
                    # fragment prose. Confirmed by record 3637 idx 98
                    # ("$now has lost ground." -- the 'n' is prose, not
                    # an opcode).
                    j = opcode_pos  # past '$' only
                if expand_conditionals:
                    # Keep the fragment prose; just advance past the
                    # operand and fall through to normal rendering.
                    i = j
                    continue
                # Skip the fragment text until the next conditional or
                # section marker. A sibling ``$``, a ``^XX`` conditional
                # (where XX are both non-controls) and ``(`` end the
                # fragment. A bare ``^`` followed by a control symbol
                # (e.g. READ LETTER's ``^% n``) is a paragraph break that
                # CAN appear inside a fragment, so we only stop on `^`
                # when it looks like a conditional opcode.
                op_controls_set = (0x1C, 0x1F, 0x1B, 0x1E, 0x21, 0x2C, 0x2F, 0x20)
                while j < n:
                    s = symbols[j]
                    if s == 0x1F or s == 0x1E:
                        break
                    if (
                        s == 0x1B
                        and j + 2 < n
                        and symbols[j + 1] not in op_controls_set
                        and symbols[j + 2] not in op_controls_set
                    ):
                        break
                    j += 1
                i = j
                continue
            if (
                sym == 0x1D
                and not expand_conditionals
                and (
                    depth > 0
                    or self.star_candidate_matcher is not None
                    or self.star_mode0_index_provider is not None
                )
            ):
                # ``msg_ctrl_star`` (overlay 06E1..0C91) can occur at any
                # cursor position. It is an N-candidate selector, not a
                # two-symbol side effect. A common use is a record-leading
                # object-name/pronoun dictionary record, but composite verb
                # records also embed the complete selector mid-stream.
                # The record is N
                # ``@``-separated candidate segments and the native routine
                # renders exactly ONE (the index is computed per mode 0..3 --
                # mode 0 = ``word_6AB mod N`` counter, modes 1..3 = a state/
                # object value via sub_AE9E/word_1DE5). Confirmed shape in the
                # object-name records 339/348 (``*ttt a@tbam@aaai%t@``,
                # ``*tti adamare@tpamare@elamare@aaaiis@``), reached from every
                # composite verb response via the object-name dict record 370.
                mode = star_control_mode(symbols[i + 1]) if i + 1 < n else None
                cursor = i + 2
                operand: int | None = None
                if mode == 3 and cursor < n:
                    operand = symbols[cursor]
                    cursor += 1
                if mode is not None and cursor + 2 < n:
                    candidate_count = symbols[cursor]
                    end_distance = msg_ctrl_break_target(
                        symbols[cursor + 1], symbols[cursor + 2]
                    )
                    cursor += 3  # count plus the two-symbol end cursor
                    # word_1DE3 is the native one-based record cursor; the
                    # saved end position therefore projects one slot earlier
                    # into this zero-based symbol list.
                    raw_selector_end = cursor + end_distance - 1
                    selector_end = min(n, raw_selector_end)
                    candidate_scan_start = cursor
                    selected_ordinal = (
                        self.star_mode0_index_provider(candidate_count)
                        if mode == 0 and self.star_mode0_index_provider is not None
                        else None
                    )
                    selected: str | None = None
                    # Whether a candidate was chosen is tracked apart from what
                    # it rendered: many candidate bodies are action-only and
                    # render no text at all -- record 2315's room->door table
                    # is 17 bodies like `(@aj` (action 53h: the scenery cursor
                    # becomes the barn door). Treating such a "" as "nothing
                    # matched" sent the renderer into the nested-star fallback
                    # below, which scans the candidate list for a 1Dh byte --
                    # and a candidate *descriptor* can contain one (`a*` = 29,
                    # "chateau roof"). That byte was then run as a phantom
                    # mode-0 selector, which picked a body by turn counter and
                    # executed another room's door action.
                    matched_any = False
                    for ordinal in range(candidate_count):
                        # Every candidate carries its own skip distance, and
                        # the native loop (msg_ctrl_star 0812..0C3B) steps to
                        # the next candidate with sub_846B(msg_ctrl_break(1))
                        # -- it never scans for a delimiter. Layout, checked
                        # against the selector's end cursor over all of
                        # MESSAGE (the skip chain lands on it exactly):
                        #   modes 1..3: descriptor(2) skip(2) body  -- 6306 stars
                        #   mode 0:                   skip(2) body  --  960 stars
                        # (mode 0 picks by word_6AB mod count and reads no
                        # descriptor). The old `@`-scan agreed on simple bodies
                        # but went wrong on 3072 of those selectors, wherever a
                        # body holds an `@` that is not a delimiter -- `%d@`
                        # capitalisation, `(@xx` actions -- after which every
                        # later descriptor was read from the wrong place.
                        if mode == 0:
                            if cursor + 1 >= n:
                                break
                            descriptor = None
                            skip = msg_ctrl_break_target(
                                symbols[cursor], symbols[cursor + 1]
                            )
                            cursor += 2
                        else:
                            if cursor + 3 >= n:
                                break
                            descriptor = msg_ctrl_break_target(
                                symbols[cursor], symbols[cursor + 1]
                            )
                            # The two sub_837B calls before msg_render_driver
                            # consume exactly these two skip symbols.
                            skip = msg_ctrl_break_target(
                                symbols[cursor + 2], symbols[cursor + 3]
                            )
                            cursor += 4
                        # sub_846B applies `cursor += skip - 1` from the
                        # symbol after the skip field.
                        end = min(max(cursor + skip - 1, cursor), n)
                        matched = (
                            ordinal == selected_ordinal
                            if selected_ordinal is not None
                            else descriptor == 0
                        )
                        if (
                            not matched
                            and descriptor is not None
                            and self.star_candidate_matcher is not None
                        ):
                            matched = self.star_candidate_matcher(
                                mode, operand, descriptor
                            ) is True
                        if matched:
                            matched_any = True
                            selected = self._render_symbol_list(
                                symbols[cursor:end],
                                depth=depth,
                                substitutions=substitutions,
                                expand_conditionals=expand_conditionals,
                                control_evaluator=active_control_evaluator,
                                dict_expand_hook=dict_expand_hook,
                                symbol_origin=0,
                                # The selected candidate continues the same
                                # output stream, so it inherits the casing
                                # context -- a candidate body is not a new
                                # sentence just because it is a new span.
                                sentence_start=(
                                    sentence_start
                                    if not "".join(out).rstrip()
                                    else "".join(out).rstrip().endswith((".", "!", "?"))
                                ),
                                capitalize_next=capitalize_next,
                            )
                            # A body that opens with a space continues the
                            # parent's word run ("Tilly" + " relaxes"); the
                            # isolated render drops leading blanks.
                            if (
                                selected
                                and cursor < n
                                and symbols[cursor] == 0x1A
                                and not selected.startswith((" ", chr(10)))
                            ):
                                selected = " " + selected
                            break
                        cursor = end
                    if matched_any:
                        if selected:
                            if out and out[-1].endswith(" ") and selected.startswith(" "):
                                selected = selected.lstrip(" ")
                            out.append(selected)
                            sentence_start = selected.rstrip().endswith((".", "!", "?", "\n"))
                        # sub_846B: the render goes on at the selector's end
                        # ("You can't while they're" + " in the desk.").
                        i = selector_end
                    elif raw_selector_end > n and candidate_scan_start < n:
                        # (Only past the end: High Stakes' record 2736 ends
                        # exactly at its last selector's end, and scanning on
                        # ran the `*` of a candidate's `$*ac` as a selector.)
                        # The end marker projects past this record (composite
                        # verb responses embed nested ``*`` selectors inside a
                        # candidate body). Skip the non-matching candidate prose
                        # and resume at the first nested star (record 2508 PUT).
                        nested_star: int | None = None
                        scan = candidate_scan_start
                        while scan < n:
                            nested_mode = (
                                star_control_mode(symbols[scan + 1])
                                if scan + 1 < n
                                else None
                            )
                            if symbols[scan] == 0x1D and nested_mode is not None:
                                nested_star = scan
                                break
                            scan += 1
                        i = nested_star if nested_star is not None else min(cursor, n)
                    else:
                        # No candidate matched: the native routine still ends
                        # by moving the cursor to the selector's end
                        # (0C6F..0C88), not to wherever the scan stopped.
                        i = min(selector_end, n)
                    continue
            if sym in (0x1D, 0x2D, 0x2E):  # '*', '=', '+' opcode controls
                # All three (msg_ctrl_star, msg_ctrl_eq, msg_ctrl_plus in the
                # overlay) read an opcode byte via sub_AE27 plus a following
                # operand byte. Their effects are state changes; only the
                # ``=h`` list prints text (through control_text_evaluator).
                # The star form that reaches here (no candidate mode) still
                # stops at top-level controls.
                j = i + 1
                if sym in (0x2D, 0x2E):
                    # msg_ctrl_eq and msg_ctrl_plus (sub_F5F9) read both
                    # operands with sub_AE27, which takes the next raw symbol
                    # whatever it is: ``+@j`` is opcode 53h ('@' + 32h) on
                    # cursor 92h ('j' + 87h), not "opcode + prose J".
                    j = min(i + 3, n)
                    if sym == 0x2E and i + 1 < n and symbols[i + 1] == 0x20 and j < n:
                        # `+%<cursor>` is 52h, the walk: sub_B9E5 reads the
                        # destination behind it -- `%` + a two-symbol
                        # descriptor or `=` + a room cursor (`+%x=j`).
                        if symbols[j] == 0x20:
                            j = min(j + 3, n)
                        elif symbols[j] == 0x2D:
                            j = min(j + 2, n)
                else:
                    op_controls = (0x1C, 0x1F, 0x1B, 0x1E, 0x21, 0x2C, 0x2F, 0x20)
                    op_consumed = 0
                    while j < n and op_consumed < 2 and symbols[j] not in op_controls:
                        j += 1
                        op_consumed += 1
                if active_control_evaluator is not None:
                    control_char = {0x1D: "*", 0x2D: "=", 0x2E: "+"}[sym]
                    result = active_control_evaluator(control_char, tuple(symbols[i + 1 : j]), i)
                    if result is not None:
                        pending_gate = result
                    if self.control_text_evaluator is not None:
                        injected = self.control_text_evaluator(
                            control_char, tuple(symbols[i + 1 : j]), i
                        )
                        if injected:
                            if out and not out[-1].endswith(" "):
                                out.append(" ")
                            out.append(injected)
                            sentence_start = False
                            pending_gate = True
                i = j
                continue
            char = chr(self.translation_table[sym])
            if char in CONTROL_CHARS:
                # Untraced control: skip rather than emit a raw glyph.
                i += 1
                continue
            if char.isalpha():
                # Native sub_3DFB inserts a break after sentence/clause
                # punctuation -- ``render_run`` already applies this for
                # literal-only runs. Mirror it here so the main renderer
                # produces the same spacing (e.g. "fast.You" -> "fast. You").
                if out and out[-1].endswith(tuple(".!?,:;")):
                    out.append(" ")
                if capitalize_next:
                    char = char.upper()
                    capitalize_next = False
                sentence_start = False
            elif char.isdigit():
                # A word that opens with a digit has started: the printer
                # (3DFB) capitalises a word's first letter only when the word
                # begins with it -- A View to a Kill's "003's body lies ...".
                sentence_start = False
            elif char in ".!?:":
                # The native printer also capitalises after a colon ("an
                # astonishing sight: A helicopter", "reads: Most improved").
                sentence_start = True
            if char == " " and (not out or out[-1].endswith((" ", "\n"))):
                # Collapse repeated blanks and never emit a leading space:
                # a segment/action-block boundary can leave the operand's
                # separator space at the very start of the (sub)render.
                i += 1
                continue
            out.append(char)
            i += 1
        text = "".join(out)
        # Controls and dictionary substitutions can divide a sentence into
        # separate output fragments.  The native printer inserts the normal
        # inter-word blank after a comma even when that boundary coincides
        # with such a fragment (for example ``pilot, Miss`` and
        # ``helicopter, it``).
        return re.sub(r",(?=[A-Za-z])", ", ", text)

    # Padding-and-label structure observed at room ``+2`` positions in the
    # depaged stream: each room's ``+2`` lands inside a composite message record
    # whose segments are framed as
    # ``<prev_segment_tail>.@@@@<label_1_or_2><room_prose>@@@@<next_label>...``.
    # The ``@`` (0x21) sym is the confirmed segment terminator (GAME.COM:4ED7
    # treats 0x40 as control), and three-plus consecutive ``@``s mark the gap
    # between adjacent segments. After the gap, 1-2 literal symbols form a
    # short section label (e.g. ``q'``, ``p%``, ``id``, ``t?``) that the native
    # dispatcher uses for ``(``-style selection; without the trace of *which*
    # label a given room asks for, this scanner picks the FIRST segment after
    # the gap, which is correct for rooms whose ``+2`` is followed by their own
    # segment and incorrect for rooms that share a composite with siblings.
    # See ``render_room_segment``.
    # Adjacent room/section payloads are separated by two or more ``@``
    # symbols.  Runs of three are common, but the mansion/field composite
    # uses ``@@<label>``; requiring three concatenated several independent
    # room descriptions into one response.
    ROOM_GAP_THRESHOLD = 2
    ROOM_LABEL_MAX = 2

    def render_room_segment(
        self,
        msg_off: int,
        max_symbols: int = 5000,
        substitutions: "dict[str, str] | None" = None,
    ) -> str:
        """Render the room-description segment at depaged ``msg_off`` position.

        This is a partial port of the move/look text-emit pipeline
        (``turn_resolve_text`` -> ``msg_emit_response``).
        The dispatcher's per-room section selection rule is not yet traced --
        this implements the simplest data-driven structural rule that matches
        the segment framing observed in the message stream:

          1. Seek to depaged symbol position ``msg_off * 8``.
          2. Scan forward past everything up to and including the first run of
             ``ROOM_GAP_THRESHOLD``+ consecutive ``@`` segment terminators
             (the gap between the previous segment and this room's segment).
          3. Skip up to ``ROOM_LABEL_MAX`` non-control literal symbols (the
             section label the dispatcher would have matched against state).
          4. Render the symbols that follow through the full control dispatcher
             (``%`` capitalize, ``@`` skip, ``|`` line-break, ``\\`` expand)
             until the next ``ROOM_GAP_THRESHOLD``+ ``@`` run, an untraced
             control symbol, or ``max_symbols`` is reached.

        For rooms whose ``+2`` lands within a composite with multiple sibling
        segments, this returns the FIRST sibling's prose rather than the
        specific room's -- a known limitation until the dispatcher's section
        selector is ported. Returns ``""`` when no segment gap is found.
        """

        if msg_off <= 0:
            return ""
        syms = self.dict_symbols
        i = msg_off * 8
        n = len(syms)
        end = min(n, i + max_symbols)

        i = self._skip_to_after_gap(syms, i, end)
        if i is None:
            return ""
        i = self._skip_section_label(syms, i, end)
        text = self._render_segment_until_gap(
            syms, i, end, substitutions=substitutions, full_controls=True
        )
        if text.strip():
            return text

        # Some native room references point into the selected payload rather
        # than before its opening gap.  In that case the next gap can be an
        # empty routing section.  Recover the containing section by locating
        # the nearest preceding @@@ boundary and rendering forward from it.
        pointer = msg_off * 8
        scan_start = max(0, pointer - max_symbols)
        previous_after: int | None = None
        j = scan_start
        while j < pointer:
            if syms[j] == 0x21:
                run_start = j
                while j < pointer and syms[j] == 0x21:
                    j += 1
                if j - run_start >= self.ROOM_GAP_THRESHOLD:
                    previous_after = j
            else:
                j += 1
        if previous_after is None:
            return ""
        previous_body = self._skip_section_label(syms, previous_after, end)
        return self._render_segment_until_gap(
            syms, previous_body, end, substitutions=substitutions,
            full_controls=True,
        )

    @classmethod
    def _skip_to_after_gap(cls, syms: list[int], start: int, end: int) -> int | None:
        i = start
        while i < end:
            if syms[i] == 0x21:  # '@' terminator
                run_start = i
                while i < end and syms[i] == 0x21:
                    i += 1
                if i - run_start >= cls.ROOM_GAP_THRESHOLD:
                    return i
            else:
                i += 1
        return None

    @classmethod
    def _skip_section_label(cls, syms: list[int], start: int, end: int) -> int:
        """Skip up to ROOM_LABEL_MAX literal symbols that form the section label.

        The label ends when a known control symbol is reached (``%`` ``|`` ``\\``
        ``(`` ``^``), since those start the section's actual rendering directives.
        """
        i = start
        skipped = 0
        controls = {0x21, 0x20, 0x1C, 0x2F, 0x1E, 0x1B, 0x1F, 0x2C, 0x1D, 0x2D, 0x2E}
        while i < end and skipped < cls.ROOM_LABEL_MAX and syms[i] not in controls:
            i += 1
            skipped += 1
        return i

    def render_symbol_segment(
        self,
        start: int,
        max_symbols: int = 900,
        substitutions: "dict[str, str] | None" = None,
    ) -> str:
        """Render a bounded MESSAGE symbol segment from an observed start.

        Some GAME.000 action responses are not standalone length-prefixed
        records; live/static tracing locates their symbol start inside a
        composite record. This helper renders from that exact symbol offset
        using the same safe segment renderer as room descriptions: stop at the
        next section gap or untraced control rather than emitting raw controls.
        """

        if start < 0:
            return ""
        end = min(len(self.dict_symbols), start + max_symbols)
        return self._render_segment_until_gap(
            self.dict_symbols, start, end, substitutions=substitutions
        )

    def render_symbol_span(
        self,
        start: int,
        length: int,
        substitutions: "dict[str, str] | None" = None,
    ) -> str:
        """Render an exact MESSAGE symbol span through the normal renderer.

        Unlike ``render_symbol_segment``, this does not stop at untraced
        condition controls. It is for trace/static-confirmed spans where
        the caller has located the exact prose start/end (e.g. a recovered
        verb-response symbol offset) and wants every byte in the span
        rendered, including any '$' fragments inside it -- so this passes
        ``expand_conditionals=True`` to ``_render_symbol_list``. Operand
        metadata (the bytes after '$'/'&' and the label after '(') is
        still skipped so it does not leak as literal letters.
        """

        if start < 0 or length <= 0:
            return ""
        end = min(len(self.dict_symbols), start + length)
        return self._render_symbol_list(
            self.dict_symbols[start:end],
            substitutions=substitutions,
            expand_conditionals=True,
        )

    def _render_segment_until_gap(
        self,
        syms: list[int],
        start: int,
        end: int,
        substitutions: "dict[str, str] | None" = None,
        full_controls: bool = False,
    ) -> str:
        """Render one framed segment through the shared control dispatcher.

        Earlier this routine duplicated only the primitive ``% @ | \\``
        cases and aborted on ``&``, ``$``, ``^`` and ``(``.  Those controls
        are normal in room descriptions, so valid rooms became empty or were
        truncated at their first predicate.  Locate the structural ``@@@``
        boundary here, then let ``_render_symbol_list`` consume all confirmed
        operand shapes consistently with ordinary MESSAGE records.
        """
        segment_end = end
        i = start
        while i < end:
            if syms[i] == 0x21:
                j = i
                while j < end and syms[j] == 0x21:
                    j += 1
                if j - i >= self.ROOM_GAP_THRESHOLD:
                    segment_end = i
                    break
                i = j
                continue
            i += 1
        if full_controls:
            return self._render_symbol_list(
                syms[start:segment_end], substitutions=substitutions
            )

        # Exact action-symbol segments retain the conservative historical
        # behaviour: stop at an unresolved control instead of spilling into
        # the neighbouring action branch.
        out: list[str] = []
        capitalize_next = False
        sentence_start = True
        i = start
        untraced = {0x1B, 0x1D, 0x1E, 0x1F, 0x2C, 0x2D, 0x2E}  # ^ * ( $ & = +
        while i < end:
            sym = syms[i]
            if sym == 0x21:  # '@'
                run_start = i
                j = i
                while j < end and syms[j] == 0x21:
                    j += 1
                if j - run_start >= self.ROOM_GAP_THRESHOLD:
                    break  # next section
                i = j  # single/double @: just skip as segment terminator
                continue
            if sym in untraced:
                break  # untraced control: stop rather than emit raw glyph
            if sym in UNMAPPED_TEMPLATE_SYMBOLS:
                break
            if sym == 0x2F:  # '\\' word-dictionary expansion
                if i + 3 < end:
                    index = syms[i + 1] * 4096 + syms[i + 2] * 64 + syms[i + 3]
                    if 0 <= index * 8 + 2 <= len(self.dict_symbols):
                        word = self.render_message_record(
                            index, substitutions=substitutions
                        )
                        if word and capitalize_next and word[0].isalpha():
                            word = word[0].upper() + word[1:]
                            capitalize_next = False
                        if any(c.isalpha() for c in word):
                            sentence_start = False
                        out.append(word)
                i += 4
                continue
            if sym == 0x20:  # '%' capitalize next
                if (
                    substitutions
                    and i + 1 < end
                    and syms[i + 1] != 0x1A
                ):
                    key = chr(self.translation_table[syms[i + 1]]).lower()
                    if key in substitutions:
                        value = substitutions[key]
                        if value and capitalize_next and value[0].isalpha():
                            value = value[0].upper() + value[1:]
                        out.append(value)
                        if any(c.isalpha() for c in value):
                            sentence_start = False
                        capitalize_next = False
                        i += 2
                        continue
                capitalize_next = True
                if (
                    i + 2 < end
                    and syms[i + 2] == 0x21
                    and substitutions
                ):
                    key = chr(self.translation_table[syms[i + 1]]).lower()
                    if key in substitutions:
                        value = substitutions[key]
                        if value and capitalize_next and value[0].isalpha():
                            value = value[0].upper() + value[1:]
                        out.append(value)
                        sentence_start = False
                        capitalize_next = False
                        i += 3
                        continue
                if i + 1 < end and syms[i + 1] == 0x1A:
                    i += 1
                i += 1
                continue
            if sym == 0x1C:  # '|' line break
                out.append("\n")
                sentence_start = True
                i += 1
                continue
            char = chr(self.translation_table[sym])
            if char in CONTROL_CHARS:
                break
            if char.isalpha():
                if capitalize_next:
                    char = char.upper()
                capitalize_next = False
                sentence_start = False
            elif char.isdigit():
                # A word that opens with a digit has started: the printer
                # (3DFB) capitalises a word's first letter only when the word
                # begins with it -- A View to a Kill's "003's body lies ...".
                sentence_start = False
            elif char in ".!?:":
                # The native printer also capitalises after a colon ("an
                # astonishing sight: A helicopter", "reads: Most improved").
                sentence_start = True
            out.append(char)
            i += 1
        text = "".join(out).strip()
        return re.sub(r",(?=[A-Za-z])", ", ", text)
