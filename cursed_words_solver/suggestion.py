"""Persist F8 solver suggestion for melmod scoring comparison."""



from __future__ import annotations



import json

from datetime import datetime, timezone

from typing import Any



from cursed_words_solver.config import LAST_SUGGESTION_PATH

from cursed_words_solver.dictionary import WordDictionary

from cursed_words_solver.fingerprints import fingerprints_from_run_state

from cursed_words_solver.models import Board, Loadout, WordResult

from cursed_words_solver.rules.stamp_behaviors import stamp_search_flags

from cursed_words_solver.search import PathValidator



SOLVER_VERSION = "0.1.0"





def _fixed_letters_align(scoring_word: str, candidate: str) -> bool:

    """True when every alphabetic char in scoring_word matches the candidate."""

    if len(scoring_word) != len(candidate):

        return False

    for a, b in zip(scoring_word, candidate, strict=True):

        if a.isalpha() and a.lower() != b.lower():

            return False

    return True


def _physical_letter_overlap(board: Board, path: list[int], candidate: str) -> int:
    """Count positions where candidate matches the tile's physical letter."""
    score = 0
    for i, idx in enumerate(path):
        if i >= len(candidate):
            break
        tile = board.get_by_index(idx)
        ph = (tile.letter or tile.char or "").strip().lower()
        if len(ph) == 1 and ph.isalpha() and ph == candidate[i]:
            score += 1
    return score


def dictionary_word_for_path(

    board: Board,

    path: list[int],

    scoring_word: str,

    loadout: Loadout,

    dictionary: WordDictionary,

    *,

    min_len: int = 3,

) -> str | None:

    """Best-effort dictionary spelling the game accepts on this path (vs scoring form)."""

    word = scoring_word.lower()

    flags = stamp_search_flags(loadout)

    validator = PathValidator(dictionary, min_len=min_len)

    if word.isalpha() and validator.word_ok(board, path, word, flags):

        return word



    word_len = len(word)

    aligned: list[str] = []

    fallback: list[str] = []

    for candidate in sorted(dictionary.words):

        if len(candidate) != word_len:

            continue

        if not validator.word_ok(board, path, candidate, flags):

            continue

        if _fixed_letters_align(word, candidate):

            aligned.append(candidate)

        else:

            fallback.append(candidate)

    if aligned:
        return max(
            aligned,
            key=lambda c: (_physical_letter_overlap(board, path, c), c),
        )

    if fallback:

        return fallback[0]

    return None





def save_last_suggestion(

    *,

    board: Board,

    loadout: Loadout,

    result: WordResult,

    predicted_trace: list[dict[str, Any]],

    run_state_snapshot: dict[str, Any] | None = None,

    dictionary: WordDictionary | None = None,

) -> None:

    """Write last_suggestion.json for the companion mod after F8 solve."""

    LAST_SUGGESTION_PATH.parent.mkdir(parents=True, exist_ok=True)

    board_fp = ""

    loadout_fp = ""

    if run_state_snapshot is not None:

        board_fp, loadout_fp = fingerprints_from_run_state(run_state_snapshot)



    scoring_word = result.word

    dict_word: str | None = None

    if dictionary is not None:

        dict_word = dictionary_word_for_path(

            board, result.path, scoring_word, loadout, dictionary

        )



    payload: dict[str, Any] = {

        "created_at": datetime.now(timezone.utc).isoformat(),

        "solver_version": SOLVER_VERSION,

        "word": scoring_word,

        "scoring_word": scoring_word,

        "path": list(result.path),

        "predicted_score": int(result.score),

        "board_fingerprint": board_fp,

        "loadout_fingerprint": loadout_fp,

        "predicted_trace": predicted_trace,

    }

    if dict_word and dict_word != scoring_word.lower():

        payload["dictionary_word"] = dict_word

    if run_state_snapshot is not None:

        payload["run_state_snapshot"] = run_state_snapshot

    LAST_SUGGESTION_PATH.write_text(

        json.dumps(payload, indent=2),

        encoding="utf-8",

    )


