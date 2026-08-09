# Search-miss follow-up (from companion log triage, Aug 2026)

Round logs where the player beat F8 by a large margin are **search quality**,
not scoring. Reproduce with:

```text
cursed-solver explain --round-log ~/.cursed_words_solver/round_logs/20260731_160825_548.json
cursed-solver explain --round-log ~/.cursed_words_solver/round_logs/20260731_160417_241.json
cursed-solver explain --round-log tests/fixtures/round_logs/20260808_falchion_path_mismatch.json
cursed-solver explain --round-log tests/fixtures/round_logs/20260808_miniatum_path_mismatch.json
cursed-solver explain --round-log tests/fixtures/round_logs/20260808_orthodox_path_mismatch.json
cursed-solver explain --round-log tests/fixtures/round_logs/20260808_entoiled_path_mismatch.json
cursed-solver explain --round-log tests/fixtures/round_logs/20260809_pouks_path_mismatch.json
cursed-solver explain --round-log tests/fixtures/round_logs/20260809_llama_path_mismatch.json
```

Observed patterns:

- `path_mismatch` with tiny F8 words (`aaa` / 562 vs `barytophyllite` / 5062)
- `path_mismatch` with short digit-only locals under Lab Coat (`457` / 98 vs `falchion` / 165; `245` / 88 vs `miniatum` / 130)
- `path_mismatch` with letter-bridged ascending numbers (`booh` / 66 vs `orthodox` / 111; `naomi` / 59 vs `entoiled` / 92)
- `path_mismatch` on shrunk Hungry Snake grids (`aah` / 1634 vs numeric wrap path ~30k on 3×2 bat)
- `path_mismatch` short ascending Number Go Up (`aahs` / 37248 vs `llama` / 50720 on 1→2→3→4→7)
- `path_extension` where the submitted path strictly extends the F8 highlight
- F8 wall time far over budget (`Done in 290s` vs 60s) with `dictionary resolve truncated`

## Status (Aug 2026 P2)

**Fixed:** premature path-extension early-stop. `_extend_leader_is_dominant`
now only crowns imm≥800 / high-margin leaders when the leader path is near
`max_len` (`len >= max_len - 1`). Mid-length 3s `extend_cap` and
`skip_post_extend` use the same near-max gate.

Regression: `tests/fixtures/round_logs/20260731_160417_241_pumpernickels_path_extension.json`
via `test_pumpernickels_extension_from_halterneck_prefix` (seeded
`halterneck` → longer extension).

**Fixed:** Lab Coat + Number Go Up digit-local misses (`457` → `falchion`,
`245` → `miniatum`, `booh` → `orthodox`, `naomi` → `entoiled`).
`rewards_number_tiles` soft-covers scored numbers and schedules a
non-`digits_only` number-cover side slice: ascending face tours with
letter-only bridges (no number detours), leave-one/two-out face subsets,
alternate neighbor-linked tiles per face (colorless `2` next to `4`),
independent letter prefix/suffix growth (`…6UM`, `O…X`), and ranking that
keeps compact high-cover cores ahead of letter-bloated leave-outs.
Bridge BFS is expansion-capped. Per-solve only — no cross-F8 cache.

Regressions: `tests/fixtures/round_logs/20260808_*_path_mismatch.json`
(falchion / miniatum / orthodox / entoiled) via
`tests/regression/test_falchion_number_cover.py`.

**Fixed:** Hungry Snake on shrunk playable grids (wrap adjacency on
`playable_min_col` ↔ `playable_max_col`). Digit-face concatenations
(`1656253`, historic display `12345`) are **not** Vocabulary words — the game
matches dictionary *letters* via number wildcards (`!`); F8 must resolve or
reject, never suggest pure digits. Ascending Number Go Up tours (e.g. `aahs`
→ `llama` / `aahed` on 1→2→3→4→7) explore ascending faces only, resolve at
leaves, and do not re-heap digit face strings.

Regressions: `tests/fixtures/round_logs/20260809_pouks_path_mismatch.json`
via `tests/regression/test_pouks_hungry_snake_wrap.py`;
`tests/fixtures/round_logs/20260809_llama_path_mismatch.json` via
`tests/regression/test_llama_ascending_number_tour.py`.

**Still open — barytophyllite (`path_mismatch`):**
`20260731_160825_548.json` (`aaa` → `barytophyllite`). Paths diverge after a
shared prefix; this is **not** a strict extension of the F8 highlight. Primary
early-stop fix alone does not recover it. Likely needs deep-extend to continue
through barren mid-length dictionary-resolve gaps
(`_deep_extend_dict_resolve_path` only recurses when a mid-length word exists).
Also: full `find_best_words` on these curse-heavy boards often never seeds the
F8 mid-length leader within budget — separate from the extension abort.
