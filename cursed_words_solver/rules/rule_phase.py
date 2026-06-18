"""Classify inventory scoring rules as board-static vs path-dynamic."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from cursed_words_solver.models import Loadout
from cursed_words_solver.rules.rule_lookup import slugify_name
from cursed_words_solver.rules.scoring_conditions import sticker_rule_int
from cursed_words_solver.solve_context import SolveContext

STATIC_TILE_TARGETS = frozenset(
    {
        "vowel",
        "consonant",
        "red",
        "blue",
        "wildcard",
        "shiny",
        "void",
        "all",
        "number",
        "red_note",
    }
)

STATIC_TILE_MULT_TARGETS = STATIC_TILE_TARGETS | frozenset({"letter"})

ORCHESTRATION_TYPES = frozenset(
    {
        "frankenstein_stitch",
        "overhand_replay",
        "unmodeled",
        "custom",
        "pin_memory_replay",
        "human_hands_pin",
        "blue_tile_base_override",
        "scatter_start_grid",
        "scatter_start_encounter",
        "reverse_scoring_order",
        "shuffle_loadout_order",
    }
)


class PipelinePhase(str, Enum):
    PIN = "pin"
    STICKER = "sticker"
    STAMP = "stamp"


class StaticRuleKind(str, Enum):
    TILE_ADD = "tile_add"
    TILE_MULT = "tile_mult"
    COLORED_NUMBER_ADD = "colored_number_add"
    WORD_ADD = "word_add"
    WORD_LENGTH = "word_length"
    RED_TILE_BONUS = "red_tile_bonus"


@dataclass(frozen=True)
class StaticRuleSpec:
    rule_id: str
    effect_type: str
    level: int
    value: float
    target_mask: int
    kind: StaticRuleKind
    phase: PipelinePhase
    target_label: str = "all"
    min_word_length: int = 4
    multiply_word_pass: bool = False


def _has_blocking_condition(rule: dict) -> bool:
    condition = str(rule.get("condition") or "").strip()
    return bool(condition) and condition != "always"


def _tile_multiply_factor(level: int, rule: dict) -> float | None:
    if (
        rule.get("scale_by_pin_right")
        or rule.get("scale_by_path_position")
        or rule.get("scale_from_extras")
        or rule.get("scale_by_consumable_count_on_path")
        or rule.get("per_level_factor")
        or "base" in rule
    ):
        return None
    factor = float(rule.get("factor", 2.0))
    if factor < 0:
        factor = float(sticker_rule_int(level, rule))
    return factor


def classify_inventory_rule(
    rule: dict,
    *,
    level: int,
    rule_id: str,
    phase: PipelinePhase,
    target_masks: dict[str, int],
) -> StaticRuleSpec | None:
    """Return a static spec when the rule is loadout/board invariant; else None."""
    if not rule:
        return None
    effect_type = str(rule.get("type") or "")
    if effect_type in ORCHESTRATION_TYPES:
        return None
    if _has_blocking_condition(rule):
        return None

    rid = slugify_name(rule_id)

    if effect_type == "add_tile_score":
        target = str(rule.get("target") or "all")
        if target not in STATIC_TILE_TARGETS:
            return None
        bonus = float(sticker_rule_int(level, rule))
        mask = target_masks.get(target, 0) if target != "all" else target_masks["all"]
        return StaticRuleSpec(
            rule_id=rid,
            effect_type=effect_type,
            level=level,
            value=bonus,
            target_mask=mask,
            kind=StaticRuleKind.TILE_ADD,
            phase=phase,
            target_label=target,
        )

    if effect_type == "colored_number_tile_bonus":
        mask = target_masks.get("colored_number", 0)
        return StaticRuleSpec(
            rule_id=rid,
            effect_type=effect_type,
            level=level,
            value=0.0,
            target_mask=mask,
            kind=StaticRuleKind.COLORED_NUMBER_ADD,
            phase=phase,
            target_label="colored_number",
        )

    if effect_type == "tile_multiply":
        target = str(rule.get("target") or "number")
        if target.startswith("letter:"):
            letter = target.split(":", 1)[1].strip().lower()
            mask = target_masks.get(f"letter:{letter}", 0)
            if not mask:
                return None
            factor = _tile_multiply_factor(level, rule)
            if factor is None:
                return None
            return StaticRuleSpec(
                rule_id=rid,
                effect_type=effect_type,
                level=level,
                value=factor,
                target_mask=mask,
                kind=StaticRuleKind.TILE_MULT,
                phase=phase,
                target_label=target,
            )
        if target not in STATIC_TILE_MULT_TARGETS and target != "number":
            return None
        factor = _tile_multiply_factor(level, rule)
        if factor is None:
            return None
        mask = target_masks.get(target, 0) if target != "all" else target_masks["all"]
        return StaticRuleSpec(
            rule_id=rid,
            effect_type=effect_type,
            level=level,
            value=factor,
            target_mask=mask,
            kind=StaticRuleKind.TILE_MULT,
            phase=phase,
            target_label=target,
        )

    if effect_type == "add_word_score":
        word_mode = str(rule.get("word_mode") or "flat")
        if word_mode not in ("flat",):
            return None
        bonus = float(sticker_rule_int(level, rule))
        return StaticRuleSpec(
            rule_id=rid,
            effect_type=effect_type,
            level=level,
            value=bonus,
            target_mask=0,
            kind=StaticRuleKind.WORD_ADD,
            phase=phase,
        )

    if effect_type == "word_length_bonus":
        bonus = float(sticker_rule_int(level, rule))
        min_len = int(rule.get("min_length", 4))
        return StaticRuleSpec(
            rule_id=rid,
            effect_type=effect_type,
            level=level,
            value=bonus,
            target_mask=0,
            kind=StaticRuleKind.WORD_LENGTH,
            phase=phase,
            min_word_length=min_len,
        )

    if effect_type == "red_tile_bonus":
        bonus = float(sticker_rule_int(level, rule))
        mask = target_masks.get("red_plain", 0)
        return StaticRuleSpec(
            rule_id=rid,
            effect_type=effect_type,
            level=level,
            value=bonus,
            target_mask=mask,
            kind=StaticRuleKind.RED_TILE_BONUS,
            phase=phase,
            target_label="red",
        )

    return None


def blocks_split_pipeline(
    loadout: Loadout,
    ctx: SolveContext,
    rules: dict[str, Any],
) -> bool:
    """True when orchestration prevents safe static/dynamic interleaving."""
    if ctx.capybara_shuffles:
        return True
    if ctx.compound_percents or ctx.compound_finalize_at_cocktail:
        return True
    from cursed_words_solver.rules.scoring_conditions import snapshot_phased_word_scoring

    if snapshot_phased_word_scoring(loadout):
        return True
    from cursed_words_solver.rules.rule_lookup import get_rule

    for sticker in loadout.stickers:
        _key, rule = get_rule(rules, "stickers", sticker.id, sticker.name)
        if rule and rule.get("type") == "frankenstein_stitch":
            return True
        if slugify_name(sticker.id or sticker.name) == "snapshot":
            return True
    return False
