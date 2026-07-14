"""Score-aware best-first / beam search for word paths.

Replaces feature-specific DFS time reserves with a unified priority frontier
guided by BoardValueModel. Final scores still come from ScoringPipeline.
"""

from __future__ import annotations

import heapq
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from cursed_words_solver.board_value_model import BoardValueModel
from cursed_words_solver.dictionary import TrieCursor
from cursed_words_solver.models import Board, CurseType, Loadout
from cursed_words_solver.rules.fraction_tiles import (
    fraction_position_valid,
    is_fraction_tile,
)
from cursed_words_solver.rules.stamp_behaviors import (
    FLAG_WORD_STITCH,
    SearchFlagsMask,
    flag_test,
)

if TYPE_CHECKING:
    from cursed_words_solver.search import WordSearcher, _CandidateHeap

DEFAULT_BEAM_WIDTH = 128
MIN_BEAM_WIDTH = 48
MAX_BEAM_WIDTH = 256


@dataclass(slots=True)
class _BeamState:
    path: list[int]
    chars: list[str]
    visited_mask: int
    prefix_cursor: TrieCursor | None
    has_wildcard: bool
    has_digit: bool
    prefix_len: int
    pattern_prefix: str | None
    pattern_cursor: TrieCursor | None
    priority: float


def beam_width_for_model(model: BoardValueModel, *, time_budget: float) -> int:
    """Adaptive beam width from board shape (no cross-solve memory)."""
    width = DEFAULT_BEAM_WIDTH
    if model.wildcard_density >= 0.2:
        width = 80
    elif model.wildcard_density >= 0.12:
        width = 96
    if model.item_count >= 2:
        width = max(width, 144)
    if model.chess_count >= 3:
        width = max(width, 128)
    if model.must_include_mask:
        width = max(width, 128)
    if time_budget < 6.0:
        width = min(width, 72)
    elif time_budget >= 30.0:
        width = min(MAX_BEAM_WIDTH, int(width * 1.35))
    return max(MIN_BEAM_WIDTH, min(MAX_BEAM_WIDTH, width))


