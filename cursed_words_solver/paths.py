"""Locate catalog files in a source checkout and in a frozen build."""

from __future__ import annotations

import sys
from pathlib import Path

PACKAGE_VERSION = "0.1.2"


def project_root() -> Path:
    """Directory that contains the ``data`` catalog.

    Source checkouts use the repository root. Frozen builds use the
    PyInstaller bundle directory (``sys._MEIPASS``), where ``data/`` is packed.
    """
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def data_path(*parts: str) -> Path:
    return project_root().joinpath(*parts)
