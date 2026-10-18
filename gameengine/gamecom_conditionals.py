"""GameComMessageEngine: $/^ conditionals, multi-fragment records and section spans."""

from __future__ import annotations

import re
from typing import Callable
from .message import DEFAULT_SYMBOL_TABLE
from .message_controls import (
    DOLLAR_TWO_SYMBOL_SELECTORS,
    DOLLAR_FGI_SELECTORS,
    DOLLAR_ONE_SYMBOL_SELECTORS,
    DOLLAR_ZERO_SYMBOL_SELECTORS,
    DOLLAR_V_SELECTOR,
    msg_ctrl_break_target,
    ConditionalSpan,
)


class ConditionalMixin:
    """Parsing and rendering conditional spans and multi-fragment records."""

    # Raw 0x1B ('^') is a native paragraph break. Raw 0x1F ('$') enters
    # msg_ctrl_dollar, the state-test dispatcher (overlay asm 32303/32724).
    _COND_CTRL_HAT = 0x1B
    _COND_CTRL_DOLLAR = 0x1F
    _COND_CTRL_AMP = 0x2C

    @classmethod
    def _native_dollar_operand_end(cls, symbols: "list[int]", pos: int) -> "int | None":
        """Return exact `$` operand end for confirmed native opcode classes.

        ``pos`` points at the dollar control.  The returned index is just past
        the opcode operand.  The following ``|xx`` descriptor is deliberately
        left to the renderer's gate handling; consuming it here globally is
        not safe for exact traced spans that include literal/gated fragments.
        Unknown opcodes return ``None`` so callers can retain conservative
        legacy scanning.
        """

        opcode_pos = pos + 1
        if opcode_pos >= len(symbols):
            return opcode_pos
        selector = 0x57 + symbols[opcode_pos]
        end = opcode_pos + 1
        if selector in (0x57, 0x58, 0x59):
            # loc_C9F4 reads two BF0D value sources. A non-zero source is one
            # BBC3 field selector; zero introduces a three-symbol literal.
            for _ in range(2):
                if end >= len(symbols):
                    return None
                if symbols[end] == 0:
                    if end + 3 >= len(symbols):
                        return None
                    end += 4
                else:
                    end += 1
            return end
        if selector in DOLLAR_TWO_SYMBOL_SELECTORS:
            if end + 1 >= len(symbols):
                return None
            return end + 2
        if selector in DOLLAR_ONE_SYMBOL_SELECTORS:
            if end >= len(symbols):
                return None
            return end + 1
        if selector in DOLLAR_ZERO_SYMBOL_SELECTORS:
            return end
        if selector == DOLLAR_V_SELECTOR:
            # loc_CF0A: sub_AE63 reads a two-symbol descriptor through
            # msg_ctrl_break(1), whatever the symbols are -- ``$$a@`` is the
            # club (node 33), ``$$aq`` the badge (node 8).
            if end + 1 >= len(symbols):
                return None
            return end + 2
        if selector in DOLLAR_FGI_SELECTORS:
            # sub_469C(0Eh) reads the two-symbol descriptor raw, whatever the
            # symbols are: The Mist's notebook record has `$ge(` (node 158),
            # whose `(` is part of the descriptor, not an action block.
            if end + 1 >= len(symbols):
                return None
            return end + 2
        # selector 74h (`$*`) enters loc_CB3B.  Its first operation is
        # sub_9711, i.e. the same two-symbol VOCAB descriptor reader used by
        # the other resolved predicates.  Treating `*` as a zero-operand
        # opcode left the descriptor visible to the prose renderer and made
        # every following effect branch run.
        if selector == 0x74:
            if end + 1 >= len(symbols):
                return None
            return end + 2
        return end

    @classmethod
    def parse_conditional_operands(cls, symbols: "list[int]") -> "list[tuple[str, int, str, int, int]]":
        """Walk a record's symbol stream and extract native test spans.

        Returns a list of tuples ``(kind, pos, operand, op_end, frag_end)``
        where:

        * ``kind`` is ``'$'``/``'&'`` for the two predicate dispatchers, or
          ``'^'`` for ``^ a opcode`` conditionals (the EXAMINE-record
          trailing predicates such as ``^ac`` "is closed").
        * ``pos`` is the symbol index of the control marker
        * ``operand`` is the decoded ASCII string the operand reads as
          (parsed up to the next control symbol or 8 chars max)
        * ``op_end`` is the symbol index just past the operand
        * ``frag_end`` is the symbol index where the fragment ends (next
          control / segment terminator)

        This helper locates candidate spans; the decoded text is not a native
        operand language. Bare ``^`` (paragraph break) is excluded -- only
        ``^`` followed by symbol ``0x00`` (literal ``a``) is treated as a
        conditional, matching the EXAMINE-data convention.
        """

        # Operand terminators: any of these end the opcode/operand scan.
        op_terminators = frozenset({
            cls._COND_CTRL_HAT, cls._COND_CTRL_DOLLAR, cls._COND_CTRL_AMP,
            0x21,    # @ segment terminator
            0x1C,    # | line break
            0x1E,    # ( section selector
            0x1D,    # * (untraced)
            0x2C,    # & (substitution)
            0x2F,    # \ dictionary expand
            0x20,    # % capitalize
        })
        # Fragment terminators: only the structural delimiters that mark
        # the END of a conditional fragment. Inline prose controls (``%``,
        # ``\\``, ``&``, ``|``) belong INSIDE a fragment and must not end
        # it -- e.g. the DEVICE EXAMINE fragment "the interior of %t is..."
        # contains ``%t``; capping at ``%`` would truncate to "the interior
        # of " and miss the rest.
        frag_terminators = frozenset({
            cls._COND_CTRL_HAT, cls._COND_CTRL_DOLLAR, cls._COND_CTRL_AMP,
            0x21,    # @ segment terminator
            0x1E,    # ( section selector
        })
        max_operand = 8
        results: list[tuple[str, int, str, int, int]] = []
        n = len(symbols)
        i = 0
        while i < n:
            s = symbols[i]
            if s == cls._COND_CTRL_AMP:
                # msg_ctrl_amp reads exactly two symbols: opcode (mode 57h)
                # and its already-resolved operand (mode 87h). It writes the
                # same byte_4B7B predicate result as msg_ctrl_dollar.
                pos = i
                j = i + 1
                op_chars: list[str] = []
                while j < n and len(op_chars) < 2 and symbols[j] not in op_terminators:
                    op_chars.append(DEFAULT_SYMBOL_TABLE.get(symbols[j], "?"))
                    j += 1
                if len(op_chars) != 2:
                    i += 1
                    continue
                frag_start = j
                if frag_start < n and symbols[frag_start] == 0x1C:
                    frag_start = min(n, frag_start + 3)
                k = frag_start
                while k < n and symbols[k] not in frag_terminators:
                    k += 1
                results.append(("&", pos, "".join(op_chars), j, k))
                i = j
                continue
            if s == cls._COND_CTRL_DOLLAR:
                kind = "$"
                pos = i
                j = i + 1
                op_chars: list[str] = []
                while j < n and len(op_chars) < max_operand and symbols[j] not in op_terminators:
                    ch = DEFAULT_SYMBOL_TABLE.get(symbols[j], "?")
                    op_chars.append(ch)
                    j += 1
                op_end = j
                # If the operand is followed by ``|`` plus a 2-symbol
                # continuation descriptor, skip past them so the fragment
                # starts at the actual prose.
                frag_start = op_end
                if frag_start < n and symbols[frag_start] == 0x1C:  # '|'
                    frag_start = min(n, frag_start + 3)
                k = frag_start
                while k < n and symbols[k] not in frag_terminators:
                    k += 1
                results.append((kind, pos, "".join(op_chars), op_end, k))
                i = op_end
                continue
            if s == cls._COND_CTRL_HAT:
                # ``^`` is a conditional when followed by two non-control
                # symbols (e.g. ``^ac`` closed-state, ``^a:`` cable-loose,
                # ``^if`` plans-readable, ``^ef`` plaque-default). A bare
                # ``^`` followed by a control symbol (``%``, ``|``) is the
                # paragraph break used by ordinary prose records and is
                # NOT a predicate.
                if (
                    i + 2 < n
                    and symbols[i + 1] not in op_terminators
                    and symbols[i + 2] not in op_terminators
                ):
                    kind = "^"
                    pos = i
                    op_chars = (
                        DEFAULT_SYMBOL_TABLE.get(symbols[i + 1], "?")
                        + DEFAULT_SYMBOL_TABLE.get(symbols[i + 2], "?")
                    )
                    op_end = i + 3
                    k = op_end
                    while k < n and symbols[k] not in frag_terminators:
                        k += 1
                    results.append((kind, pos, op_chars, op_end, k))
                    i = op_end
                    continue
                i += 1
                continue
            i += 1
        return results

    def render_with_conditionals(
        self,
        record_index: int,
        evaluator: "Callable[[str, str], bool]",
        substitutions: "dict[str, str] | None" = None,
    ) -> str:
        """Render a MESSAGE record with the legacy `$` span evaluator applied.

        ``evaluator(kind, operand)`` returns ``True`` to KEEP the
        following fragment, ``False`` to SKIP it. ``kind`` is ``'^'`` or
        ``'$'``; ``operand`` is the decoded ASCII operand (1-8 chars).

        Skipped fragments are dropped from the symbol stream before the
        normal symbol renderer runs. With ``evaluator = lambda k, o: True``
        the output is the same as ``render_message_record`` (all fragments
        included). With ``evaluator = lambda k, o: False`` all conditional
        fragments are removed, leaving only the unconditional prose.

        This is a STRUCTURAL prototype -- the operand semantics (which
        state-bit each operand tests) are caller-defined. When the
        chase-state model is built, the chase verb handlers pass an
        evaluator that maps operands like ``p1``/``pjb``/``ay`` to the
        appropriate Mercedes-distance/phase tests.
        """

        return self.render_with_conditional_spans(
            record_index,
            lambda span: evaluator(span.kind, span.operand),
            substitutions=substitutions,
        )

    def render_with_conditional_spans(
        self,
        record_index: int,
        evaluator: "Callable[[ConditionalSpan], bool]",
        substitutions: "dict[str, str] | None" = None,
        _depth: int = 0,
        _cache: "dict[int, str] | None" = None,
        _in_progress: "set[int] | None" = None,
    ) -> str:
        """Render a MESSAGE record using detailed conditional span metadata.

        The evaluator's keep/drop decision is applied recursively to every
        ``\\`` dictionary-referenced record too (via ``dict_expand_hook``),
        not just ``record_index``'s own top-level spans. Without this, a
        large composite record that references other composite records
        (common for the multi-object verb-response records) would render
        every branch of every nested record unconditionally, producing a
        combinatorial explosion instead of the intended single resolved
        fragment. ``_depth`` caps that recursion (matching the existing
        dictionary-expansion depth cap in ``_render_symbol_list``) so a
        cyclic or very deep dictionary chain cannot recurse unboundedly.

        ``_cache`` memoizes a rendered dictionary record's text for the
        duration of one top-level call. Common short phrases (e.g. "the
        table keyboard") are referenced from dozens of sibling ``$``
        branches within the same composite record, and re-filtering the
        same referenced record from scratch every time is what actually
        made this combinatorially expensive, not genuine content diversity.
        The one known tradeoff: an ``(`` action block nested inside a
        dictionary record fires only on the first reference, not once per
        repeated reference, since a cache hit skips re-rendering. Dictionary
        entries are overwhelmingly short reusable noun phrases without
        embedded action blocks, so this is considered an acceptable,
        documented limitation rather than a silent correctness bug.

        ``_in_progress`` breaks genuine reference cycles (a dictionary
        record whose own expansion, directly or transitively, references
        itself again). ``_cache`` alone cannot help here: the cycle is hit
        again *before* the first traversal finishes and writes a cache
        entry, so every occurrence would re-descend the whole subtree until
        the depth cap -- exponential cost for a self-reference that has no
        single well-defined resolved branch anyway. A record already on the
        current call stack instead falls back to the plain unfiltered
        rendering for that one occurrence.
        """

        if _cache is None:
            _cache = {}
        if _in_progress is None:
            _in_progress = set()
        if record_index in _cache:
            return _cache[record_index]
        if record_index in _in_progress:
            # A record that (directly or transitively) references itself has
            # no single well-defined resolved branch. Re-rendering it here
            # even through the old unfiltered path is not just semantically
            # incoherent, it is also expensive: that path resets its own
            # depth counter to 0 on every fallback entry, so a record with
            # several distinct cyclic references would re-run a fresh
            # bounded-but-costly expansion at each one. Per the project's
            # "empty is correct, gibberish is not" rule, the safe and cheap
            # answer for an unresolvable self-reference is no text.
            return ""
        if _depth == 0 and self.record_open_callback is not None:
            self.record_open_callback()
        symbols = self.record_symbols(record_index)
        conds = self.parse_conditional_spans(symbols)
        n_sym = len(symbols)
        # Build a set of symbol indices to drop (control marker + operand
        # + fragment) for each conditional that evaluates False.
        drop_ranges: list[tuple[int, int]] = []
        for span in conds:
            if evaluator(span):
                continue
            end = span.frag_end
            # If the dropped fragment is immediately followed by the
            # composite-alternative separator ``@|<label>:`` (e.g. PLAQUE
            # uses ``$ya@|a:$ypo...`` to gate one alternative behind a
            # short label), extend the drop range to include that label
            # so it does not surface as visible ``\nA:`` prose.
            probe = end
            if probe < n_sym and symbols[probe] == 0x21:  # '@'
                probe += 1
            if probe < n_sym and symbols[probe] == 0x1C:  # '|'
                probe += 1
                label_start = probe
                # Walk literal letters (sym 0x00..0x19) up to 4 chars
                while (
                    probe < n_sym
                    and 0x00 <= symbols[probe] <= 0x19
                    and probe - label_start < 4
                ):
                    probe += 1
                if probe < n_sym and symbols[probe] == 0x2B:  # ':'
                    end = probe + 1
            drop_ranges.append((span.pos, end))
        # Render the (optionally filtered) symbol list with the conditional
        # gate handlers DISABLED -- the caller has already made the keep/skip
        # decision for every '$' span via the evaluator, so the renderer must
        # not second-guess by also skipping unconditional spans.
        dict_expand_hook = (
            (lambda index: self.render_with_conditional_spans(
                index, evaluator, substitutions=substitutions,
                _depth=_depth + 1, _cache=_cache, _in_progress=_in_progress,
            ))
            if _depth < 8
            else None
        )
        _in_progress.add(record_index)
        try:
            if not drop_ranges:
                result = self._render_symbol_list(
                    symbols,
                    substitutions=substitutions,
                    expand_conditionals=True,
                    control_evaluator=lambda _control, _operands, _pos: None,
                    dict_expand_hook=dict_expand_hook,
                )
                _cache[record_index] = result
                return result
            # Merge overlapping ranges then filter the symbol list.
            drop_ranges.sort()
            merged: list[tuple[int, int]] = []
            for start, end in drop_ranges:
                if merged and start <= merged[-1][1]:
                    merged[-1] = (merged[-1][0], max(merged[-1][1], end))
                else:
                    merged.append((start, end))
            filtered: list[int] = []
            last = 0
            for start, end in merged:
                filtered.extend(symbols[last:start])
                last = end
            filtered.extend(symbols[last:])
            result = self._render_symbol_list(
                filtered,
                substitutions=substitutions,
                expand_conditionals=True,
                control_evaluator=lambda _control, _operands, _pos: None,
                dict_expand_hook=dict_expand_hook,
            )
            _cache[record_index] = result
            return result
        finally:
            _in_progress.discard(record_index)

    @classmethod
    def parse_conditional_spans(cls, symbols: "list[int]") -> "list[ConditionalSpan]":
        """Detailed variant of :meth:`parse_conditional_operands`.

        This preserves the native continuation descriptor after ``|`` instead
        of folding it into ``frag_start`` and losing it.  The older tuple API is
        intentionally kept for callers/tests that only need branch filtering.
        """

        spans: list[ConditionalSpan] = []
        for kind, pos, operand, op_end, frag_end in cls.parse_conditional_operands(symbols):
            frag_start = op_end
            continuation = ""
            jump_target: int | None = None
            if frag_start < len(symbols) and symbols[frag_start] == 0x1C:
                chars: list[str] = []
                for offset in (frag_start + 1, frag_start + 2):
                    if offset < len(symbols):
                        chars.append(DEFAULT_SYMBOL_TABLE.get(symbols[offset], "?"))
                continuation = "".join(chars)
                if frag_start + 2 < len(symbols):
                    jump_target = msg_ctrl_break_target(
                        symbols[frag_start + 1], symbols[frag_start + 2]
                    )
                frag_start = min(len(symbols), frag_start + 3)
            spans.append(
                ConditionalSpan(
                    kind=kind,
                    pos=pos,
                    operand=operand,
                    op_end=op_end,
                    frag_start=frag_start,
                    frag_end=frag_end,
                    continuation=continuation,
                    jump_target=jump_target,
                    raw_operand=tuple(symbols[pos + 1 : op_end]),
                )
            )
        return spans

    def assemble_multi_fragment(
        self,
        records: "list",
        substitutions: "dict[str, str] | None" = None,
        separator: str = " ",
        on_section_state: "Callable[[int], None] | None" = None,
        control_evaluator: "Callable[[str, tuple[int, ...], int], bool | None] | None" = None,
    ) -> str:
        """Port of GAME.000:sub_8628 structural pattern -- stitch multi-record turn responses.

        The native ``sub_8628`` calls ``turn_resolve_text`` (``sub_4E03``)
        repeatedly with different field discriminators (``7``, ``0``,
        ``byte_1BE8``), each call resolving and rendering one fragment,
        then concatenates the rendered output. The CONDITION-EVALUATION
        loop that decides *which* records to include is state-driven via
        the not-yet-traced ``sub_3A93``/``sub_3BA7`` checks, so this port
        takes the record list as input and just performs the
        resolve-render-stitch pass.

        For each record, calls ``turn_resolve_text()`` (the port of
        sub_4E03), extracts ``message_ref``, and renders that MESSAGE
        record. Records whose discriminator path doesn't yield a
        ``message_ref`` (default / 0x17 / 0x19 branches) are skipped.

        ``on_section_state`` is an optional callback that receives the
        ``section_state`` value (`[DS:0x4B11]`) each ``turn_resolve_text``
        produces. The native engine writes the latest section_state into
        the global before rendering that fragment, so the downstream ``(``
        section selector / predicate dispatcher sees the same state. Callers
        wiring this into the VM pass a callback that updates the shared
        action state.

        ``control_evaluator`` is forwarded into each fragment render. This
        keeps the multi-fragment path on the same live VM predicate machinery
        as ``render_message_record`` instead of degrading to static composite
        expansion.

        Returns the concatenated rendered fragments joined by ``separator``
        (default single space, matching the native segment joiner).
        """

        fragments: list[str] = []
        max_index = len(self.dict_symbols) // 8
        for record in records:
            resolved = record.turn_resolve_text()
            if on_section_state is not None:
                on_section_state(resolved.section_state)
            if resolved.message_ref is None:
                continue
            # Defensive: not every record's +4/+6/+8 word is a valid MESSAGE
            # index. Some discriminator paths set word_4B7F to a value the
            # native dispatcher routes through additional translation we
            # haven't ported (e.g. the type-0x00 NPC records have refs in
            # the 40000+ range, way past MESSAGE's record count). Skip
            # silently so a single odd record doesn't crash the assembler.
            if not (0 <= resolved.message_ref < max_index):
                continue
            try:
                text = self.render_message_record(
                    resolved.message_ref,
                    substitutions=substitutions,
                    control_evaluator=control_evaluator,
                )
            except (IndexError, ValueError):
                continue
            if text:
                fragments.append(text)
        return separator.join(fragments)

    def render_message_record(
        self,
        index: int,
        section: "str | list[int] | tuple[int, ...] | None" = None,
        _depth: int = 0,
        substitutions: "dict[str, str] | None" = None,
        control_evaluator: "Callable[[str, tuple[int, ...], int], bool | None] | None" = None,
        span: "tuple[int, int] | None" = None,
    ) -> str:
        """Render MESSAGE record ``index``, expanding the ``\\`` word dictionary.

        Ported from the live-traced GAME.000 control dispatcher (the ``\\``
        case at 0x10df7): the ``\\`` control (symbol 0x2f) is followed by three
        packed symbols forming a base-64 index ``s0*4096 + s1*64 + s2`` (read by
        sub_1985e); the expander (sub_19ab1 -> the record reader) renders MESSAGE
        record ``index`` inline, then resumes. Words are therefore other MESSAGE
        records, not a separate table. ``% x@`` capitalises the next letter
        (``@`` ends the one-letter segment) and ``|`` breaks the line.

        ``section`` selects ONE labelled span of a composite record via the ``(``
        control (symbol 0x1e == GAME.000:0x1e232 section selector). A composite
        record (e.g. record 3899) is a sequence of ``( label  content`` spans;
        the native selector renders only the span whose label matches the
        dispatcher's currently-requested section, up to the next ``(``. Pass the
        requested label (decoded string such as ``"lqaaai"`` or a symbol list);
        the matching span is *located in the data* (never a hardcoded offset).
        When ``section`` is given but no matching label exists, this returns ``""``
        -- an unresolved reference yields no prose, never gibberish.

        HYPOTHESIS (label parse): the selector matches the symbols immediately
        after ``(`` against the requested label and renders to the next ``(``.
        The general label-length/terminator rule (labels vary 4..6 symbols in the
        data) is not yet trace-confirmed, so the caller supplies the exact label;
        the match length is ``len(label)``. See docs/data-format.md.

        Controls that still need a trace (``^ $ ) & = + *``) are skipped, so
        the output is faithful prose plus its known capitalisation/line breaks,
        never raw control bytes.
        """

        # msg_dict_expand has no recursion guard: KISS (2838) re-renders
        # itself once 2831 has put Pussy on cursor m. The cap only stops a
        # runaway expansion; real records terminate on the state they set.
        if self._record_stack.count(index) >= 3:
            return ""
        self._record_stack.append(index)
        # `%t`, `%e` ... read the cursors at print time natively, at any
        # depth: a nested record (an object's description printed by `=`)
        # sees the same names as the record that printed it.
        if _depth > 0 and self._substitution_stack:
            inherited = dict(self._substitution_stack[-1])
            inherited.update(substitutions or {})
            substitutions = inherited
        self._substitution_stack.append(substitutions or {})
        try:
            if _depth == 0 and self.record_open_callback is not None:
                self.record_open_callback()
            symbols = self.record_symbols(index)
            if section is not None:
                found = self._find_section_span(symbols, self._encode_label(section))
                if found is None:
                    return ""
                symbols = symbols[found[0] : found[1]]
                symbol_origin = found[0]
            elif span is not None:
                # A caller-chosen branch of the record, rendered live: the
                # record still opens (cursor binding), and the branch's own
                # jumps are relative, so they land where they do natively.
                symbols = symbols[span[0] : span[1]]
                symbol_origin = span[0]
            else:
                symbol_origin = 0
            return self._render_symbol_list(
                symbols,
                _depth,
                substitutions=substitutions,
                control_evaluator=control_evaluator,
                symbol_origin=symbol_origin,
            )
        finally:
            self._substitution_stack.pop()
            self._record_stack.pop()

    def render_message_record_span(
        self,
        index: int,
        start: int,
        length: int,
        substitutions: "dict[str, str] | None" = None,
    ) -> str:
        """Render a confirmed symbol slice within one MESSAGE record.

        Caller-located slice -> render every byte in the slice including
        conditional fragments; operand metadata is still skipped.
        """

        symbols = self.record_symbols(index)
        if start < 0 or length <= 0 or start >= len(symbols):
            return ""
        return self._render_symbol_list(
            symbols[start : start + length],
            substitutions=substitutions,
            expand_conditionals=True,
            symbol_origin=start,
        )

    def render_last_prose_fragment(
        self,
        index: int,
        substitutions: "dict[str, str] | None" = None,
    ) -> str:
        """Render the final `@`-delimited prose fragment of a composite record.

        This is a conservative fallback for dispatcher-selected composites
        whose live state selector is not fully reconstructed yet. It does not
        expand the whole composite; it renders only the last segment bounded by
        native `@` terminators, returning ``""`` if no such segment exists.
        """

        symbols = self.record_symbols(index)
        end = len(symbols)
        while end > 0 and symbols[end - 1] == 0x21:
            end -= 1
        if end <= 0:
            return ""
        start = end - 1
        while start >= 0 and symbols[start] != 0x21:
            start -= 1
        start += 1
        if start >= end:
            return ""
        return self._render_symbol_list(
            symbols[start:end],
            substitutions=substitutions,
            expand_conditionals=True,
            control_evaluator=lambda _control, _operands, _pos: None,
            symbol_origin=start,
        )

    @staticmethod
    def _encode_label(section: "str | list[int] | tuple[int, ...]") -> list[int]:
        """Map a requested section label to packed symbols (``(`` selector input)."""

        if isinstance(section, str):
            reverse = {char: symbol for symbol, char in DEFAULT_SYMBOL_TABLE.items()}
            return [reverse[char] for char in section]
        return list(section)

    @staticmethod
    def _find_section_span(symbols: list[int], label: list[int]) -> "tuple[int, int] | None":
        """Locate the ``( label`` span in ``symbols`` for the ``(`` selector.

        Scans for a ``(`` (0x1e) whose following symbols equal ``label`` and
        returns ``(content_start, content_end)`` where ``content_end`` is the
        next ``(`` (or end of record). Returns ``None`` if the label is absent.
        """

        if not label:
            return None
        width = len(label)
        total = len(symbols)
        for i in range(total):
            if symbols[i] != 0x1E:
                continue
            if symbols[i + 1 : i + 1 + width] != label:
                continue
            start = i + 1 + width
            end = start
            while end < total and symbols[end] != 0x1E:
                end += 1
            return start, end
        return None
