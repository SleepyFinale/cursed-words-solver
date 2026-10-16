"""Game-faithful simulator (cursed_words_solver/sim/game)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cursed_words_solver.sim.game import core as C
from cursed_words_solver.sim.game.challenges import QUESTS, make_challenge
from cursed_words_solver.sim.game.core import Rng, Tile
from cursed_words_solver.sim.game.importer import apply_player, game_from_game_state
from cursed_words_solver.sim.game.items import catalog_rows, make_item
from cursed_words_solver.sim.game.player import Node, Player, character_rows, resolve_character
from cursed_words_solver.sim.game.run import Game, RunConfig

CAPTURES = Path(__file__).resolve().parents[1] / "fixtures" / "captures"


def _player(**kw) -> Player:
    p = Player("WetDennis", kw.pop("ascension", 0))
    for k, v in kw.items():
        setattr(p, k, v)
    return p


# ---------------------------------------------------------------- tiles


def test_tile_values_follow_tile_getvalue():
    p = _player(money=7)
    t = Tile(letter="q")
    assert t.get_value(p) == 10
    t.tile_type = C.RED
    assert t.get_value(p) == 11
    t.tile_type = C.PURPLE
    assert t.get_value(p) == 12
    t.tile_type = C.VOID
    assert t.get_value(p) == -10
    t.tile_type = C.SHINY
    assert t.get_value(p) == 50
    t.tile_type = C.GOLD
    assert t.get_value(p) == 7
    t.tile_type = C.NORMAL
    t.set_number(9)
    assert t.get_value(p) == 9
    t.set_chess(C.KING, True)
    assert t.get_value(p) == 15


def test_crown_three_lowers_letter_values():
    assert Tile(letter="e").get_value(_player(ascension=3)) == 0
    assert Tile(letter="e").get_value(_player(ascension=2)) == 1


def test_purple_counts_as_red_and_blue():
    t = Tile(letter="a", tile_type=C.PURPLE)
    assert t.is_type(C.RED) and t.is_type(C.BLUE) and not t.is_type(C.VOID)


# ---------------------------------------------------------------- run rules


def test_targets_match_a_real_crown0_run():
    """Targets from a Carpman crown-0 win (round logs 2026-10-16)."""
    p = _player()
    run = p.run
    got = [
        run.encounter_target(stage, node, p)
        for stage in range(1, 6)
        for node in (Node.ENCOUNTER_FIRST, Node.ENCOUNTER_SECOND, Node.BOSS)
    ]
    assert got == [12, 17, 24, 48, 67, 96, 168, 235, 336, 660, 924, 1320, 2508, 3511, 5016]


def test_characters_resolve_by_display_name():
    assert resolve_character("Carpman") == "WetDennis"
    assert resolve_character("Rodman") == "WetDennis"
    assert resolve_character("Nat-H4") == "NathaServo"
    assert len(character_rows()) == 11


def test_every_quest_constructs():
    for name in QUESTS:
        ch = make_challenge(name)
        assert ch is not None and ch.game_class == name


def test_padlocks_fill_slots_at_crowns_4_and_6():
    g = Game(RunConfig(character="WetDennis", ascension=6, seed=3))
    stamps = [s.game_class for s in g.player.stamps if s]
    stickers = [s.game_class for s in g.player.stickers if s]
    assert stamps.count("StampPadlock") == 2
    assert stickers.count("StickerPadlock") == 2


def test_crown7_has_one_fewer_grid():
    g0 = Game(RunConfig(character="WetDennis", ascension=0, seed=1))
    g7 = Game(RunConfig(character="WetDennis", ascension=7, seed=1))
    assert g0.encounter.total_grids == 5
    assert g7.encounter.total_grids == 4


def test_boss_drafts_curse_one_option_per_floor_from_crown1():
    g = Game(RunConfig(character="WetDennis", ascension=1, seed=9))
    drafts = g.player.run.boss_drafts
    assert len(drafts) == 6
    for d in drafts[:5]:
        assert sum(b.cursed for b in d.options) == 1
    assert drafts[5].options[0].game_class == "MichaelBoss"
    assert drafts[5].options[0].floor_mod == 3


def test_same_seed_same_first_grid():
    a = Game(RunConfig(character="NinaNix", seed=42))
    b = Game(RunConfig(character="NinaNix", seed=42))
    sa = [(t.srep(), t.tile_type) for t in a.encounter.grid.tiles]
    sb = [(t.srep(), t.tile_type) for t in b.encounter.grid.tiles]
    assert sa == sb


def test_carp_streamers_scatter_red_and_blue():
    g = Game(RunConfig(character="WetDennis", seed=11))
    types = [t.tile_type for t in g.encounter.grid.available()]
    assert types.count(C.RED) >= 1 and types.count(C.BLUE) >= 1


def test_every_catalog_item_instantiates_and_serialises():
    for cls, row in catalog_rows().items():
        it = make_item(cls)
        state = it.to_state()
        assert state["class"] == cls
        assert len(state["levels"]) == len(row.get("components") or ())


# ---------------------------------------------------------------- shop


def test_first_shop_pick_is_free_at_crown0():
    g = Game(RunConfig(character="WetDennis", seed=2))
    enc = g.encounter
    # Clear the first encounter instantly.
    enc.remaining_target = 0
    enc._try_next_grid(type("R", (), {"won": False, "lost": False, "payout": 0})())
    g._after_encounter_action()
    assert g.phase == "shop"
    money = g.player.money
    offer = next(k for k, o in enumerate(g.shop.stickers) if o is not None)
    assert g.buy("sticker", offer)
    assert g.player.money == money


# ---------------------------------------------------------------- captures


def _capture_files():
    return sorted(CAPTURES.glob("*.json")) if CAPTURES.is_dir() else []


@pytest.mark.parametrize("path", _capture_files(), ids=lambda p: p.stem)
def test_capture_replays_exactly_through_sim_state(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    cap = data.get("capture") or {}
    gs = cap.get("pre_submit")
    actual = (data.get("actual") or {}).get("score")
    if not isinstance(gs, dict) or actual is None:
        pytest.skip("no capture")
    g = game_from_game_state(gs)
    sc = cap.get("scoring_call") or {}
    if isinstance(sc.get("item_states"), dict):
        gs2 = dict(gs)
        gs2["player"] = {**gs["player"], **{k: v for k, v in sc["item_states"].items() if k in ("stickers", "stamps", "pin")}}
        apply_player(g.player, gs2)
    sub = cap.get("submission") or {}
    path_xy = [(int(t["x"]), int(t["y"])) for t in sub.get("tiles") or []]
    words = [str(w) for w in sub.get("words") or [] if str(w)]
    res = g.encounter.score_preview(path_xy, words)
    score = int(res.int_score)
    if g.player.run.challenge_is("TwoWrongs"):
        score = -score
    if res.nondeterministic:
        pytest.skip("nondeterministic score")
    assert score == int(actual)
