"""Restore stdout for a windowed PyInstaller build before the app imports."""

import os
import sys


def _restore(name, fd):
    if getattr(sys, name) is not None:
        return
    try:
        setattr(
            sys,
            name,
            os.fdopen(
                fd,
                "w",
                buffering=1,
                encoding="utf-8",
                errors="replace",
                closefd=False,
            ),
        )
    except OSError:
        pass


_restore("stdout", 1)
_restore("stderr", 2)
