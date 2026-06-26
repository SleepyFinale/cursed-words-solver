"""The Bones Round poker bonus scoring."""

from cursed_words_solver.models import Board, CurseType, Loadout, Tile, TileColor
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.quest_scoring import (
    apply_bones_round_early_bonus,
    bones_round_poker_bonus,
    zero_tile_scores_for_bones,
)


def _card(idx: int, rank: str, suit: str) -> Tile:
    row, col = divmod(idx, 5)
    return Tile(
        row=row,
        col=col,
        char=rank,
        letter=rank,
        base_score=5,
        color=TileColor.COLORLESS,
        curse=CurseType.LETTER,
        metadata={"card_rank": rank, "card_suit": suit},
    )


def test_bones_round_zeros_tiles_and_adds_pair_bonus() -> None:
    path = [0, 1, 2]
    ranks = ["2", "2", "3"]
    grid: list[list[Tile]] = []
    for r in range(5):
        row: list[Tile] = []
        for c in range(5):
            idx = r * 5 + c
            if idx < len(ranks):
                row.append(_card(idx, ranks[idx], "hearts"))
            else:
                row.append(
                    Tile(
                        row=r,
                        col=c,
                        char="x",
                        letter="x",
                        base_score=1,
                        color=TileColor.COLORLESS,
                        curse=CurseType.LETTER,
                    )
                )
        grid.append(row)
    board = Board(tiles=grid, money=0)
    loadout = Loadout(extras={"challenge_game_class": "TheBonesRound"})
    state = {"tile_scores": [5.0, 5.0, 5.0], "word_score": 0.0}
    zero_tile_scores_for_bones(state)
    assert sum(state["tile_scores"]) == 0.0
    bonus, hand = bones_round_poker_bonus(board, path, loadout)
    assert hand in ("pair", "two_pair", "three_of_a_kind", "high_card")
    state = apply_bones_round_early_bonus(state, board, path, loadout)
    assert state.get("bones_poker_bonus", 0) >= 0


def test_bones_round_early_bonus_trace_step_receives_state() -> None:
    path = [0, 1, 2]
    ranks = ["2", "2", "3"]
    grid: list[list[Tile]] = []
    for r in range(5):
        row: list[Tile] = []
        for c in range(5):
            idx = r * 5 + c
            if idx < len(ranks):
                row.append(_card(idx, ranks[idx], "hearts"))
            else:
                row.append(
                    Tile(
                        row=r,
                        col=c,
                        char="x",
                        letter="x",
                        base_score=1,
                        color=TileColor.COLORLESS,
                        curse=CurseType.LETTER,
                    )
                )
        grid.append(row)
    board = Board(tiles=grid, money=0)
    loadout = Loadout(extras={"challenge_game_class": "TheBonesRound"})
    state: dict = {"tile_scores": [0.0, 0.0, 0.0], "word_score": 0.0, "_trace": []}
    calls: list[tuple] = []

    def trace_step(st, phase, **kwargs):
        calls.append((st, phase, kwargs))

    apply_bones_round_early_bonus(state, board, path, loadout, trace_step=trace_step)
    assert len(calls) == 1
    st, phase, kwargs = calls[0]
    assert st is state
    assert phase == "quest_bones_poker"
    assert "hand" in kwargs
    assert "bonus" in kwargs


def test_bones_round_score_with_trace_does_not_crash() -> None:
    path = [0, 1, 2]
    ranks = ["2", "2", "3"]
    grid: list[list[Tile]] = []
    for r in range(5):
        row: list[Tile] = []
        for c in range(5):
            idx = r * 5 + c
            if idx < len(ranks):
                row.append(_card(idx, ranks[idx], "hearts"))
            else:
                row.append(
                    Tile(
                        row=r,
                        col=c,
                        char="x",
                        letter="x",
                        base_score=1,
                        color=TileColor.COLORLESS,
                        curse=CurseType.LETTER,
                    )
                )
        grid.append(row)
    board = Board(tiles=grid, money=0)
    loadout = Loadout(extras={"challenge_game_class": "TheBonesRound"})
    score, _bd, trace = ScoringPipeline().score_with_trace(board, path, "223", loadout)
    assert score >= 0
    assert trace is not None
    poker_steps = [s for s in trace if s.get("phase") == "quest_bones_poker"]
    assert len(poker_steps) == 1
    assert poker_steps[0].get("bonus", 0) >= 0


def test_bones_round_letter_cards_group_by_spelled_letter() -> None:
    """Regression: serenities — N,I,T,I,S suited letters are pair of I, not rank-0 x-of-a-kind."""
    from cursed_words_solver.models import LoadoutItem
    from cursed_words_solver.rules.quest_scoring import detect_poker_hand
    from cursed_words_solver.rules.scoring_conditions import card_suit

    path = [23, 19, 14, 13, 7, 1, 5, 11, 16, 17]
    rows = [
        "AIAUS",
        "TRNTE",
        "AINER",
        "EESPE",
        "LGXSA",
    ]
    suited = {
        7: ("N", "clubs"),
        1: ("I", "diamonds"),
        5: ("T", "spades"),
        11: ("I", "diamonds"),
        17: ("S", "clubs"),
    }
    grid: list[list[Tile]] = []
    for r, row_chars in enumerate(rows):
        row_tiles: list[Tile] = []
        for c, ch in enumerate(row_chars):
            idx = r * 5 + c
            meta: dict = {}
            if idx in suited:
                rank, suit = suited[idx]
                meta = {"card_rank": rank, "card_suit": suit}
            row_tiles.append(
                Tile(
                    row=r,
                    col=c,
                    char=ch.lower(),
                    letter=ch,
                    base_score=0,
                    color=TileColor.COLORLESS,
                    curse=CurseType.LETTER,
                    metadata=meta,
                )
            )
        grid.append(row_tiles)
    board = Board(tiles=grid, money=6)
    cards = [board.get_by_index(i) for i in path if card_suit(board.get_by_index(i))]
    hand, _ = detect_poker_hand(cards)
    assert hand == "pair"

    loadout = Loadout(
        extras={
            "challenge_game_class": "TheBonesRound",
            "pin_effect": "bicycle",
            "bicycle_word_score_bonus": "2",
            "cards_submitted": "2",
        },
        stickers=[
            LoadoutItem(id="postal_horn", name="Postal Horn", level=1),
            LoadoutItem(id="poker_face", name="Poker Face", level=1),
        ],
    )
    bonus, hand_name = bones_round_poker_bonus(board, path, loadout)
    assert hand_name == "pair"
    assert bonus == 20
    score, _, trace = ScoringPipeline().score_with_trace(
        board, path, "serenities", loadout
    )
    assert int(score) == 26
    poker_steps = [s for s in trace if s.get("phase") == "quest_bones_poker"]
    assert poker_steps and poker_steps[0].get("hand") == "pair"
