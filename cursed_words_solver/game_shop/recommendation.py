"""Port of ShopRecommendation from Assembly-CSharp."""

from __future__ import annotations

from cursed_words_solver.game_shop.advice_resolve import (
    advice_summary,
    resolve_advice_actions,
)
from cursed_words_solver.game_shop.types import (
    AdviceData,
    BuildData,
    GameShopItem,
    GameShopTile,
    ItemFunction,
    ItemFunctionTag,
    ItemTag,
    ShopAdviceContext,
)
from cursed_words_solver.game_shop.utility_advice import high_priority_utility_advice
from cursed_words_solver.models import Loadout, ShopOffer, ShopState
from cursed_words_solver.game_shop.metadata import lookup_metadata_for_slug

_DEFAULT_UNLOCKS = frozenset(
    {"numbers", "chess", "cards", "cursed"}
)

_BASE_SYNERGY_TAGS = [
    ItemTag.BLUE_BUILD,
    ItemTag.RED_BUILD,
    ItemTag.VOID_BUILD,
    ItemTag.SHINY_BUILD,
    ItemTag.BLANK_BUILD,
    ItemTag.COLOURLESS_BUILD,
    ItemTag.RAINBOW_BUILD,
    ItemTag.CONSUMABLE_BUILD,
    ItemTag.NO_BUILD,
    ItemTag.CASH_BUILD,
    ItemTag.SCATTERED_ITEMS_BUILD,
]

_UNLOCK_TAG_MAP = {
    "numbers": (ItemTag.NUMBERS_BUILD, ItemTag.BIG_NUMBERS_BUILD),
    "chess": (ItemTag.CHESS_BUILD,),
    "cards": (ItemTag.CARDS_BUILD,),
    "cursed": (ItemTag.CURSE_BUILD,),
}


def get_build_synergy_tags(unlocks: frozenset[str] | None = None) -> list[ItemTag]:
    tags = list(_BASE_SYNERGY_TAGS)
    active = unlocks if unlocks is not None else _DEFAULT_UNLOCKS
    for key, extra in _UNLOCK_TAG_MAP.items():
        if key in active:
            tags.extend(extra)
    return tags


def item_fulfills_function(item: GameShopItem, function: ItemFunction) -> bool:
    return item.fulfills_function(function)


def get_function_tag_counts(inventory: list[GameShopItem]) -> dict[ItemFunction, int]:
    counts = {
        ItemFunction.MULTIPLIER: 0,
        ItemFunction.ADDITIVE: 0,
        ItemFunction.SCATTERER: 0,
        ItemFunction.OTHER: 0,
        ItemFunction.SCORING: 0,
    }
    for func in counts:
        for item in inventory:
            if item_fulfills_function(item, func):
                counts[func] += 1
    return counts


def get_most_common_builds(
    inventory: list[GameShopItem],
    *,
    unlocks: frozenset[str] | None = None,
) -> list[ItemTag]:
    synergy = {t.value for t in get_build_synergy_tags(unlocks)}
    counts: dict[ItemTag, int] = {}
    for item in inventory:
        for tag_name in item.shop_advice_tags:
            if tag_name not in synergy:
                continue
            tag = ItemTag(tag_name)
            counts[tag] = counts.get(tag, 0) + 1
    if not counts:
        return []
    max_count = max(counts.values())
    return [tag for tag, n in counts.items() if n == max_count]


def get_build_data_for_build(
    build_tag: ItemTag,
    inventory: list[GameShopItem],
) -> BuildData:
    relevant: list[GameShopItem] = []
    for item in inventory:
        if build_tag.value in item.shop_advice_tags:
            relevant.append(item)
            continue
        if ItemFunctionTag.GENERIC_ADDITIVE.value in item.function_tags:
            relevant.append(item)
            continue
        if ItemFunctionTag.GENERIC_MULTIPLIER.value in item.function_tags:
            relevant.append(item)
    return BuildData(
        build_tag=build_tag,
        relevant_items=relevant,
        function_tag_counts=get_function_tag_counts(relevant),
    )


def get_items_fulfilling_function_for_build(
    shop_items: list[GameShopItem],
    build: ItemTag,
    function: ItemFunction,
) -> list[GameShopItem]:
    return [
        item
        for item in shop_items
        if item.has_build_tag(build) and item_fulfills_function(item, function)
    ]


