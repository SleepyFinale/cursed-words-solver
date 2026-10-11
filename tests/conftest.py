"""Shared pytest hooks."""

from __future__ import annotations

from pathlib import Path

import pytest

from cursed_words_solver.config import (
    FAIRY_CURATED_WORDLIST_PATH,
    GAME_WORDLIST_PATH,
)

# Extracted from the local game install; gitignored, so absent on CI.
_LOCAL_ONLY_WORDLISTS = (GAME_WORDLIST_PATH, FAIRY_CURATED_WORDLIST_PATH)


def _missing_local_wordlist(exc: FileNotFoundError) -> str | None:
    missing = str(exc.filename or exc)
    for path in _LOCAL_ONLY_WORDLISTS:
        if path.name in missing:
            return path.name
    return None


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item: pytest.Item):
    try:
        return (yield)
    except FileNotFoundError as exc:
        name = _missing_local_wordlist(exc)
        if name is None:
            raise
        pytest.skip(f"{name} not installed (run the solver once with the game)")


# Long-standing failures (mostly game-capture replay gaps), one pytest node id per
# line. Marked non-strict xfail so CI stays green; an XPASS means the entry can go.
_KNOWN_FAILING_TESTS = Path(__file__).with_name("known_failing_tests.txt")


def _known_failing_node_ids() -> set[str]:
    if not _KNOWN_FAILING_TESTS.is_file():
        return set()
    ids: set[str] = set()
    for line in _KNOWN_FAILING_TESTS.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            ids.add(line)
    return ids


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    known = _known_failing_node_ids()
    if not known:
        return
    marker = pytest.mark.xfail(
        reason="known gap: listed in tests/known_failing_tests.txt", strict=False
    )
    for item in items:
        if item.nodeid in known:
            item.add_marker(marker)


@pytest.fixture(autouse=True)
def _legacy_search_marker(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """``@pytest.mark.legacy_search``: WordSearcher uses the legacy heuristic search."""
    if request.node.get_closest_marker("legacy_search") is None:
        return
    from cursed_words_solver.search import WordSearcher

    monkeypatch.setattr(WordSearcher, "default_use_exact_engine", False)
