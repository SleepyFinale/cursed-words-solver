"""Start-of-grid / encounter board mutations (Item.ApplyStartOfGridEffect)."""

from __future__ import annotations

import copy
import random
from typing import Any

from cursed_words_solver.models import Board, CurseType, Loadout, Tile, TileColor
from cursed_words_solver.rules.rule_lookup import get_pin_branch_rule, get_rule, resolve_rule_id, slugify_name
from cursed_words_solver.rules.scoring_conditions import pin_left_level, pin_left_variable


def _clone_board(board: Board) -> Board:
    tiles = [
        [
            Tile(
                row=t.row,
                col=t.col,
                char=t.char,
                letter=t.letter,
                base_score=t.base_score,
                color=t.color,
                curse=t.curse,
                number_value=t.number_value,
                fraction_value=t.fraction_value,
                ocr_confidence=t.ocr_confidence,
                metadata=dict(t.metadata),
            )
            for t in row
        ]
        for row in board.tiles
    ]
    return Board(
        tiles=tiles,
        money=board.money,
        rows=board.rows,
        cols=board.cols,
        active=list(board.active),
        playable_origin=board.playable_origin,
        playable_min_row=board.playable_min_row,
        playable_max_row=board.playable_max_row,
        playable_min_col=board.playable_min_col,
        playable_max_col=board.playable_max_col,
    )


def _scatter_rule_ids(loadout: Loadout, rules: dict, *, timing: str) -> list[tuple[str, dict, int]]:
    """Return (slug, rule, level) for scatter stickers/stamps matching timing."""
    out: list[tuple[str, dict, int]] = []
    for sticker in loadout.stickers:
        _key, rule = get_rule(rules, "stickers", sticker.id, sticker.name)
        if not rule:
            continue
        if rule.get("type") not in ("scatter_start_grid", "scatter_start_encounter", "custom"):
            continue
        if rule.get("effect_class") != "scatter" and not rule.get("type", "").startswith(
            "scatter_"
        ):
            continue
        grid_timing = rule.get("grid_timing", "start")
        if timing == "encounter" and grid_timing not in ("encounter", "start_encounter"):
            if "ENCOUNTER" not in str(rule.get("wiki_effect", "")).upper():
                continue
        elif timing == "grid" and grid_timing == "encounter":
            continue
        slug = _key or sticker.id or slugify_name(sticker.name)
        out.append((slug, rule, sticker.level))
    for stamp in loadout.stamps:
        _key, rule = get_rule(rules, "stamps", stamp.id, stamp.name)
        if not rule:
            continue
        stype = rule.get("type", "")
        if stype not in ("scatter_start_grid", "scatter_start_encounter", "custom"):
            if not str(stype).startswith("scatter_"):
                continue
        if rule.get("effect_class") != "scatter" and not str(stype).startswith("scatter_"):
            continue
        grid_timing = rule.get("grid_timing", "start")
        if timing == "encounter" and grid_timing not in ("encounter", "start_encounter"):
            if "ENCOUNTER" not in str(rule.get("wiki_effect", "")).upper():
                continue
        elif timing == "grid" and grid_timing == "encounter":
            continue
        slug = _key or stamp.id or slugify_name(stamp.name)
        out.append((slug, rule, 1))
    return out


def _apply_colorize_letters(
    board: Board,
    letters: list[str],
    color: TileColor,
    *,
    rng: random.Random,
) -> int:
    changed = 0
    targets = {c.upper() for c in letters if c}
    for tile in board.flat:
        if not board.is_active_index(tile.index):
            continue
        if tile.letter.upper() not in targets:
            continue
        if tile.color != color:
            tile.color = color
            changed += 1
    return changed


