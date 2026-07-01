"""Pre-item tile scoring: glitch settle, currency, pink, poison (game ScoreCalculation order)."""

from __future__ import annotations

import hashlib
import random
from copy import deepcopy
from typing import Any

from cursed_words_solver.models import (
    Board,
    CURRENCY_MAP,
    CurseType,
    Loadout,
    Tile,
    TileColor,
    normalize_tile_glyph,
)
from cursed_words_solver.rules.base_scoring import (
    microscope_init_contribution,
    tile_base_contribution,
)

# SettleGlitchTiles colour pool (excludes Glitch)
_GLITCH_COLOR_POOL: list[TileColor] = [
    TileColor.COLORLESS,
    TileColor.BLUE,
    TileColor.CACTUS,
    TileColor.GOLD,
    TileColor.GREEN,
    TileColor.PURPLE,
    TileColor.PINK,
    TileColor.WHITE,
    TileColor.RED,
    TileColor.VOID,
    TileColor.SHINY,
]

_CHESS_CURSES = (
    CurseType.CHESS_PAWN,
    CurseType.CHESS_BISHOP,
    CurseType.CHESS_ROOK,
    CurseType.CHESS_KNIGHT,
    CurseType.CHESS_QUEEN,
    CurseType.CHESS_KING,
)


