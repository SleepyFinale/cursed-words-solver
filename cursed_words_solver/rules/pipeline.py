"""Full scoring pipeline: pin -> stickers -> stamps -> boss."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cursed_words_solver.models import Board, Loadout
from cursed_words_solver.rules.base_scoring import score_word_base
from cursed_words_solver.rules.rule_lookup import (
    collect_unmapped_items,
    count_mapped_items,
    get_pin_branch_rule,
    get_rule,
    resolve_rule_id,
)

STICKERS_PATH = Path(__file__).resolve().parents[2] / "data" / "wiki" / "stickers.json"


def _load_sticker_rules() -> dict[str, Any]:
    if STICKERS_PATH.exists():
        return json.loads(STICKERS_PATH.read_text(encoding="utf-8"))
    return {"stickers": {}, "stamps": {}, "bosses": {}, "pins": {}, "aliases": {}}


class ScoringPipeline:
    """Apply loadout effects in game order."""

    def __init__(self) -> None:
        self.rules = _load_sticker_rules()

    def loadout_mapping_summary(self, loadout: Loadout | None) -> tuple[int, int, list[str]]:
        """Mapped count, total count, unmapped item labels."""
        loadout = loadout or Loadout()
        mapped, total = count_mapped_items(self.rules, loadout)
        unmapped = collect_unmapped_items(self.rules, loadout)
        return mapped, total, unmapped

    def score(
        self,
        board: Board,
        path: list[int],
        word: str,
        loadout: Loadout | None = None,
    ) -> tuple[float, dict[str, Any]]:
        loadout = loadout or Loadout(money=board.money)
        base_score, breakdown = score_word_base(board, path, word)
        state: dict[str, Any] = {
            "word": word,
            "path": path,
            "base_score": base_score,
            "word_score": base_score,
            "multiplier": 1.0,
            "effects": [],
        }

        pin_effect = str(loadout.extras.get("pin_effect", "") or "").strip()
        if pin_effect:
            branch_rule = get_pin_branch_rule(
                self.rules, pin_effect, loadout.pin_branch
            )
            if branch_rule:
                state = self._apply_rule(
                    branch_rule, state, board, path, loadout, 1
                )
            else:
                state = self._apply_named_effect(
                    pin_effect, state, board, path, loadout
                )

        for sticker in loadout.stickers:
            _key, rule = get_rule(
                self.rules, "stickers", sticker.id, sticker.name
            )
            if rule and rule.get("type") != "unmodeled":
                state = self._apply_rule(
                    rule, state, board, path, loadout, sticker.level
                )

        for stamp in loadout.stamps:
            _key, rule = get_rule(self.rules, "stamps", stamp.id, stamp.name)
            if rule and rule.get("type") != "unmodeled":
                state = self._apply_rule(rule, state, board, path, loadout, 1)

        if loadout.boss_id or loadout.boss_name:
            _key, boss = get_rule(
                self.rules, "bosses", loadout.boss_id, loadout.boss_name
            )
            if boss and boss.get("type") != "unmodeled":
                state = self._apply_rule(boss, state, board, path, loadout, 1)
        elif loadout.boss_effect:
            state = self._apply_named_effect(
                loadout.boss_effect, state, board, path, loadout
            )

        final = state["word_score"] * state["multiplier"]
        breakdown["pipeline"] = state
        return final, breakdown

    def _apply_named_effect(
        self,
        effect_id: str,
        state: dict,
        board: Board,
        path: list[int],
        loadout: Loadout,
    ) -> dict:
        for bucket in ("stickers", "stamps", "bosses", "pins"):
            _key, rule = get_rule(self.rules, bucket, effect_id, effect_id)
            if rule and rule.get("type") not in ("unmodeled", None):
                if bucket == "pins":
                    branch_rule = get_pin_branch_rule(
                        self.rules, effect_id, loadout.pin_branch
                    )
                    if branch_rule:
                        return self._apply_rule(
                            branch_rule, state, board, path, loadout, 1
                        )
                return self._apply_rule(rule, state, board, path, loadout, 1)
        canonical = resolve_rule_id(self.rules, "stickers", effect_id, effect_id)
        if canonical:
            rule = self.rules.get("stickers", {}).get(canonical)
            if rule and rule.get("type") != "unmodeled":
                return self._apply_rule(rule, state, board, path, loadout, 1)
        return state

    def _apply_rule(
        self,
        rule: dict,
        state: dict,
        board: Board,
        path: list[int],
        loadout: Loadout,
        level: int,
    ) -> dict:
        effect_type = rule.get("type", "")
        if effect_type in ("unmodeled", "custom"):
            return state

        value = rule.get("value", 0) * level

        if effect_type == "add_word_score":
            state["word_score"] += value
            state["effects"].append(f"+{value} word score")
        elif effect_type == "multiply":
            state["multiplier"] *= rule.get("factor", 1.0) ** level
            state["effects"].append(f"x{rule.get('factor')} multiplier")
        elif effect_type == "red_tile_bonus":
            red_count = sum(
                1
                for i in path
                if board.get_by_index(i).color.value == "red"
            )
            if red_count:
                bonus = value * red_count
                state["word_score"] += bonus
                state["effects"].append(f"+{bonus} for {red_count} red tiles")
        elif effect_type == "void_flip":
            for i in path:
                t = board.get_by_index(i)
                if t.color.value == "void":
                    state["word_score"] += abs(t.base_score) * 2
                    state["effects"].append("void flip")
        elif effect_type == "word_length_bonus":
            if len(state["word"]) >= rule.get("min_length", 4):
                state["word_score"] += value
        elif effect_type == "shiny_chain":
            shiny = sum(
                1
                for i in path
                if board.get_by_index(i).color.value == "shiny"
            )
            if shiny >= 2:
                state["word_score"] += value * (shiny - 1)
        elif effect_type == "boss_zero_vowel":
            vowels = set("aeiou")
            if any(c in vowels for c in state["word"].lower()):
                state["multiplier"] = 0
                state["effects"].append("boss: no vowels")

        return state
