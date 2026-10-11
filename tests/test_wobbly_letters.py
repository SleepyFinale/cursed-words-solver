"""Wobbly / variable letter resolution during search."""

from __future__ import annotations

from cursed_words_solver.models import CurseType, Tile, TileColor
from cursed_words_solver.rules.stamp_behaviors import (
    FLAG_J_AS_H_OR_Y,
    FLAG_RED_AS_E,
    FLAG_RED_AS_S,
    FLAG_RED_LETTER_PLUS_MINUS_ONE,
)


