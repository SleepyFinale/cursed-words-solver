"""Sam Gambit unlock stamp catalog (wiki: Unlocked when unlocking Sam Gambit)."""

from cursed_words_solver.models import Loadout, LoadoutItem
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.rule_lookup import get_rule, slugify_name

from tests.catalog.stamps._coverage import assert_loadout_stamp_coverage

SAM_STAMP_NAMES = [
    "Business Goose",
    "Queen Bee",
]

GRID_ONLY_SLUGS = {
    "business_goose",
    "queen_bee",
}


def test_all_sam_stamps_catalogued():
    pipeline = ScoringPipeline()
    for name in SAM_STAMP_NAMES:
        slug = slugify_name(name)
        _key, rule = get_rule(pipeline.rules, "stamps", slug, name)
        assert rule is not None, slug
        assert rule.get("type") != "unmodeled", slug
        assert rule.get("effect_class") == "scatter", slug


def test_count_scoring_vs_grid_only_sam_stamps():
    pipeline = ScoringPipeline()
    assert_loadout_stamp_coverage(pipeline.rules, SAM_STAMP_NAMES)

