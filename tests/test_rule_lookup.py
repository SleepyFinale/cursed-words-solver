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


def test_abacus_pin_alias_resolves_to_hayley_unmodeled():
    rules = {
        "aliases": {"pins": {"abacus": "hayley_bayles"}},
        "pins": {
            "hayley_bayles": {
                "name": "Hayley Bayles",
                "type": "unmodeled",
            }
        },
    }
    assert resolve_rule_id(rules, "pins", "abacus", "") == "hayley_bayles"
    assert get_pin_branch_rule(rules, "abacus", "left") is None


def test_hayley_pin_does_not_inflate_virge_score():
    pipeline = ScoringPipeline()
    from cursed_words_solver.loadout import parse_board_from_run_state
    import json
    from pathlib import Path

    path = Path.home() / ".cursed_words_solver" / "debug" / "parse_20260521_160425.json"
    if not path.exists():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    run_state = {
        "board": {
            "source": "melmod",
            "row_order": "top_first",
            "money": 6,
            "tiles": [
                {
                    "row": t["row"],
                    "col": t["col"],
                    "char": t["char"],
                    "letter": t["letter"],
                    "base_score": t["base_score"],
                    "color": t["color"],
                    "curse": t["curse"],
                }
                for t in data["tiles"]
            ],
        }
    }
    board = parse_board_from_run_state(run_state)
    loadout = Loadout(
        character="Hayley Bayles",
        pin_branch="left",
        extras={"pin_effect": "abacus"},
    )
    score, _ = pipeline.score(board, [21, 16, 17, 18, 24], "virge", loadout)
    assert score == 10.0


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


def test_pipeline_pin_branch_affects_score():
    pipeline = ScoringPipeline()
    from cursed_words_solver.models import Board, Tile, TileColor, CurseType

    def tile(ch: str, row: int, col: int) -> Tile:
        return Tile(
            row=row,
            col=col,
            char=ch,
            letter=ch,
            base_score=1,
            color=TileColor.COLORLESS,
            curse=CurseType.LETTER,
        )

    board = Board(
        tiles=[[tile("c", r, c) for c in range(5)] for r in range(5)],
        money=0,
    )
    loadout_left = Loadout(extras={"pin_effect": "beans"}, pin_branch="left")
    loadout_right = Loadout(extras={"pin_effect": "beans"}, pin_branch="right")

    score_left, _ = pipeline.score(board, [0, 1, 2], "cat", loadout_left)
    score_right, _ = pipeline.score(board, [0, 1, 2], "cat", loadout_right)
    assert score_left != score_right
