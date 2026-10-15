"""Encounter grid generation — ``GridUtilitySingleton.GenerateBasicGridData``.

Each of the 25 tiles rolls a weighted letter (crown 5+ uses the ascension weights),
colourless. Start-of-grid item / boss mutations are applied afterwards by the
existing ``encounter_board.effective_board_for_loadout`` pipeline.
"""

from __future__ import annotations

import random

from cursed_words_solver.encounter_board import effective_board_for_loadout
from cursed_words_solver.models import Board, CurseType, Loadout, Tile, TileColor
from cursed_words_solver.sim.run_rules import GRID_DIMENSION, Ascension, letter_values, random_letter


def generate_letter_grid(
    rng: random.Random,
    ascension: Ascension | int = Ascension.NONE,
    *,
    size: int = GRID_DIMENSION,
) -> Board:
    values = letter_values(ascension)
    rows: list[list[Tile]] = []
    for r in range(size):
        row: list[Tile] = []
        for c in range(size):
            letter = random_letter(rng, ascension)
            row.append(
                Tile(
                    row=r,
                    col=c,
                    char=letter.upper(),
                    letter=letter.upper(),
                    base_score=float(values[letter]),
                    color=TileColor.COLORLESS,
                    curse=CurseType.LETTER,
                    metadata={"source": "sim"},
                )
            )
        rows.append(row)
    return Board(tiles=rows, rows=size, cols=size)


def generate_encounter_grid(
    rng: random.Random,
    loadout: Loadout,
    rules: dict,
    ascension: Ascension | int = Ascension.NONE,
) -> Board:
    """Basic grid + simulated start-of-encounter / boss / start-of-grid mutations.

    Mutation RNG is seeded from ``loadout.extras["scatter_seed"]`` (set per grid by the
    caller) so runs stay reproducible.
    """
    board = generate_letter_grid(rng, ascension)
    loadout.extras.setdefault("scatter_seed", rng.randrange(2**31))
    return effective_board_for_loadout(board, loadout, rules)
