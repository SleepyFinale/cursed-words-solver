"""Parallel search payload tests."""

from __future__ import annotations

from concurrent.futures import Future

from cursed_words_solver.models import Board, Loadout
from cursed_words_solver.search import WordSearcher, _CandidateHeap
from cursed_words_solver.search_parallel import parallel_collect_fair_starts
from tests.test_search import _tile


class _CaptureExecutor:
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    def submit(self, fn, payload):  # noqa: ANN001
        self.payloads.append(payload)
        fut: Future = Future()
        fut.set_result([])
        return fut


def test_parallel_payload_includes_required_consumable_indices():
    board = Board(tiles=[[_tile("a", r, c) for c in range(5)] for r in range(5)])
    loadout = Loadout()
    candidates = _CandidateHeap(10)
    executor = _CaptureExecutor()
    required = frozenset({2, 7})

    parallel_collect_fair_starts(
        executor=executor,
        workers=2,
        board=board,
        loadout=loadout,
        candidates=candidates,
        deadline=1e9,
        max_len=5,
        min_len=3,
        starts=[0, 1, 2, 3],
        digits_only=False,
        setup_weight=0.0,
        setup_discount=0.0,
        use_fast_rank=False,
        use_tier2_screen=False,
        required_consumable_indices=required,
    )

    assert executor.payloads
    for payload in executor.payloads:
        assert payload["required_consumable_indices"] == [2, 7]


def test_searcher_passes_required_indices_to_parallel(monkeypatch):
    board = Board(tiles=[[_tile("a", r, c) for c in range(5)] for r in range(5)])
    loadout = Loadout()
    captured: list[frozenset[int]] = []

    def fake_parallel(**kwargs):
        captured.append(kwargs.get("required_consumable_indices") or frozenset())

    monkeypatch.setattr(
        "cursed_words_solver.search_parallel.parallel_collect_fair_starts",
        fake_parallel,
    )

    searcher = WordSearcher(
        dictionary=None,
        min_len=3,
        max_len=5,
        time_budget=1.0,
        search_workers=8,
    )
    searcher._parallel_executor = object()
    searcher.validator.required_consumable_indices = frozenset({12})
    candidates = _CandidateHeap(10)

    searcher._collect_words_fair_starts(
        board,
        loadout,
        candidates,
        pass_deadline=1e9,
        max_len=5,
        starts=[0, 1, 2, 3],
    )

    assert captured == [frozenset({12})]
