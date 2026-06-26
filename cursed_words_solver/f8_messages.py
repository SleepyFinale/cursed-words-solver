"""User-facing messages for the single-F8 workflow."""

from __future__ import annotations

F8_RETRY_HINT = "wait a moment and press F8 again"


def gather_block_reason(missing: list[str] | None) -> str:
    """Machine-readable block reason for incomplete F8 gather."""
    if not missing:
        return "gather_incomplete"
    field = missing[0].replace("/", "_").replace(" ", "_")
    return f"gather_incomplete:{field}"


def gather_incomplete_message(missing: list[str] | None) -> str:
    """Human-readable message when melmod did not export required fields in time."""
    if missing:
        fields = ", ".join(missing)
    else:
        fields = "required export fields"
    return f"F8 export incomplete ({fields}) — {F8_RETRY_HINT}."


_BLOCK_REASON_OVERLAY: dict[str, str] = {
    "workflow_bleed": (
        f"Scoring cache not ready — path shown; score untrusted. {F8_RETRY_HINT}."
    ),
    "submit_projection_mismatch": (
        f"Encounter historic may not match submit — path shown; score untrusted. "
        f"{F8_RETRY_HINT}."
    ),
    "historic_catchup_stale": f"Historic still catching up — {F8_RETRY_HINT}.",
    "behind_disk": f"Melmod export behind disk — {F8_RETRY_HINT}.",
    "bento_previous_word_stale": f"Previous-word letter stale — {F8_RETRY_HINT}.",
    "empty_historic_on_later_grid": f"Encounter historic missing — {F8_RETRY_HINT}.",
    "no_playable_dictionary_word": (
        f"No dictionary word on path — path shown; score untrusted. {F8_RETRY_HINT}."
    ),
    "invalid_path_movement": (
        f"Path uses illegal moves for this quest — path shown; score untrusted. "
        f"{F8_RETRY_HINT}."
    ),
}


def format_f8_block_reason_html(block_reason: str | None) -> str:
    """Overlay warning HTML when F8 capture was blocked."""
    if not block_reason:
        return ""
    text = _BLOCK_REASON_OVERLAY.get(block_reason)
    if text is None:
        text = f"Suggestion not saved ({block_reason}) — {F8_RETRY_HINT}."
    return (
        f"<span style='color:#fa0;font-weight:bold'>{text}</span>"
    )
