"""Keep every melmod ``run_state.json`` export of a play session (shops, boss drafts, pins).

    python scripts/record_run.py            # leave running while you play; Ctrl+C to stop

Round logs already hold the state at each word submit; this adds what happens in between
(shop stock and restocks, freezes, sells, boss draft options, pin choices), which the
mod only writes to ``run_state.json`` and overwrites. Each changed export is appended to
``~/.cursed_words_solver/run_journal/<start time>.jsonl`` as ``{"seen_at", "run_state"}``.
Press F7 in the shop after a restock if no new line is logged (auto-export follows the
mod's fingerprint, which may not include shop stock).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime
from pathlib import Path

ROOT = Path.home() / ".cursed_words_solver"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--state", default=str(ROOT / "run_state.json"))
    ap.add_argument("--out-dir", default=str(ROOT / "run_journal"))
    ap.add_argument("--interval", type=float, default=0.3, help="seconds between checks")
    args = ap.parse_args(argv)
    state = Path(args.state)
    out = Path(args.out_dir) / f"{datetime.now():%Y%m%d_%H%M%S}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    print(f"recording {state} -> {out} (Ctrl+C to stop)")
    last_mtime, last_hash, n = None, None, 0
    try:
        while True:
            time.sleep(args.interval)
            try:
                mtime = state.stat().st_mtime
                if mtime == last_mtime:
                    continue
                raw = state.read_bytes()
                doc = json.loads(raw)
            except (OSError, ValueError):
                continue  # missing, or caught mid-write: retry next tick
            last_mtime = mtime
            # exported_at changes on every write; skip exports whose content did not.
            body = {k: v for k, v in doc.items() if k not in ("exported_at", "export_diagnostics")}
            if isinstance(body.get("game_state"), dict):
                body["game_state"] = {k: v for k, v in body["game_state"].items() if k not in ("captured_at", "trigger")}
            h = hashlib.sha1(json.dumps(body, sort_keys=True).encode()).hexdigest()
            if h == last_hash:
                continue
            last_hash = h
            with out.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"seen_at": datetime.now().isoformat(timespec="milliseconds"), "run_state": doc}) + "\n")
            n += 1
            print(f"{datetime.now():%H:%M:%S} #{n} {doc.get('character', '?')} ${doc.get('money', '?')}", flush=True)
    except KeyboardInterrupt:
        print(f"stopped: {n} exports in {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
