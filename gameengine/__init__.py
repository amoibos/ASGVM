"""Mindscape Adventure engine — reusable across sibling games.

This package contains code that is engine-invariant across the 8 known
Mindscape adventure titles built on the same engine (Goldfinger,
Indiana Jones, Dick Francis, Forbidden Castle, A View to a Kill,
Rambo, The Mist, Voodoo Island). Per-game bindings live under
``games/<title>/``.

See ``docs/architecture.md`` for the engine variants (40-byte vs 47-byte
TABLES records being the main split).
"""
