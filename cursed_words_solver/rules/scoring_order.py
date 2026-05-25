"""Game-accurate scoring item order (EncounterController + ScoreCalculation)."""

from __future__ import annotations

import hashlib
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
    from cursed_words_solver.rules.boss_effects import get_active_boss_rule

    _key, boss = get_active_boss_rule(rules, loadout)
    if boss and boss.get("type") == "shuffle_loadout_order":
        return True
    for sticker in loadout.stickers:
        _key, rule = get_rule(rules, "stickers", sticker.id, sticker.name)
        if rule and rule.get("type") == "shuffle_loadout_order":
            return True
    return False


def _path_grid_item_refs(board: Board, path: list[int], rules: dict) -> list[ScoringItemRef]:
    refs: list[ScoringItemRef] = []
    for idx in path:
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
        refs.append(
            ScoringItemRef(
                kind="grid_path",
                item=None,
                rule_id=_key or slug,
                level=1,
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


def build_scoring_item_sequence(
    board: Board,
    path: list[int],
    loadout: Loadout | None,
    rules: dict,
) -> list[ScoringItemRef]:
    """Mirror GetItemsForWordSubmission + Hourglass reverse."""
    if not loadout:
        return []
    loadout = _maybe_shuffled_loadout(loadout, rules, path)
    refs = _path_grid_item_refs(board, path, rules) + _inventory_item_refs(loadout, rules)
    if hourglass_reverses_order(loadout, rules):
        refs = list(reversed(refs))
    return refs


def apply_green_tile_word_transfer(
    board: Board,
    path: list[int],
    state: dict,
) -> None:
    """Wiki step: GREEN tile scores join word score before finalize."""
    transfer = 0.0
    for i, idx in enumerate(path):
        if board.get_by_index(idx).color == TileColor.GREEN:
            transfer += state["tile_scores"][i]
            state["tile_scores"][i] = 0.0
    if transfer:
        state["word_score"] += transfer
        state["effects"].append(f"+{transfer:g} GREEN tile score → word")