def get_items_fulfilling_functions_for_build(
    shop_items: list[GameShopItem],
    build: ItemTag,
    functions: list[ItemFunction],
) -> dict[ItemFunction, list[GameShopItem]]:
    return {
        func: get_items_fulfilling_function_for_build(shop_items, build, func)
        for func in functions
    }


def get_non_scatter_items_for_build(
    shop_items: list[GameShopItem],
    build: ItemTag,
) -> list[GameShopItem]:
    return [
        item
        for item in shop_items
        if item.has_build_tag(build)
        and item_fulfills_function(item, ItemFunction.BUILD)
        and ItemFunctionTag.SCATTERER.value not in item.function_tags
    ]


def get_generic_items_fulfilling_function(
    shop_items: list[GameShopItem],
    function: ItemFunction,
) -> list[GameShopItem]:
    result: list[GameShopItem] = []
    if function in {ItemFunction.ADDITIVE, ItemFunction.SCORING}:
        result.extend(
            i
            for i in shop_items
            if ItemFunctionTag.GENERIC_ADDITIVE.value in i.function_tags
        )
    if function in {ItemFunction.MULTIPLIER, ItemFunction.SCORING}:
        result.extend(
            i
            for i in shop_items
            if ItemFunctionTag.GENERIC_MULTIPLIER.value in i.function_tags
        )
    return result


def _inventory_ids(inventory: list[GameShopItem]) -> set[str]:
    return {(i.id or "").lower() for i in inventory}


def _filter_owned_upgrades(
    advice_list: list[AdviceData],
    inventory: list[GameShopItem],
) -> list[AdviceData]:
    inv_ids = _inventory_ids(inventory)
    if not any(
        any((i.id or "").lower() in inv_ids for i in a.recommended_items)
        for a in advice_list
    ):
        return advice_list
    filtered: list[AdviceData] = []
    for advice in advice_list:
        matches = [
            i
            for i in advice.recommended_items
            if (i.id or "").lower() in inv_ids
        ]
        if matches:
            advice.recommended_items = matches
            advice.is_upgrade = True
            filtered.append(advice)
    return filtered


def _prefer_non_empty(advice_list: list[AdviceData]) -> list[AdviceData]:
    if any(a.recommended_items for a in advice_list):
        return [a for a in advice_list if a.recommended_items]
    return advice_list


def _prefer_build_specific(advice_list: list[AdviceData]) -> list[AdviceData]:
    if any(not a.is_generic for a in advice_list):
        return [a for a in advice_list if not a.is_generic]
    return advice_list


def baseline_build_functions_advice_data(
    builds: list[BuildData],
    shop_items: list[GameShopItem],
    is_free_item: bool,
    inventory: list[GameShopItem],
) -> list[AdviceData]:
    priority = [
        ItemFunction.SCATTERER,
        ItemFunction.SCORING,
        ItemFunction.ADDITIVE,
        ItemFunction.MULTIPLIER,
    ]
    result: list[AdviceData] = []
    for build in builds:
        for func in priority:
            if build.function_tag_counts.get(func, 0) != 0:
                continue
            matches = get_items_fulfilling_function_for_build(
                shop_items, build.build_tag, func
            )
            if matches:
                result.append(
                    AdviceData(
                        build=build.build_tag,
                        recommended_items=matches,
                        function_fulfilled=func,
                    )
                )
                break
            matches = list(
                get_generic_items_fulfilling_function(shop_items, func)
            )
            if matches:
                result.append(
                    AdviceData(
                        build=ItemTag.NO_BUILD if is_free_item else build.build_tag,
                        recommended_items=matches,
                        is_generic=True,
                        function_fulfilled=func,
                    )
                )
            elif is_free_item:
                any_build = get_items_fulfilling_function_for_build(
                    shop_items, build.build_tag, ItemFunction.BUILD
                )
                result.append(
                    AdviceData(
                        build=build.build_tag if any_build else ItemTag.NO_BUILD,
                        recommended_items=any_build,
                        function_fulfilled=ItemFunction.BUILD,
                    )
                )
            else:
                result.append(
                    AdviceData(
                        build=build.build_tag,
                        recommended_items=[],
                        function_fulfilled=func,
                    )
                )
            break
    result = _prefer_non_empty(result)
    result = _prefer_build_specific(result)
    return _filter_owned_upgrades(result, inventory)


