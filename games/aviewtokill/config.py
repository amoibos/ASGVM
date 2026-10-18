"""A View to a Kill: engine configuration.

Same shape as ``games/goldfinger/config.py``: this package is config + data
only, running on the shared VM (``gameengine.AsgVm`` via
``gameengine.game.AsgGame``) exactly like every other Mindscape title.
"""

from __future__ import annotations

from gameengine.data import default_root

from gameengine.config import AsgConfig

LAUNCHER_NAME = "GAME.COM"

# TABLES record stride -- Variant B (47-byte records), same cluster as
# The Mist / Voodoo Island / Rambo / Forbidden Castle.
TABLES_RECORD_SIZE = 47

DISPLAY_NAME = "James Bond 007: A View to a Kill"
YEAR = 1985
PUBLISHER = "Mindscape"

# activation.initial_native_room_id, confirmed 2026-07-03 to match this
# title's own VM-derived value (2) via
# ``AsgVm.from_decoder(tables).activation.initial_native_room_id`` -- not a
# guess.
INITIAL_NATIVE_ROOM_ID = 2

CONFIG = AsgConfig(
    key="aviewtokill",
    display_name=DISPLAY_NAME,
    root=default_root("aviewtokill"),
    launcher_name=LAUNCHER_NAME,
    table_record_size=TABLES_RECORD_SIZE,
    initial_native_room_id=INITIAL_NATIVE_ROOM_ID,
)
