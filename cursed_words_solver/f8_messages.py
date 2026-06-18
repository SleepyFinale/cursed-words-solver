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
