"""Load per-item shop advice tags from data/game/item_subclasses.json."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_METADATA_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "game" / "item_subclasses.json"
)
_CATALOG_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "wiki" / "stickers.json"
)

# Wiki slug / catalog game_class → Assembly-CSharp class when names diverge.
_GAME_CLASS_ALIASES: dict[str, str] = {
    "young_cardinal": "NorthernCardinal",
    "YoungCardinal": "NorthernCardinal",
}


@dataclass(frozen=True)
class ItemAdviceMetadata:
    game_class: str
    tags: tuple[str, ...]
    dependency_tags: tuple[str, ...]
    shop_advice_additional_tags: tuple[str, ...]
    shop_advice_tags: tuple[str, ...]
    function_tags: tuple[str, ...]
    blacklisted_from_shop_recommendations: bool


def slug_to_game_class(slug: str) -> str:
    parts = re.sub(r"[^a-z0-9]+", "_", (slug or "").lower()).strip("_").split("_")
    return "".join(p.capitalize() for p in parts if p)


def _tuple_list(value: object) -> tuple[str, ...]:
    if not value:
        return ()
    if isinstance(value, list):
        return tuple(str(v) for v in value if v)
    if isinstance(value, str):
        return (value,)
    return ()


@lru_cache(maxsize=1)
def load_item_metadata_by_class() -> dict[str, ItemAdviceMetadata]:
    if not _METADATA_PATH.is_file():
        return {}
    data = json.loads(_METADATA_PATH.read_text(encoding="utf-8"))
    out: dict[str, ItemAdviceMetadata] = {}
    for row in data.get("subclasses") or []:
        name = row.get("name") or ""
        if not name:
            continue
        out[name] = ItemAdviceMetadata(
            game_class=name,
            tags=_tuple_list(row.get("tags")),
            dependency_tags=_tuple_list(row.get("dependency_tags")),
            shop_advice_additional_tags=_tuple_list(
                row.get("shop_advice_additional_tags")
            ),
            shop_advice_tags=_tuple_list(row.get("shop_advice_tags")),
            function_tags=_tuple_list(row.get("function_tags")),
            blacklisted_from_shop_recommendations=bool(
                row.get("blacklisted_from_shop_recommendations", False)
            ),
        )
    return out


def _catalog_game_class(slug: str) -> str | None:
    if not _CATALOG_PATH.is_file():
        return None
    try:
        data = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    for section in ("stickers", "stamps"):
        entry = (data.get(section) or {}).get(slug) or {}
        gc = entry.get("game_class")
        if gc:
            return str(gc)
    return None


def resolve_game_class(slug: str) -> str:
    key = (slug or "").lower()
    if key in _GAME_CLASS_ALIASES:
        return _GAME_CLASS_ALIASES[key]
    catalog = _catalog_game_class(slug)
    if catalog:
        return _GAME_CLASS_ALIASES.get(catalog, catalog)
    return slug_to_game_class(slug)


def lookup_metadata_for_slug(slug: str) -> ItemAdviceMetadata | None:
    by_class = load_item_metadata_by_class()
    game_class = resolve_game_class(slug)
    return by_class.get(game_class)