def collect_beam_candidates(
    searcher: WordSearcher,
    board: Board,
    loadout: Loadout,
    candidates: _CandidateHeap,
    deadline: float,
    *,
    max_len: int,
    value_model: BoardValueModel,
    beam_width: int | None = None,
    start_indices: list[int] | None = None,
    must_include_index: int | None = None,
) -> None:
    """Best-first beam expansion into ``candidates`` until deadline."""
    from cursed_words_solver.search import (
        _iter_expansion_neighbors,
        _legal_word_start_indices,
        _min_steps_to_index,
        _order_number_wildcard_branch_letters,
        _trie_branch_letters,
        _wildcard_branch_letters,
        neighbors_mask,
        number_position_valid,
        path_scattered_search_flags_mask,
        resolve_letter,
        resolve_letter_options,
        tile_playable_for_path,
    )
    from cursed_words_solver.suggestion import path_tiles_need_dictionary_resolve

    ctx = searcher._search_ctx(loadout)
    stamp_flags = ctx.search_flags
    if flag_test(stamp_flags, FLAG_WORD_STITCH):
        # Stitch needs suffix-cursor state; fall back to DFS collector.
        searcher._collect_words(
            board,
            loadout,
            candidates,
            deadline,
            max_len,
            start_indices=start_indices,
            must_include_index=must_include_index,
        )
        return

    graph_ctx = searcher._board_graph(board)
    timing = searcher._active_timing
    width = beam_width or beam_width_for_model(
        value_model, time_budget=max(1.0, searcher.time_budget)
    )
    hard_must = value_model.must_include_mask
    if must_include_index is not None:
        hard_must |= 1 << must_include_index

    use_prune = searcher._use_mult_prune_for(loadout)
    use_tier2 = searcher._use_tier2_screen_for(loadout)
    use_heap = use_prune or use_tier2
    prev_heap = searcher._prune_heap
    prev_deadline = searcher._active_deadline
    searcher._prune_heap = candidates if use_heap else None
    searcher._active_deadline = deadline
    check_interval = searcher._time_check_interval(loadout)
    hanafuda_level = ctx.hanafuda_level
    use_hanafuda_physical = hanafuda_level > 0
    mult_hints = searcher._mult_hints

    def path_flags_for(path: list[int]) -> SearchFlagsMask:
        return path_scattered_search_flags_mask(
            board, path, stamp_flags, searcher.scoring.rules
        )

    def score_path(
        path: list[int],
        word: str,
        *,
        resolved_word: str | None = None,
    ) -> float | None:
        return searcher._rank_score_for_candidate(
            board,
            path,
            word,
            loadout,
            prune_heap=candidates if use_heap else None,
            resolved_word=resolved_word,
        )

    def consider_word(
        path: list[int],
        chars: list[str],
        *,
        prefix_cursor: TrieCursor | None,
        has_wildcard: bool,
        has_digit: bool,
        pattern_cursor: TrieCursor | None,
    ) -> None:
        if len(chars) < searcher.min_len:
            return
        if hard_must and (hard_must & _path_mask(path)) != hard_must:
            # Incomplete hard cover — still allow if more tiles can be added later
            # only when scoring at max length; otherwise skip candidate.
            if len(path) >= max_len:
                return
            # Soft: don't score incomplete must-include paths as finalists
            return
        letter_trie = not has_digit
        is_alpha_path = not has_wildcard and not has_digit
        trie_fast_end = (
            letter_trie
            and is_alpha_path
            and prefix_cursor is not None
            and searcher.dictionary.cursor_is_word(prefix_cursor)
        )
        if not (trie_fast_end or has_wildcard or has_digit):
            return
        word = "".join(chars).lower()
        trie_compatible = (
            prefix_cursor is not None and not has_digit and is_alpha_path
        )
        path_flags = path_flags_for(path)
        ok, score_word = searcher._accept_path_for_search(
            board,
            path,
            word,
            loadout,
            path_flags,
            trie_compatible=trie_compatible,
            prefix_cursor=prefix_cursor if letter_trie else None,
            pattern_cursor=pattern_cursor,
            use_hanafuda_physical=use_hanafuda_physical,
        )
        if not ok:
            return
        trie_confirmed = (
            trie_compatible
            and prefix_cursor is not None
            and searcher.dictionary.cursor_is_word(prefix_cursor)
        )
        resolved_word = (
            score_word
            if trie_confirmed and score_word.isalpha() and "?" not in score_word
            else None
        )
        searcher._consider_path_candidate(
            board,
            loadout,
            candidates,
            path,
            score_word,
            path_flags,
            score_path,
            resolved_word=resolved_word,
        )

    def step_token_cursor(
        cursor: TrieCursor | None, token: str
    ) -> TrieCursor | None:
        node = cursor
        for c in token:
            if timing is not None:
                timing.trie_steps += 1
            node = searcher.dictionary.step_cursor(node, c)
            if node is None:
                return None
        return node

    def pattern_after_token(
        pattern_prefix: str | None, token: str, *, active: bool
    ) -> str | None:
        if not active and pattern_prefix is None:
            return None
        out = pattern_prefix or ""
        for ch in token.lower():
            if ch.isdigit():
                out += "?"
            elif ch.isalpha():
                out += ch
        return out

    def step_pattern_cursor(
        cursor: TrieCursor | None, token: str, *, active: bool
    ) -> TrieCursor | None:
        if not active:
            return cursor
        mixed = searcher.dictionary.mixed_step_cursor(cursor, token)
        if timing is not None:
            timing.trie_steps += len(token)
        return mixed

    def prefix_can_continue(
        letter_trie: bool,
        prefix_cursor: TrieCursor | None,
        pattern_prefix: str | None,
        pattern_cursor: TrieCursor | None,
        has_digit_path: bool,
        *,
        path: list[int],
        steps_left: int,
    ) -> bool:
        if letter_trie and prefix_cursor is not None:
            return True
        if has_digit_path and pattern_cursor is not None:
            return True
        if has_digit_path and pattern_prefix is not None:
            return searcher.dictionary.pattern_has_prefix(pattern_prefix)
        if (
            steps_left > 0
            and path_tiles_need_dictionary_resolve(
                board,
                path,
                flags=path_scattered_search_flags_mask(
                    board, path, stamp_flags, searcher.scoring.rules
                ),
            )
        ):
            return True
        return False

    def _path_mask(path: list[int]) -> int:
        m = 0
        for i in path:
            m |= 1 << i
        return m

    # Frontier: (-priority, seq, state)
    frontier: list[tuple[float, int, _BeamState]] = []
    seq = 0
    expansions = 0
    timed_out = False

    def push_state(state: _BeamState) -> None:
        nonlocal seq
        seq += 1
        heapq.heappush(frontier, (-state.priority, seq, state))

    def prune_frontier() -> None:
        if len(frontier) <= width * 3:
            return
        # Keep the best `width` by priority (most negative -priority = best)
        best = heapq.nsmallest(width, frontier)
        frontier.clear()
        frontier.extend(best)
        heapq.heapify(frontier)

    if start_indices is not None:
        starts = [s for s in start_indices if board.is_active_index(s)]
    else:
        starts = _legal_word_start_indices(board)
    starts = value_model.ordered_starts(starts)

    # Prefer covering starts when hard must-include is a non-start cell:
    # still seed all starts; priority handles cover pressure.
    for start in starts:
        if timed_out or searcher._time_expired() or time.monotonic() > deadline:
            timed_out = True
            break
        tile = board.get_by_index(start)
        if not tile_playable_for_path(tile):
            continue
        if is_fraction_tile(tile) and not fraction_position_valid(
            tile, 0, relaxed=False
        ):
            continue
        token = resolve_letter(tile, 0, flags=stamp_flags)
        has_wildcard = "?" in token
        has_digit = any(c.isdigit() for c in token)
        prefix_len = len(token)
        start_options = resolve_letter_options(tile, 0, flags=stamp_flags)
        num_wildcard_letters = (
            _wildcard_branch_letters(tile, 0, flags=stamp_flags)
            if tile.curse == CurseType.NUMBER
            else ()
        )
        branch_letters = _trie_branch_letters(
            tile,
            0,
            start_options,
            token,
            has_digit=has_digit,
            flags=stamp_flags,
        )
        if branch_letters:
            for ch in branch_letters:
                cursor = step_token_cursor(searcher.dictionary.root_cursor(), ch)
                if cursor is None and not has_digit and "?" not in ch:
                    continue
                pat_active = has_wildcard or has_digit or tile.curse == CurseType.NUMBER
                pat = pattern_after_token(None, ch, active=pat_active)
                pat_cursor = step_pattern_cursor(
                    searcher.dictionary.root_cursor() if pat_active else None,
                    ch,
                    active=pat_active,
                )
                pri = value_model.start_priority(start) + value_model.cell_score(start)
                state = _BeamState(
                    path=[start],
                    chars=[ch],
                    visited_mask=1 << start,
                    prefix_cursor=cursor,
                    has_wildcard=has_wildcard or "?" in ch,
                    has_digit=has_digit or any(c.isdigit() for c in ch),
                    prefix_len=len(ch),
                    pattern_prefix=pat,
                    pattern_cursor=pat_cursor,
                    priority=pri,
                )
                push_state(state)
                consider_word(
                    state.path,
                    state.chars,
                    prefix_cursor=state.prefix_cursor,
                    has_wildcard=state.has_wildcard,
                    has_digit=state.has_digit,
                    pattern_cursor=state.pattern_cursor,
                )
        else:
            # Single-token start (digit face, etc.)
            cursor = None
            if not has_digit and token.isalpha():
                cursor = step_token_cursor(searcher.dictionary.root_cursor(), token)
            pat_active = has_wildcard or has_digit
            pat = pattern_after_token(None, token, active=pat_active)
            pat_cursor = step_pattern_cursor(
                searcher.dictionary.root_cursor() if pat_active else None,
                token,
                active=pat_active,
            )
            pri = value_model.start_priority(start)
            state = _BeamState(
                path=[start],
                chars=[token],
                visited_mask=1 << start,
                prefix_cursor=cursor,
                has_wildcard=has_wildcard,
                has_digit=has_digit,
                prefix_len=prefix_len,
                pattern_prefix=pat,
                pattern_cursor=pat_cursor,
                priority=pri,
            )
            push_state(state)

    try:
        while frontier and not timed_out:
            if expansions % check_interval == 0:
                if searcher._time_expired() or time.monotonic() > deadline:
                    timed_out = True
                    break
                searcher._update_tier2_adaptive_mode()
                prune_frontier()

            _neg_pri, _seq, state = heapq.heappop(frontier)
            expansions += 1
            if timing is not None:
                timing.dfs_expansions += 1

            path = state.path
            if len(path) >= max_len:
                consider_word(
                    path,
                    state.chars,
                    prefix_cursor=state.prefix_cursor,
                    has_wildcard=state.has_wildcard,
                    has_digit=state.has_digit,
                    pattern_cursor=state.pattern_cursor,
                )
                continue

            # Score intermediate words before expanding further
            if len(state.chars) >= searcher.min_len:
                consider_word(
                    path,
                    state.chars,
                    prefix_cursor=state.prefix_cursor,
                    has_wildcard=state.has_wildcard,
                    has_digit=state.has_digit,
                    pattern_cursor=state.pattern_cursor,
                )

            path_flags = path_flags_for(path)
            cell = path[-1]
            nbr_mask = neighbors_mask(
                board,
                state.visited_mask,
                cell_id=cell,
                flags=path_flags,
                graph_ctx=graph_ctx,
                loadout=loadout,
            )
            if not nbr_mask:
                continue

            letter_trie = not state.has_digit
            steps_left = max_len - len(path)
            if not prefix_can_continue(
                letter_trie,
                state.prefix_cursor,
                state.pattern_prefix,
                state.pattern_cursor,
                state.has_digit,
                path=path,
                steps_left=steps_left,
            ):
                if timing is not None:
                    timing.trie_prunes += 1
                continue

            for idx in _iter_expansion_neighbors(
                board,
                state.visited_mask,
                cell_id=cell,
                path=path,
                path_length=len(path),
                flags=path_flags,
                hints=mult_hints,
                graph_ctx=graph_ctx,
                loadout=loadout,
                nbr_mask=nbr_mask,
            ):
                if timed_out or searcher._time_expired():
                    timed_out = True
                    break
                tile = board.get_by_index(idx)
                if not tile_playable_for_path(tile):
                    continue
                if is_fraction_tile(tile) and not fraction_position_valid(
                    tile, len(path), relaxed=False
                ):
                    continue
                if (
                    tile.curse == CurseType.NUMBER
                    and not state.has_digit
                    and not number_position_valid(
                        tile, len(path), flags=path_flags
                    )
                ):
                    if timing is not None:
                        timing.number_position_prunes += 1
                    continue

                # Hard must-include reachability prune
                if hard_must:
                    remaining_must = hard_must & ~(state.visited_mask | (1 << idx))
                    if remaining_must:
                        remaining_after = max_len - len(path) - 1
                        if remaining_after < remaining_must.bit_count():
                            continue
                        # Single must cell: BFS distance check
                        if remaining_must.bit_count() == 1:
                            must_idx = remaining_must.bit_length() - 1
                            if idx != must_idx:
                                need = _min_steps_to_index(
                                    board,
                                    idx,
                                    must_idx,
                                    state.visited_mask | (1 << idx),
                                    flags=path_flags,
                                    graph_ctx=graph_ctx,
                                )
                                if need is None or need > remaining_after:
                                    continue

                prefix_len = state.prefix_len
                token = resolve_letter(tile, prefix_len, flags=path_flags)
                partial_seg = "".join(state.chars).lower()
                next_has_digit = state.has_digit or any(c.isdigit() for c in token)
                letter_options = resolve_letter_options(
                    tile, prefix_len, flags=path_flags
                )
                num_wildcard_letters = (
                    _wildcard_branch_letters(
                        tile, prefix_len, flags=path_flags, segment=partial_seg
                    )
                    if tile.curse == CurseType.NUMBER
                    else ()
                )
                branch_letters = _trie_branch_letters(
                    tile,
                    prefix_len,
                    letter_options,
                    token,
                    has_digit=next_has_digit,
                    flags=path_flags,
                    segment=partial_seg,
                )
                if branch_letters and num_wildcard_letters:
                    branch_letters = _order_number_wildcard_branch_letters(
                        searcher.dictionary,
                        branch_letters,
                        prefix_cursor=state.prefix_cursor,
                        partial_seg=partial_seg,
                        shuffle_seed=idx * 31 + len(partial_seg) + board.cols,
                        min_remaining=max(0, searcher.min_len - len(state.chars)),
                    )

                child_tokens: list[tuple[str, TrieCursor | None, TrieCursor | None, bool, str | None]] = []
                if branch_letters:
                    pat_active = (
                        state.has_wildcard
                        or state.has_digit
                        or state.pattern_prefix is not None
                        or state.pattern_cursor is not None
                    )
                    for ch in branch_letters:
                        child = step_token_cursor(state.prefix_cursor, ch)
                        letter_pat_active = (
                            state.has_wildcard
                            or state.has_digit
                            or (
                                tile.curse == CurseType.NUMBER
                                and bool(num_wildcard_letters)
                            )
                        )
                        next_pat = pattern_after_token(
                            state.pattern_prefix, ch, active=letter_pat_active or pat_active
                        )
                        next_pat_cursor = step_pattern_cursor(
                            state.pattern_cursor
                            if state.pattern_cursor is not None
                            else (
                                searcher.dictionary.root_cursor()
                                if letter_pat_active or pat_active
                                else None
                            ),
                            ch,
                            active=letter_pat_active or pat_active,
                        )
                        if (
                            child is None
                            and not next_has_digit
                            and "?" not in ch
                            and not state.has_wildcard
                        ):
                            if timing is not None:
                                timing.trie_prunes += 1
                            continue
                        child_tokens.append(
                            (ch, child, next_pat_cursor, "?" in ch, next_pat)
                        )
                else:
                    # Non-branching token (digit faces, etc.)
                    next_pat_active = (
                        state.has_wildcard
                        or next_has_digit
                        or state.pattern_prefix is not None
                    )
                    next_pat = pattern_after_token(
                        state.pattern_prefix, token, active=next_pat_active
                    )
                    next_pat_cursor = step_pattern_cursor(
                        state.pattern_cursor
                        if state.pattern_cursor is not None
                        else (
                            searcher.dictionary.root_cursor()
                            if next_pat_active
                            else None
                        ),
                        token,
                        active=next_pat_active,
                    )
                    next_cursor = state.prefix_cursor
                    if not next_has_digit and not state.has_wildcard:
                        next_cursor = step_token_cursor(state.prefix_cursor, token)
                        if next_cursor is None and token.isalpha():
                            if timing is not None:
                                timing.trie_prunes += 1
                            continue
                    child_tokens.append(
                        (
                            token,
                            next_cursor,
                            next_pat_cursor,
                            "?" in token,
                            next_pat,
                        )
                    )

                for ext_token, next_cursor, ext_pat_cursor, ext_wild, next_pattern in child_tokens:
                    next_has_wildcard = state.has_wildcard or ext_wild or "?" in ext_token
                    next_ext_has_digit = next_has_digit or any(
                        c.isdigit() for c in ext_token
                    )
                    next_prefix_len = state.prefix_len + len(ext_token)
                    pri = value_model.expand_priority(
                        path=path,
                        visited_mask=state.visited_mask,
                        next_idx=idx,
                        prefix_len=state.prefix_len,
                        min_len=searcher.min_len,
                    )
                    # Prefer trie-continuing letter children slightly
                    if next_cursor is not None and not next_ext_has_digit:
                        pri += 3.0
                    child = _BeamState(
                        path=path + [idx],
                        chars=state.chars + [ext_token],
                        visited_mask=state.visited_mask | (1 << idx),
                        prefix_cursor=next_cursor,
                        has_wildcard=next_has_wildcard,
                        has_digit=next_ext_has_digit,
                        prefix_len=next_prefix_len,
                        pattern_prefix=next_pattern,
                        pattern_cursor=ext_pat_cursor,
                        priority=pri + state.priority * 0.05,
                    )
                    push_state(child)

            if len(frontier) > width * 4:
                prune_frontier()
    finally:
        searcher._prune_heap = prev_heap
        searcher._active_deadline = prev_deadline
