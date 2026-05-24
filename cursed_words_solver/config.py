"""Application configuration."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

CONFIG_DIR = Path.home() / ".cursed_words_solver"
CONFIG_PATH = CONFIG_DIR / "config.json"
LEGACY_SEARCH_TIME_BUDGET_SEC = 2.0
PREVIOUS_SEARCH_TIME_BUDGET_SEC = 15.0
LEGACY_MAX_WORD_LENGTH = 12
RUN_STATE_PATH = CONFIG_DIR / "run_state.json"
LAST_SUGGESTION_PATH = CONFIG_DIR / "last_suggestion.json"
SCORING_MISMATCHES_DIR = CONFIG_DIR / "scoring_mismatches"
DEBUG_DIR = CONFIG_DIR / "debug"
WORDLIST_PATH = CONFIG_DIR / "enable1.txt"
GAME_WORDLIST_PATH = CONFIG_DIR / "game_words.txt"
GAME_WORDLIST_META_PATH = CONFIG_DIR / "game_words_meta.json"
GAME_WORDLIST_MIN_BYTES = 1024
WORDLIST_URL = (
    "https://raw.githubusercontent.com/dolph/dictionary/master/enable1.txt"
)


@dataclass
class Region:
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0

    def is_valid(self) -> bool:
        return self.width > 0 and self.height > 0

    def to_dict(self) -> dict[str, int]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Region:
        return cls(
            x=int(data.get("x", 0)),
            y=int(data.get("y", 0)),
            width=int(data.get("width", 0)),
            height=int(data.get("height", 0)),
        )


@dataclass
class AppConfig:
    board_region: Region = field(default_factory=Region)
    money_region: Region | None = None
    hotkey: str = "f8"
    min_word_length: int = 3
    max_word_length: int = 15
    search_time_budget_sec: float = 45.0
    top_n_results: int = 3
    ocr_use_gpu: bool = False
    cell_inset_ratio: float = 0.1
    debug_ocr: bool = False
    wordlist: str = "game"
    show_board_highlight: bool = True

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "board_region": self.board_region.to_dict(),
            "money_region": (
                self.money_region.to_dict() if self.money_region else None
            ),
            "hotkey": self.hotkey,
            "min_word_length": self.min_word_length,
            "max_word_length": self.max_word_length,
            "search_time_budget_sec": self.search_time_budget_sec,
            "top_n_results": self.top_n_results,
            "ocr_use_gpu": self.ocr_use_gpu,
            "cell_inset_ratio": self.cell_inset_ratio,
            "debug_ocr": self.debug_ocr,
            "wordlist": self.wordlist,
            "show_board_highlight": self.show_board_highlight,
        }
        CONFIG_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @classmethod
    def load(cls) -> AppConfig:
        if not CONFIG_PATH.exists():
            return cls()
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        money = data.get("money_region")
        max_word_length = int(data.get("max_word_length", 15))
        search_time_budget_sec = float(data.get("search_time_budget_sec", 30.0))
        migrated = False
        if search_time_budget_sec == LEGACY_SEARCH_TIME_BUDGET_SEC:
            search_time_budget_sec = 30.0
            migrated = True
        elif search_time_budget_sec == PREVIOUS_SEARCH_TIME_BUDGET_SEC:
            search_time_budget_sec = 30.0
            migrated = True
        if max_word_length == LEGACY_MAX_WORD_LENGTH:
            max_word_length = 15
            migrated = True
        cfg = cls(
            board_region=Region.from_dict(data.get("board_region", {})),
            money_region=Region.from_dict(money) if money else None,
            hotkey=data.get("hotkey", "f8"),
            min_word_length=int(data.get("min_word_length", 3)),
            max_word_length=max_word_length,
            search_time_budget_sec=search_time_budget_sec,
            top_n_results=int(data.get("top_n_results", 3)),
            ocr_use_gpu=bool(data.get("ocr_use_gpu", False)),
            cell_inset_ratio=float(data.get("cell_inset_ratio", 0.1)),
            debug_ocr=bool(data.get("debug_ocr", False)),
            wordlist=str(data.get("wordlist", "game")),
            show_board_highlight=bool(data.get("show_board_highlight", True)),
        )
        if migrated:
            cfg.save()
        return cfg


def _game_wordlist_usable() -> bool:
    return (
        GAME_WORDLIST_PATH.exists()
        and GAME_WORDLIST_PATH.stat().st_size > GAME_WORDLIST_MIN_BYTES
    )


def resolve_wordlist(wordlist: str = "game") -> Path:
    """Return path to the word list file for the solver."""
    if wordlist == "enable1":
        return ensure_wordlist()
    if _game_wordlist_usable():
        return GAME_WORDLIST_PATH
    return ensure_wordlist()


def wordlist_count(path: Path) -> int | None:
    """Approximate word count from meta file or line count."""
    if path == GAME_WORDLIST_PATH and GAME_WORDLIST_META_PATH.exists():
        try:
            meta = json.loads(GAME_WORDLIST_META_PATH.read_text(encoding="utf-8"))
            count = meta.get("count")
            if isinstance(count, int) and count > 0:
                return count
        except (json.JSONDecodeError, OSError):
            pass
    try:
        return sum(1 for _ in path.open(encoding="utf-8", errors="ignore"))
    except OSError:
        return None


def describe_wordlist(path: Path, preference: str = "game") -> str:
    """Human-readable label for logs (source and approximate size)."""
    count = wordlist_count(path)
    count_str = f"{count} words" if count is not None else "unknown size"
    if path == GAME_WORDLIST_PATH:
        return f"game ({count_str})"
    if preference == "game":
        return f"enable1 fallback ({count_str}) — press F7 in-game to export game_words.txt"
    return f"enable1 ({count_str})"


def ensure_wordlist() -> Path:
    """Download enable1 word list if missing."""
    if WORDLIST_PATH.exists() and WORDLIST_PATH.stat().st_size > 1000:
        return WORDLIST_PATH
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        import urllib.request

        urllib.request.urlretrieve(WORDLIST_URL, WORDLIST_PATH)
    except Exception:
        # Minimal fallback for offline use
        WORDLIST_PATH.write_text(
            "\n".join(
                [
                    "the", "and", "for", "are", "but", "not", "you", "all",
                    "can", "had", "her", "was", "one", "our", "out", "day",
                    "get", "has", "him", "his", "how", "man", "new", "now",
                    "old", "see", "two", "way", "who", "boy", "did", "its",
                    "let", "put", "say", "she", "too", "use", "buy", "game",
                    "this", "that", "word", "words", "score", "tile", "run",
                ]
            ),
            encoding="utf-8",
        )
    return WORDLIST_PATH
