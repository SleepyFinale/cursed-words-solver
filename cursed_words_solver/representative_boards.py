"""Select fixture boards for shop-time score simulation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.models import Board, Loadout

_FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
_BOARD_DIRS = (
    _FIXTURE_ROOT / "boards",
    _FIXTURE_ROOT / "mismatches",
)


@dataclass(frozen=True)
class BoardFixture:
    path: Path
    board: Board
    loadout: Loadout
    character: str
    area: int
    score: int


def _character_slug(loadout: Loadout) -> str:
    extras = loadout.extras or {}
    slug = str(extras.get("character_slug") or "").strip().lower()
    if slug:
        return slug
    return (loadout.character or "").strip().lower().replace(" ", "_")


def _area_number(loadout: Loadout) -> int:
    extras = loadout.extras or {}
    for key in ("boss_area_number", "area_number"):
        try:
            return max(1, int(extras.get(key, 1)))
        except (TypeError, ValueError):
            continue
    return 1


def _load_fixture(path: Path) -> BoardFixture | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    run_state = data.get("run_state") if isinstance(data.get("run_state"), dict) else data
    if not isinstance(run_state, dict):
        return None

    board = parse_board_from_run_state(run_state)
    if board is None:
        return None

    loadout = parse_run_state(run_state)
    char = _character_slug(loadout)
    area = _area_number(loadout)
    sim_score = 0
    if char and area:
        sim_score = (10 if char in _character_slug(loadout) else 0) + max(0, 5 - abs(area - _area_number(loadout)))

    return BoardFixture(
        path=path,
        board=board,
        loadout=loadout,
        character=char,
        area=area,
        score=sim_score,
    )


def _iter_fixture_paths() -> list[Path]:
    paths: list[Path] = []
    for root in _BOARD_DIRS:
        if not root.is_dir():
            continue
        paths.extend(sorted(root.glob("*.json")))
    return paths


def select_representative_boards(
    loadout: Loadout,
    *,
    max_boards: int = 3,
) -> list[Board]:
    """Return up to max_boards boards weighted by character and area similarity."""
    target_char = _character_slug(loadout)
    target_area = _area_number(loadout)

    ranked: list[tuple[int, Board]] = []
    for path in _iter_fixture_paths():
        fixture = _load_fixture(path)
        if fixture is None:
            continue
        score = 0
        if target_char and fixture.character:
            if fixture.character == target_char:
                score += 20
            elif target_char.split("_")[0] in fixture.character:
                score += 8
        score += max(0, 6 - abs(fixture.area - target_area))
        ranked.append((score, fixture.board))

    if not ranked:
        return []

    ranked.sort(key=lambda pair: pair[0], reverse=True)
    seen: set[int] = set()
    boards: list[Board] = []
    for _, board in ranked:
        fp = id(board)
        if fp in seen:
            continue
        seen.add(fp)
        boards.append(board)
        if len(boards) >= max_boards:
            break
    return boards
