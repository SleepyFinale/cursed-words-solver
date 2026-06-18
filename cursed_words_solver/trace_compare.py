"""Normalized scoring trace comparison (solver vs melmod)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (value or "").lower()).strip("_")


def _rule_id_from_item_name(name: str) -> str:
    return _slug(name)


def _normalize_word_effect(
    *,
    word_score: float | int | None = None,
    word_bonus: int | None = None,
    word_bonus_multiplicative: bool | None = None,
    detail: str = "",
) -> tuple[float, str]:
    """Return (effective_multiplier_or_additive, kind) where kind is mult|add|none."""
    if word_bonus_multiplicative and word_bonus:
        return word_bonus / 100.0, "mult"
    if word_bonus and not word_bonus_multiplicative:
        return float(word_bonus), "add"
    if word_score:
        ws = float(word_score)
        if ws >= 100 and ws % 100 == 0:
            return ws / 100.0, "mult"
        return ws, "add"
    mult_match = re.search(r"×\s*([0-9]+(?:\.[0-9]+)?)", detail or "")
    if mult_match:
        return float(mult_match.group(1)), "mult"
    add_match = re.search(r"\+\s*([0-9]+(?:\.[0-9]+)?)\s*word", detail or "", re.I)
    if add_match:
        return float(add_match.group(1)), "add"
    return 0.0, "none"


@dataclass(frozen=True)
class CanonicalStep:
    index: int
    step_id: str
    phase: str
    tile_scores: list[int]
    word_effect: float
    word_effect_kind: str
    subtotal: float | None
    source: str


def canonicalize_predicted_step(index: int, step: dict[str, Any]) -> CanonicalStep:
    phase = str(step.get("phase") or "")
    rule_id = str(step.get("rule_id") or phase or f"step_{index}")
    tiles = [int(round(float(v))) for v in step.get("tile_scores", [])]
    word_effect, kind = _normalize_word_effect(
        word_score=step.get("word_score"),
        detail=str(step.get("detail") or ""),
    )
    subtotal = step.get("subtotal")
    return CanonicalStep(
        index=index,
        step_id=_slug(rule_id),
        phase=phase,
        tile_scores=tiles,
        word_effect=word_effect,
        word_effect_kind=kind,
        subtotal=float(subtotal) if subtotal is not None else None,
        source="predicted",
    )


def canonicalize_actual_step(index: int, step: dict[str, Any]) -> CanonicalStep:
    name = str(step.get("item_name") or step.get("item_id") or f"step_{index}")
    phase = str(step.get("phase") or "rule")
    tiles = [int(round(float(v))) for v in step.get("tile_scores", [])]
    word_effect, kind = _normalize_word_effect(
        word_bonus=int(step.get("word_bonus") or 0),
        word_bonus_multiplicative=bool(step.get("word_bonus_multiplicative")),
    )
    subtotal = step.get("running_subtotal", step.get("subtotal"))
    return CanonicalStep(
        index=index,
        step_id=_rule_id_from_item_name(name),
        phase=phase,
        tile_scores=tiles,
        word_effect=word_effect,
        word_effect_kind=kind,
        subtotal=float(subtotal) if subtotal is not None else None,
        source="actual",
    )


@dataclass
class TraceDiff:
    first_index: int | None
    summary: str
    hypothesis: str
    predicted_subtotal: float | None
    actual_subtotal: float | None

    @property
    def has_divergence(self) -> bool:
        return self.first_index is not None


def _hypothesis_for_step(pred: CanonicalStep, actual: CanonicalStep) -> str:
    if pred.phase.startswith("tile_init") or actual.phase.startswith("tile_init"):
        return "tile_init / currency / glitch settlement"
    if pred.phase == "multiply" or actual.phase == "multiply":
        return "finalize / word-multiplier ordering"
    if pred.word_effect_kind == "mult" or actual.word_effect_kind == "mult":
        return "word multiplier (×WORD) semantics"
    if pred.step_id != actual.step_id:
        return "scoring item order or missing rule"
    return "tile score application"


def compare_traces(
    pred_trace: list[dict[str, Any]],
    actual_trace: list[dict[str, Any]],
) -> TraceDiff:
    """Find first meaningful divergence between normalized traces."""
    n = min(len(pred_trace), len(actual_trace))
    for i in range(n):
        pred = canonicalize_predicted_step(i, pred_trace[i])
        actual = canonicalize_actual_step(i, actual_trace[i])
        if pred.tile_scores != actual.tile_scores:
            return TraceDiff(
                first_index=i,
                summary=(
                    f"[{i}] tile_scores pred={pred.tile_scores} "
                    f"actual={actual.tile_scores} "
                    f"(pred {pred.step_id} vs actual {actual.step_id})"
                ),
                hypothesis=_hypothesis_for_step(pred, actual),
                predicted_subtotal=pred.subtotal,
                actual_subtotal=actual.subtotal,
            )
        if pred.step_id and actual.step_id and pred.step_id != actual.step_id:
            return TraceDiff(
                first_index=i,
                summary=(
                    f"[{i}] step_id pred={pred.step_id} actual={actual.step_id}"
                ),
                hypothesis=_hypothesis_for_step(pred, actual),
                predicted_subtotal=pred.subtotal,
                actual_subtotal=actual.subtotal,
            )
        if (
            pred.word_effect_kind == actual.word_effect_kind
            and pred.word_effect_kind != "none"
            and abs(pred.word_effect - actual.word_effect) > 0.01
        ):
            return TraceDiff(
                first_index=i,
                summary=(
                    f"[{i}] word_effect pred={pred.word_effect} "
                    f"actual={actual.word_effect} ({pred.word_effect_kind})"
                ),
                hypothesis=_hypothesis_for_step(pred, actual),
                predicted_subtotal=pred.subtotal,
                actual_subtotal=actual.subtotal,
            )
    if len(pred_trace) != len(actual_trace):
        return TraceDiff(
            first_index=n,
            summary=f"length mismatch pred={len(pred_trace)} actual={len(actual_trace)}",
            hypothesis="scoring item order or missing finalize step",
            predicted_subtotal=None,
            actual_subtotal=None,
        )
    return TraceDiff(
        first_index=None,
        summary="none",
        hypothesis="",
        predicted_subtotal=None,
        actual_subtotal=None,
    )
