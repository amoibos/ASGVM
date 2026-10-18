"""Voodoo Island: native verb-to-record table.

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
    0x01: 1510,   # quit
    0x02: 1497,   # save
    0x03:  586,   # inventory
    0x04:  916,   # put on / wear
    0x05:  599,   # look
    0x06:  728,   # get / grab / pick up / take
    0x07: 2279,   # pour
    0x08: 1446,   # page / read
    0x09: 1472,   # describe / examine / look at / look in / look into
    0x0A:  964,   # throw / toss
    0x0B: 2025,   # hit / kill / murder / stab
    0x0C: 1046,   # break / tear
    0x0D: 1173,   # destroy
    0x0E: 1174,   # restore
    0x0F:  676,   # drop / put down
    0x10:  936,   # remove / take off
    0x11: 1762,   # cut / open
    0x12: 2220,   # put
    0x13: 1980,   # lock
    0x14: 1981,   # unlock
    0x15: 1921,   # close / shut
    0x16:  888,   # take off of
    0x17: 2278,   # put on top
    0x18:  889,   # take out of
    0x19: 2283,   # prt
    0x1A: 1504,   # restart
    0x1B:  352,   # wait
}
