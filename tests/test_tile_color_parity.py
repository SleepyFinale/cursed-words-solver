"""One verification per TileType hook (game GetValue / ScoreCalculation parity)."""

from __future__ import annotations

import json

from cursed_words_solver.loadout import green_poison_from_historic_words
from cursed_words_solver.models import Board, CurseType, Loadout, Tile, TileColor, tile_counts_as_color
from cursed_words_solver.rules.base_scoring import tile_base_contribution
from cursed_words_solver.rules.quest_movement import _white_portal_mask
from cursed_words_solver.rules.scoring_order import apply_green_tile_word_transfer
from cursed_words_solver.rules.tile_scoring import pink_store_money, settle_glitch_tiles


def _letter(color: TileColor, *, base: float = 1, letter: str = "A") -> Tile:
    return Tile(0, 0, letter, letter, base, color, CurseType.LETTER)


def test_normal_scrabble_letter() -> None:
    assert tile_base_contribution(_letter(TileColor.COLORLESS, letter="Q", base=10)) == 10


def test_red_color_plus_one() -> None:
    assert tile_base_contribution(_letter(TileColor.RED)) == 2


def test_blue_color_plus_one() -> None:
    assert tile_base_contribution(_letter(TileColor.BLUE)) == 2


def test_shiny_flat_fifty_ocr() -> None:
    assert tile_base_contribution(_letter(TileColor.SHINY)) == 50


def test_void_negate_face() -> None:
    t = _letter(TileColor.VOID, letter="E")
    t.base_score = 0
    assert tile_base_contribution(t) == -1


def test_cactus_melmod_packet_authoritative() -> None:
    t = _letter(TileColor.CACTUS, base=5)
    t.metadata["source"] = "melmod"
    t.metadata["cactus_growth"] = 9
    assert tile_base_contribution(t) == 5


def test_pink_store_money_decrements_bank() -> None:
    board = Board(tiles=[[_letter(TileColor.PINK), _letter(TileColor.PINK, letter="B")]], money=4)
    loadout = Loadout(money=4)
    assert pink_store_money(board, [0, 1], loadout) == 2


def test_gold_uses_player_money() -> None:
    board = Board(tiles=[[_letter(TileColor.GOLD)]], money=12)
    assert tile_base_contribution(board.tiles[0][0], board.money) == 12


def test_green_transfer_finalize() -> None:
    board = Board(tiles=[[_letter(TileColor.GREEN, base=3)]], money=0)
    state = {"tile_scores": [3.0], "word_score": 0.0, "effects": []}
    apply_green_tile_word_transfer(board, [0], state)
    assert state["word_score"] == 3.0
    assert state["tile_scores"] == [0.0]


def test_green_poison_from_historic_words() -> None:
    extras = {
        "historic_words": json.dumps(
            [{"word": "gree", "score": 10, "green_tile_count": 1}]
        ),
        "encounter_score_earned": "10",
    }
    assert green_poison_from_historic_words(extras) == 1.0


def test_green_poison_skips_cross_encounter_rows() -> None:
    extras = {
        "historic_words": json.dumps(
            [
                {"word": "watt", "score": 210, "green_tile_count": 0},
                {"word": "wealthmaker", "score": 604, "green_tile_count": 2},
                {"word": "felidomancy", "score": 156, "green_tile_count": 1},
            ]
        ),
        "encounter_score_earned": "156",
    }
    assert green_poison_from_historic_words(extras) == 16.0


def test_green_poison_zero_when_encounter_not_started() -> None:
    extras = {
        "historic_words": json.dumps(
            [{"word": "wealthmaker", "score": 604, "green_tile_count": 2}]
        ),
        "encounter_score_earned": "0",
    }
    assert green_poison_from_historic_words(extras) == 0.0


def test_green_poison_infers_enc_earned_on_grid2_when_f8_missing() -> None:
    """F8 may lack encounter_score_earned; infer from historic when spc > 0."""
    extras = {
        "grid_number": "2",
        "scoring_previous_words_count": "1",
        "historic_words": json.dumps(
            [{"word": "jWwwqD", "score": 72, "green_tile_count": 1}]
        ),
    }
    assert green_poison_from_historic_words(extras) == 7.0


def test_green_poison_explicit_zero_enc_earned_stays_zero() -> None:
    """encounter_score_earned='0' must not infer stale cross-encounter poison."""
    extras = {
        "grid_number": "2",
        "scoring_previous_words_count": "1",
        "historic_words": json.dumps(
            [{"word": "wealthmaker", "score": 604, "green_tile_count": 2}]
        ),
        "encounter_score_earned": "0",
    }
    assert green_poison_from_historic_words(extras) == 0.0


def test_green_poison_robo_eel_grid_reset_live_historic() -> None:
    """Robo-Eel resets grid_number to 1; live encounter historic still poisons."""
    extras = {
        "grid_number": "1",
        "scoring_previous_words_count": "3",
        "encounter_score_earned": "0",
        "encounter_historic_source": "live",
        "historic_words": json.dumps(
            [
                {
                    "word": "attractor",
                    "score": 10255,
                    "green_tile_count": 1,
                },
                {
                    "word": "entireties",
                    "score": 18546,
                    "green_tile_count": 1,
                },
            ]
        ),
    }
    assert green_poison_from_historic_words(extras) == 2881.0


def test_green_poison_grid2_live_historic_all_prior_words() -> None:
    """Grid 2+ sums poison from all live encounter historic rows (not enc_earned cap)."""
    extras = {
        "grid_number": "2",
        "scoring_previous_words_count": "4",
        "encounter_score_earned": "13021",
        "encounter_historic_source": "live",
        "historic_words": json.dumps(
            [
                {"word": "attractor", "score": 10255, "green_tile_count": 1},
                {"word": "entireties", "score": 18546, "green_tile_count": 1},
                {"word": "saurians", "score": 13021, "green_tile_count": 1},
            ]
        ),
    }
    assert green_poison_from_historic_words(extras) == 4183.0


def test_purple_counts_as_red_and_blue() -> None:
    t = _letter(TileColor.PURPLE)
    assert tile_counts_as_color(t, TileColor.RED)
    assert tile_counts_as_color(t, TileColor.BLUE)
    assert tile_base_contribution(t) == 3


def test_white_portal_teleport_mask() -> None:
    board = Board(
        tiles=[
            [_letter(TileColor.WHITE) for _ in range(5)]
            for _ in range(5)
        ]
    )
    active_mask = (1 << 25) - 1
    mask = _white_portal_mask(board, 0, 1 << 0, active_mask=active_mask)
    assert mask & (1 << 12)


def test_glitch_settle_leaves_colour_pool() -> None:
    board = Board(tiles=[[_letter(TileColor.GLITCH)]])
    loadout = Loadout(extras={"run_seed": "parity"})
    settle_glitch_tiles(board, [0], loadout)
    assert board.tiles[0][0].color != TileColor.GLITCH