def build_upgrades_advice_data(
    builds: list[BuildData],
    shop_items: list[GameShopItem],
) -> list[AdviceData]:
    result: list[AdviceData] = []
    for build in builds:
        owned_types = {(i.id or "").lower() for i in build.relevant_items}
        matches = [
            item for item in shop_items if (item.id or "").lower() in owned_types
        ]
        if matches:
            result.append(
                AdviceData(
                    build=build.build_tag,
                    recommended_items=matches,
                    is_upgrade=True,
                )
            )
    return result


def high_priority_utility_advice_data(
    builds: list[BuildData],
    shop_items: list[GameShopItem],
    ctx: ShopAdviceContext,
) -> list[AdviceData]:
    result: list[AdviceData] = []
    for item in shop_items:
        advice = high_priority_utility_advice(item, ctx, builds)
        if advice is not None:
            result.append(advice)
    return result


def low_priority_utility_advice_data(
    builds: list[BuildData],
    shop_items: list[GameShopItem],
    ctx: ShopAdviceContext,
) -> list[AdviceData]:
    return []


def build_functions_advice_to_level(
    builds: list[BuildData],
    shop_items: list[GameShopItem],
    level: int,
    *,
    is_forcing_recommendation: bool,
    inventory: list[GameShopItem],
) -> list[AdviceData]:
    funcs = [
        ItemFunction.ADDITIVE,
        ItemFunction.MULTIPLIER,
        ItemFunction.SCATTERER,
    ]
    result: list[AdviceData] = []
    for build in builds:
        for i in range(1, level + 1):
            scatter_cap = min(i, 2)
            sc = build.function_tag_counts
            if (
                sc.get(ItemFunction.SCATTERER, 0) <= scatter_cap
                and sc.get(ItemFunction.SCATTERER, 0)
                == sc.get(ItemFunction.ADDITIVE, 0)
                == sc.get(ItemFunction.MULTIPLIER, 0)
            ):
                matches = get_items_fulfilling_function_for_build(
                    shop_items, build.build_tag, ItemFunction.BUILD
                )
                if matches:
                    result.append(
                        AdviceData(
                            build=build.build_tag,
                            recommended_items=matches,
                            function_fulfilled=ItemFunction.BUILD,
                        )
                    )
                    break
            if (
                sc.get(ItemFunction.SCATTERER, 0) > scatter_cap
                and sc.get(ItemFunction.ADDITIVE, 0) >= 2
                and sc.get(ItemFunction.MULTIPLIER, 0) >= 2
                and i > 2
            ):
                matches = get_non_scatter_items_for_build(shop_items, build.build_tag)
                if matches:
                    result.append(
                        AdviceData(
                            build=build.build_tag,
                            recommended_items=matches,
                            function_fulfilled=ItemFunction.BUILD,
                        )
                    )
                    break
            unfulfilled = [
                f
                for f in funcs
                if sc.get(f, 0) < i and (f != ItemFunction.SCATTERER or i <= 2)
            ]
            by_func = get_items_fulfilling_functions_for_build(
                shop_items, build.build_tag, unfulfilled
            )
            found = False
            for func, matches in by_func.items():
                if matches:
                    result.append(
                        AdviceData(
                            build=build.build_tag,
                            recommended_items=matches,
                            function_fulfilled=func,
                        )
                    )
                    found = True
            if found:
                break
            for func in unfulfilled:
                generic = get_generic_items_fulfilling_function(shop_items, func)
                if generic:
                    result.append(
                        AdviceData(
                            build=build.build_tag,
                            recommended_items=generic,
                            is_generic=True,
                            function_fulfilled=func,
                        )
                    )
                    break
                if sc.get(ItemFunction.OTHER, 0) <= 2:
                    utility = get_items_fulfilling_function_for_build(
                        shop_items, build.build_tag, ItemFunction.OTHER
                    )
                    if utility:
                        result.append(
                            AdviceData(
                                build=build.build_tag,
                                recommended_items=utility,
                                function_fulfilled=ItemFunction.BUILD,
                            )
                        )
                        break
        if is_forcing_recommendation:
            least: list[ItemFunction] = []
            min_count = 9999
            for func in funcs:
                count = sc.get(func, 0)
                if func == ItemFunction.SCATTERER and count >= 3:
                    continue
                if count < min_count:
                    least = [func]
                    min_count = count
                elif count == min_count:
                    least.append(func)
            if len(least) == 1:
                result.append(
                    AdviceData(
                        build=build.build_tag,
                        recommended_items=[],
                        function_fulfilled=least[0],
                    )
                )
            elif len(least) == 3:
                result.append(
                    AdviceData(
                        build=build.build_tag,
                        recommended_items=[],
                        function_fulfilled=ItemFunction.BUILD,
                    )
                )
            elif (
                ItemFunction.ADDITIVE in least and ItemFunction.MULTIPLIER in least
            ):
                result.append(
                    AdviceData(
                        build=build.build_tag,
                        recommended_items=[],
                        function_fulfilled=ItemFunction.SCORING,
                    )
                )
            elif least:
                result.append(
                    AdviceData(
                        build=build.build_tag,
                        recommended_items=[],
                        function_fulfilled=least[0],
                    )
                )
    result = _prefer_non_empty(result)
    result = _prefer_build_specific(result)
    return _filter_owned_upgrades(result, inventory)


