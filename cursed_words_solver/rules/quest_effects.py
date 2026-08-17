"""Quest/challenge constraints (wiki Quests, game ChallengeRun subclasses)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from cursed_words_solver.models import Board, Loadout, Tile, TileColor
from cursed_words_solver.rules.scoring_conditions import tile_is_cursed_for_lexographer
from cursed_words_solver.rules.rule_lookup import slugify_name

_RULES_PATH = Path(__file__).resolve().parents[2] / "data" / "wiki" / "quests.json"

# game_class -> wiki slug
_GAME_CLASS_TO_SLUG: dict[str, str] = {
    "SupplyAndDemand": "on_cooldown",
    "DecisionParalysis": "shelf_life",
    "Sudoku": "advent_calendar",
    "SicilianDefense": "knight_time",
    "ColourSwap": "chromatic_aberration",
    "SpeedrunChallenge": "were_finally_landing",
    "TheBonesRound": "the_bones_round",
    "CallOfTheVoid": "call_of_the_void",
    "EmptyGrid": "empty_grid",
}


@lru_cache(maxsize=1)
def load_quests_catalog() -> dict[str, Any]:
    if not _RULES_PATH.exists():
        return {"quests": {}}
    data = json.loads(_RULES_PATH.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {"quests": {}}


def _extra_str(loadout: Loadout, key: str) -> str:
    return str((loadout.extras or {}).get(key, "") or "").strip()


def _extra_bool(loadout: Loadout, key: str) -> bool:
    val = (loadout.extras or {}).get(key, False)
    return val in (True, "true", "True", "1", 1)


def challenge_game_class_from_fingerprint(fingerprint: str) -> str:
    """Parse quest C# class from melmod ComputeFingerprint (boss|challenge|pin segment)."""
    fp = (fingerprint or "").strip()
    if not fp:
        return ""
    parts = fp.split("|")
    if len(parts) < 6:
        return ""
    candidate = parts[5].strip()
    if not candidate or candidate == "-":
        return ""
    return candidate


def active_quest_game_class(loadout: Loadout | None) -> str:
    if loadout is None:
        return ""
    for key in ("challenge_game_class", "challenge_id"):
        raw = _extra_str(loadout, key)
        if raw:
            return raw
    fp = _extra_str(loadout, "export_diagnostics_fingerprint")
    if fp:
        derived = challenge_game_class_from_fingerprint(fp)
        if derived:
            return derived
    return ""


def path_uses_crossed_out_tile(board: Board, path: list[int]) -> bool:
    """True when any path index is on a crossed-out tile."""
    for idx in path:
        if tile_is_crossed_out(board.get_by_index(idx)):
            return True
    return False


def board_has_crossed_out_tile(board: Board) -> bool:
    for idx in range(25):
        if not board.is_active_index(idx):
            continue
        if tile_is_crossed_out(board.get_by_index(idx)):
            return True
    return False


def active_quest_slug(loadout: Loadout | None) -> str:
    game_class = active_quest_game_class(loadout)
    if not game_class:
        return ""
    if game_class in _GAME_CLASS_TO_SLUG:
        return _GAME_CLASS_TO_SLUG[game_class]
    catalog = load_quests_catalog().get("quests", {})
    for slug, row in catalog.items():
        if isinstance(row, dict) and row.get("game_class") == game_class:
            return slug
    return slugify_name(game_class)


def active_quest_rule(loadout: Loadout | None) -> dict[str, Any] | None:
    slug = active_quest_slug(loadout)
    if not slug:
        return None
    row = load_quests_catalog().get("quests", {}).get(slug)
    return row if isinstance(row, dict) else None


def active_quest_name(loadout: Loadout | None) -> str:
    if loadout is None:
        return ""
    name = _extra_str(loadout, "challenge_name")
    if name:
        return name
    rule = active_quest_rule(loadout)
    if rule:
        return str(rule.get("wiki_name") or "")
    return ""


@dataclass(frozen=True)
class QuestConstraints:
    blocked: bool = False
    block_reason: str = ""
    require_center_index: int | None = None
    knight_only: bool = False
    bones_round: bool = False
    lexographer: bool = False
    two_wrongs: bool = False
    bullseye: bool = False
    playing_favourites: bool = False


def quest_constraints(loadout: Loadout | None) -> QuestConstraints:
    rule = active_quest_rule(loadout)
    if not rule:
        return QuestConstraints()
    game_class = str(rule.get("game_class") or active_quest_game_class(loadout))
    effect = str(rule.get("effect_class") or "")
    center_idx = _up_and_up_center_index(loadout)
    return QuestConstraints(
        require_center_index=center_idx if game_class == "UpAndUp" else None,
        knight_only=game_class == "SicilianDefense" or effect == "movement_override",
        bones_round=game_class == "TheBonesRound",
        lexographer=game_class == "Lexographer",
        two_wrongs=game_class == "TwoWrongs",
        bullseye=game_class == "Bullseye",
        playing_favourites=game_class == "PlayingFavourites",
    )


