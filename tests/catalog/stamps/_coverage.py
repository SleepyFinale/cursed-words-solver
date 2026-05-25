"""Shared helpers for stamp catalog coverage tests."""

from cursed_words_solver.models import Loadout, LoadoutItem
from cursed_words_solver.rules.rule_lookup import (
    count_scoring_items,
    get_rule,
    is_scoring_rule,
    slugify_name,
    stamp_is_catalog_inactive,
)


def expected_stamp_counts(rules: dict, names: list[str]) -> tuple[int, int, int]:
    """Return (scoring, grid_only, search_only) for stamp display names."""
    scoring = grid_only = search_only = 0
    for name in names:
        slug = slugify_name(name)
        _key, rule = get_rule(rules, "stamps", slug, name)
        if not rule:
            continue
        if is_scoring_rule(rule):
            scoring += 1
        elif rule.get("effect_class") == "movement" or rule.get("search_flags"):
            search_only += 1
        elif stamp_is_catalog_inactive(rule):
            grid_only += 1
    return scoring, grid_only, search_only


def assert_loadout_stamp_coverage(rules: dict, names: list[str]) -> None:
    loadout = Loadout(
        stamps=[
            LoadoutItem(id=slugify_name(n), name=n, level=1, kind="stamp") for n in names
        ]
    )
    scoring, total, grid_only = count_scoring_items(rules, loadout)
    assert total == len(names)
    exp_scoring, exp_grid, exp_search = expected_stamp_counts(rules, names)
    assert grid_only == exp_grid, f"grid_only {grid_only} != {exp_grid}"
    assert scoring == exp_scoring, f"scoring {scoring} != {exp_scoring}"
