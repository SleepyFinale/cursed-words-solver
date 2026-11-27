"""DLC fixes from the 2026-11-26 test runs: Literary Saga, GetStringRepresentation font
keys, rack tiles keeping their game glyph, the per-length word validator, brackets never
spending a letter, the bracket-board beam, the engine-based F8 mapping summary, boss
modifier JSON and rich-text character names."""

from __future__ import annotations

import json

from cursed_words_solver.engine import EnginePlan
from cursed_words_solver.engine.trie import CsrTrie
from cursed_words_solver.models import Loadout

from tests.engine.test_dlc_items import _put
from tests.engine.test_engine_item_rules import _loadout
from tests.engine.test_engine_units import _board


def _two_word_board():
    # Uppercase C-A-T and lowercase d-o on one path: two submitted words.
    b = _board(["catdo", "zzzzz", "zzzzz"])
    _put(b, 0, 3, "Letter", "d", 2, flags=["lowercase"])
    _put(b, 0, 4, "Letter", "o", 1, flags=["lowercase"])
    return b


def test_literary_saga_multiplies_by_word_count() -> None:
    b = _two_word_board()
    base = EnginePlan.build(b, Loadout()).score([0, 1, 2, 3, 4], "cat do").int_score
    saga = EnginePlan.build(b, _loadout(["literary_saga"])).score([0, 1, 2, 3, 4], "cat do").int_score
    assert saga == 2 * base
    # One word: no step at all.
    one = _board(["catzz", "zzzzz", "zzzzz"])
    assert (
        EnginePlan.build(one, _loadout(["literary_saga"])).score([0, 1, 2], "").int_score
        == EnginePlan.build(one, Loadout()).score([0, 1, 2], "").int_score
    )


def test_game_srep_font_keys_map_to_engine_tokens() -> None:
    from cursed_words_solver.engine.calc import SCATTER_EMOJI_SLUGS, game_srep_to_engine

    assert game_srep_to_engine("<font=NotoSansJPBold SDF>l</font>") == "<lower:l>"
    assert game_srep_to_engine("<font=NotoSansJPBold SDF>║</font>") == "<wire:║>"
    assert game_srep_to_engine("<font=NotoSansSymbols2-Regular SDF>⚂</font>") == "<dice:3>"
    assert game_srep_to_engine("<font=NotoSansCuneiform>\U00012199</font>") == "<hyper:\U00012199>"
    assert game_srep_to_engine("<font=NotoSansSymbols-VariableFont_wght SDF>♈</font>") == "<zodiac:♈>"
    emoji, slug = next(iter(SCATTER_EMOJI_SLUGS.items()))
    assert game_srep_to_engine(f"<font=TwemojiMozillaAll>{emoji}</font>") == f"<item:{slug}>"
    assert game_srep_to_engine("Q") == "q"


def test_rack_tiles_keep_their_game_tile() -> None:
    from cursed_words_solver.consumable_placement import consumable_rack_tiles

    game = [{"glyph": "Domino", "letter": "\U0001f03b", "value": 5, "type": "Normal", "flags": ["on_rack"]}]
    lo = Loadout(extras={
        "consumable_rack": json.dumps([{"letter": "?", "curse": "letter", "base_score": 5, "rack_index": 0}]),
        "consumable_rack_game_tiles": json.dumps(game),
    })
    (tile,) = consumable_rack_tiles(lo)
    raw = tile.metadata["game_tile"]
    assert raw["glyph"] == "Domino" and raw["letter"] == "\U0001f03b"
    assert "on_rack" not in raw["flags"] and "was_consumable" in raw["flags"]


def test_length_matrices_and_fast_match() -> None:
    from cursed_words_solver.engine import dlc_rules as R

    words = ["cab", "cat", "cot", "dog", "do", "a"]
    trie = CsrTrie.from_words(words)
    mats = R.length_matrices(trie)
    assert sorted(bytes(r).decode() for m in mats.values() for r in m) == sorted(words)
    assert [bytes(r).decode() for r in mats[3]] == ["cab", "cat", "cot", "dog"]
    # c ? t -> alphabetically first: "cat"; "" (bracket) tiles take no letter.
    assert R._match_by_length(trie, [False, True, False], [["c"], ["!"], ["t"]], [set(), set(), set()]) == "cat"
    assert R._match_by_length(trie, [False, False, False, False], [["d"], [""], ["o"], ["g"]], [set()] * 4) == "dog"
    assert R._match_by_length(trie, [False, False], [["z"], ["q"]], [set(), set()]) is None


