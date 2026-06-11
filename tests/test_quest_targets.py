"""Two Wrongs and Bullseye target math."""

from cursed_words_solver.models import Loadout
from cursed_words_solver.rules.quest_scoring import (
    effective_submit_score,
    remaining_target_after_submit,
    target_met,
    target_rescue_worth_trying_quest,
)


def test_two_wrongs_negates_submit_score() -> None:
    loadout = Loadout(extras={"challenge_game_class": "TwoWrongs"})
    assert effective_submit_score(120.0, loadout) == -120.0
    assert remaining_target_after_submit(500.0, 120.0, loadout) == 620.0


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
