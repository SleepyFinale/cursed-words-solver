"""Game-accurate scoring item order (EncounterController + ScoreCalculation)."""

from __future__ import annotations

import hashlib
from typing import Any
import random
from dataclasses import dataclass

from cursed_words_solver.models import Board, CurseType, Loadout, LoadoutItem, TileColor
from cursed_words_solver.rules.rule_lookup import get_rule, resolve_rule_id, slugify_name


@dataclass(frozen=True)
class ScoringItemRef:
    """One entry in the game's combined items list for CalculateOverallScore."""

    kind: str  # grid_path | pin | sticker | stamp
    item: LoadoutItem | None
    rule_id: str
    level: int = 1


def hourglass_reverses_order(loadout: Loadout | None, rules: dict) -> bool:
    """Odd Hourglass count reverses inventory item order (game: GetUnpackedItemsOfType)."""
    if not loadout:
        return False
    extra = str(loadout.extras.get("hourglass_count", "") or "").strip()
    if extra.isdigit():
        return int(extra) % 2 == 1
    count = 0
    for stamp in loadout.stamps:
        _key, rule = get_rule(rules, "stamps", stamp.id, stamp.name)
        if rule and rule.get("type") == "reverse_scoring_order":
            count += 1
    return count % 2 == 1


def capybara_shuffles_loadout(loadout: Loadout | None, rules: dict) -> bool:
    if not loadout:
        return False
    if str(loadout.extras.get("capybara_shuffle", "") or "").lower() in ("1", "true", "yes"):
        return True
    from cursed_words_solver.rules.boss_effects import get_active_boss_rules

    for _key, boss in get_active_boss_rules(rules, loadout):
        if boss and boss.get("type") == "shuffle_loadout_order":
            return True
    for sticker in loadout.stickers:
        _key, rule = get_rule(rules, "stickers", sticker.id, sticker.name)
        if rule and rule.get("type") == "shuffle_loadout_order":
            return True
    return False


def path_grid_item_refs(
    board: Board,
    path: list[int],
    rules: dict,
    loadout: Loadout | None = None,
    *,
    cache: dict[tuple[int, ...], tuple[ScoringItemRef, ...]] | None = None,
    cache_timing: object | None = None,
) -> tuple[ScoringItemRef, ...]:
    """Path-dependent scattered grid items; cached per path during a solve pass."""
    key = tuple(path)
    if cache is not None and key in cache:
        if cache_timing is not None:
            cache_timing.grid_refs_cache_hits += 1
        return cache[key]
    refs = tuple(_path_grid_item_refs(board, path, rules, loadout))
    if cache is not None:
        if cache_timing is not None:
            cache_timing.grid_refs_cache_misses += 1
        cache[key] = refs
    return refs


def _path_grid_item_refs(
    board: Board,
    path: list[int],
    rules: dict,
    loadout: Loadout | None = None,
) -> list[ScoringItemRef]:
    from cursed_words_solver.rules.scoring_conditions import grid_path_sticker_level
    refs: list[ScoringItemRef] = []
    for path_pos, idx in enumerate(path):
        tile = board.get_by_index(idx)
        if tile.curse != CurseType.ITEM:
            continue
        slug = str(tile.metadata.get("scattered_item_id") or "").strip()
        if not slug:
            continue
        _key, rule = get_rule(rules, "stickers", slug, slug)
        bucket = "stickers"
        if not rule:
            _key, rule = get_rule(rules, "stamps", slug, slug)
            bucket = "stamps"
        if not rule:
            continue
        rule_id = _key or slug
        refs.append(
            ScoringItemRef(
                kind="grid_path",
                item=None,
                rule_id=rule_id,
                level=grid_path_sticker_level(
                    loadout,
                    rule_id,
                    board=board,
                    path=path,
                    path_tile_index=path_pos,
                ),
            )
        )
    return refs


def _capybara_shuffle_seed(loadout: Loadout, path: list[int]) -> int:
    material = ",".join(str(i) for i in path)
    material += f"|{loadout.extras.get('run_seed', '')}|{loadout.boss_id}"
    return int(hashlib.sha256(material.encode()).hexdigest()[:16], 16)


def _maybe_shuffled_loadout(loadout: Loadout, rules: dict, path: list[int]) -> Loadout:
    """Capybara / RandomiseItemOrder: shuffle sticker+stamp order before scoring."""
    if not capybara_shuffles_loadout(loadout, rules):
        return loadout
    rng = random.Random(_capybara_shuffle_seed(loadout, path))
    stickers = list(loadout.stickers)
    stamps = list(loadout.stamps)
    rng.shuffle(stickers)
    rng.shuffle(stamps)
    from dataclasses import replace

    return replace(loadout, stickers=stickers, stamps=stamps)


