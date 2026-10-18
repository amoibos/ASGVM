"""Mindscape Adventure engine — reusable across sibling games.

This package contains code that is engine-invariant across the 8 known
Mindscape adventure titles built on the same engine (Goldfinger,
Indiana Jones, Dick Francis, Forbidden Castle, A View to a Kill,
Rambo, The Mist, Voodoo Island). Per-game bindings live under
``games/<title>/``.

The engine exists in two variants, told apart by the TABLES record size
(40 or 47 bytes).
"""
