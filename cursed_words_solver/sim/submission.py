"""Submission input for one encounter step."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ConsumablePlacement:
    rack_index: int
    board_index: int
    letter: str = ""
    tile_id: str = ""


@dataclass
class Submission:
    """Enough to replay one round (EncounterController.SubmitWord)."""

    word: str
    path: list[int]
    scoring_word: str | None = None
    consumable_placements: list[ConsumablePlacement] = field(default_factory=list)
    submit_method: str = "EncounterController.SubmitWord"

    @property
    def effective_scoring_word(self) -> str:
        return self.scoring_word or self.word

    def to_dict(self) -> dict[str, Any]:
        return {
            "word": self.word,
            "path": list(self.path),
            "scoring_word": self.scoring_word,
            "submit_method": self.submit_method,
            "consumable_placements": [
                {
                    "rack_index": p.rack_index,
                    "board_index": p.board_index,
                    "letter": p.letter,
                    "tile_id": p.tile_id,
                }
                for p in self.consumable_placements
            ],
        }

    @classmethod
    def from_round_log(cls, data: dict[str, Any]) -> Submission | None:
        actual = data.get("actual")
        if not isinstance(actual, dict):
            return None
        word = str(actual.get("word", "") or "").strip()
        path = actual.get("path")
        if not word or not isinstance(path, list):
            return None
        path_ints = [int(p) for p in path]
        solver = data.get("solver")
        scoring_word = None
        if isinstance(solver, dict):
            sw = str(solver.get("scoring_word", "") or "").strip()
            if sw:
                scoring_word = sw
        placements: list[ConsumablePlacement] = []
        consumables = data.get("consumables")
        if isinstance(consumables, dict):
            raw_placements = consumables.get("placements_this_round")
            if isinstance(raw_placements, list):
                for row in raw_placements:
                    if not isinstance(row, dict):
                        continue
                    try:
                        placements.append(
                            ConsumablePlacement(
                                rack_index=int(row.get("rack_index", 0)),
                                board_index=int(row.get("board_index", 0)),
                                letter=str(row.get("letter", "") or ""),
                                tile_id=str(row.get("tile_id", "") or ""),
                            )
                        )
                    except (TypeError, ValueError):
                        continue
        return cls(
            word=word,
            path=path_ints,
            scoring_word=scoring_word,
            consumable_placements=placements,
            submit_method=str(data.get("submit_method", "") or cls.submit_method),
        )
