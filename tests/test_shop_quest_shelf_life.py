"""Shelf Life (DecisionParalysis) blocks restock advice."""

from cursed_words_solver.game_shop.advice_resolve import resolve_advice_actions
from cursed_words_solver.game_shop.types import (
    AdviceData,
    ItemTag,
    ShopAdviceContext,
    player_should_restock,
)
from cursed_words_solver.models import Loadout
from cursed_words_solver.shop_advisor import run_shop_advisor
from cursed_words_solver.models import ShopState


def test_shelf_life_blocks_restock_in_resolve() -> None:
    advice = AdviceData(build=ItemTag.BLUE_BUILD, recommended_items=[])
    ctx = ShopAdviceContext(
        money=20,
        sticker_count=1,
        stamp_count=1,
        tile_count=0,
        inventory=[],
        shop_items=[],
        shop_tiles=[],
        restock_cost=2,
        free_item_available=False,
        block_restock=True,
    )
    assert player_should_restock(ctx.money, ctx.restock_cost)
    out = resolve_advice_actions(advice, ctx, free_item_active=False)
    assert not out.should_restock
    assert out.should_leave


def test_shelf_life_advisor_no_restock() -> None:
    loadout = Loadout(
        money=20,
        extras={"challenge_game_class": "DecisionParalysis"},
    )
    shop = ShopState(restock_cost=2, offers=[])
    advice = run_shop_advisor(loadout, shop)
    assert advice.restock is None
