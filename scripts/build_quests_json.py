#!/usr/bin/env python3
"""Build data/wiki/quests.json from quest_taxonomy.json + unlock mapping."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TAX = ROOT / "data" / "game" / "quest_taxonomy.json"
OUT = ROOT / "data" / "wiki" / "quests.json"

# ChallengeRuns.ItemUnlocks (game class -> unlock item type name).
_UNLOCK: dict[str, str | None] = {
    "SupplyAndDemand": "mirror_ball",
    "DecisionParalysis": "head_trauma",
    "Sudoku": "busy_schedule",
    "UpAndUp": "number_go_up",
    "SecretSanta": "mystery_gift",
    "MunchTime": "hungry_hippo",
    "Antiphilatelist": "bar_of_soap",
    "Masochist": "honeypot",
    "CallOfTheVoid": "ruler",
    "Chromaphilia": "christmas_tree",
    "Chromaphobia": "sushi",
    "TwoWrongs": "ambulance",
    "Bullseye": "dartboard",
    "SicilianDefense": "eight_ball",
    "TheBonesRound": "wind_chime",
    "Cursophobia": "juice_box",
    "Lexographer": "michaels_book",
    "InTheBeginning": "chick",
    "RedLetterDay": "spicy_pepper",
    "RedPepperDay": "rosebud",
    "EmptyGrid": "luffing_jib_crane",
    "DoNotPassGo": "future_funds",
    "Embargo": "eraser",
    "PlayingFavourites": "base_camp",
    "ColourSwap": "can_of_beans",
    "SpeedrunChallenge": None,
}

_STEAM: dict[str, str] = {
    "SupplyAndDemand": "ACH_SUPPLY_AND_DEMAND",
    "DecisionParalysis": "ACH_DECISION_PARALYSIS",
    "Sudoku": "ACH_ADVENT_CALENDAR",
    "UpAndUp": "ACH_UP_AND_UP",
    "SecretSanta": "ACH_SECRET_SANTA",
    "MunchTime": "ACH_MUNCH_TIME",
    "Antiphilatelist": "ACH_ANTIPHILATELIST",
    "Masochist": "ACH_MASOCHIST",
    "CallOfTheVoid": "ACH_CALL_OF_THE_VOID",
    "Chromaphilia": "ACH_CHROMAPHILIA",
    "Chromaphobia": "ACH_CHROMAPHOBIA",
    "TwoWrongs": "ACH_TWO_WRONGS",
    "Bullseye": "ACH_BULLSEYE",
    "SicilianDefense": "ACH_KNIGHT_TIME",
    "TheBonesRound": "ACH_THE_BONES_ROUND",
    "Cursophobia": "ACH_CURSOPHOBIA",
    "Lexographer": "ACH_LEXOGRAPHER",
    "InTheBeginning": "ACH_IN_THE_BEGINNING",
    "RedLetterDay": "ACH_RED_LETTER_DAY",
    "RedPepperDay": "ACH_RED_PEPPER_DAY",
    "EmptyGrid": "ACH_EMPTY_GRID",
    "DoNotPassGo": "ACH_DO_NOT_PASS_GO",
    "Embargo": "ACH_EMBARGO",
    "PlayingFavourites": "ACH_PLAYING_FAVOURITES",
    "ColourSwap": "ACH_CHROMATIC_ABERRATION",
    "SpeedrunChallenge": "ACH_WERE_FINALLY_LANDING",
}

# Wiki slug overrides where game_class slug differs from wiki convention.
_SLUG_OVERRIDE: dict[str, str] = {
    "supply_and_demand": "on_cooldown",
    "decision_paralysis": "shelf_life",
    "sudoku": "advent_calendar",
    "sicilian_defense": "knight_time",
    "the_bones_round": "the_bones_round",
    "colour_swap": "chromatic_aberration",
    "speedrun_challenge": "were_finally_landing",
    "red_letter_day": "red_letter_day",
    "red_pepper_day": "red_pepper_day",
    "call_of_the_void": "call_of_the_void",
    "empty_grid": "empty_grid",
}


def _wiki_slug(game_class: str, wiki_name: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", game_class.strip().lower()).strip("_")
    if key in _SLUG_OVERRIDE:
        return _SLUG_OVERRIDE[key]
    if wiki_name and wiki_name.strip() not in ("", " "):
        return re.sub(r"[^a-z0-9]+", "_", wiki_name.strip().lower()).strip("_")
    return key


def main() -> int:
    tax = json.loads(TAX.read_text(encoding="utf-8"))
    quests_out: dict[str, dict] = {}
    for _slug, row in sorted(tax.get("quests", {}).items()):
        game_class = str(row.get("game_class") or "").strip()
        wiki_name = str(row.get("wiki_name") or "").strip()
        wiki_slug = _wiki_slug(game_class, wiki_name)
        entry = {
            "wiki_name": wiki_name or game_class,
            "game_class": game_class,
            "effect_class": row.get("effect_class", "board_gen"),
            "elite_quest": bool(row.get("elite_quest")),
        }
        unlock = _UNLOCK.get(game_class)
        if unlock:
            entry["unlock_item"] = unlock
        steam = _STEAM.get(game_class)
        if steam:
            entry["steam_achievement"] = steam
        if game_class == "TheBonesRound":
            entry["poker_scores"] = {
                "straight_flush": 800,
                "four_of_a_kind": 420,
                "full_house": 160,
                "flush": 140,
                "straight": 120,
                "three_of_a_kind": 90,
                "two_pair": 40,
                "pair": 20,
                "high_card": 5,
            }
        quests_out[wiki_slug] = entry
    payload = {
        "_meta": {"source": "quest_taxonomy.json + ChallengeRuns decompile"},
        "quests": quests_out,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)} ({len(quests_out)} quests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
