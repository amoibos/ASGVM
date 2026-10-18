"""Port of sub_6F8B's command grammar: which native dispatcher takes a sentence.

GAME.000 IDA 7570..7B9F tries a fixed chain of sentence patterns over the
parsed word list and hands the first match to its dispatcher (decoded
2026-10-15). The parser keeps the
recognised words as a linked list; every helper looks at the node *after*
the cursor and advances it on a match:

* ``51EC`` CLASSNEXT(set) -- the next word's class (+6) is in the set;
* ``56A1`` PRONOUN -- the next word is "it"/"them" (class 0Bh);
* ``580E`` NOUN -- a pronoun, or the next word is an object (kind 0);
* ``5752`` KINDNEXT(set) -- a pronoun, or the next word's kind is in the set;
* ``52B6`` PERSON -- the next word is a person (kind 1);
* ``514A`` FINDKIND(k) -- the first word of kind k anywhere ahead;
* ``5992`` WITH_NOUN -- the last "WITH <noun>" anywhere ahead.

The patterns, in the order the chain tries them:

==========  =========================================  ==========
pattern     sentence                                    dispatcher
==========  =========================================  ==========
67DC        TAKE (14h) / RIDE (12h) + vehicle / place   4B36
641D        OPEN/CLOSE class (DS:4BC4) [+ noun/WITH]    3AD5
5A58        KILL (2Ah) person [WITH noun]               3CCC
5BC3        IN/INTO (0Ch) + noun anywhere               3E2E
65BF        PUT / PUT ON TOP (24h/25h) ...              46FD
6083        a person first ("TILLY, ...")              410C
5F66        verb + Phase-9 noun                         3FDA
6284        verb + noun / WITH                          4857 or 423E
6C32        movement word or direction                  4A74 or 4B36
==========  =========================================  ==========

6284's verb goes to 4857 when its class is LOOK/QUIT/SAVE/INVENTORY (18h,
1Ah, 1Bh, 2Dh), to 423E when its value is in DS:4B6B (the union of every
object's +0Eh verb set) and to 4857 otherwise. A sentence no pattern takes
is left to the caller (the port's talk/verb-alone paths).

Speech (sub_6F8B's first part, loc_73C4: question / give / trade / greeting)
is classified before this chain and handled by the speech dispatcher.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

# DS:4BC4 -- the verb classes of pattern 641D (measured on the original:
# 00 C0 00 00 00 00 03 -> classes 14, 15, 48, 49).
GENERIC_VERB_CLASSES = frozenset((0x0E, 0x0F, 0x30, 0x31))
LOOK_LIKE_VERB_CLASSES = frozenset((0x18, 0x1A, 0x1B, 0x2D))
DIRECTION_CLASSES = frozenset(range(6))
PRONOUN_CLASS = 0x0B


@dataclass(frozen=True)
class Word:
    """One node of the parsed word list: class (+6), kind (+8), value (+9)."""

    word: str
    class_id: int
    kind: int
    value: int


@dataclass(frozen=True)
class Sentence:
    """The pattern that took the sentence and its dispatcher (IDA address)."""

    pattern: int
    dispatcher: int
    verb: "Word | None" = None


def _next(words: Sequence[Word], cursor: int) -> "Word | None":
    return words[cursor + 1] if cursor + 1 < len(words) else None


def _classnext(words, cursor, classes):
    nxt = _next(words, cursor)
    if nxt is not None and nxt.class_id in classes:
        return True, cursor + 1
    return False, cursor


def _pronoun(words, cursor):
    current = words[cursor] if cursor >= 0 else None
    if current is not None and current.kind == 7:
        return False, cursor
    nxt = _next(words, cursor)
    if nxt is not None and nxt.class_id == PRONOUN_CLASS:
        return True, cursor + 1
    return False, cursor


def _kindnext(words, cursor, kinds):
    ok, moved = _pronoun(words, cursor)
    if ok:
        return True, moved
    nxt = _next(words, cursor)
    if nxt is not None and nxt.kind in kinds:
        return True, cursor + 1
    return False, cursor


def _noun(words, cursor):
    return _kindnext(words, cursor, (0,))


def _person(words, cursor):
    nxt = _next(words, cursor)
    if nxt is not None and nxt.kind == 1:
        return True, cursor + 1
    return False, cursor


def _findkind(words, cursor, kind):
    for index in range(cursor + 1, len(words)):
        if words[index].kind == kind:
            return True, index
    return False, cursor


def _with_noun(words, cursor):
    found, position = False, cursor
    for index in range(cursor, len(words)):
        ok, after_with = _classnext(words, index, (0x07,))
        if ok:
            ok, noun_at = _noun(words, after_with)
            if ok:
                found, position = True, noun_at
    return found, position


def _vehicle(words, cursor):
    """sub_67E8: KINDNEXT(3) -- a vehicle (Phase-9 noun) or a pronoun."""

    return _kindnext(words, cursor, (3,))


def _to_place(words, cursor):
    """sub_6839: an optional TO (class 6), then KINDNEXT(2) -- a place."""

    ok, at = _classnext(words, cursor, (0x06,))
    return _kindnext(words, at if ok else cursor, (2,))


def _pattern_67dc(words, start, referent_kind):
    """sub_68F8: TAKE (14h) or RIDE (12h) first, then a vehicle and/or place.

    RIDE always matches (vehicle and place optional). TAKE needs IT with a
    place after it or a vehicle referent (byte_1A56 == 3, IDA 69C9), else a
    vehicle (67E8) or a place (6839).
    """

    ok, at = _classnext(words, start, (0x14, 0x12))
    if not ok:
        return None
    verb = words[at]
    if verb.class_id == 0x12:
        return Sentence(0x67DC, 0x4B36, verb)
    ok, it_at = _pronoun(words, at)
    if ok:
        if _to_place(words, it_at)[0] or referent_kind == 3:
            return Sentence(0x67DC, 0x4B36, verb)
        return None
    if _vehicle(words, at)[0] or _to_place(words, at)[0]:
        return Sentence(0x67DC, 0x4B36, verb)
    return None


def take_or_ride_pattern(words, referent_kind=None) -> "Sentence | None":
    """67DC from the list head: TAKE/RIDE + vehicle or place (-> 4B36)."""

    return _pattern_67dc(list(words), -1, referent_kind)


# sub_6D38's movement words: GO/DRIVE/CLIMB/GET IN/GET OUT, ENTER, EXIT.
MOVEMENT_WORD_CLASSES = frozenset((0x13, 0x0D, 0x10))


def _pattern_6c32(words, start, place_within_reach, byte_1aec):
    """sub_6C32 and the chain's tail (IDA 7A04..7B96).

    sub_6D38 takes a movement word first and leaves state 3 -- except for a
    named place (FINDKIND 2, its value is a room id) that sub_FE5B does not
    find while byte_1AEC is clear: state 2. sub_FE5B is overlay-relative:
    with this group's delta (+3116h, IDA 4A64 = runtime 7B7A; 7570 near-calls
    both 4A74 and 6C32) it runs at 0876:2F71, the routine dumped live as
    sub_665B (a breakpoint there during GO TO AIRPORT returns to 9F34,
    right after 6D38's call) -- the player's room or one of its six exits
    is within reach
    (``place_within_reach``, a pure test; AsgVm.sub_665b also moves 6AA).
    sub_6C3E takes a direction first: state 3. State 2 goes to 4B36; state
    3 goes to 4A74, or to 4B36 when ON (class 8, sub_5278) and a vehicle
    follow (6749).
    """

    ok, at = _classnext(words, start, MOVEMENT_WORD_CLASSES)
    if ok:
        state = 3
        found, place_at = _findkind(words, at, 2)
        if (
            found
            and place_within_reach is not None
            and not place_within_reach(words[place_at].value)
            and byte_1aec != 1
        ):
            state = 2
    else:
        ok, at = _classnext(words, start, DIRECTION_CLASSES)
        if not ok:
            return None
        state = 3
    verb = words[at]
    if state == 2:
        return Sentence(0x6C32, 0x4B36, verb)
    on, on_at = _classnext(words, at, (0x08,))
    if on and _vehicle(words, on_at)[0]:
        return Sentence(0x6C32, 0x4B36, verb)
    return Sentence(0x6C32, 0x4A74, verb)


def classify(
    words: Sequence[Word],
    *,
    object_verbs_4b6b: Iterable[int] = (),
    referent_kind: "int | None" = None,
    place_within_reach: "Callable[[int], bool] | None" = None,
    byte_1aec: int = 0,
) -> "Sentence | None":
    """Run the native pattern chain (IDA 7570..7B9F) over the word list.

    ``referent_kind`` is byte_1A56 (the kind IT refers to);
    ``place_within_reach`` and ``byte_1aec`` see ``_pattern_6c32``.
    """

    words = list(words)
    start = -1  # the cursor sits on the list head, before the first word
    sentence = _pattern_67dc(words, start, referent_kind)
    if sentence is not None:
        return sentence
    ok, at = _classnext(words, start, GENERIC_VERB_CLASSES)
    if ok:
        return Sentence(0x641D, 0x3AD5, words[at])
    ok, at = _classnext(words, start, (0x2A,))
    if ok:
        return Sentence(0x5A58, 0x3CCC, words[at])
    for index in range(start, len(words)):
        ok, after_in = _classnext(words, index, (0x0C,))
        if ok and _noun(words, after_in)[0]:
            return Sentence(0x5BC3, 0x3E2E)
    ok, at = _classnext(words, start, (0x24, 0x25))
    if ok:
        return Sentence(0x65BF, 0x46FD, words[at])
    if _person(words, start)[0]:
        return Sentence(0x6083, 0x410C)
    ok, verb_at = _findkind(words, start, 6)
    if ok:
        nxt = _next(words, verb_at)
        if nxt is not None and nxt.kind == 3:
            return Sentence(0x5F66, 0x3FDA, words[verb_at])
        noun_ok = _noun(words, verb_at)[0]
        with_ok = _classnext(words, verb_at, (0x07,))[0]
        if noun_ok or with_ok:
            verb = words[verb_at]
            if verb.class_id in LOOK_LIKE_VERB_CLASSES:
                return Sentence(0x6284, 0x4857, verb)
            if verb.value in set(object_verbs_4b6b):
                return Sentence(0x6284, 0x423E, verb)
            return Sentence(0x6284, 0x4857, verb)
    return _pattern_6c32(words, start, place_within_reach, byte_1aec)


SPEECH_CLASSES = frozenset((0x11, 0x16, 0x17, 0x19, 0x1C))


def route(
    words: Sequence[Word],
    *,
    object_verbs_4b6b: Iterable[int] = (),
    referent_kind: "int | None" = None,
    place_within_reach: "Callable[[int], bool] | None" = None,
    byte_1aec: int = 0,
) -> Sentence:
    """The caller of the chain (IDA 82AD..8345): grammar, speech, verb, default.

    7570 (the chain above) first; then sub_6F8B's speech part (a question,
    GIVE/TRADE, a greeting -- dispatcher 4D59, the talk dispatch); then 63B1,
    any verb word anywhere -> 4857 (LOOK, WAIT, FLIP WOMAN, LOOK WINDOW);
    otherwise 50D8, loc_3548 + sub_3870 -- the talk record (XYZZY).
    """

    sentence = classify(
        words,
        object_verbs_4b6b=object_verbs_4b6b,
        referent_kind=referent_kind,
        place_within_reach=place_within_reach,
        byte_1aec=byte_1aec,
    )
    if sentence is not None:
        return sentence
    if any(word.kind == 0x0A and word.class_id in SPEECH_CLASSES for word in words):
        return Sentence(0x6F8B, 0x4D59)
    ok, verb_at = _findkind(list(words), -1, 6)
    if ok:
        return Sentence(0x63B1, 0x4857, list(words)[verb_at])
    return Sentence(0x50D8, 0x50D8)


def words_from_entries(entries) -> list[Word]:
    """The parsed word list from VOCAB entries (live metadata).

    The parser's word loop (IDA 7E18..81D8) appends a node (sub_33F6) for
    every word except two kinds, which only set state:

    - class 2Eh (the oaths): loc_813B sets byte_4B7E and skips the append;
    - class 33h of kind 10 (modifiers: "white", "closely"): loc_8152 skips
      the append when ``kind == 0Ah and class == 33h``; loc_80D2 has already
      put the word's value_b into the kind-10 set DS:4BA6.

    So PRESS WHITE BUTTON reaches the verb + noun pattern.
    """

    return [
        Word(e.word, e.class_id, e.value_a, e.value_b)
        for e in entries
        if e.class_id != 0x2E and not (e.class_id == 0x33 and e.value_a == 0x0A)
    ]