def _tile_matches_build(tile: GameShopTile, build: ItemTag) -> bool:
    color = (tile.color or "").lower()
    curse = (tile.curse or "").lower()
    if build == ItemTag.BLUE_BUILD:
        return color == "blue"
    if build == ItemTag.RED_BUILD:
        return color == "red"
    if build == ItemTag.VOID_BUILD:
        return color == "void"
    if build == ItemTag.SHINY_BUILD:
        return color == "shiny"
    if build == ItemTag.RAINBOW_BUILD:
        return color in {"shiny", "colorless", "colourless", "normal"}
    if build == ItemTag.CHESS_BUILD:
        return "chess" in curse or curse in {
            "chess_king",
            "chess_queen",
            "chess_rook",
            "chess_bishop",
            "chess_knight",
            "chess_pawn",
        }
    if build == ItemTag.BLANK_BUILD:
        return curse in {"wildcard", "blank"} or "?" in (tile.letter or "")
    if build == ItemTag.CASH_BUILD:
        return curse == "currency"
    if build == ItemTag.NUMBERS_BUILD:
        return curse in {"number", "fraction"}
    if build == ItemTag.ARROW_BUILD:
        return curse == "arrow"
    if build == ItemTag.SCATTERED_ITEMS_BUILD:
        return curse == "item"
    if build == ItemTag.CURSE_BUILD:
        return curse not in {"", "letter", "colorless", "currency"}
    if build == ItemTag.CARDS_BUILD:
        return curse in {"card", "bespoke_card", "joker"} or "card" in curse
    if build == ItemTag.CONSUMABLE_BUILD:
        return True
    return False


def affordable_build_relevant_tiles(
    build: BuildData,
    shop_tiles: list[GameShopTile],
    *,
    money: int,
    tile_count: int,
) -> list[GameShopTile]:
    if tile_count >= 5:
        return []
    return [
        tile
        for tile in shop_tiles
        if not tile.sold
        and tile.price <= money
        and _tile_matches_build(tile, build.build_tag)
    ]


def get_tile_advice_data(
    builds: list[BuildData],
    shop_tiles: list[GameShopTile],
    *,
    money: int,
    tile_count: int,
) -> list[AdviceData]:
    result: list[AdviceData] = []
    for build in builds:
        tiles = affordable_build_relevant_tiles(
            build, shop_tiles, money=money, tile_count=tile_count
        )
        if tiles:
            advice = AdviceData(
                build=build.build_tag,
                recommended_tiles=tiles,
                function_fulfilled=ItemFunction.TILE,
                should_buy=True,
            )
            result.append(advice)
    return result


def select_advice_tier(
    ctx: ShopAdviceContext,
    *,
    advice_index: int = 0,
) -> AdviceData:
    shop_items = [i for i in ctx.shop_items if not i.blacklisted]
    builds = [
        get_build_data_for_build(tag, ctx.inventory)
        for tag in get_most_common_builds(ctx.inventory, unlocks=ctx.unlocks)
    ]
    free_item = ctx.free_item_available

    baseline = baseline_build_functions_advice_data(
        builds, shop_items, free_item, ctx.inventory
    )
    upgrades = build_upgrades_advice_data(builds, shop_items)
    utility_hi = high_priority_utility_advice_data(builds, shop_items, ctx)

    if not any(a.recommended_items for a in baseline) and (
        any(a.recommended_items for a in upgrades)
        or any(a.recommended_items for a in utility_hi)
    ):
        baseline = []

    level2 = build_functions_advice_to_level(
        builds, shop_items, 2, is_forcing_recommendation=False, inventory=ctx.inventory
    )
    level_low = low_priority_utility_advice_data(builds, shop_items, ctx)
    level_tiles = get_tile_advice_data(
        builds,
        ctx.shop_tiles,
        money=ctx.money,
        tile_count=ctx.tile_count,
    )
    level10 = build_functions_advice_to_level(
        builds,
        shop_items,
        10,
        is_forcing_recommendation=True,
        inventory=ctx.inventory,
    )
    no_build = [AdviceData(build=ItemTag.NO_BUILD, recommended_items=[])]

    tiers = [
        baseline,
        upgrades,
        utility_hi,
        level2,
        level_low + level_tiles,
        level10,
        no_build,
    ]
    for tier in tiers:
        if tier:
            return tier[advice_index % len(tier)]
    return AdviceData(build=ItemTag.NO_BUILD, recommended_items=[])


