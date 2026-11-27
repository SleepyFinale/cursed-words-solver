"""``EngineScorer``: score one path with the engine (the solver's only scorer).

Same call shape the old ``ScoringPipeline`` had -- ``score(board, path, word,
loadout)`` -> ``(score, breakdown)`` -- so callers that score a single path
(F8 prediction, replays, the simulator, tests) do not build an ``EnginePlan``
themselves. Capybara boards score as the expected value over item shuffles,
exactly like the search ranks them.
"""

from __future__ import annotations

from typing import Any

from cursed_words_solver.models import Board, Loadout


class EngineScorer:
    """Exact game score for a path on a board with a loadout."""

    @property
    def rules(self) -> dict[str, Any]:
        """The item / boss / pin rules catalog (display names, quest metadata)."""
        from cursed_words_solver.rules.rule_lookup import rules_catalog

        return rules_catalog()

    def score(self, board: Board, path: list[int], word: str, loadout: Loadout | None = None, **_ignored: Any) -> tuple[float, dict[str, Any]]:
        from cursed_words_solver.engine import packet as P
        from cursed_words_solver.engine.calc import EnginePlan
        from cursed_words_solver.engine.solver import _capybara_mode, capybara_score_range

        loadout = loadout or Loadout(money=board.money)
        plan = EnginePlan.build(board, loadout)
        mode = _capybara_mode(loadout)
        if mode:
            ev, lo, hi, count, exhaustive = capybara_score_range(plan, list(path), word, mode)
            return float(ev), {
                "engine": "exact",
                "nondeterministic": True,
                "score_min": lo,
                "score_max": hi,
                "orderings": count,
                "exhaustive": exhaustive,
            }
        res = plan.score(list(path), word)
        breakdown = summarize_steps(res.steps)
        breakdown.update(
            engine="exact",
            nondeterministic=res.nondeterministic,
            trace=res.trace(),
            final_states=res.final_states,
        )
        return float(P.to_int(res.score)), breakdown

    def score_total_only(self, board: Board, path: list[int], word: str, loadout: Loadout | None = None, **kw: Any) -> float:
        return self.score(board, path, word, loadout, **kw)[0]

    def score_with_trace(self, board: Board, path: list[int], word: str, loadout: Loadout | None = None, **kw: Any) -> tuple[float, dict[str, Any], list[dict[str, Any]]]:
        score, breakdown = self.score(board, path, word, loadout, **kw)
        return score, breakdown, list(breakdown.get("trace") or [])

    def loadout_mapping_summary(self, loadout: Loadout | None) -> tuple[int, int, int, list[str]]:
        """(scoring-active items, total items, grid-only items, unmapped labels) for the F8 log.

        Items (pin, stickers, stamps) are judged by what the engine models: an item is
        mapped when its slug is in ``item_data.ITEMS`` and affects score when the engine
        has a scoring hook for its class. Bosses still come from the rules catalog."""
        from cursed_words_solver.rules.rule_lookup import (
            _catalog_boss_slugs,
            _count_boss_catalog,
            resolve_rule_id,
        )

        from cursed_words_solver.engine.calc import _slug
        from cursed_words_solver.engine.item_data import ITEMS
        from cursed_words_solver.engine.items import engine_scoring_classes

        loadout = loadout or Loadout()
        scoring_cls = engine_scoring_classes()
        scoring = grid_only = total = 0
        missing: list[str] = []
        rows = _loadout_item_rows(loadout)
        for kind, raw in rows:
            total += 1
            info = ITEMS.get(_slug(raw))
            if info is None:
                missing.append(f"{kind}:{raw}")
            elif info.cls in scoring_cls:
                scoring += 1
            else:
                grid_only += 1
        boss_slugs = _catalog_boss_slugs(loadout)
        total += len(boss_slugs)
        _mapped, boss_scoring, boss_grid = _count_boss_catalog(self.rules, loadout)
        scoring += boss_scoring
        grid_only += boss_grid
        missing += [f"boss:{b}" for b in boss_slugs if resolve_rule_id(self.rules, "bosses", b, b) is None]
        return scoring, total, grid_only, missing


def _loadout_item_rows(loadout: Loadout) -> list[tuple[str, str]]:
    """(kind, id) for the pin, stickers and stamps the engine will build -- from the
    exact ``item_states`` when melmod sent them (as ``EnginePlan.build`` does), else
    from the loadout lists and ``pin_effect``."""
    import json

    extras = loadout.extras if isinstance(loadout.extras, dict) else {}
    states = extras.get("item_states")
    if isinstance(states, str):
        try:
            states = json.loads(states)
        except ValueError:
            states = None
    if isinstance(states, dict) and "stickers" in states:
        rows: list[tuple[str, str]] = []
        pin = states.get("pin")
        if isinstance(pin, dict) and pin.get("id"):
            rows.append(("pin", str(pin["id"])))
        for kind in ("sticker", "stamp"):
            for row in states.get(kind + "s") or ():
                if isinstance(row, dict) and row.get("id"):
                    rows.append((kind, str(row["id"])))
        return rows
    pin = str(extras.get("pin_effect", "") or "")
    return ([("pin", pin)] if pin else []) + [("sticker", s.id or s.name) for s in loadout.stickers] + [
        ("stamp", s.id or s.name) for s in loadout.stamps
    ]


def summarize_steps(steps: list) -> dict[str, Any]:
    """Readable totals from ``ScoreCalcVizInfo`` steps.

    ``tile_scores`` / ``tile_total``: tile scores after every item; ``base_total``:
    before any; ``word_score``: additive word bonuses (poison included);
    ``multiplier``: product of the multiplicative word bonuses (x1.5 = 1.5);
    ``money_bonus``: money gained while scoring; ``effects``: one line per step
    that changed something, in scoring order.
    """
    from cursed_words_solver.engine import packet as P

    if not steps:
        return {"tile_scores": [], "tile_total": 0, "base_total": 0, "word_score": 0, "multiplier": 1.0, "money_bonus": 0, "effects": []}
    word_score: int | float = 0
    multiplier = 1.0
    effects: list[str] = []
    prev = steps[0]
    for st in steps[1:]:
        label = st.item or st.note or "step"
        parts = []
        deltas = [P.to_int(P.add(a, -b if isinstance(b, int) else -b)) for a, b in zip(st.ts, prev.ts)] if len(st.ts) == len(prev.ts) else []
        if any(deltas):
            parts.append("tiles " + ", ".join(f"{d:+d}" for d in deltas if d))
        if st.wb is not None:
            if st.wb.mult:
                multiplier *= float(st.wb.value) / 100.0
                parts.append(f"word x{float(st.wb.value) / 100.0:g}")
            else:
                word_score = P.add(word_score, st.wb.value)
                parts.append(f"word {P.to_int(st.wb.value):+d}" + (" (poison)" if st.wb.poison else ""))
        if st.money != prev.money:
            parts.append(f"money {st.money - prev.money:+d}")
        if parts:
            effects.append(f"{label}: " + "; ".join(parts))
        prev = st
    ts = [P.to_int(v) for v in steps[-1].ts]
    summary = {
        "tile_scores": ts,
        "tile_total": sum(ts),
        "base_total": sum(P.to_int(v) for v in steps[0].ts),
        "word_score": P.to_int(word_score),
        "multiplier": multiplier,
        "money_bonus": steps[-1].money - steps[0].money,
        "effects": effects,
    }
    summary["pipeline"] = dict(summary)  # old ScoringPipeline breakdown shape
    return summary
