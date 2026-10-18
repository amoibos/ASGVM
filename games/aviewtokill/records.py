"""A View to a Kill: native verb-to-record table.

Pure data module, same shape as ``games/goldfinger/records.py``. Verb ids
come from VOCAB ``value_b`` of group=0x02 value_a=0x06 entries; MESSAGE
record indices are six-byte-block positions into the depaged ``MESSAGE``
file.
"""

from __future__ import annotations


# Native verb-to-MESSAGE-record table at DS:0x5F0 (this title's own data
# segment; the 47-byte-stride cluster's GAME.COM runs at DS=0x1594, not
# Goldfinger's DS=0x15DD), captured via DOSBox-X MEMDUMPBIN after a new-game
# starts (2026-07-03), same method as `games/goldfinger/records.py`'s table
# (`docs/vm.md`, Activation).
# Each value is the BASE template; the response actually rendered is typically a
# `(`-section-selected sub-fragment of the base record, same as Goldfinger.
VERB_RESPONSE_RECORDS: dict[int, int] = {
    0x01: 2414,   # quit
    0x02: 2401,   # save
    0x03: 1869,   # inv / inventory
    0x04: 1986,   # wear
    0x05: 2386,   # l / look
    0x06: 1913,   # get / grab / hold / pick up / take
    0x07: 3026,   # pour
    0x08:   41,   # read
    0x09: 2325,   # ex / examine / look at / look in / search / x
    0x0A: 2036,   # throw / toss
    0x0B: 2886,   # kill / murder
    0x0C: 2616,   # break
    0x0D: 2651,   # destroy
    0x0E: 3030,   # restore
    0x0F: 1881,   # drop / put down
    0x10: 2011,   # draw / remove / take off
    0x11: 2522,   # open
    0x12: 2915,   # insert / load / put / screw
    0x13: 2715,   # lock
    0x14: 2730,   # pick / unlock
    0x15: 2652,   # close
    0x16: 1984,   # take off of
    0x17: 3025,   # put on top
    0x18: 1985,   # take out of
    0x19: 1029,   # shoot
    0x1A: 1717,   # flip / trip
    0x1B: 1805,   # dial
    0x1C: 1676,   # kick / punch
    0x1D: 1286,   # kiss
    0x1E: 2408,   # restart
    0x1F: 3034,   # prt
    0x20:  711,   # shine
    0x21: 1833,   # turn
}
