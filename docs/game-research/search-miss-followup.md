# Search-miss follow-up (from companion log triage, Aug 2026)

Round logs where the player beat F8 by a large margin are **search quality**,
not scoring. Reproduce with:

```text
cursed-solver explain --round-log ~/.cursed_words_solver/round_logs/20260731_160825_548.json
cursed-solver explain --round-log ~/.cursed_words_solver/round_logs/20260731_160417_241.json
```

Observed patterns:

- `path_mismatch` with tiny F8 words (`aaa` / 562 vs `barytophyllite` / 5062)
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

**Still open — barytophyllite (`path_mismatch`):**
`20260731_160825_548.json` (`aaa` → `barytophyllite`). Paths diverge after a
shared prefix; this is **not** a strict extension of the F8 highlight. Primary
early-stop fix alone does not recover it. Likely needs deep-extend to continue
through barren mid-length dictionary-resolve gaps
(`_deep_extend_dict_resolve_path` only recurses when a mid-length word exists).
Also: full `find_best_words` on these curse-heavy boards often never seeds the
F8 mid-length leader within budget — separate from the extension abort.
