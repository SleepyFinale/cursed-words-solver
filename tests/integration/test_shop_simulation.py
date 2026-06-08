"""Shop purchase simulation smoke test."""

from __future__ import annotations

from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.models import Board, CurseType, Loadout, LoadoutItem, ShopOffer, Tile, TileColor
from cursed_words_solver.shop_simulation import SimulationConfig, evaluate_purchase
from tests.helpers.boards import _make_wordlist


def _score_board() -> Board:
    tiles = [
        [
            Tile(r, c, "q", "q", 1, TileColor.COLORLESS, CurseType.LETTER)
            for c in range(5)
        ]
        for r in range(5)
    ]
    tiles[2][0] = Tile(2, 0, "c", "c", 1, TileColor.SHINY, CurseType.LETTER)
    tiles[2][1] = Tile(2, 1, "a", "a", 1, TileColor.SHINY, CurseType.LETTER)
    tiles[2][2] = Tile(2, 2, "t", "t", 1, TileColor.SHINY, CurseType.LETTER)
    return Board(tiles=tiles)


def test_purchase_evaluation_runs(tmp_path):
    wl = _make_wordlist(tmp_path)
    dictionary = WordDictionary(wl)
    loadout = Loadout(
        stickers=[LoadoutItem(id="sticky_plaster", name="Sticky Plaster", level=1)],
        extras={"grids_remaining": "2"},
    )
    offer = ShopOffer(slot="sticker", index=0, id="brain", name="Brain", price=3, level=1)
    config = SimulationConfig(budget_sec=1.5, max_boards=1)
    lift, net, _reason = evaluate_purchase(
        offer,
        loadout,
        None,
        [_score_board()],
        dictionary,
        config=config,
    )
    assert isinstance(lift, float)
    assert isinstance(net, float)