def _pin_scatter_rule_ids(
    loadout: Loadout, rules: dict, *, timing: str
) -> list[tuple[str, dict, int]]:
    pin_effect = str((loadout.extras or {}).get("pin_effect", "") or "").strip()
    if not pin_effect:
        return []
    canonical = resolve_rule_id(rules, "pins", pin_effect, pin_effect) or pin_effect
    left = get_pin_branch_rule(rules, pin_effect, "left")
    if not left:
        return []
    left_type = left.get("type", "")
    if timing == "encounter":
        if left_type != "scatter_start_encounter":
            return []
    elif left_type != "scatter_start_grid":
        return []
    level = pin_left_level(loadout)
    var = pin_left_variable(loadout)
    if var is not None and var > 0:
        level = max(level, var)
    slug = str(left.get("grid_handler") or canonical)
    return [(slug, left, max(1, level))]


def card_suit(tile: Tile) -> str | None:
    suit = (tile.metadata or {}).get("card_suit")
    return str(suit) if suit else None


def _apply_pin_scatter_handler(
    slug: str,
    rule: dict,
    board: Board,
    loadout: Loadout,
    *,
    rng: random.Random,
) -> int:
    """Pin left-track scatter (best-effort when board is not from melmod)."""
    effect = rule.get("wiki_effect") or rule.get("grid_effect") or ""
    upper = effect.upper()
    level = int(rule.get("_scatter_level") or pin_left_level(loadout) or 1)

    if slug in ("rodman", "carp_streamers") or ("RED" in upper and "BLUE" in upper):
        active = [t for t in board.flat if board.is_active_index(t.index)]
        changed = 0
        if active:
            t = rng.choice(active)
            if t.color != TileColor.RED:
                t.color = TileColor.RED
                changed += 1
        if len(active) >= 2:
            candidates = [t for t in active if t.color != TileColor.RED] or active
            t = rng.choice(candidates)
            if t.color != TileColor.BLUE:
                t.color = TileColor.BLUE
                changed += 1
        return changed

    if slug == "abacus":
        count = min(5, max(1, level))
        active = [t for t in board.flat if board.is_active_index(t.index)]
        rng.shuffle(active)
        changed = 0
        for i, tile in enumerate(active[:count]):
            n = i + 1
            tile.curse = CurseType.NUMBER
            tile.number_value = n
            tile.char = str(n)
            tile.letter = str(n)
            changed += 1
        return changed

    if slug == "milky_way" or ("VOID" in upper and "SCATTER" in upper):
        count = int(rule.get("scatter_count") or max(3, level))
        active = [t for t in board.flat if board.is_active_index(t.index)]
        rng.shuffle(active)
        changed = 0
        for tile in active[:count]:
            if tile.color != TileColor.VOID:
                tile.color = TileColor.VOID
                changed += 1
        return changed

    if slug == "rainbow" or "UNUSUAL" in upper:
        active = [t for t in board.flat if board.is_active_index(t.index)]
        if not active:
            return 0
        tile = rng.choice(active)
        unusual = (TileColor.PURPLE, TileColor.PINK, TileColor.GOLD)
        new_color = rng.choice(unusual)
        if tile.color != new_color:
            tile.color = new_color
            return 1
        return 0

    if slug in ("cretaceous_meg", "wad_of_cash") or "CURRENCY" in upper:
        active = [t for t in board.flat if board.is_active_index(t.index)]
        rng.shuffle(active)
        changed = 0
        for tile in active[: max(1, level)]:
            if not tile.metadata.get("currency"):
                tile.metadata["currency"] = True
                changed += 1
        return changed

    if slug in ("bones_the_dog", "bicycle") or "CARD" in upper:
        active = [t for t in board.flat if board.is_active_index(t.index)]
        rng.shuffle(active)
        suits = ("hearts", "spades", "clubs", "diamonds")
        changed = 0
        for tile in active[: max(2, level + 1)]:
            if not card_suit(tile):
                tile.metadata["card_suit"] = rng.choice(suits)
                changed += 1
        return changed

    return _apply_scatter_handler(slug, rule, board, loadout, grid_number=1, rng=rng)