def test_bracket_never_stands_for_a_letter() -> None:
    from cursed_words_solver.engine.dlc_search import DlcSearch
    from cursed_words_solver.engine.model import G_BRACKET
    from cursed_words_solver.engine.search import ExactSearch

    b = _board(["czt", "zzz", "zzz"])
    _put(b, 0, 1, "Bracket", "(", 0)
    s = ExactSearch(EnginePlan.build(b, Loadout()), CsrTrie.from_words(["cat", "ct"]))
    ds = DlcSearch(s)
    t = s.plan.grid.tiles[1]
    assert t.glyph == G_BRACKET
    wild, texts, _codes = ds._matcher(t, 1)
    assert wild is False and texts == [""]


def test_beam_finds_paths_when_enumeration_is_cut_short() -> None:
    from cursed_words_solver.engine.dlc_search import DlcSearch
    from cursed_words_solver.engine.search import _numpy_trie
    from cursed_words_solver.engine.search import ExactSearch

    b = _board(["catdo", "zzzzz", "zzzzz"])
    s = ExactSearch(EnginePlan.build(b, Loadout()), CsrTrie.from_words(["cat", "cats", "do"]))
    ds = DlcSearch(s)
    found = ds.beam(_numpy_trie(ds.es.trie), None, None, None, width=16)
    assert (0, 1, 2) in found


def test_mapping_summary_uses_engine_items() -> None:
    from cursed_words_solver.engine.scorer import EngineScorer

    lo = _loadout(["literary_saga"], ["turtle"], pin={"id": "tennis_ball", "levels": [1, 1]},
                  extras={"boss_modifiers": "[]"})
    scoring, total, grid_only, missing = EngineScorer().loadout_mapping_summary(lo)
    assert missing == []
    assert total == 3 and scoring + grid_only == 3
    unknown = _loadout([{"id": "not_a_real_item", "levels": [1]}])
    assert EngineScorer().loadout_mapping_summary(unknown)[3] == ["sticker:not_a_real_item"]


def test_boss_modifiers_json_string() -> None:
    from cursed_words_solver.rules.boss_effects import active_boss_ids

    assert active_boss_ids(Loadout(extras={"boss_modifiers": "[]"})) == []
    assert active_boss_ids(Loadout(extras={"boss_modifiers": '["capybara", "fox"]'})) == ["capybara", "fox"]
    assert active_boss_ids(Loadout(extras={"boss_modifiers": "capybara, fox"})) == ["capybara", "fox"]


def test_plain_rich_text_character_names() -> None:
    from cursed_words_solver.loadout import plain_rich_text

    assert plain_rich_text("Human Boy<sup>3</sup>") == "Human Boy³"
    assert plain_rich_text("<lowercase>RODMAN</lowercase>") == "rodman"
    assert plain_rich_text("<color=#F87470>B</color><color=#E7B158>e</color>ans") == "Beans"
    assert plain_rich_text("Na<font=NotoSansJPBold SDF>╦</font>H4") == "Na╦H4"
    assert plain_rich_text("Cretaceous Meg") == "Cretaceous Meg"


def test_f8_dice_result_carries_a_score_range() -> None:
    import types

    from cursed_words_solver import app as A
    from cursed_words_solver.engine.scorer import EngineScorer
    from tests.engine.test_dlc_items import DIE, ROWS

    cls = next(v for v in vars(A).values() if isinstance(v, type) and hasattr(v, "_score_top_with_capybara"))
    b = _board(ROWS)
    _put(b, 0, 0, "Dice", DIE[3], 3)
    fake = types.SimpleNamespace(_scoring=EngineScorer())
    score, bd, _trace, stats = cls._score_top_with_capybara(
        fake, b, types.SimpleNamespace(path=(0, 1, 2)), "", _loadout(["cricket_bat"])
    )
    assert stats is not None and stats.min_score < score < stats.max_score
    assert (bd["score_min"], bd["score_max"]) == (int(stats.min_score), int(stats.max_score))
