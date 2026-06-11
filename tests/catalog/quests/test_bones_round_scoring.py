"""The Bones Round poker bonus scoring."""

from cursed_words_solver.models import Board, CurseType, Loadout, Tile, TileColor
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
