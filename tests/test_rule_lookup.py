from cursed_words_solver.models import Loadout, LoadoutItem
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.rule_lookup import (
    collect_unmapped_items,
    get_pin_branch_rule,
    resolve_rule_id,
)


def test_resolve_rule_id_with_alias():
    rules = {
        "aliases": {"stickers": {"stickyplaster": "sticky_plaster"}},
        "stickers": {
            "sticky_plaster": {"name": "Sticky Plaster", "type": "unmodeled"},
        },
    }
    assert resolve_rule_id(rules, "stickers", "stickyplaster", "") == "sticky_plaster"


def test_collect_unmapped_items():
    rules = {
        "stickers": {"known": {"type": "add_word_score", "value": 1}},
        "stamps": {},
        "bosses": {},
        "pins": {},
        "aliases": {},
    }
    loadout = Loadout(
        stickers=[LoadoutItem(id="unknown_x", name="Unknown X", kind="sticker")],
        stamps=[LoadoutItem(id="known", name="Known", kind="stamp")],
    )
    missing = collect_unmapped_items(rules, loadout)
    assert "sticker:unknown_x" in missing
    assert "stamp:known" in missing


def test_abacus_pin_alias_resolves_to_scoring_rule():
    rules = {
        "aliases": {"pins": {"abacus": "abacus", "hayley_bayles": "abacus"}},
        "pins": {
            "abacus": {
                "name": "Abacus",
                "type": "colored_number_tile_bonus",
                "value": 10,
            }
        },
    }
    assert resolve_rule_id(rules, "pins", "abacus", "") == "abacus"
    assert get_pin_branch_rule(rules, "abacus", "left") is not None


def test_abacus_pin_no_bonus_without_coloured_numbers_on_path():
    pipeline = ScoringPipeline()
    from cursed_words_solver.models import Board, Tile, TileColor, CurseType

    def tile(ch: str, row: int, col: int) -> Tile:
        return Tile(
            row=row,
            col=col,
            char=ch,
            letter=ch,
            base_score=2,
            color=TileColor.COLORLESS,
            curse=CurseType.LETTER,
            metadata={"source": "melmod"},
        )

    board = Board(
        tiles=[[tile("v", r, c) for c in range(5)] for r in range(5)],
        money=0,
    )
    loadout = Loadout(
        character="Hayley Bayles",
        pin_branch="left",
        extras={"pin_effect": "abacus"},
    )
    score, _ = pipeline.score(board, [0, 1, 2, 3, 4], "virge", loadout)
    base, _ = pipeline.score(board, [0, 1, 2, 3, 4], "virge", Loadout())
    assert score == base


def test_pin_branch_rule_left():
    rules = {
        "pins": {
            "beans": {
                "branches": {
                    "left": {"type": "add_word_score", "value": 5},
                    "right": {"type": "multiply", "factor": 2.0},
                }
            }
        }
    }
    left = get_pin_branch_rule(rules, "beans", "left")
    right = get_pin_branch_rule(rules, "beans", "right")
    assert left["value"] == 5
    assert right["factor"] == 2.0


def test_pipeline_brain_level_affects_multiplier():
    pipeline = ScoringPipeline()
    from cursed_words_solver.models import Board, Tile, CurseType

    board = Board(
        tiles=[
            [
                Tile(0, 0, "4", "4", 4, curse=CurseType.NUMBER, number_value=4),
                Tile(0, 1, "5", "5", 5, curse=CurseType.NUMBER, number_value=5),
                Tile(0, 2, "6", "6", 6, curse=CurseType.NUMBER, number_value=6),
            ]
            + [Tile(0, c, "A", "A", 1) for c in range(3, 5)]
        ]
        + [[Tile(r, c, "T", "T", 1) for c in range(5)] for r in range(1, 5)],
        money=0,
    )
    loadout_l1 = Loadout(
        stickers=[LoadoutItem(id="brain", name="Brain", level=1, kind="sticker")]
    )
    loadout_l2 = Loadout(
        stickers=[LoadoutItem(id="brain", name="Brain", level=2, kind="sticker")]
    )
    score_l1, _ = pipeline.score(board, [0, 1, 2], "456", loadout_l1)
    score_l2, _ = pipeline.score(board, [0, 1, 2], "456", loadout_l2)
    assert score_l2 > score_l1
