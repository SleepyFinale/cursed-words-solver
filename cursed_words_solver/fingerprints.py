"""Fingerprints aligned with melmod RunStateExporter / BoardExporter."""

from __future__ import annotations

from cursed_words_solver.models import Board, Loadout, LoadoutItem


def _tile_crossed_out_from_metadata(tile: object) -> bool:
    meta = getattr(tile, "metadata", None) or {}
    if not isinstance(meta, dict):
        return False
    val = meta.get("is_crossed_out")
    return val in (True, "true", "True", "1", 1)


def boss_fingerprint_id(boss_id: str) -> str:
    """Match melmod AppendBossFingerprint (empty boss → '-')."""
    return boss_id if boss_id else "-"


def slugify(art_or_name: str, fallback: str = "") -> str:
    """Match RunStateExporter.Slugify (melmod)."""
    raw = (art_or_name or fallback or "").strip()
    if not raw:
        return "unknown"
    if "." in raw:
        raw = raw.rsplit(".", 1)[0]
    out: list[str] = []
    prev_us = False
    for ch in raw.lower():
        if ch.isalnum():
            out.append(ch)
            prev_us = False
        elif not prev_us:
            out.append("_")
            prev_us = True
    slug = "".join(out).strip("_")
    return slug or "unknown"


def _append_items(parts: list[str], items: list[LoadoutItem]) -> None:
    first = True
    for item in items:
        if not first:
            parts.append(",")
        first = False
        parts.append(item.id or slugify(item.name))
        parts.append(":")
        parts.append(str(item.level))


def _tile_fingerprint_parts(
    letter: str,
    curse: str,
    color: str,
    *,
    crossed_out: bool = False,
) -> list[str]:
    """Letter/curse/color segment for one tile (optional /x when crossed out)."""
    parts = [letter or "", "/", curse or "", "/", color or ""]
    if crossed_out:
        parts.append("/x")
    parts.append(";")
    return parts


def board_fingerprint(board: Board) -> str:
    """Match BoardExporter.ComputeBoardFingerprint."""
    parts: list[str] = [str(board.money), "|"]
    for t in board.flat:
        parts.extend(
            [
                str(t.row),
                ",",
                str(t.col),
                ":",
                *_tile_fingerprint_parts(
                    t.letter or "",
                    t.curse.value if t.curse else "",
                    t.color.value if t.color else "",
                    crossed_out=_tile_crossed_out_from_metadata(t),
                ),
            ]
        )
    return "".join(parts)


def loadout_fingerprint(loadout: Loadout) -> str:
    """Match melmod loadout portion of ComputeFingerprint (no board)."""
    parts: list[str] = [
        loadout.character or "",
        "|",
        str(loadout.money),
        "|",
    ]
    _append_items(parts, loadout.stickers)
    parts.append("|")
    _append_items(parts, loadout.stamps)
    parts.append("|")
    parts.append(boss_fingerprint_id(loadout.boss_id))
    parts.append("|")
    pin_effect = str(loadout.extras.get("pin_effect", "") or "")
    parts.append(pin_effect)
    parts.append(":")
    parts.append(loadout.pin_branch or "")
    return "".join(parts)


def fingerprints_from_run_state(data: dict) -> tuple[str, str]:
    """Board + loadout fingerprints from raw run_state.json (melmod shape)."""
    board_data = data.get("board") if isinstance(data.get("board"), dict) else {}
    money = int(board_data.get("money", data.get("money", 0)))
    tile_parts: list[str] = [str(money), "|"]
    tiles = board_data.get("tiles") if isinstance(board_data.get("tiles"), list) else []
    for t in tiles:
        if not isinstance(t, dict):
            continue
        crossed = t.get("is_crossed_out") in (True, "true", "True", "1", 1)
        tile_parts.extend(
            [
                str(t.get("row", 0)),
                ",",
                str(t.get("col", 0)),
                ":",
                *_tile_fingerprint_parts(
                    str(t.get("letter") or ""),
                    str(t.get("curse") or ""),
                    str(t.get("color") or ""),
                    crossed_out=crossed,
                ),
            ]
        )
    board_fp = "".join(tile_parts)

    lo_parts: list[str] = [
        str(data.get("character") or ""),
        "|",
        str(data.get("money", 0)),
        "|",
    ]
    for key in ("stickers", "stamps"):
        items = data.get(key) if isinstance(data.get(key), list) else []
        first = True
        for item in items:
            if not isinstance(item, dict):
                continue
            if not first:
                lo_parts.append(",")
            first = False
            lo_parts.append(str(item.get("id") or slugify(str(item.get("name", "")))))
            lo_parts.append(":")
            lo_parts.append(str(item.get("level", 1)))
        lo_parts.append("|")
    boss = data.get("boss") if isinstance(data.get("boss"), dict) else {}
    lo_parts.append(
        boss_fingerprint_id(str(boss.get("id") or data.get("boss_id") or ""))
    )
    lo_parts.append("|")
    extras = data.get("extras") if isinstance(data.get("extras"), dict) else {}
    lo_parts.append(str(extras.get("pin_effect", "") or ""))
    lo_parts.append(":")
    lo_parts.append(str(data.get("pin_branch") or ""))
    return board_fp, "".join(lo_parts)


def board_tiles_fingerprint_suffix(board_fp: str) -> str:
    """Tile portion of melmod board fingerprint (after leading money|)."""
    fp = (board_fp or "").strip()
    if "|" in fp:
        return fp.split("|", 1)[1]
    return fp