def _glitch_rng(path: list[int], loadout: Loadout | None) -> random.Random:
    seed_material = ",".join(str(i) for i in path)
    if loadout:
        seed_material += "|" + str(loadout.extras.get("run_seed", ""))
        seed_material += "|" + str(loadout.money)
    digest = hashlib.sha256(seed_material.encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


def _apply_glitch_transform(tile: Tile, rng: random.Random) -> None:
    tile.color = rng.choice(_GLITCH_COLOR_POOL)
    tile.metadata["was_glitch"] = True
    if rng.random() < 0.25:
        tile.metadata["card_suit"] = rng.choice(
            ("clubs", "spades", "hearts", "diamonds")
        )
        tile.curse = CurseType.CARD
    roll = rng.randint(0, 7)
    if roll == 0:
        tile.curse = CurseType.LETTER
        tile.letter = rng.choice("AEIOURSTLNHDCMPFGWYBVKJXQZ")
        tile.char = tile.letter
    elif roll == 1:
        tile.curse = CurseType.CURRENCY
        sym = rng.choice(list(CURRENCY_MAP.keys()))
        tile.char = sym
        tile.letter = CURRENCY_MAP[sym]
    elif roll == 2:
        tile.curse = CurseType.FRACTION
        a, b = rng.randint(1, 9), rng.randint(2, 9)
        tile.fraction_value = a / b
        tile.metadata["fraction_parts"] = [a, b]
        tile.char = f"{a}/{b}"
        tile.letter = tile.char
    elif roll == 3:
        tile.curse = CurseType.NUMBER
        tile.number_value = rng.randint(1, 9)
        tile.letter = str(tile.number_value)
        tile.char = tile.letter
    elif roll == 4:
        tile.curse = CurseType.BLANK
        tile.letter = "?"
        tile.char = "?"
    elif roll == 5:
        tile.curse = CurseType.ITEM
        tile.letter = "?"
        tile.char = "?"
    elif roll == 6:
        tile.curse = rng.choice(_CHESS_CURSES)
        tile.letter = "?"
        tile.char = "?"
        tile.metadata["chess_color"] = rng.choice(("white", "black"))
    else:
        tile.curse = CurseType.CARD
        tile.metadata["card_suit"] = "joker"
        tile.metadata["is_joker"] = True
        tile.letter = "?"
        tile.char = "?"


def settle_glitch_tiles(
    board: Board,
    path: list[int],
    loadout: Loadout | None = None,
) -> list[int]:
    """Return path indices whose glitch tiles were settled (scoring copy only)."""
    settled: list[int] = []
    for idx in path:
        tile = board.get_by_index(idx)
        if tile.color != TileColor.GLITCH:
            continue
        if tile.metadata.get("glitch_settled"):
            continue
        _apply_glitch_transform(tile, _glitch_rng(path, loadout))
        tile.metadata["glitch_settled"] = True
        settled.append(idx)
    return settled


def path_needs_scoring_board_copy(board: Board, path: list[int]) -> bool:
    """True when tile-init must mutate glitch tiles (requires a board copy)."""
    for idx in path:
        tile = board.get_by_index(idx)
        if tile.color == TileColor.GLITCH and not tile.metadata.get("glitch_settled"):
            return True
    return False


def scoring_board_copy(board: Board) -> Board:
    """Shallow board copy for tile-init mutations (glitch settle)."""
    tiles = [[deepcopy(board.tiles[r][c]) for c in range(5)] for r in range(5)]
    return Board(
        tiles=tiles,
        money=board.money,
        rows=board.rows,
        cols=board.cols,
        active=list(board.active),
        playable_origin=board.playable_origin,
        playable_min_row=board.playable_min_row,
        playable_max_row=board.playable_max_row,
        playable_min_col=board.playable_min_col,
        playable_max_col=board.playable_max_col,
    )


def initial_tile_scores(
    board: Board,
    path: list[int],
    *,
    money: int,
    loadout: Loadout | None = None,
    microscope_base: bool = False,
    blue_base_override: int | None = None,
    word: str = "",
) -> tuple[list[float], float]:
    """Per-path tile scores after GetValue parity."""
    from cursed_words_solver.models import CurseType as CT

    from cursed_words_solver.rules.base_scoring import melmod_void_currency_init_contribution

    first_void_currency_path_index: int | None = None
    for i, idx in enumerate(path):
        tile = board.get_by_index(idx)
        if (
            tile.color == TileColor.VOID
            and tile.curse == CT.CURRENCY
            and tile.metadata.get("source") == "melmod"
        ):
            first_void_currency_path_index = i
            break

    from cursed_words_solver.rules.scoring_conditions import path_letter_for_count

    word_lower = (word or "").lower()
    scores: list[float] = []
    total = 0.0
    for i, idx in enumerate(path):
        tile = board.get_by_index(idx)
        if tile.curse == CT.ITEM:
            scores.append(0.0)
            continue
        void_currency_in_word = False
        if (
            tile.color == TileColor.VOID
            and tile.curse == CT.CURRENCY
            and i < len(word_lower)
        ):
            glyph = normalize_tile_glyph(tile.char or tile.letter or "")
            mapped = CURRENCY_MAP.get(glyph, "").lower()
            if not mapped and len(glyph) == 1 and glyph.isalpha():
                mapped = glyph.lower()
            face = path_letter_for_count(tile)
            if mapped and mapped == word_lower[i]:
                void_currency_in_word = True
            elif face and face.lower() == word_lower[i]:
                void_currency_in_word = True
        # Row-0 path-start void currency still gets melmod_void_currency_init (gyrene).
        if void_currency_in_word and not (
            i == 0
            and tile.row == 0
            and tile.metadata.get("source") == "melmod"
        ):
            from cursed_words_solver.rules.base_scoring import (
                _void_currency_path_init_penalty,
            )

            contrib = -float(_void_currency_path_init_penalty(tile, loadout))
        elif microscope_base:
            contrib = microscope_init_contribution(tile, money, loadout)
        elif tile.color == TileColor.BLUE and blue_base_override is not None:
            contrib = float(blue_base_override)
        elif (
            tile.curse == CT.CURRENCY
            and tile.metadata.get("source") == "melmod"
            and tile.color == TileColor.VOID
        ):
            contrib = melmod_void_currency_init_contribution(
                tile,
                first_void_currency_on_path=(
                    i == first_void_currency_path_index
                ),
                path_index=i,
                loadout=loadout,
            )
        elif (
            tile.curse == CT.CURRENCY
            and tile.metadata.get("source") == "melmod"
            and tile.color != TileColor.VOID
        ):
            contrib = float(tile.base_score)
        elif (
            tile.metadata.get("source") == "melmod"
            and tile.curse == CT.LETTER
            and tile.color in (TileColor.COLORLESS, TileColor.VOID)
        ):
            contrib = float(tile.base_score)
        else:
            contrib = float(tile_base_contribution(tile, money, loadout))
        scores.append(contrib)
        total += contrib
    return scores, total


def currency_money_from_path(
    board: Board,
    path: list[int],
    loadout: Loadout | None = None,
) -> int:
    """GetMoneyFromCurrencyTiles: +1 per currency tile (Kokeshi uses letter value)."""
    bonus = 0
    kokeshi = False
    if loadout:
        kokeshi = bool(loadout.extras.get("kokeshi_dolls"))
    for idx in path:
        tile = board.get_by_index(idx)
        if tile.curse != CurseType.CURRENCY:
            continue
        if kokeshi:
            sym = normalize_tile_glyph(tile.char)
            letter = CURRENCY_MAP.get(sym, tile.letter or "A")
            from cursed_words_solver.letter_values import SCRABBLE_VALUES

            bonus += SCRABBLE_VALUES.get(letter.upper(), 1)
        else:
            bonus += 1
    return bonus


def pink_store_money(
    board: Board,
    path: list[int],
    loadout: Loadout | None,
) -> int:
    """StoreMoneyInPinkTiles: spend $1 per pink tile while money remains."""
    pink_count = sum(
        1 for idx in path if board.get_by_index(idx).color == TileColor.PINK
    )
    if pink_count <= 0:
        return 0
    available = max(board.money, (loadout.money if loadout else 0), 0)
    stored = min(pink_count, available)
    if loadout is not None:
        loadout.extras["pink_saved_this_word"] = str(stored)
    return stored


def poison_from_previous_words(loadout: Loadout | None) -> float:
    """ApplyPoisonEffect: sum over historic words of green_count × 10% word score."""
    if not loadout:
        return 0.0
    extras = loadout.extras if isinstance(loadout.extras, dict) else {}
    from cursed_words_solver.loadout import (
        _encounter_historic_trusted_for_poison,
        _grid_number_from_extras,
        _scoring_previous_words_count_from_extras,
        green_poison_from_historic_words,
    )

    if (
        _grid_number_from_extras(extras) == 1
        and _scoring_previous_words_count_from_extras(extras) == 0
        and not _encounter_historic_trusted_for_poison(extras)
    ):
        return 0.0

    derived = green_poison_from_historic_words(extras)
    if derived > 0:
        return derived
    raw = extras.get("green_poison_bonus")
    if raw is not None:
        try:
            return float(raw)
        except (TypeError, ValueError):
            pass
    return 0.0


def apply_tile_init(
    board: Board,
    path: list[int],
    word: str,
    loadout: Loadout,
    state: dict[str, Any],
    *,
    microscope_base: bool = False,
    blue_base_override: int | None = None,
    trace_step: Any = None,
) -> Board:
    """
    Run pre-item tile pipeline on a scoring board copy.
    Mutates state tile_scores / money_bonus / word_score.
    """
    if path_needs_scoring_board_copy(board, path):
        work = scoring_board_copy(board)
        settled = settle_glitch_tiles(work, path, loadout)
    else:
        work = board
        settled = []
    if settled and trace_step:
        trace_step(
            state,
            "tile_init",
            phase_detail="glitch_settle",
            detail=f"settled {len(settled)} glitch tiles",
        )

    scores, base_total = initial_tile_scores(
        work,
        path,
        money=max(board.money, loadout.money),
        loadout=loadout,
        microscope_base=microscope_base,
        blue_base_override=blue_base_override,
        word=word,
    )
    state["tile_scores"] = scores
    state["base_score"] = base_total

    currency = currency_money_from_path(work, path, loadout)
    if currency:
        state["money_bonus"] = int(state.get("money_bonus", 0)) + currency
        state["effects"].append(f"+${currency} currency tiles")
        if trace_step:
            trace_step(
                state,
                "tile_init",
                phase_detail="currency",
                detail=f"+${currency}",
            )

    pink_saved = pink_store_money(board, path, loadout)
    if pink_saved:
        state["effects"].append(f"−${pink_saved} pink piggy bank")
        if trace_step:
            trace_step(
                state,
                "tile_init",
                phase_detail="pink",
                detail=f"saved ${pink_saved}",
            )

    if trace_step:
        trace_step(
            state,
            "tile_init",
            phase_detail="init_scores",
            detail=f"base tile sum {base_total}",
        )
    return work
