"""Catalog paths resolve to the repository data directory in a checkout."""

from cursed_words_solver.paths import data_path, project_root


def test_project_root_contains_sticker_catalog():
    root = project_root()
    assert (root / "data" / "wiki" / "stickers.json").is_file()
    assert data_path("data", "wiki", "stickers.json") == (
        root / "data" / "wiki" / "stickers.json"
    )
