"""Stephen King's The Mist: native verb-to-record table.

Pure data module, same shape as ``games/goldfinger/records.py``. Verb ids
come from VOCAB ``value_b`` of group=0x02 value_a=0x06 entries; MESSAGE
record indices are six-byte-block positions into the depaged ``MESSAGE``
file.
"""

from __future__ import annotations


# Native verb-to-MESSAGE-record table at DS:0x5F0 (this title's own data
# segment; NOTE the 47-byte-stride cluster's GAME.COM runs at DS=0x1594,
# not Goldfinger's DS=0x15DD), captured via DOSBox-X MEMDUMPBIN after a
# new-game starts (2026-07-03), same method as `games/goldfinger/records.py`'s
# table (`docs/data-format.md`, "Verb-to-MESSAGE-record lookup table"). Each
# value is the BASE template; the response actually rendered is typically a
# `(`-section-selected sub-fragment of the base record, same as Goldfinger.
VERB_RESPONSE_RECORDS: dict[int, int] = {
    0x01: 2771,   # quit
    0x02: 2764,   # save
    0x03: 2055,   # inv / inventory
    0x04: 2197,   # wear
    0x05: 2743,   # l / look
    0x06: 2100,   # grab / pick up / take
    0x07: 3335,   # pour / syphon
    0x08: 2663,   # page / read
    0x09: 2694,   # ex / examine / look at / look in / look into / x
    0x0A: 2248,   # pitch / throw / toss
    0x0B: 3239,   # kill / murder
    0x0C: 2329,   # break
    0x0D: 2354,   # destroy
    0x0E: 3406,   # restore
    0x0F: 2070,   # drop / put down
    0x10: 2225,   # draw / remove / take off
    0x11: 2985,   # open
    0x12: 3266,   # load / place / put
    0x13: 3117,   # lock
    0x14: 3180,   # unlock
    0x15: 3071,   # close / shut
    0x16: 2195,   # take off of
    0x17: 3327,   # put on top
    0x18: 2196,   # take out of
    0x19: 1183,   # shoot
    0x1A: 1222,   # (present in the runtime table, no VOCAB word maps to it)
    0x1B: 2758,   # restart
    0x1C:  245,   # dig
    0x1D:  133,   # touch
}
