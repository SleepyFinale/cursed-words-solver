"""Shop quest constraint dataclass per game class."""

from cursed_words_solver.models import Loadout
from cursed_words_solver.rules.shop_quest_effects import shop_quest_constraints


def test_shelf_life_blocks_restock() -> None:
    q = shop_quest_constraints(
        Loadout(extras={"challenge_game_class": "DecisionParalysis"})
    )
    assert q.block_restock
    assert not q.block_sell


def test_embargo_blocks_sell() -> None:
    q = shop_quest_constraints(
        Loadout(
            extras={
                "challenge_game_class": "Embargo",
                "embargoed_item_types": "Blueberries",
            }
        )
    )
    assert q.block_sell
    assert "Blueberries" in q.embargoed_game_classes


def test_masochist_disables_sticker_shop() -> None:
    q = shop_quest_constraints(
        Loadout(extras={"challenge_game_class": "Masochist"})
    )
    assert not q.sticker_shop_enabled
    assert q.stamp_shop_enabled


def test_antiphilatelist_disables_stamp_shop() -> None:
    q = shop_quest_constraints(
        Loadout(extras={"challenge_game_class": "Antiphilatelist"})
    )
    assert q.sticker_shop_enabled
    assert not q.stamp_shop_enabled


def test_in_the_beginning_disables_both() -> None:
    q = shop_quest_constraints(
        Loadout(extras={"challenge_game_class": "InTheBeginning"})
    )
    assert not q.sticker_shop_enabled
    assert not q.stamp_shop_enabled


def test_secret_santa_flag() -> None:
    q = shop_quest_constraints(
        Loadout(extras={"challenge_game_class": "SecretSanta"})
    )
    assert q.secret_santa


def test_do_not_pass_go_zero_rewards() -> None:
    q = shop_quest_constraints(
        Loadout(extras={"challenge_game_class": "DoNotPassGo"})
    )
    assert q.zero_encounter_rewards


def test_encounter_reward_for_quest() -> None:
    from cursed_words_solver.rules.quest_scoring import encounter_reward_for_quest

    loadout = Loadout(extras={"challenge_game_class": "DoNotPassGo"})
    assert encounter_reward_for_quest(loadout, 5) == 0
    assert encounter_reward_for_quest(Loadout(), 5) == 5
