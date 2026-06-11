"""RunState — board + loadout + encounter counters for simulation."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any

from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.models import Board, Loadout
from cursed_words_solver.setup_value import grids_remaining_from_loadout
from cursed_words_solver.sim.board import board_snapshot_dict, clone_board


def _extras_int(extras: dict[str, Any], *keys: str, default: int = 0) -> int:
    for key in keys:
        if key not in extras:
            continue
        try:
            return int(extras[key])
        except (TypeError, ValueError):
            continue
    return default


def _normalize_extras_for_canonical(extras: dict[str, Any]) -> dict[str, str]:
    """Melmod stores extras as string values; normalize for replay comparison."""
    out: dict[str, str] = {}
    for key in sorted(extras.keys()):
        val = extras[key]
        if val is None:
            continue
        if isinstance(val, (dict, list)):
            out[str(key)] = json.dumps(val, sort_keys=True, separators=(",", ":"))
        else:
            out[str(key)] = str(val)
    return out


@dataclass
class RunState:
    board: Board
    loadout: Loadout
    run_seed: str | int = ""
    step_index: int = 0
    encounter_won: bool = False
    encounter_lost: bool = False
    encounter_score_earned: int = 0
    _rules: dict | None = field(default=None, repr=False, compare=False)

    @property
    def extras(self) -> dict[str, Any]:
        if self.loadout.extras is None:
            self.loadout.extras = {}
        return self.loadout.extras

    @property
    def grids_remaining(self) -> int:
        return grids_remaining_from_loadout(self.loadout)

    @property
    def encounter_remaining_target(self) -> int:
        return _extras_int(self.extras, "encounter_remaining_target", "remaining_target")

    @property
    def grid_number(self) -> int:
        return max(1, _extras_int(self.extras, "grid_number", default=1))

    @property
    def total_grids_per_round(self) -> int:
        g = self.grids_remaining
        n = self.grid_number
        return max(n, g + n - 1)

    def clone(self) -> RunState:
        loadout_copy = Loadout(
            character=self.loadout.character,
            pin_branch=self.loadout.pin_branch,
            stickers=list(self.loadout.stickers),
            stamps=list(self.loadout.stamps),
            boss_id=self.loadout.boss_id,
            boss_name=self.loadout.boss_name,
            boss_effect=self.loadout.boss_effect,
            money=self.loadout.money,
            extras=copy.deepcopy(self.loadout.extras),
        )
        return RunState(
            board=clone_board(self.board),
            loadout=loadout_copy,
            run_seed=self.run_seed,
            step_index=self.step_index,
            encounter_won=self.encounter_won,
            encounter_lost=self.encounter_lost,
            encounter_score_earned=self.encounter_score_earned,
            _rules=self._rules,
        )

    def to_canonical_dict(self) -> dict[str, Any]:
        return {
            "board": board_snapshot_dict(self.board),
            "money": self.loadout.money,
            "extras": _normalize_extras_for_canonical(self.extras),
            "run_seed": str(self.run_seed),
            "step_index": self.step_index,
            "encounter_won": self.encounter_won,
            "encounter_lost": self.encounter_lost,
            "encounter_score_earned": self.encounter_score_earned,
        }

    @classmethod
    def from_run_state_dict(
        cls,
        data: dict[str, Any],
        *,
        rules: dict | None = None,
    ) -> RunState | None:
        board = parse_board_from_run_state(data)
        if board is None:
            return None
        loadout = parse_run_state(data)
        extras = loadout.extras or {}
        run_seed = extras.get("run_seed", extras.get("RunSeed", ""))
        return cls(
            board=board,
            loadout=loadout,
            run_seed=run_seed if run_seed is not None else "",
            _rules=rules,
        )

    def set_encounter_remaining_target(self, value: int) -> None:
        self.extras["encounter_remaining_target"] = str(int(value))

    def set_grids_remaining(self, value: int) -> None:
        self.extras["grids_remaining"] = str(max(0, int(value)))

    def set_grid_number(self, value: int) -> None:
        self.extras["grid_number"] = str(max(1, int(value)))
