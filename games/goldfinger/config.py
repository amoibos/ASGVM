"""Goldfinger-specific engine configuration.

Pinned values that tell the shared engine how to load Goldfinger's
data files and which TABLES variant to expect. Used by the play
entry point and by tooling that explicitly targets Goldfinger.
"""

from __future__ import annotations

# Launcher .COM filename. Goldfinger ships ``GAME.COM``; sibling
# titles use ``CASTLE.COM`` (Forbidden Castle), etc. The
# ``gameengine.data.GameData.load`` loader accepts this as the
# ``launcher_name`` argument.
LAUNCHER_NAME = "GAME.COM"

# TABLES record stride. Goldfinger is a Variant A title (40-byte
# records); ``gameengine.tables.TableDecoder`` auto-detects this from
# file size, but we keep the explicit constant for documentation and
# any future loader that wants to assert the variant up front.
TABLES_RECORD_SIZE = 40

# Display name used in REPL banners / titles.
DISPLAY_NAME = "James Bond 007: Goldfinger"

# Year + publisher (informational only).
YEAR = 1986
PUBLISHER = "Mindscape"

# --- VM-driven binding -------------------------------------------------------
# Goldfinger now runs on the shared VM (gameengine/AsgVm via gameengine.game),
# exactly like the other Mindscape titles: this package is CONFIG + DATA only.
# The verb-response table is the game's DS:0x5F0 data; everything else the VM
# derives from MESSAGE/VOCAB/TABLES.
from gameengine.data import default_root
from gameengine.config import AsgConfig

# The real turn-0 room: native 0x14 (= room index 19), the Aston Martin DB5
# chase scene, which is where the game actually starts once the boot cutscene
# runs. The pristine activation room (sub_D61's first DS:06A9 write) is native
# 0x0F, but a scripted "opening sequence" overwrites DS:06A9 several times
# during the cutscene (live-traced 0x0F -> 0x15 -> 0x14 -> ..., BP at the sole
# write site 0xDF88; see docs/vm-migration-audit.md) and leaves the player at
# 0x14 before the first prompt. That opening sequence isn't ported, so we set
# the confirmed post-sequence value here directly -- it is the correct starting
# point (LOOK now renders "The cockpit of the DB5...", OPEN ARMREST works).
#
# The DS:0x025C room-lookup convention is CONFIRMED (2026-07-05, direct live
# measurement at the chase prompt): native room id r -> slot r -> TABLES type-2
# record at file index r-1 (the "-1" convention this module uses). byte_6A9=0x14
# dereferenced to exactly rooms[19].
INITIAL_NATIVE_ROOM_ID = 20


CONFIG = AsgConfig(
    key="goldfinger",
    display_name=DISPLAY_NAME,
    root=default_root("goldfinger"),
    launcher_name=LAUNCHER_NAME,
    table_record_size=TABLES_RECORD_SIZE,
    initial_native_room_id=INITIAL_NATIVE_ROOM_ID,
    # VOCAB's bare noun for object 6 is "ball"; the native prose says "golf ball".
    object_display_names={6: "golf ball"},
    # room_description_spans is left unset: room descriptions now render through
    # render_message_record (the message_offset is a record index), which
    # renders each room's own description correctly -- the per-room span
    # override (originally added for native room 60) is no longer needed.
    arrival_record=1669,
    movement_record=1712,
    movement_command_record=1893,
    movement_transition_records=None,
    text_attribute=0x0E,  # yellow on the original screen (B800)
)