def _inventory_item_refs(loadout: Loadout, rules: dict) -> list[ScoringItemRef]:
    refs: list[ScoringItemRef] = []
    pin_effect = str(loadout.extras.get("pin_effect", "") or "").strip()
    if pin_effect and resolve_rule_id(rules, "pins", pin_effect, pin_effect):
        refs.append(
            ScoringItemRef(
                kind="pin",
                item=None,
                rule_id=pin_effect,
                level=int(loadout.extras.get("pin_right_level") or 1),
            )
        )
    for sticker in loadout.stickers:
        _key, rule = get_rule(rules, "stickers", sticker.id, sticker.name)
        if not rule or rule.get("type") in ("unmodeled",):
            continue
        if rule.get("type") in (
            "shuffle_loadout_order",
            "reverse_scoring_order",
            "frankenstein_stitch",
            "overhand_replay",
        ):
            continue
        refs.append(
            ScoringItemRef(
                kind="sticker",
                item=sticker,
                rule_id=_key or sticker.id or slugify_name(sticker.name),
                level=sticker.level,
            )
        )
    for stamp in loadout.stamps:
        _key, rule = get_rule(rules, "stamps", stamp.id, stamp.name)
        if not rule or rule.get("type") in ("unmodeled",):
            continue
        if rule.get("type") in ("shuffle_loadout_order", "reverse_scoring_order") and rule.get(
            "effect_class"
        ) in ("meta", "encounter", None):
            continue
        refs.append(
            ScoringItemRef(
                kind="stamp",
                item=stamp,
                rule_id=_key or stamp.id or slugify_name(stamp.name),
                level=1,
            )
        )
    return refs


def capybara_shuffled_loadout(
    loadout: Loadout,
    rules: dict,
    path: list[int],
    *,
    cache: dict[tuple[int, ...], Loadout] | None = None,
) -> Loadout:
    """Return path-shuffled loadout, optionally cached per path."""
    if not capybara_shuffles_loadout(loadout, rules):
        return loadout
    key = tuple(path)
    if cache is not None and key in cache:
        return cache[key]
    shuffled = _maybe_shuffled_loadout(loadout, rules, path)
    if cache is not None:
        cache[key] = shuffled
    return shuffled


def build_scoring_item_sequence(
    board: Board,
    path: list[int],
    loadout: Loadout | None,
    rules: dict,
    *,
    hourglass_reversed: bool | None = None,
    inventory_refs: tuple[ScoringItemRef, ...] | list[ScoringItemRef] | None = None,
    capybara_shuffles: bool | None = None,
    grid_refs_cache: dict[tuple[int, ...], tuple[ScoringItemRef, ...]] | None = None,
    capybara_loadout_cache: dict[tuple[int, ...], Loadout] | None = None,
    grid_refs_timing: object | None = None,
) -> list[ScoringItemRef]:
    """Mirror GetItemsForWordSubmission + Hourglass reverse.

    Capybara order randomization is handled by capybara_scoring (permutation EV),
    not by a synthetic shuffle here — loadout slot order is used as-is.
    """
    del capybara_shuffles, capybara_loadout_cache
    if not loadout:
        return []
    inv = (
        list(inventory_refs)
        if inventory_refs is not None
        else _inventory_item_refs(loadout, rules)
    )
    grid_refs = path_grid_item_refs(
        board,
        path,
        rules,
        loadout,
        cache=grid_refs_cache,
        cache_timing=grid_refs_timing,
    )
    refs = list(grid_refs) + inv
    reversed_order = (
        hourglass_reversed
        if hourglass_reversed is not None
        else hourglass_reverses_order(loadout, rules)
    )
    if reversed_order:
        refs = list(reversed(refs))
    return refs


def sort_grid_path_refs(
    refs: list[ScoringItemRef], rules: dict
) -> list[ScoringItemRef]:
    """First-of-colour grid ×N (e.g. Cocktail) before path word mults; other grid stickers keep path order."""

    def _priority(ref: ScoringItemRef) -> tuple[int, int]:
        _key, rule = get_rule(rules, "stickers", ref.rule_id, ref.rule_id)
        if not rule:
            _key, rule = get_rule(rules, "stamps", ref.rule_id, ref.rule_id)
        effect = rule.get("type") if rule else ""
        if effect == "tile_multiply" and rule.get("target") == "first_of_each_colour":
            return (0, 0)
        if effect == "multiply_word_scaled":
            return (1, 0)
        return (2, 0)

    return sorted(refs, key=_priority)


def path_has_green_tiles(board: Board, path: list[int]) -> bool:
    """True when any path tile is GREEN (wiki step 6 applies)."""
    return any(board.get_by_index(idx).color == TileColor.GREEN for idx in path)


def tile_sum_excluding_green(board: Board, path: list[int], state: dict) -> float:
    """Sum path tile scores omitting GREEN indices (word-track at finalize)."""
    return float(
        sum(
            state["tile_scores"][i]
            for i, idx in enumerate(path)
            if board.get_by_index(idx).color != TileColor.GREEN
        )
    )


def apply_green_tile_word_transfer(
    board: Board,
    path: list[int],
    state: dict,
    *,
    trace_step: Any = None,
) -> None:
    """Wiki step 6: GREEN tile scores join word score before step-7 word multipliers."""
    if state.get("_green_transferred"):
        return
    transfer = 0.0
    for i, idx in enumerate(path):
        if board.get_by_index(idx).color == TileColor.GREEN:
            transfer += state["tile_scores"][i]
            state["tile_scores"][i] = 0.0
    if transfer:
        state["word_score"] += transfer
        state["effects"].append(f"+{transfer:g} GREEN tile score → word")
    if transfer or path_has_green_tiles(board, path):
        state["_green_transferred"] = True
    if transfer and trace_step is not None:
        trace_step(
            state,
            "green_transfer",
            detail=f"+{transfer:g} GREEN → word",
        )
