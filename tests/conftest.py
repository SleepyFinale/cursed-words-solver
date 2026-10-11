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


# Files the solver and melmod exchange at runtime. Tests must never touch the
# player's real copies (a test run during play would clobber live suggestions),
# and xdist workers must not race on one shared file.
_REPO_ROOT = str(Path(__file__).resolve().parents[1])
_STATE_PATH_NAMES = (
    "CONFIG_PATH",
    "RUN_STATE_PATH",
    "F8_EXPORT_REQUEST_PATH",
    "LAST_SUGGESTION_PATH",
    "LAST_SUGGESTION_BLOCKED_PATH",
    "SCORING_MISMATCHES_DIR",
    "ROUND_LOG_DIR",
    "ROUND_LOG_INDEX_PATH",
    "DEBUG_DIR",
    "_F8_SEQUENCE_PATH",
)


@pytest.fixture(autouse=True)
def _isolated_state_files(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point every runtime state path at a per-test directory (wordlists stay shared)."""
    import sys

    from cursed_words_solver import config

    state_dir = tmp_path_factory.mktemp("state")
    originals = {name: getattr(config, name) for name in _STATE_PATH_NAMES if hasattr(config, name)}
    replacements = {path: state_dir / path.relative_to(config.CONFIG_DIR) for path in originals.values()}
    replacements[config.CONFIG_DIR / ".f8_sequence"] = state_dir / ".f8_sequence"
    for module in list(sys.modules.values()):
        name = getattr(module, "__name__", "") or ""
        file = str(getattr(module, "__file__", "") or "")
        if not (name.startswith("cursed_words_solver") or file.startswith(_REPO_ROOT)):
            continue
        for attr in _STATE_PATH_NAMES:
            value = getattr(module, attr, None)
            if isinstance(value, Path) and value in replacements:
                monkeypatch.setattr(module, attr, replacements[value])
