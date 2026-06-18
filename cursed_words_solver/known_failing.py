"""Registry of mismatch fixtures with known replay gaps (not pipeline regressions)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

_REGISTRY_PATH = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "fixtures"
    / "known_failing.json"
)


@dataclass(frozen=True)
class KnownFailingEntry:
    stem: str
    category: str
    reason: str
    tracking_issue: str = ""


@lru_cache(maxsize=1)
def load_known_failing_registry() -> dict[str, KnownFailingEntry]:
    if not _REGISTRY_PATH.exists():
        return {}
    raw = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    entries = raw.get("entries") if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        return {}
    out: dict[str, KnownFailingEntry] = {}
    for item in entries:
        if not isinstance(item, dict):
            continue
        stem = str(item.get("stem") or "").strip()
        if not stem:
            continue
        out[stem] = KnownFailingEntry(
            stem=stem,
            category=str(item.get("category") or "replay_gap"),
            reason=str(item.get("reason") or ""),
            tracking_issue=str(item.get("tracking_issue") or ""),
        )
    return out


def known_failing_stems() -> frozenset[str]:
    return frozenset(load_known_failing_registry().keys())


def is_known_failing(stem: str) -> bool:
    return stem in load_known_failing_registry()


def known_failing_info(stem: str) -> KnownFailingEntry | None:
    return load_known_failing_registry().get(stem)


def registry_summary() -> list[dict[str, Any]]:
    return [
        {
            "stem": e.stem,
            "category": e.category,
            "reason": e.reason,
            "tracking_issue": e.tracking_issue,
        }
        for e in load_known_failing_registry().values()
    ]