def _game_item_from_offer(offer: ShopOffer) -> GameShopItem:
    meta = lookup_metadata_for_slug(offer.id or "")
    tags = frozenset(meta.shop_advice_tags if meta else ())
    func_tags = frozenset(meta.function_tags if meta else ())
    blacklisted = meta.blacklisted_from_shop_recommendations if meta else False
    return GameShopItem(
        id=offer.id or "",
        name=offer.name or offer.id or "Item",
        slot=offer.slot,
        index=offer.index,
        price=max(0, offer.price),
        shop_advice_tags=tags,
        function_tags=func_tags,
        blacklisted=blacklisted,
    )


def _game_item_from_loadout_item(item_id: str, name: str, slot: str) -> GameShopItem:
    meta = lookup_metadata_for_slug(item_id)
    tags = frozenset(meta.shop_advice_tags if meta else ())
    func_tags = frozenset(meta.function_tags if meta else ())
    return GameShopItem(
        id=item_id,
        name=name or item_id,
        slot=slot,
        index=-1,
        price=0,
        shop_advice_tags=tags,
        function_tags=func_tags,
    )


def _tile_from_offer(offer: ShopOffer) -> GameShopTile:
    return GameShopTile(
        index=offer.index,
        price=max(0, offer.price),
        color=offer.color or "",
        curse=offer.curse or "",
        letter=offer.letter or "",
        sold=offer.sold,
    )


def _tile_count_from_loadout(loadout: Loadout) -> int:
    extras = loadout.extras or {}
    for key in ("consumable_tile_count", "tile_count", "tiles_owned"):
        try:
            return int(extras.get(key, 0))
        except (TypeError, ValueError):
            continue
    return 0


def build_shop_context(loadout: Loadout, shop: ShopState) -> ShopAdviceContext:
    inventory: list[GameShopItem] = []
    for sticker in loadout.stickers:
        inventory.append(
            _game_item_from_loadout_item(
                sticker.id or "", sticker.name or "", "sticker"
            )
        )
    for stamp in loadout.stamps:
        inventory.append(
            _game_item_from_loadout_item(stamp.id or "", stamp.name or "", "stamp")
        )

    shop_items: list[GameShopItem] = []
    shop_tiles: list[GameShopTile] = []
    for offer in shop.offers:
        if offer.sold:
            continue
        if offer.slot == "tile":
            shop_tiles.append(_tile_from_offer(offer))
        else:
            shop_items.append(_game_item_from_offer(offer))

    return ShopAdviceContext(
        money=loadout.money,
        sticker_count=len(loadout.stickers),
        stamp_count=len(loadout.stamps),
        tile_count=_tile_count_from_loadout(loadout),
        inventory=inventory,
        shop_items=shop_items,
        shop_tiles=shop_tiles,
        restock_cost=max(0, shop.restock_cost),
        free_item_available=shop.free_item_available,
        unlocks=_DEFAULT_UNLOCKS,
    )


def compute_shop_advice(loadout: Loadout, shop: ShopState) -> AdviceData:
    ctx = build_shop_context(loadout, shop)
    advice = select_advice_tier(ctx)
    free_active = ctx.free_item_available
    advice = resolve_advice_actions(advice, ctx, free_item_active=free_active)
    advice.is_free_item = free_active
    return advice


def compute_shop_advice_summary(loadout: Loadout, shop: ShopState) -> str:
    advice = compute_shop_advice(loadout, shop)
    ctx = build_shop_context(loadout, shop)
    return advice_summary(
        advice,
        free_item_active=ctx.free_item_available,
        money=loadout.money,
    )
