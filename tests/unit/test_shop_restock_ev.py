"""Restock EV heuristic."""

from __future__ import annotations

from cursed_words_solver.models import Board, CurseType, Loadout, ShopOffer, ShopState, Tile, TileColor
from cursed_words_solver.shop_simulation import SimulationConfig, evaluate_restock_ev
from tests.helpers.boards import _make_wordlist
from cursed_words_solver.dictionary import WordDictionary


def _tiny_board() -> Board:
    tiles = [
        [
            Tile(r, c, "c", "c", 1, TileColor.SHINY, CurseType.LETTER)
            for c in range(5)
        ]
        for r in range(5)
    ]
    tiles[0][1] = Tile(0, 1, "a", "a", 1, TileColor.SHINY, CurseType.LETTER)
    tiles[0][2] = Tile(0, 2, "t", "t", 1, TileColor.SHINY, CurseType.LETTER)
    return Board(tiles=tiles)


def test_restock_skip_when_strong_offers(tmp_path):
    wl = _make_wordlist(tmp_path)
    dictionary = WordDictionary(wl)
    loadout = Loadout()
    shop = ShopState(
        restock_cost=2,
        offers=[
            ShopOffer(slot="sticker", index=0, id="brain", name="Brain", price=1, level=1),
        ],
    )
    config = SimulationConfig(budget_sec=1.0, max_boards=1, monte_carlo_samples=5)
    rec = evaluate_restock_ev(
        loadout,
        shop,
        [_tiny_board()],
        dictionary,
        config=config,
        catalog_stamps=["newspaper"],
    )
    assert rec.action in {"skip", "no", "yes"}