def _up_and_up_center_index(loadout: Loadout | None) -> int | None:
    if loadout is None:
        return None
    extras = loadout.extras or {}
    raw = extras.get("up_and_up_center_index")
    if raw not in (None, ""):
        try:
            return int(raw)
        except (TypeError, ValueError):
            pass
    raw_row = extras.get("up_and_up_center_row")
    raw_col = extras.get("up_and_up_center_col")
    try:
        row = int(raw_row)
        col = int(raw_col)
        if 0 <= row < 5 and 0 <= col < 5:
            return row * 5 + col
    except (TypeError, ValueError):
        pass
    return None


def tile_is_crossed_out(tile: Tile) -> bool:
    meta = tile.metadata or {}
    val = meta.get("is_crossed_out")
    return val in (True, "true", "True", "1", 1)


def tile_is_up_and_up_center(tile: Tile) -> bool:
    meta = tile.metadata or {}
    val = meta.get("is_up_and_up_center")
    return val in (True, "true", "True", "1", 1)


def tile_is_normal_type(tile: Tile) -> bool:
    """Game TileType.Normal ≈ colorless on melmod export."""
    return tile.color == TileColor.COLORLESS


def tile_is_colored_type(tile: Tile) -> bool:
    return not tile_is_normal_type(tile)


def tile_forbidden_on_quest_path(tile: Tile, loadout: Loadout | None) -> bool:
    """True when ``tile`` can never appear on a quest-legal path.

    Used to prune DFS neighbor expansion (e.g. Cursophobia must not walk onto
    chess ``?`` tiles — those 26-way wildcard explosions starve letter words).
    """
    if tile_is_crossed_out(tile):
        return True
    slug = active_quest_slug(loadout)
    if slug == "chromaphobia":
        return tile_is_colored_type(tile)
    if slug == "chromaphilia":
        return tile_is_normal_type(tile)
    if slug == "cursophobia":
        return tile_is_cursed_for_lexographer(tile, loadout)
    return False


def quest_path_allowed(
    board: Board,
    path: list[int],
    *,
    quest: QuestConstraints | None = None,
    loadout: Loadout | None = None,
) -> bool:
    if not path:
        return True
    q = quest if quest is not None else quest_constraints(loadout)
    for idx in path:
        if tile_forbidden_on_quest_path(board.get_by_index(idx), loadout):
            return False
    if q.require_center_index is not None and q.require_center_index not in path:
        return False
    return True


_HUMAN_HAND_STAMPS = frozenset({"left_human_hand", "right_human_hand"})
_ALWAYS_INCLUDE_STICKERS = frozenset({"left_human_hand"})
_ALWAYS_INCLUDE_STAMPS = frozenset({"right_human_hand"})


def _parse_id_list(raw: str) -> frozenset[str]:
    return frozenset(
        s.strip().lower()
        for s in (raw or "").split(",")
        if s.strip()
    )


def filter_playing_favourites_loadout(loadout: Loadout) -> Loadout:
    """Return loadout with stickers/stamps filtered like Player.GetAllItems (PlayingFavourites)."""
    if active_quest_game_class(loadout) != "PlayingFavourites":
        return loadout
    extras = loadout.extras or {}
    fav_stickers = _parse_id_list(str(extras.get("favourite_sticker_ids", "")))
    fav_stamps = _parse_id_list(str(extras.get("favourite_stamp_ids", "")))
    stickers = []
    for item in loadout.stickers:
        sid = (item.id or slugify_name(item.name)).lower()
        if sid in _ALWAYS_INCLUDE_STICKERS or sid in fav_stickers:
            stickers.append(item)
    stamps: list = []
    right_idx = None
    for i, item in enumerate(loadout.stamps):
        sid = (item.id or slugify_name(item.name)).lower()
        if sid in _ALWAYS_INCLUDE_STAMPS:
            right_idx = i
            stamps.append(item)
            break
    if right_idx is not None and right_idx + 1 < len(loadout.stamps):
        stamps.append(loadout.stamps[right_idx + 1])
    for item in loadout.stamps:
        sid = (item.id or slugify_name(item.name)).lower()
        if sid in fav_stamps and item not in stamps:
            stamps.append(item)
    from dataclasses import replace

    return replace(loadout, stickers=stickers, stamps=stamps)
