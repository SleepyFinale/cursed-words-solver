"""Parse 5x5 board from captured region."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from cursed_words_solver.capture import save_debug_image
from cursed_words_solver.models import (
    CURRENCY_MAP,
    Board,
    CurseType,
    Tile,
    normalize_tile_glyph,
)
from cursed_words_solver.rules.fraction_tiles import (
    attach_fraction_metadata,
    parse_fraction_parts_from_text,
)
from cursed_words_solver.letter_values import SCRABBLE_VALUES
from cursed_words_solver.vision.color_detect import classify_tile_color

LETTER_ALLOWLIST = "ABCDEFGHIJKLMNOPQRSTUVWXYZ?"
DIGIT_ALLOWLIST = "0123456789"
MIXED_ALLOWLIST = LETTER_ALLOWLIST + DIGIT_ALLOWLIST

SUIT_SYMBOL_TO_NAME: dict[str, str] = {
    "♣": "clubs",
    "♠": "spades",
    "♥": "hearts",
    "♦": "diamonds",
}

SUIT_WORD_TO_NAME: dict[str, str] = {
    "club": "clubs",
    "clubs": "clubs",
    "spade": "spades",
    "spades": "spades",
    "heart": "hearts",
    "hearts": "hearts",
    "diamond": "diamonds",
    "diamonds": "diamonds",
}

CHESS_GLYPHS = {
    "pawn": CurseType.CHESS_PAWN,
    "bishop": CurseType.CHESS_BISHOP,
    "rook": CurseType.CHESS_ROOK,
    "knight": CurseType.CHESS_KNIGHT,
    "queen": CurseType.CHESS_QUEEN,
    "king": CurseType.CHESS_KING,
}

CHESS_MIN_CONF = 0.35
MIN_PRIMARY_AREA_FRAC = 0.06
SUBSCRIPT_Y_FRAC = 0.68


@dataclass
class OcrDetection:
    text: str
    confidence: float
    aspect: float | None
    area: float
    cy_frac: float


@dataclass
class CellOcrDebug:
    row: int
    col: int
    letter_texts: list[str] = field(default_factory=list)
    score_texts: list[str] = field(default_factory=list)
    fallback_texts: list[str] = field(default_factory=list)
    score_override: int | None = None
    chosen_variant: str = ""


@lru_cache(maxsize=1)
def _get_ocr_reader(gpu: bool = False):
    import easyocr

    device = "GPU" if gpu else "CPU"
    print(f"Loading EasyOCR models ({device})...", flush=True)
    reader = easyocr.Reader(["en"], gpu=gpu, verbose=False)
    print("EasyOCR ready.", flush=True)
    return reader


def _crop_roi(
    cell_bgr: np.ndarray,
    x_frac: float,
    y_frac: float,
    w_frac: float,
    h_frac: float,
) -> np.ndarray:
    h, w = cell_bgr.shape[:2]
    x0 = int(w * x_frac)
    y0 = int(h * y_frac)
    x1 = min(w, int(w * (x_frac + w_frac)))
    y1 = min(h, int(h * (y_frac + h_frac)))
    if x1 <= x0 or y1 <= y0:
        return cell_bgr.copy()
    return cell_bgr[y0:y1, x0:x1].copy()


def letter_roi(cell_bgr: np.ndarray) -> np.ndarray:
    """Upper-center region — main glyph only, excludes subscript corner."""
    return _crop_roi(cell_bgr, 0.14, 0.06, 0.72, 0.52)


def letter_roi_wide(cell_bgr: np.ndarray) -> np.ndarray:
    """Slightly larger center crop for difficult glyphs."""
    return _crop_roi(cell_bgr, 0.10, 0.04, 0.80, 0.58)


def score_roi(cell_bgr: np.ndarray) -> np.ndarray:
    """Bottom-right subscript point value."""
    return _crop_roi(cell_bgr, 0.52, 0.58, 0.46, 0.38)


def _preprocess_letter(cell_bgr: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(cell_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, (160, 160), interpolation=cv2.INTER_CUBIC)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    gray = cv2.equalizeHist(gray)
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return cv2.cvtColor(thresh, cv2.COLOR_GRAY2BGR)


def _preprocess_letter_inverted(cell_bgr: np.ndarray) -> np.ndarray:
    proc = _preprocess_letter(cell_bgr)
    return cv2.bitwise_not(proc)


def _preprocess_letter_raw(cell_bgr: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(cell_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, (160, 160), interpolation=cv2.INTER_CUBIC)
    gray = cv2.equalizeHist(gray)
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


def _preprocess_score(cell_bgr: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(cell_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, (96, 96), interpolation=cv2.INTER_CUBIC)
    gray = cv2.equalizeHist(gray)
    thresh = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
    )
    return cv2.cvtColor(thresh, cv2.COLOR_GRAY2BGR)


def _preprocess_cell(cell_bgr: np.ndarray) -> np.ndarray:
    return _preprocess_letter(cell_bgr)


def _first_alnum(text: str) -> str | None:
    cleaned = re.sub(r"[^A-Za-z0-9?]", "", text.upper())
    if not cleaned:
        return None
    return cleaned[0]


def _disambiguate_letter(ch: str, aspect: float | None, score_override: int | None) -> str:
    if score_override == 1 and ch in ("0", "O"):
        return "O"
    if score_override is not None and ch.isdigit() and int(ch) == score_override:
        return ""

    if aspect is None:
        return ch

    tall = aspect < 0.55
    wide = aspect > 1.35

    if ch in ("0", "O"):
        return "O" if not tall or aspect > 0.75 else "1"
    if ch == "1" and wide:
        return "I"
    return ch


def _parse_score_override(texts: list[str]) -> int | None:
    combined = " ".join(texts)
    nums = re.findall(r"\d{1,2}", combined)
    if not nums:
        return None
    val = int(nums[-1])
    return max(0, min(10, val))


def _detect_card_overlay(text: str) -> tuple[str | None, str | None, bool]:
    """Return (suit, rank_hint, is_joker) from OCR text."""
    combined = text or ""
    lower = combined.lower()
    is_joker = bool(re.search(r"\bjoker\b", lower)) or "🃏" in combined
    if is_joker:
        return None, None, True

    suit: str | None = None
    for sym, name in SUIT_SYMBOL_TO_NAME.items():
        if sym in combined:
            suit = name
            break
    if suit is None:
        for word, name in SUIT_WORD_TO_NAME.items():
            if re.search(rf"\b{re.escape(word)}\b", lower):
                suit = name
                break

    rank: str | None = None
    cleaned = re.sub(r"[^A-Za-z0-9?]", "", combined.upper())
    for sym in SUIT_SYMBOL_TO_NAME:
        cleaned = cleaned.replace(sym, "")
    if cleaned:
        ch = cleaned[0]
        if ch.isalnum() and ch != "?":
            rank = ch

    return suit, rank, is_joker


def _detect_chess(combined_lower: str, conf: float) -> CurseType | None:
    if conf < CHESS_MIN_CONF:
        return None
    for name, ctype in CHESS_GLYPHS.items():
        if re.search(rf"\b{re.escape(name)}\b", combined_lower):
            return ctype
    return None


def _pick_primary_detection(
    detections: list[OcrDetection],
    score_override: int | None,
    roi_pixels: int,
) -> tuple[str, float, float | None] | None:
    if not detections:
        return None

    max_area = max(d.area for d in detections)
    min_area = max_area * MIN_PRIMARY_AREA_FRAC

    ranked: list[tuple[float, str, float, float | None]] = []
    for d in detections:
        if d.area < min_area:
            continue
        if d.cy_frac > SUBSCRIPT_Y_FRAC and d.area < max_area * 0.35:
            continue

        ch = _first_alnum(d.text)
        if not ch:
            continue

        resolved = _disambiguate_letter(ch, d.aspect, score_override)
        if not resolved:
            continue
        if score_override is not None and resolved.isdigit() and int(resolved) == score_override:
            if d.area < max_area * 0.5:
                continue

        area_frac = d.area / max(roi_pixels, 1)
        score = d.confidence * (0.5 + area_frac * 4.0)
        if resolved.isalpha():
            score += 0.15
        ranked.append((score, resolved, d.confidence, d.aspect))

    if not ranked:
        return None

    ranked.sort(key=lambda x: x[0], reverse=True)
    _, resolved, conf, aspect = ranked[0]
    return resolved, conf, aspect


def _parse_char_and_score(
    texts: list[str],
    confidences: list[float],
    *,
    score_override: int | None = None,
    bbox_aspects: list[float | None] | None = None,
    prefer_number: bool = False,
) -> tuple[str, str, int, CurseType, float]:
    """Extract letter, display char, base score, curse from OCR lines."""
    combined = " ".join(texts).strip()
    conf = sum(confidences) / max(len(confidences), 1) if confidences else 0.5

    score = score_override if score_override is not None else 0
    if score == 0 and score_override is None:
        score_match = re.findall(r"\b(\d{1,2})\b", combined)
        if score_match:
            score = max(0, min(10, int(score_match[-1])))

    cleaned = re.sub(r"\s+", "", combined).upper()
    letter = "?"
    display = "?"
    curse = CurseType.LETTER

    if not cleaned:
        return display, letter, score, curse, conf

    for sym, ch in CURRENCY_MAP.items():
        if sym in combined:
            return sym, ch, 0, CurseType.CURRENCY, conf

    if "?" in cleaned or cleaned == "WILD":
        return "?", "?", score, CurseType.WILDCARD, conf

    frac = re.search(r"(\d+)\s*/\s*(\d+)", combined)
    if frac:
        num, den = int(frac.group(1)), int(frac.group(2))
        base = num + den
        return frac.group(0), "?", base, CurseType.FRACTION, conf

    vulgar = parse_fraction_parts_from_text(combined)
    if vulgar is not None:
        num, den = vulgar
        glyph = normalize_tile_glyph(combined.strip())
        base = num + den
        return glyph or f"{num}/{den}", "?", base, CurseType.FRACTION, conf

    if len(cleaned) == 1:
        resolved = _disambiguate_letter(cleaned, None, score_override)
        if resolved.isalpha():
            letter = resolved
            display = resolved
            if score == 0:
                score = SCRABBLE_VALUES.get(resolved, 1)
            return display, letter, score, CurseType.LETTER, conf

    if prefer_number and re.fullmatch(r"\d", cleaned):
        v = int(cleaned)
        return cleaned, str(v), v, CurseType.NUMBER, conf

    if re.fullmatch(r"\d", cleaned):
        if score_override is not None and int(cleaned) == score_override:
            pass
        else:
            v = int(cleaned)
            return cleaned, str(v), v, CurseType.NUMBER, conf

    lower = combined.lower()
    chess = _detect_chess(lower, conf)
    if chess is not None:
        for name, ctype in CHESS_GLYPHS.items():
            if ctype == chess:
                return name[:1].upper(), "?", 0, ctype, conf

    aspects = bbox_aspects or []
    aspect_idx = 0
    for ch in cleaned:
        if ch.isalpha() or ch.isdigit():
            aspect = aspects[aspect_idx] if aspect_idx < len(aspects) else None
            aspect_idx += 1
            resolved = _disambiguate_letter(ch, aspect, score_override)
            if not resolved:
                continue
            if resolved.isalpha():
                letter = resolved
                display = resolved
                if score == 0:
                    score = SCRABBLE_VALUES.get(resolved, 1)
                return display, letter, score, CurseType.LETTER, conf
            if resolved.isdigit() and re.fullmatch(r"\d", resolved):
                v = int(resolved)
                return resolved, str(v), v, CurseType.NUMBER, conf

    return display, letter, score, curse, conf


def tile_appears_unread(tile: Tile) -> bool:
    """True when a tile looks unidentified (for overlay OCR warnings).

    Fraction, wildcard, and chess tiles use letter ``?`` for search but are not
    OCR failures when ``char`` carries the display glyph.
    """
    if tile.metadata.get("is_joker"):
        return False
    if tile.curse in {
        CurseType.FRACTION,
        CurseType.WILDCARD,
        CurseType.CHESS_PAWN,
        CurseType.CHESS_BISHOP,
        CurseType.CHESS_ROOK,
        CurseType.CHESS_KNIGHT,
        CurseType.CHESS_QUEEN,
        CurseType.CHESS_KING,
    }:
        return False
    display = normalize_tile_glyph(tile.char or "")
    if tile.letter == "?" and display and display != "?":
        if parse_fraction_parts_from_text(display) is not None:
            return False
        if tile.curse == CurseType.NUMBER:
            return False
    return tile.letter == "?" or tile.char == "?"


def _format_tile_char(tile: Tile) -> str:
    if tile.curse == CurseType.FRACTION:
        ch = normalize_tile_glyph(tile.char or "")
        if ch and ch != "?":
            return ch
        parts = parse_fraction_parts_from_text(tile.char or tile.letter or "")
        if parts is not None:
            return f"{parts[0]}/{parts[1]}"
    if tile.curse == CurseType.CURRENCY:
        sym = normalize_tile_glyph(tile.char or tile.letter or "")
        if sym in CURRENCY_MAP:
            return sym
        if tile.letter and len(tile.letter) == 1:
            return tile.letter.upper()
    ch = normalize_tile_glyph(tile.char if tile.char and tile.char != "?" else tile.letter)
    if not ch or ch == "?":
        return "?"
    if len(ch) == 1:
        return ch.upper()
    return ch[:1].upper()


def _active_cell_bounds(board: Board) -> tuple[int, int, int, int] | None:
    """Return (min_row, max_row, min_col, max_col) for active cells, or None."""
    min_r, max_r, min_c, max_c = 5, -1, 5, -1
    for r in range(5):
        for c in range(5):
            if board.is_active_cell(r, c):
                min_r = min(min_r, r)
                max_r = max(max_r, r)
                min_c = min(min_c, c)
                max_c = max(max_c, c)
    if max_r < 0:
        return None
    return min_r, max_r, min_c, max_c


def format_playable_size(board: Board) -> str:
    """Game convention: width×height (cols×rows), e.g. 4×3 for four wide, three tall."""
    bounds = _active_cell_bounds(board)
    if bounds is not None:
        min_r, max_r, min_c, max_c = bounds
        width = max_c - min_c + 1
        height = max_r - min_r + 1
    else:
        width, height = board.cols, board.rows
    return f"{width}×{height}"


def format_board_grid(board: Board, *, compact: bool = False) -> str:
    """ASCII grid of parsed tile chars.

    When *compact* is True and the board is smaller than 5×5, crop to the
    active-cell bounding box and prefix with playable dimensions.
    """
    use_compact = compact and (board.rows < 5 or board.cols < 5)
    bounds = _active_cell_bounds(board) if use_compact else None

    if bounds is not None:
        min_r, max_r, min_c, max_c = bounds
        lines = []
        for r in range(min_r, max_r + 1):
            cells = [
                _format_tile_char(board.tiles[r][c])
                for c in range(min_c, max_c + 1)
            ]
            lines.append(" ".join(cells))
        header = f"Playable {format_playable_size(board)}:"
        return header + "\n" + "\n".join(lines)

    lines = []
    for row in board.tiles:
        cells = [_format_tile_char(t) for t in row]
        lines.append(" ".join(cells))
    return "\n".join(lines)


class BoardParser:
    def __init__(
        self,
        use_gpu: bool = False,
        cell_inset_ratio: float = 0.1,
        debug_ocr: bool = False,
    ) -> None:
        self.use_gpu = use_gpu
        self.cell_inset_ratio = max(0.0, min(0.25, cell_inset_ratio))
        self.debug_ocr = debug_ocr
        self._reader = None
        self.last_cell_debug: list[CellOcrDebug] = []

    @property
    def reader(self):
        if self._reader is None:
            self._reader = _get_ocr_reader(self.use_gpu)
        return self._reader

    def split_cells(self, board_bgr: np.ndarray) -> list[np.ndarray]:
        h, w = board_bgr.shape[:2]
        inset_x = int(w * self.cell_inset_ratio / 5)
        inset_y = int(h * self.cell_inset_ratio / 5)
        cells = []
        for r in range(5):
            for c in range(5):
                y0, y1 = r * h // 5, (r + 1) * h // 5
                x0, x1 = c * w // 5, (c + 1) * w // 5
                y0 += inset_y
                y1 -= inset_y
                x0 += inset_x
                x1 -= inset_x
                cells.append(board_bgr[y0:y1, x0:x1].copy())
        return cells

    def _read_detections(
        self,
        proc_bgr: np.ndarray,
        *,
        allowlist: str | None = None,
    ) -> list[OcrDetection]:
        kwargs: dict = {"detail": 1, "paragraph": False}
        if allowlist is not None:
            kwargs["allowlist"] = allowlist
        results = self.reader.readtext(proc_bgr, **kwargs)
        h, w = proc_bgr.shape[:2]
        roi_pixels = h * w
        detections: list[OcrDetection] = []
        for item in results:
            if len(item) < 3:
                continue
            bbox, text, conf = item[0], str(item[1]), float(item[2])
            aspect = None
            area = 0.0
            cy_frac = 0.5
            if bbox and len(bbox) >= 4:
                xs = [p[0] for p in bbox]
                ys = [p[1] for p in bbox]
                bw = max(xs) - min(xs)
                bh = max(ys) - min(ys)
                area = bw * bh
                cy_frac = (min(ys) + max(ys)) / 2.0 / max(h, 1)
                if bh > 0:
                    aspect = bw / bh
            detections.append(
                OcrDetection(
                    text=text,
                    confidence=conf,
                    aspect=aspect,
                    area=area,
                    cy_frac=cy_frac,
                )
            )
        return detections, roi_pixels

    def _ocr_primary_char(
        self,
        roi_bgr: np.ndarray,
        score_override: int | None,
        *,
        allowlist: str | None = None,
        prefer_number: bool = False,
    ) -> tuple[list[str], list[float], list[float | None], str] | None:
        """Return (texts, confs, aspects, char) from best detection, or None."""
        best_char: tuple[str, float, list[str], list[float], list[float | None]] | None = None

        for preprocess in (_preprocess_letter, _preprocess_letter_inverted, _preprocess_letter_raw):
            proc = preprocess(roi_bgr)
            detections, roi_pixels = self._read_detections(proc, allowlist=allowlist)
            picked = _pick_primary_detection(detections, score_override, roi_pixels)
            if picked is None:
                continue
            resolved, conf, aspect = picked
            texts = [resolved]
            confs = [conf]
            aspects: list[float | None] = [aspect]
            rank = conf * (2.0 if resolved.isalpha() else 1.0)
            if best_char is None or rank > best_char[0]:
                best_char = (rank, resolved, texts, confs, aspects)

        if best_char is None:
            return None
        _, _resolved, texts, confs, aspects = best_char
        return texts, confs, aspects, texts[0]

    def _read_score(self, cell_bgr: np.ndarray) -> int | None:
        for roi_fn in (score_roi, lambda c: _crop_roi(c, 0.45, 0.52, 0.52, 0.45)):
            proc = _preprocess_score(roi_fn(cell_bgr))
            detections, _ = self._read_detections(proc, allowlist=DIGIT_ALLOWLIST)
            texts = [d.text for d in detections]
            val = _parse_score_override(texts)
            if val is not None:
                return val
        return None

    def _try_roi_pass(
        self,
        roi_bgr: np.ndarray,
        score_override: int | None,
        *,
        allowlist: str | None,
        preps: tuple,
        prefer_number: bool = False,
    ) -> tuple[list[str], list[float], list[float | None], float] | None:
        best_rank = -1.0
        best_pack: tuple[list[str], list[float], list[float | None], float] | None = None
        for prep in preps:
            proc = prep(roi_bgr)
            detections, roi_pixels = self._read_detections(proc, allowlist=allowlist)
            picked = _pick_primary_detection(detections, score_override, roi_pixels)
            if picked is None:
                continue
            resolved, conf, aspect = picked
            rank = conf * (2.5 if resolved.isalpha() else 1.2)
            if prefer_number and resolved.isdigit():
                rank += 0.5
            if rank > best_rank:
                best_rank = rank
                best_pack = ([resolved], [conf], [aspect], rank)
        return best_pack

    def _read_letter_candidates(
        self,
        cell_bgr: np.ndarray,
        score_override: int | None,
    ) -> list[tuple[str, list[str], list[float], list[float | None], float]]:
        """Collect candidates; stops early on high-confidence alpha reads."""
        candidates: list[tuple[str, list[str], list[float], list[float | None], float]] = []
        high_conf = 0.82

        def add(variant: str, pack: tuple | None) -> float | None:
            if pack is None:
                return None
            texts, confs, aspects, rank = pack
            candidates.append((variant, texts, confs, aspects, rank))
            return rank

        roi = letter_roi(cell_bgr)
        std_preps = (_preprocess_letter, _preprocess_letter_inverted, _preprocess_letter_raw)

        rank = add(
            "letter/alpha",
            self._try_roi_pass(
                roi, score_override, allowlist=LETTER_ALLOWLIST, preps=std_preps
            ),
        )
        if rank is not None and rank >= high_conf and candidates[-1][1][0].isalpha():
            return candidates

        add(
            "letter/alpha_inv",
            self._try_roi_pass(
                roi,
                score_override,
                allowlist=LETTER_ALLOWLIST,
                preps=(_preprocess_letter_inverted, _preprocess_letter),
            ),
        )

        rank = add(
            "letter/mixed",
            self._try_roi_pass(
                roi, score_override, allowlist=MIXED_ALLOWLIST, preps=std_preps
            ),
        )
        if rank is not None and rank >= high_conf:
            return candidates

        add(
            "letter/mixed_num",
            self._try_roi_pass(
                roi,
                score_override,
                allowlist=MIXED_ALLOWLIST,
                preps=std_preps,
                prefer_number=True,
            ),
        )

        wide = letter_roi_wide(cell_bgr)
        add(
            "wide/alpha",
            self._try_roi_pass(
                wide, score_override, allowlist=LETTER_ALLOWLIST, preps=std_preps
            ),
        )

        if not candidates or candidates[0][4] < 0.45:
            fallback_proc = _preprocess_cell(cell_bgr)
            detections, roi_pixels = self._read_detections(
                fallback_proc, allowlist=MIXED_ALLOWLIST
            )
            picked = _pick_primary_detection(detections, score_override, roi_pixels)
            if picked:
                resolved, conf, aspect = picked
                candidates.append(
                    (
                        "fallback",
                        [resolved],
                        [conf],
                        [aspect],
                        conf * (2.0 if resolved.isalpha() else 1.0),
                    )
                )

        return candidates

    def parse_cell(self, cell_bgr: np.ndarray, row: int, col: int) -> Tile:
        color = classify_tile_color(cell_bgr)
        debug = CellOcrDebug(row=row, col=col)

        score_override = self._read_score(cell_bgr)
        debug.score_override = score_override

        candidates = self._read_letter_candidates(cell_bgr, score_override)

        texts: list[str] = []
        confs: list[float] = []
        aspects: list[float | None] = []
        chosen_variant = ""

        if candidates:
            candidates.sort(key=lambda c: c[4], reverse=True)
            chosen_variant, texts, confs, aspects, _ = candidates[0]
            debug.letter_texts = texts
            debug.chosen_variant = chosen_variant

        prefer_number = chosen_variant.endswith("num") or (
            texts and texts[0].isdigit() and score_override is None
        )

        display, letter, score, curse, conf = _parse_char_and_score(
            texts,
            confs,
            score_override=score_override,
            bbox_aspects=aspects,
            prefer_number=prefer_number,
        )

        if letter == "?" or (
            letter.isdigit()
            and score_override is not None
            and int(letter) == score_override
        ):
            for variant, alt_texts, alt_confs, alt_aspects, _ in candidates[1:]:
                d, l, s, c, cf = _parse_char_and_score(
                    alt_texts,
                    alt_confs,
                    score_override=score_override,
                    bbox_aspects=alt_aspects,
                )
                if l.isalpha():
                    display, letter, score, curse, conf = d, l, s, c, cf
                    debug.fallback_texts = alt_texts
                    debug.chosen_variant = variant
                    break

        debug.score_override = score_override
        self.last_cell_debug.append(debug)

        number_value = None
        fraction_value = None
        meta: dict = {}
        if curse == CurseType.NUMBER and letter.isdigit():
            number_value = int(letter)
        if curse == CurseType.FRACTION:
            parts = parse_fraction_parts_from_text(display)
            if parts is not None:
                num, den = parts
                meta["fraction_num"] = num
                meta["fraction_den"] = den
                fraction_value = num / den if den else None

        overlay_text = " ".join(texts)
        suit, overlay_rank, is_joker = _detect_card_overlay(overlay_text)
        if is_joker:
            meta["is_joker"] = True
            curse = CurseType.WILDCARD
            letter = "?"
            display = "?"
        if suit:
            meta["card_suit"] = suit
            if overlay_rank and overlay_rank != "?":
                meta["card_rank"] = overlay_rank
            elif letter and letter != "?":
                meta["card_rank"] = letter.upper()[:1]

        tile = Tile(
            row=row,
            col=col,
            char=display,
            letter=letter,
            base_score=score,
            color=color,
            curse=curse,
            number_value=number_value,
            fraction_value=fraction_value,
            ocr_confidence=conf,
            metadata=meta,
        )
        if curse == CurseType.FRACTION:
            attach_fraction_metadata(tile)
        return tile

    def parse_board(self, board_bgr: np.ndarray, money: int = 0) -> Board:
        self.last_cell_debug = []
        cells = self.split_cells(board_bgr)
        tiles: list[list[Tile]] = []
        idx = 0
        total = len(cells)
        print(
            f"Reading {total} tiles (first solve on CPU can take several minutes)...",
            flush=True,
        )
        for r in range(5):
            row_tiles = []
            for c in range(5):
                row_tiles.append(self.parse_cell(cells[idx], r, c))
                idx += 1
                if idx % 5 == 0 or idx == total:
                    print(f"  OCR progress: {idx}/{total} tiles", flush=True)
            tiles.append(row_tiles)
        board = Board(tiles=tiles, money=money)
        print("Parsed board:", flush=True)
        print(format_board_grid(board), flush=True)
        return board

    def parse_money(self, money_bgr: np.ndarray) -> int:
        proc = _preprocess_cell(money_bgr)
        results = self.reader.readtext(proc, detail=0, paragraph=False)
        text = " ".join(results)
        nums = re.findall(r"\d+", text.replace(",", ""))
        if nums:
            return int(nums[-1])
        return 0

    def save_debug_tiles(
        self, board_bgr: np.ndarray, debug_dir: Path
    ) -> None:
        if not self.debug_ocr:
            return
        cells = self.split_cells(board_bgr)
        tiles_dir = debug_dir / "tiles"
        tiles_dir.mkdir(parents=True, exist_ok=True)
        for idx, cell in enumerate(cells):
            r, c = idx // 5, idx % 5
            prefix = f"r{r}_c{c}"
            save_debug_image(letter_roi(cell), tiles_dir / f"{prefix}_letter.png")
            save_debug_image(score_roi(cell), tiles_dir / f"{prefix}_score.png")
