"""Indiana Jones in Revenge of the Ancients: native verb-to-record table.

Pure data module, same shape as ``games/goldfinger/records.py``. Verb ids
come from VOCAB ``value_b`` of group=0x02 value_a=0x06 entries; MESSAGE
record indices are six-byte-block positions into the depaged ``MESSAGE``
file.

Confirmed: this title shares Goldfinger's core verb-id assignments
(quit/save/inventory/wear/look/take/pour/read/examine/throw/kill/break/
destroy(=burn)/restore/drop/remove/open/put/lock/unlock/close/take off of/
put on top/take out of/prt/restart, ids 0x01..0x1A) but diverges beyond
that -- Indiana Jones has no kiss/kick/flip/duck/light/extinguish verbs;
instead ids 0x1B..0x26 are its own puzzle verbs (pull/crack/lasso/jump/
wait/feel/hiss/climb/shoot/swing/press/cut). Do not reuse Goldfinger's
``VERB_*`` name constants for ids beyond 0x1A.
"""

from __future__ import annotations


# Native verb-to-MESSAGE-record table at DS:0x5F0, captured via DOSBox-X
# MEMDUMPBIN after a new-game starts (2026-07-03), same method as
# `games/goldfinger/records.py`'s table. Each value is the BASE template; the
# response actually rendered is typically a `(`-section-selected
# sub-fragment of the base record, same as Goldfinger.
VERB_RESPONSE_RECORDS: dict[int, int] = {
    0x01: 3264,   # quit
    0x02: 3251,   # save
    0x03: 2496,   # inv / inventory
    0x04: 2511,   # put on / wear
    0x05:   86,   # l / look / watch
    0x06: 2667,   # grab / pick up / take
    0x07: 3462,   # pour
    0x08: 3183,   # read
    0x09: 3203,   # describe / ex / examine / look at / x
    0x0A: 3070,   # throw / toss
    0x0B: 3010,   # kill / murder
    0x0C: 2553,   # break
    0x0D: 2581,   # destroy
    0x0E: 2582,   # restore
    0x0F: 3766,   # drop / put down
    0x10: 2538,   # remove / take off
    0x11: 3983,   # open
    0x12: 2777,   # put
    0x13: 3377,   # lock
    0x14: 3371,   # unlock
    0x15: 3317,   # close / shut
    0x16: 2771,   # take off of
    0x17: 3459,   # put on top
    0x18: 2772,   # take out of
    0x19: 3460,   # prt
    0x1A: 3258,   # restart
    0x1B: 3169,   # pull
    0x1C: 2125,   # crack / snap
    0x1D: 2097,   # lasso
    0x1E: 3634,   # jump
    0x1F: 3478,   # stay / wait
    0x20: 2426,   # feel
    0x21: 2195,   # hiss
    0x22: 3733,   # climb
    0x23: 2474,   # shoot
    0x24: 2264,   # swing
    0x25: 3378,   # press / push
    0x26: 2387,   # cut
}
