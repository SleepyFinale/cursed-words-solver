"""Persist F8 solver suggestion for melmod scoring comparison."""



from __future__ import annotations



import json

from datetime import datetime, timezone

from typing import Any



from cursed_words_solver.config import LAST_SUGGESTION_PATH

from cursed_words_solver.dictionary import WordDictionary

from cursed_words_solver.fingerprints import board_fingerprint, fingerprints_from_run_state

from cursed_words_solver.models import Board, Loadout, WordResult

from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.stamp_behaviors import stamp_search_flags

from cursed_words_solver.search import PathValidator, physical_word_for_path



SOLVER_VERSION = "0.1.0"

_F8_SEQUENCE_PATH = LAST_SUGGESTION_PATH.parent / ".f8_sequence"



def stale_suggestion_warning(
    current_board_fp: str,
    *,
    current_loadout_fp: str | None = None,
) -> str | None:
    """Return a startup note when last F8 was for a different board or run context."""
    current = (current_board_fp or "").strip()
    if not current or not LAST_SUGGESTION_PATH.exists():
        return None
    try:
        data = json.loads(LAST_SUGGESTION_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    previous_board = str(data.get("board_fingerprint") or "").strip()
    loadout = (current_loadout_fp or "").strip()
    previous_loadout = str(data.get("loadout_fingerprint") or "").strip()
    if previous_board and previous_board == current:
        if loadout and previous_loadout and previous_loadout != loadout:
            return (
                "Note: loadout changed since last F8 (e.g. Bicycle acc) — "
                "press F8 again before submitting."
            )
        return None
    if not previous_board:
        return None
    if loadout and previous_loadout and previous_loadout != loadout:
        return (
            "Note: last F8 was for a different run — "
            "press F8 to refresh before submitting."
        )
    return (
        "Note: board changed since last F8 — "
        "press F8 again before submitting."
    )


def _last_suggestion_fingerprint_data() -> dict[str, Any] | None:
    if not LAST_SUGGESTION_PATH.exists():
        return None
    try:
        data = json.loads(LAST_SUGGESTION_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _mutating_dna_letter_counts_equal(previous: str, current: str) -> bool:
    """True when JSON letter-count maps match (key order ignored)."""
    prev = (previous or "").strip() or "{}"
    cur = (current or "").strip() or "{}"
    if prev == cur:
        return True
    try:
        prev_obj = json.loads(prev)
        cur_obj = json.loads(cur)
    except (json.JSONDecodeError, TypeError):
        return prev == cur
    if not isinstance(prev_obj, dict) or not isinstance(cur_obj, dict):
        return prev == cur
    prev_norm = {
        str(k).lower(): int(v)
        for k, v in prev_obj.items()
        if str(k).strip()
    }
    cur_norm = {
        str(k).lower(): int(v)
        for k, v in cur_obj.items()
        if str(k).strip()
    }
    return prev_norm == cur_norm


def _historic_words_count(raw: str) -> int:
    """Parse historic_words JSON array length safely."""
    raw = (raw or "").strip()
    if not raw or raw == "[]":
        return 0
    try:
        arr = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return 0
    return len(arr) if isinstance(arr, list) else 0


def _f8_snapshot_extras(data: dict[str, Any]) -> dict[str, Any]:
    snapshot = data.get("run_state_snapshot")
    if isinstance(snapshot, dict):
        raw = snapshot.get("extras")
        if isinstance(raw, dict):
            return raw
    return {}


def workflow_stale_vs_f8_snapshot(
    run_state_extras: dict[str, Any] | None,
    f8_snapshot_extras: dict[str, Any] | None,
) -> str | None:
    """Human-readable reason when workflow extras drifted since F8 (mirrors melmod)."""
    extras = run_state_extras if isinstance(run_state_extras, dict) else {}
    f8_extras = f8_snapshot_extras if isinstance(f8_snapshot_extras, dict) else {}
    notes: list[str] = []

    prev_letter_f8 = str(f8_extras.get("previous_word_first_letter", "") or "").strip()
    prev_letter_cur = str(extras.get("previous_word_first_letter", "") or "").strip()
    if (
        prev_letter_f8
        and prev_letter_cur
        and prev_letter_f8.lower() != prev_letter_cur.lower()
    ):
        notes.append(f"previous word letter {prev_letter_f8}→{prev_letter_cur}")

    hist_f8 = str(f8_extras.get("historic_words", "") or "").strip()
    hist_cur = str(extras.get("historic_words", "") or "").strip()
    if hist_f8 != hist_cur and (hist_f8 or hist_cur):
        count_f8 = _historic_words_count(hist_f8)
        count_cur = _historic_words_count(hist_cur)
        if count_cur > count_f8:
            notes.append(f"historic words changed ({count_f8}→{count_cur})")
        elif hist_f8 and hist_cur:
            notes.append("historic words changed")

    prev_dna = str(f8_extras.get("mutating_dna_letter_counts", "") or "").strip()
    cur_dna = str(extras.get("mutating_dna_letter_counts", "") or "").strip()
    has_dna = (prev_dna and prev_dna != "{}") or (cur_dna and cur_dna != "{}")
    if (
        has_dna
        and prev_dna
        and cur_dna
        and not _mutating_dna_letter_counts_equal(prev_dna, cur_dna)
    ):
        notes.append("mutating DNA counts changed")

    if not notes:
        return None
    return "; ".join(notes)


def f8_prior_suggestion_stale_note(
    run_state_extras: dict[str, Any] | None,
) -> str | None:
    """Note when run_state workflow drifted since the prior F8 embed (before overwriting)."""
    if not LAST_SUGGESTION_PATH.exists():
        return None
    data = _last_suggestion_fingerprint_data()
    if data is None:
        return None
    reason = workflow_stale_vs_f8_snapshot(
        run_state_extras if isinstance(run_state_extras, dict) else {},
        _f8_snapshot_extras(data),
    )
    if reason is None:
        return None
    return (
        "Played a word since last F8 "
        f"({reason}) — prior overlay suggestion was stale; this F8 refreshes it."
    )


def clear_stale_last_suggestion_if_workflow_changed(
    run_state_extras: dict[str, Any] | None,
) -> str | None:
    """Remove last_suggestion.json when a word was played since F8 (no board-fp gate)."""
    data = _last_suggestion_fingerprint_data()
    if data is None:
        return None
    reason = workflow_stale_vs_f8_snapshot(
        run_state_extras,
        _f8_snapshot_extras(data),
    )
    if reason is None:
        return None
    if clear_last_suggestion():
        return reason
    return None


def clear_stale_last_suggestion_if_fingerprint_changed(
    current_board_fp: str,
    *,
    current_loadout_fp: str | None = None,
) -> str | None:
    """Remove last_suggestion.json when board or loadout fingerprint drifted since F8."""
    if not LAST_SUGGESTION_PATH.exists():
        return None
    note = stale_suggestion_warning(
        current_board_fp,
        current_loadout_fp=current_loadout_fp,
    )
    if note is None:
        return None
    if clear_last_suggestion():
        return note
    return None


def poll_invalidate_last_suggestion(
    run_state_extras: dict[str, Any] | None,
    *,
    current_board_fp: str = "",
    current_loadout_fp: str | None = None,
) -> str | None:
    """Clear last_suggestion.json when workflow or fingerprint drift is detected."""
    if not LAST_SUGGESTION_PATH.exists():
        return None

    reason = clear_stale_last_suggestion_if_workflow_changed(run_state_extras)
    if reason:
        return f"Played word since F8 ({reason})"

    fp_reason = clear_stale_last_suggestion_if_fingerprint_changed(
        current_board_fp,
        current_loadout_fp=current_loadout_fp,
    )
    if fp_reason:
        return fp_reason

    if clear_stale_last_suggestion_if_context_changed(
        current_board_fp,
        current_loadout_fp=current_loadout_fp,
        run_state_extras=run_state_extras,
    ):
        return "loadout or scoring extras changed on same board"

    return None


def clear_stale_last_suggestion_if_context_changed(
    current_board_fp: str,
    *,
    current_loadout_fp: str | None = None,
    run_state_extras: dict[str, Any] | None = None,
) -> bool:
    """Remove last_suggestion.json when board/loadout/extras drift on the same board."""
    data = _last_suggestion_fingerprint_data()
    if data is None:
        return False
    previous_board = str(data.get("board_fingerprint") or "").strip()
    current_board = (current_board_fp or "").strip()
    if not previous_board or not current_board or previous_board != current_board:
        return False

    previous_loadout = str(data.get("loadout_fingerprint") or "").strip()
    current_loadout = (current_loadout_fp or "").strip()
    if current_loadout and previous_loadout and previous_loadout != current_loadout:
        return clear_last_suggestion()

    snapshot_extras = _f8_snapshot_extras(data)
    extras = run_state_extras if isinstance(run_state_extras, dict) else {}
    if workflow_stale_vs_f8_snapshot(extras, snapshot_extras):
        return clear_last_suggestion()

    for key in ("bicycle_word_score_bonus", "cards_submitted"):
        prev = str(snapshot_extras.get(key, "") or "").strip()
        cur = str(extras.get(key, "") or "").strip()
        if prev and cur and prev != cur:
            return clear_last_suggestion()
    return False


def clear_last_suggestion() -> bool:
    """Remove last_suggestion.json (failed solve or explicit invalidation)."""
    if not LAST_SUGGESTION_PATH.exists():
        return False
    try:
        LAST_SUGGESTION_PATH.unlink()
    except OSError:
        return False
    return True


def clear_stale_last_suggestion_if_loadout_changed(current_loadout_fp: str) -> bool:
    """Remove last_suggestion.json when character/loadout changed (new run)."""
    current = (current_loadout_fp or "").strip()
    if not current or not LAST_SUGGESTION_PATH.exists():
        return False
    try:
        data = json.loads(LAST_SUGGESTION_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    previous = str(data.get("loadout_fingerprint") or "").strip()
    if not previous or previous == current:
        return False
    try:
        LAST_SUGGESTION_PATH.unlink()
    except OSError:
        return False
    return True


def stale_suggestion_warning_for_board(board: Board) -> str | None:
    return stale_suggestion_warning(board_fingerprint(board))


def format_suggestion_word(result: WordResult) -> str:
    """Human-readable suggestion: scoring pattern → dictionary word when they differ."""
    if result.dictionary_word and result.dictionary_word.lower() != result.word.lower():
        return f"{result.word} → {result.dictionary_word}"
    return result.word





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

    pipeline: ScoringPipeline | None = None,

) -> str | None:

    """Best-effort dictionary spelling the game accepts on this path (vs scoring form)."""

    word = scoring_word.lower()

    flags = stamp_search_flags(loadout)

    validator = PathValidator(dictionary, min_len=min_len)

    if word.isalpha() and validator.word_ok(board, path, word, flags):

        return word



    word_len = len(word)

    valid: list[str] = []

    for candidate in dictionary.words_of_length(word_len):
        if "?" in word and not _fixed_letters_align(word, candidate):
            continue
        if not validator.word_ok(board, path, candidate, flags):
            continue
        valid.append(candidate)

    if not valid:

        return None

    aligned = [c for c in valid if _fixed_letters_align(word, c)]

    pool = aligned if aligned else valid

    if pipeline is not None and loadout is not None:
        if len(pool) > 64:
            pool = sorted(
                pool,
                key=lambda c: -_physical_letter_overlap(board, path, c),
            )[:64]

        scored = [
            (c, pipeline.score_total_only(board, path, c, loadout)) for c in pool
        ]
        best_score = max(sc for _, sc in scored)
        top = [c for c, sc in scored if sc >= best_score - 1e-6]
        myrrh_family = [c for c in top if "myrrh" in c]
        pick_from = myrrh_family or top
        return max(
            pick_from,
            key=lambda c: (_physical_letter_overlap(board, path, c), c),
        )

    return max(pool, key=lambda c: (_physical_letter_overlap(board, path, c), c))





def save_last_suggestion(

    *,

    board: Board,

    loadout: Loadout,

    result: WordResult,

    predicted_trace: list[dict[str, Any]],

    run_state_snapshot: dict[str, Any] | None = None,

    dictionary: WordDictionary | None = None,
    min_len: int = 3,
    export_diagnostics: dict[str, Any] | None = None,
    export_warnings: list[str] | None = None,
    solver_session_extras: dict[str, Any] | None = None,

) -> None:

    """Write last_suggestion.json for the companion mod after F8 solve."""

    LAST_SUGGESTION_PATH.parent.mkdir(parents=True, exist_ok=True)

    board_fp = ""

    loadout_fp = ""

    if run_state_snapshot is not None:

        board_fp, loadout_fp = fingerprints_from_run_state(run_state_snapshot)



    scoring_word = result.word
    phys_word = physical_word_for_path(
        board, result.path, flags=stamp_search_flags(loadout)
    )
    if phys_word != scoring_word.lower():
        scoring_word = phys_word

    dict_word: str | None = None

    if dictionary is not None:

        dict_word = dictionary_word_for_path(

            board,
            result.path,
            scoring_word,
            loadout,
            dictionary,
            min_len=max(1, int(min_len)),

        )



    f8_sequence = _next_f8_sequence()

    payload: dict[str, Any] = {

        "created_at": datetime.now(timezone.utc).isoformat(),

        "f8_sequence": f8_sequence,

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

    if export_diagnostics:
        payload["export_diagnostics"] = export_diagnostics

    if export_warnings:
        payload["export_warnings"] = list(export_warnings)

    if solver_session_extras:
        payload["solver_session_extras"] = dict(solver_session_extras)

    LAST_SUGGESTION_PATH.write_text(

        json.dumps(payload, indent=2),

        encoding="utf-8",

    )


def _next_f8_sequence() -> int:
    """Monotonic F8 counter for correlating with round_logs."""
    LAST_SUGGESTION_PATH.parent.mkdir(parents=True, exist_ok=True)
    seq = 0
    if _F8_SEQUENCE_PATH.exists():
        try:
            seq = int(_F8_SEQUENCE_PATH.read_text(encoding="utf-8").strip())
        except (TypeError, ValueError):
            seq = 0
    seq += 1
    _F8_SEQUENCE_PATH.write_text(str(seq), encoding="utf-8")
    return seq


