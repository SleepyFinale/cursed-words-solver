#!/usr/bin/env python3
"""Build data/wiki/stickers.json from wiki API dumps and hand-tuned rules."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WIKI_DIR = ROOT / "data" / "wiki"
OUT_PATH = WIKI_DIR / "stickers.json"

# Hand-tuned rules (override generated placeholders)
TUNED_STICKERS: dict[str, dict] = {
    "sticky_plaster": {
        "name": "Sticky Plaster",
        "type": "unmodeled",
        "description": "Number tiles stick; +5/10/15 BASE per level (wiki)",
    },
    "tombstone": {"name": "Tombstone", "type": "add_word_score", "value": 3},
    "red_rider": {"name": "Red Rider", "type": "red_tile_bonus", "value": 10},
    "void_flip": {"name": "Void Flip", "type": "void_flip", "value": 0},
    "long_word": {
        "name": "Long Word",
        "type": "word_length_bonus",
        "value": 20,
        "min_length": 5,
    },
    "shiny_chain": {"name": "Shiny Chain", "type": "shiny_chain", "value": 25},
    "double_score": {"name": "Double Score", "type": "multiply", "factor": 2.0},
}

TUNED_STAMPS: dict[str, dict] = {
    "newspaper": {"name": "Newspaper", "type": "add_word_score", "value": 8},
    "moai": {
        "name": "Moai",
        "type": "word_length_bonus",
        "value": 15,
        "min_length": 4,
    },
}

TUNED_BOSSES: dict[str, dict] = {
    "mole": {
        "name": "Mole",
        "type": "custom",
        "description": "Scatters void tiles; pair with void_flip sticker",
    },
    "no_vowels": {"name": "No Vowels Boss", "type": "boss_zero_vowel"},
    "axolotl": {"name": "Axolotl", "type": "custom"},
    "badger": {"name": "Badger", "type": "custom"},
    "bat": {"name": "Bat", "type": "custom"},
    "bison": {"name": "Bison", "type": "custom"},
    "capybara": {"name": "Capybara", "type": "custom"},
    "cobra": {"name": "Cobra", "type": "custom"},
    "fox": {"name": "Fox", "type": "custom"},
    "hyena": {"name": "Hyena", "type": "custom"},
    "robo_eel": {"name": "Robo-Eel", "type": "custom"},
    "robo_monkey": {"name": "Robo-Monkey", "type": "custom"},
    "salamander": {"name": "Salamander", "type": "custom"},
    "toothed_whale": {"name": "Toothed Whale", "type": "custom"},
    "wolf": {"name": "Wolf", "type": "custom"},
    "yeti_crab": {"name": "Yeti Crab", "type": "custom"},
}

def _default_pin_branches(name: str) -> dict:
    return {
        "name": name,
        "branches": {
            "left": {"type": "add_word_score", "value": 2},
            "right": {"type": "add_word_score", "value": 3},
        },
    }


# Characters whose pin uses non-default art ids; do not assign placeholder +2/+3 branches.
PINS_UNMODELED: dict[str, dict] = {
    "hayley_bayles": {
        "name": "Hayley Bayles",
        "type": "unmodeled",
        "description": "Pin (abacus art); effect not verified in-game",
    },
}

TUNED_PINS: dict[str, dict] = {
    "beans": {
        "name": "Beans",
        "branches": {
            "left": {"type": "add_word_score", "value": 2},
            "right": {"type": "multiply", "factor": 1.1},
        },
    },
    "bones_the_dog": {
        "name": "Bones The Dog",
        "branches": {
            "left": {"type": "add_word_score", "value": 2},
            "right": {"type": "add_word_score", "value": 4},
        },
    },
}

ALIASES: dict[str, dict[str, str]] = {
    "stickers": {
        "stickyplaster": "sticky_plaster",
        "sticky_plaster_sticker": "sticky_plaster",
        "voidflip": "void_flip",
        "redrider": "red_rider",
        "doublescore": "double_score",
        "longword": "long_word",
        "shinychain": "shiny_chain",
    },
    "stamps": {
        "beam_me_up": "beam_me_up",
    },
    "bosses": {
        "robo_eel_boss": "robo_eel",
        "robo_monkey_boss": "robo_monkey",
        "yeti": "yeti_crab",
    },
    "pins": {
        "bones": "bones_the_dog",
        "human_boy": "human_boy",
        "hayley": "hayley_bayles",
        "abacus": "hayley_bayles",
    },
}


def slugify_name(name: str) -> str:
    raw = (name or "").strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "_", raw).strip("_")
    return slug or "unknown"


def load_titles(filename: str) -> list[str]:
    path = WIKI_DIR / filename
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [
        m["title"]
        for m in data["query"]["categorymembers"]
        if not m["title"].startswith("Category:")
    ]


def catalog_entry(name: str, kind: str) -> dict:
    slug = slugify_name(name)
    return {
        "name": name,
        "type": "unmodeled",
        "description": f"Wiki catalog entry ({kind}); scoring not yet modeled",
    }


def build_bucket(
    titles: list[str],
    tuned: dict[str, dict],
    kind: str,
) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for title in sorted(titles, key=str.lower):
        slug = slugify_name(title)
        if slug in tuned:
            out[slug] = dict(tuned[slug])
            if "name" not in out[slug]:
                out[slug]["name"] = title
        else:
            out[slug] = catalog_entry(title, kind)
    for slug, rule in tuned.items():
        if slug not in out:
            out[slug] = dict(rule)
    return out


def build_pins(char_titles: list[str]) -> dict[str, dict]:
    pins = dict(TUNED_PINS)
    pins.update(PINS_UNMODELED)
    for title in char_titles:
        slug = slugify_name(title)
        if slug not in pins:
            pins[slug] = _default_pin_branches(title)
    return pins


def main() -> int:
    sticker_titles = load_titles("_stickers_raw.json")
    stamp_titles = load_titles("_stamps_raw.json")
    char_titles = load_titles("_chars_raw.json")

    payload = {
        "_meta": {
            "source": "cursedwords.wiki.gg categories + hand-tuned overrides",
            "regenerate": "python scripts/build_stickers_json.py",
        },
        "aliases": ALIASES,
        "stickers": build_bucket(sticker_titles, TUNED_STICKERS, "sticker"),
        "stamps": build_bucket(stamp_titles, TUNED_STAMPS, "stamp"),
        "bosses": dict(TUNED_BOSSES),
        "pins": build_pins(char_titles),
    }

    OUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(
        f"Wrote {OUT_PATH.name}: "
        f"{len(payload['stickers'])} stickers, "
        f"{len(payload['stamps'])} stamps, "
        f"{len(payload['bosses'])} bosses, "
        f"{len(payload['pins'])} pins"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
