"""Two Wrongs and Bullseye target math."""

from cursed_words_solver.models import Loadout
from cursed_words_solver.rules.quest_scoring import (
    display_score_for_quest,
    effective_submit_score,
    quest_rank_beats_baseline,
    remaining_target_after_submit,
    search_rank_for_quest,
    target_met,
    target_rescue_worth_trying_quest,
)


def test_two_wrongs_negates_submit_score() -> None:
    loadout = Loadout(extras={"challenge_game_class": "TwoWrongs"})
    assert effective_submit_score(120.0, loadout) == -120.0
    assert remaining_target_after_submit(500.0, 120.0, loadout) == 620.0


def test_two_wrongs_ibex_regresses_target() -> None:
    loadout = Loadout(extras={"challenge_game_class": "TwoWrongs"})
    assert remaining_target_after_submit(12.0, 53.0, loadout) == 65.0
    assert not target_met(53.0, 12.0, loadout)
    assert target_met(-53.0, 12.0, loadout)


def test_two_wrongs_search_rank_inverted() -> None:
    loadout = Loadout(extras={"challenge_game_class": "TwoWrongs"})
    assert search_rank_for_quest(53.0, loadout) == -53.0
    assert search_rank_for_quest(3.0, loadout) == -3.0
    assert quest_rank_beats_baseline(3.0, 53.0, loadout)
    assert not quest_rank_beats_baseline(53.0, 3.0, loadout)


def test_two_wrongs_display_score() -> None:
    loadout = Loadout(extras={"challenge_game_class": "TwoWrongs"})
    assert display_score_for_quest(53.0, loadout) == -53.0


def test_two_wrongs_rescue_worth_trying_positive_baseline() -> None:
    loadout = Loadout(extras={"challenge_game_class": "TwoWrongs"})
    assert target_rescue_worth_trying_quest(53.0, 12, loadout)
    assert not target_rescue_worth_trying_quest(0.0, 12, loadout)


def test_bullseye_exact_hit() -> None:
    loadout = Loadout(extras={"challenge_game_class": "Bullseye"})
    assert remaining_target_after_submit(100.0, 80.0, loadout) == 20.0
    assert remaining_target_after_submit(100.0, 100.0, loadout) == 0.0
    assert target_met(100.0, 100.0, loadout)
    assert not target_met(99.0, 100.0, loadout)


def test_target_rescue_worth_trying_bullseye() -> None:
    loadout = Loadout(extras={"challenge_game_class": "Bullseye"})
    assert target_rescue_worth_trying_quest(50.0, 100, loadout)
    assert not target_rescue_worth_trying_quest(100.0, 100, loadout)
