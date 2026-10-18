"""Goldfinger MESSAGE record references + native verb-to-record table.

Pure data module. Verb ids come from VOCAB ``value_b`` of group=0x02
value_a=0x06 entries; MESSAGE record indices are six-byte-block
positions into the depaged ``MESSAGE`` file.
"""

from __future__ import annotations


# CAUTION (found+fixed 2026-07-24): record 1745 (the previous capture here)
# is a 5-symbol stub whose sole content is a raw "\amk@" dictionary
# back-reference -- rendering it via render_message_record_span expanded
# into an entire ~17KB unfiltered composite (the death sequence, the
# restart flow, and other unrelated state-gated fragments all concatenated,
# because this render path has no predicate/section context to filter
# them). Captured directly against the depaged symbol stream instead,
# bypassing the broken `\` indirection -- same pattern as the other
# chase MESSAGE_SYMBOL_CHASE_* constants below.
MESSAGE_SYMBOL_CHASE_CANT_DRIVE = 3224
MESSAGE_SYMBOL_CHASE_CANT_DRIVE_LEN = 39


# Native verb-to-MESSAGE-record table at DS:0x5F0, captured via DOSBox-X
# MEMDUMPBIN after a new-game starts (2026-06-22). The native dispatcher
# resolves word_4B7F = VERB_RESPONSE_RECORDS[verb_value_b] via sub_3A88.
# Each value is the BASE template; the response actually rendered is
# typically a `(`-section-selected sub-fragment of the base record (the
# native `(` selector at msg_ctrl_section / loc_EF31 picks the variant
# based on chase/scene/inventory state).
#
# VALIDATION ORACLE ONLY -- no longer wired into the runtime. The VM now
# derives this table from the phase-1 activation pointer at load time
# (``AsgActivationTables.build_verb_response_records``, port of the native
# DS:0x5F0 builder GAME.000:2df3..2e51). This frozen capture is retained as
# a differential-validation fixture: the data-driven builder reproduces it
# exactly (and, for The Mist, recovers one slot this hand-capture missed).
# It is an oracle and a fallback, not the runtime data source.
VERB_RESPONSE_RECORDS: dict[int, int] = {
    0x01: 2180,   # quit
    0x02: 2167,   # save
    0x03:  309,   # inventory
    0x04: 1592,   # put on / wear
    0x05: 1672,   # look
    0x06: 1480,   # take
    0x07: 2830,   # pour
    0x08: 2079,   # read
    0x09: 2097,   # examine
    0x0A: 2726,   # throw
    0x0B: 2502,   # kill
    0x0C: 1635,   # break
    0x0D: 1665,   # burn
    0x0E: 1666,   # restore
    0x0F: 1447,   # drop
    0x10: 1621,   # remove
    0x11: 2315,   # open
    0x12: 2508,   # put
    0x13: 2465,   # lock
    0x14: 2501,   # unlock
    0x15: 2427,   # close
    0x16: 1590,   # take off of
    0x17: 2725,   # put on top
    0x18: 1591,   # take out of
    0x19: 2752,   # prt
    0x1A: 2174,   # restart
    0x1B: 1408,   # wait        <-- matches MESSAGE_RECORD_WAIT_A_WHILE
    0x1C: 3823,   # press
    0x1D: 2281,   # type
    0x1E: 2838,   # kiss
    0x1F: 3041,   # kick
    0x20: 3110,   # flip
    0x21: 2754,   # light
    0x22: 2816,   # extinguish
    0x23: 3296,   # duck        <-- base template (3298 is the standalone sub-variant)
}
