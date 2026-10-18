"""Indiana Jones in Revenge of the Ancients: engine configuration.

Same shape as ``games/goldfinger/config.py``: this package is config + data
only, running on the shared VM (``gameengine.AsgVm`` via
``gameengine.game.AsgGame``) exactly like every other Mindscape title.

``GAME.COM``/``GAME.000`` are byte-identical to Goldfinger's and High
Stakes's (same 40-byte TABLES-record cluster, confirmed MD5 match,
`docs/engine-compatibility.md`) -- only ``MESSAGE``/``VOCAB``/``TABLES``
differ, so the shared VM runs this title from its own data with no
title-specific engine code.
"""

from __future__ import annotations

from gameengine.data import default_root

from gameengine.config import AsgConfig

# Launcher .COM filename.
LAUNCHER_NAME = "GAME.COM"

# TABLES record stride -- Variant A (40-byte records), same cluster as
# Goldfinger/High Stakes.
TABLES_RECORD_SIZE = 40

DISPLAY_NAME = "Indiana Jones in Revenge of the Ancients"
YEAR = 1987
PUBLISHER = "Mindscape"

# activation.initial_native_room_id, read directly off this title's own
# TABLES via the shared activation chain (not guessed/hardcoded) --
# confirmed 2026-07-03 by loading GameData and reading
# ``AsgVm.from_decoder(tables).activation.initial_native_room_id``.
INITIAL_NATIVE_ROOM_ID = 7

CONFIG = AsgConfig(
    key="indiana-jones",
    display_name=DISPLAY_NAME,
    root=default_root("indiana_jones"),
    launcher_name=LAUNCHER_NAME,
    table_record_size=TABLES_RECORD_SIZE,
    initial_native_room_id=INITIAL_NATIVE_ROOM_ID,
    text_attribute=0x0E,  # yellow on the original screen (B800)
)