def _apply_scatter_handler(
    slug: str,
    rule: dict,
    board: Board,
    loadout: Loadout,
    *,
    grid_number: int,
    rng: random.Random,
) -> int:
    """Best-effort scatter; returns tiles changed. Melmod boards usually pre-applied."""
    effect = rule.get("grid_effect") or rule.get("wiki_effect") or ""
    upper = effect.upper()
    level = rule.get("_scatter_level", 1)

    if slug == "april_shower" or "BECOME BLUE" in upper:
        n = int(rule.get("scatter_count") or level or 3)
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        chosen = loadout.extras.get("april_shower_letters")
        if isinstance(chosen, str) and chosen:
            letters = [c for c in chosen.upper() if c.isalpha()]
        else:
            letters = rng.sample(list(alphabet), min(n, 26))
        return _apply_colorize_letters(board, letters, TileColor.BLUE, rng=rng)

    if "RED" in upper and "SCATTER" in upper:
        count = int(rule.get("scatter_count") or 3)
        active = [t for t in board.flat if board.is_active_index(t.index)]
        rng.shuffle(active)
        changed = 0
        for tile in active[:count]:
            if tile.color != TileColor.RED:
                tile.color = TileColor.RED
                changed += 1
        return changed

    if "VOID" in upper and "SCATTER" in upper:
        count = int(rule.get("scatter_count") or 5)
        active = [t for t in board.flat if board.is_active_index(t.index)]
        rng.shuffle(active)
        changed = 0
        for tile in active[:count]:
            if tile.color != TileColor.VOID:
                tile.color = TileColor.VOID
                changed += 1
        return changed

    if "BLUE" in upper and ("LETTER" in upper or "COLOUR" in upper or "COLOR" in upper):
        n = int(rule.get("scatter_count") or level or 2)
        alphabet = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
        letters = rng.sample(alphabet, min(n, 26))
        return _apply_colorize_letters(board, letters, TileColor.BLUE, rng=rng)

    return 0


def apply_start_of_encounter_mutations(
    board: Board,
    loadout: Loadout | None,
    rules: dict,
    *,
    seed: int | None = None,
) -> Board:
    if not loadout:
        return board
    if str(loadout.extras.get("board_from_melmod", "")).lower() in ("1", "true"):
        return board
    out = _clone_board(board)
    rng = random.Random(seed if seed is not None else loadout.extras.get("scatter_seed"))
    grid_num = int(loadout.extras.get("grid_number") or 1)
    for slug, rule, level in _scatter_rule_ids(loadout, rules, timing="encounter"):
        rule = dict(rule)
        rule["_scatter_level"] = level
        _apply_scatter_handler(slug, rule, out, loadout, grid_number=grid_num, rng=rng)
    for slug, rule, level in _pin_scatter_rule_ids(loadout, rules, timing="encounter"):
        rule = dict(rule)
        rule["_scatter_level"] = level
        _apply_pin_scatter_handler(slug, rule, out, loadout, rng=rng)
    return out


def apply_start_of_grid_mutations(
    board: Board,
    loadout: Loadout | None,
    rules: dict,
    *,
    seed: int | None = None,
) -> Board:
    if not loadout:
        return board
    if str(loadout.extras.get("board_from_melmod", "")).lower() in ("1", "true"):
        return board
    out = _clone_board(board)
    rng = random.Random(seed if seed is not None else loadout.extras.get("scatter_seed"))
    grid_num = int(loadout.extras.get("grid_number") or 1)
    for slug, rule, level in _scatter_rule_ids(loadout, rules, timing="grid"):
        rule = dict(rule)
        rule["_scatter_level"] = level
        _apply_scatter_handler(slug, rule, out, loadout, grid_number=grid_num, rng=rng)
    for slug, rule, level in _pin_scatter_rule_ids(loadout, rules, timing="grid"):
        rule = dict(rule)
        rule["_scatter_level"] = level
        _apply_pin_scatter_handler(slug, rule, out, loadout, rng=rng)
    return out
