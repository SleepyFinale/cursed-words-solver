"""Set-transformer policy / value network (PyTorch).

State = a global token (from the global vector) + entity tokens (items, rack, shop offers,
bosses, ...). A small transformer mixes them; each candidate action is embedded from its
type, its features and the encoded tokens it refers to, and scored against the pooled state
(pointer head, softmax over that decision's candidates). Heads: policy logits, value
(return still to come), and auxiliary P(win) / P(Michael win) for representation learning.

``collate`` pads a list of ``env.pack`` dicts into one batch.

Older checkpoints (fewer global / token / action columns: obs and actions only ever append
columns) load with the new input columns at zero weight, so they score exactly as before;
inputs narrower or wider than the model are zero-padded / cut (steps from older shards).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F


@dataclass
class ModelConfig:
    n_global: int
    n_tok_feat: int
    n_act_feat: int
    n_classes: int
    n_tok_types: int = 16
    n_act_types: int = 17
    d: int = 128
    layers: int = 3
    heads: int = 4
    ff: int = 256
    cls_dim: int = 32
    dropout: float = 0.0


def default_config() -> ModelConfig:
    from cursed_words_solver.rl.actions import N_ACTION_TYPES, n_action_features
    from cursed_words_solver.rl.obs import N_TOK_TYPES, class_vocab, n_global_features, n_token_features

    return ModelConfig(n_global=n_global_features(), n_tok_feat=n_token_features(), n_act_feat=n_action_features(),
                       n_classes=len(class_vocab()), n_tok_types=N_TOK_TYPES, n_act_types=N_ACTION_TYPES)


def upgrade_config(cfg: ModelConfig) -> ModelConfig:
    """A config at an older obs / action layout (a known legacy width) widened to the current
    one; anything else is returned unchanged."""
    from cursed_words_solver.rl import actions, obs

    cur = {"n_global": (obs.n_global_features(), getattr(obs, "LEGACY_GLOBAL", ())),
           "n_tok_feat": (obs.n_token_features(), getattr(obs, "LEGACY_TOKEN", ())),
           "n_act_feat": (actions.n_action_features(), getattr(actions, "LEGACY_ACTION", ()))}
    kw = {k: n for k, (n, old) in cur.items() if getattr(cfg, k) in old and getattr(cfg, k) < n}
    return replace(cfg, **kw) if kw else cfg


def conditioned(cfg: "ModelConfig | dict", state: dict | None = None) -> bool:
    """Whether a config is at least obs-v3 wide (has the target-build columns).

    ``Policy`` widens v1 / v2 configs on load (zero weight on the new columns, i.e. acts as
    FREE), so to ask whether a checkpoint was TRAINED with targets pass its saved config
    (``torch.load(path)["config"]``), not ``Policy.cfg``. A widened checkpoint saved again
    (e.g. a resumed v2 run's champion) is v3 wide but still has all-zero weight on the target
    columns: pass its ``state`` too, and it then also needs nonzero weight there."""
    from cursed_words_solver.rl.obs import LEGACY_GLOBAL, V3_GLOBAL

    n = cfg["n_global"] if isinstance(cfg, dict) else cfg.n_global
    if int(n) < V3_GLOBAL:
        return False
    w = (state or {}).get("glob_in.0.weight")
    if w is None:
        return True
    return bool(w[:, LEGACY_GLOBAL[-1]:V3_GLOBAL].abs().sum() > 0)


# input layers whose weight columns are feature columns: (state key, config field)
_INPUT_WEIGHTS = (("glob_in.0.weight", "n_global"), ("tok_in.weight", "n_tok_feat"), ("act_in.weight", "n_act_feat"))


def _pad_cols(t: torch.Tensor, n: int) -> torch.Tensor:
    if t.dim() != 2 or t.shape[1] >= n:
        return t
    return torch.cat([t, t.new_zeros(t.shape[0], n - t.shape[1])], dim=1)


def pad_state(state: dict, cfg: ModelConfig) -> dict:
    """Zero weight for the feature columns a checkpoint predates."""
    out = dict(state)
    for k, f in _INPUT_WEIGHTS:
        if k in out:
            out[k] = _pad_cols(out[k], getattr(cfg, f))
    return out


def _fit(x: torch.Tensor, n: int) -> torch.Tensor:
    """Last dim to ``n``: zero-pad (older shards) or cut (columns newer than the model)."""
    w = x.shape[-1]
    if w == n:
        return x
    if w > n:
        return x[..., :n]
    return torch.cat([x, x.new_zeros(*x.shape[:-1], n - w)], dim=-1)


class Policy(nn.Module):
    def __init__(self, cfg: ModelConfig) -> None:
        super().__init__()
        cfg = upgrade_config(cfg)
        self.cfg = cfg
        d = cfg.d
        self.glob_in = nn.Sequential(nn.Linear(cfg.n_global, d), nn.GELU(), nn.Linear(d, d))
        self.tok_in = nn.Linear(cfg.n_tok_feat, d)
        self.tok_type = nn.Embedding(cfg.n_tok_types, d)
        self.cls_emb = nn.Embedding(cfg.n_classes, cfg.cls_dim)
        self.cls_proj = nn.Linear(cfg.cls_dim, d, bias=False)
        layer = nn.TransformerEncoderLayer(d, cfg.heads, cfg.ff, cfg.dropout, activation="gelu", batch_first=True,
                                           norm_first=True)
        self.enc = nn.TransformerEncoder(layer, cfg.layers, enable_nested_tensor=False)
        self.norm = nn.LayerNorm(d)
        self.act_in = nn.Linear(cfg.n_act_feat, d)
        self.act_type = nn.Embedding(cfg.n_act_types, d)
        self.ref1 = nn.Linear(d, d, bias=False)
        self.ref2 = nn.Linear(d, d, bias=False)
        self.act_mlp = nn.Sequential(nn.Linear(3 * d, d), nn.GELU(), nn.Linear(d, d), nn.GELU(), nn.Linear(d, 1))
        self.value = nn.Sequential(nn.Linear(d, d), nn.GELU(), nn.Linear(d, 1))
        self.aux = nn.Sequential(nn.Linear(d, d), nn.GELU(), nn.Linear(d, 2))  # win, michael logits

    def load_state_dict(self, state_dict, strict: bool = True, assign: bool = False):
        return super().load_state_dict(pad_state(state_dict, self.cfg), strict=strict, assign=assign)

    def forward(self, b: dict[str, torch.Tensor]) -> dict[str, torch.Tensor]:
        cfg = self.cfg
        B, T = b["tok_type"].shape
        g = self.glob_in(_fit(b["glob"], cfg.n_global)).unsqueeze(1)  # (B,1,d)
        t = self.tok_in(_fit(b["tok_feat"], cfg.n_tok_feat)) + self.tok_type(b["tok_type"]) \
            + self.cls_proj(self.cls_emb(b["tok_cls"]))
        x = torch.cat([g, t], dim=1)                                  # (B,1+T,d)
        pad = torch.cat([torch.zeros(B, 1, dtype=torch.bool, device=x.device), b["tok_mask"] == 0], dim=1)
        h = self.norm(self.enc(x, src_key_padding_mask=pad))
        pooled = h[:, 0]                                              # (B,d)
        toks = h[:, 1:]                                               # (B,T,d)
        A = b["act_type"].shape[1]

        def gather(ref: torch.Tensor) -> torch.Tensor:
            idx = ref.clamp(min=0).unsqueeze(-1).expand(B, A, toks.shape[-1])
            out = torch.gather(toks, 1, idx) if T > 0 else torch.zeros(B, A, toks.shape[-1], device=x.device)
            return out * (ref >= 0).unsqueeze(-1).to(out.dtype)

        a = self.act_in(_fit(b["act_feat"], cfg.n_act_feat)) + self.act_type(b["act_type"])
        a = a + self.ref1(gather(b["act_ref1"])) + self.ref2(gather(b["act_ref2"]))
        p = pooled.unsqueeze(1).expand(B, A, pooled.shape[-1])
        logits = self.act_mlp(torch.cat([a, p, a * p], dim=-1)).squeeze(-1)
        logits = logits.masked_fill(b["act_mask"] == 0, -1e9)
        return {"logits": logits, "value": self.value(pooled).squeeze(-1), "aux": self.aux(pooled)}


# ------------------------------------------------------------------------- batching

KEYS_INT = ("tok_type", "tok_cls", "act_type", "act_ref1", "act_ref2")


def collate(items: list[dict[str, np.ndarray]], device: str | torch.device = "cpu") -> dict[str, torch.Tensor]:
    """Pads to the widest item, so steps from older shards (fewer feature columns) mix in
    with zeros in the newer columns."""
    B = len(items)
    T = max(1, max(len(it["tok_type"]) for it in items))
    A = max(1, max(len(it["act_type"]) for it in items))
    G = max(it["glob"].shape[0] for it in items)
    Ft = max((it["tok_feat"].shape[1] if it["tok_feat"].ndim == 2 else 0) for it in items)
    Fa = max(it["act_feat"].shape[1] for it in items)
    glob = np.zeros((B, G), np.float32)
    tok_type = np.zeros((B, T), np.int64)
    tok_cls = np.zeros((B, T), np.int64)
    tok_feat = np.zeros((B, T, Ft), np.float32)
    tok_mask = np.zeros((B, T), np.float32)
    act_type = np.zeros((B, A), np.int64)
    r1 = np.full((B, A), -1, np.int64)
    r2 = np.full((B, A), -1, np.int64)
    act_feat = np.zeros((B, A, Fa), np.float32)
    act_mask = np.zeros((B, A), np.float32)
    for i, it in enumerate(items):
        g = it["glob"]
        glob[i, : g.shape[0]] = g
        n = len(it["tok_type"])
        if n:
            tf = it["tok_feat"]
            tok_type[i, :n] = it["tok_type"]
            tok_cls[i, :n] = it["tok_cls"]
            tok_feat[i, :n, : tf.shape[1]] = tf
            tok_mask[i, :n] = 1
        m = len(it["act_type"])
        af = it["act_feat"]
        act_type[i, :m] = it["act_type"]
        r1[i, :m] = it["act_ref1"]
        r2[i, :m] = it["act_ref2"]
        if m:
            act_feat[i, :m, : af.shape[1]] = af
        act_mask[i, :m] = 1
    out = {"glob": glob, "tok_type": tok_type, "tok_cls": tok_cls, "tok_feat": tok_feat, "tok_mask": tok_mask,
           "act_type": act_type, "act_ref1": r1, "act_ref2": r2, "act_feat": act_feat, "act_mask": act_mask}
    return {k: torch.from_numpy(v).to(device, non_blocking=True) for k, v in out.items()}


# ------------------------------------------------------------------------- save / load


def save_policy(model: Policy, path, extra: dict | None = None) -> None:
    import io

    from cursed_words_solver.rl.store import atomic_write_bytes

    buf = io.BytesIO()
    torch.save({"config": asdict(model.cfg), "state": {k: v.detach().cpu() for k, v in model.state_dict().items()},
                "extra": extra or {}}, buf)
    atomic_write_bytes(path, buf.getvalue())


def load_policy(path, device: str = "cpu") -> tuple[Policy, dict]:
    ck = torch.load(path, map_location=device, weights_only=False)
    m = Policy(ModelConfig(**ck["config"]))
    m.load_state_dict(ck["state"])
    m.to(device).eval()
    return m, ck.get("extra", {})


def upgrade_optimizer_state(opt_state: dict, model: Policy) -> dict:
    """Optimizer state from an older checkpoint with its moments zero-padded to the widened
    input weights (call before ``opt.load_state_dict`` on resume; a no-op for current ones).
    Assumes the optimizer was built over ``model.parameters()`` in order."""
    params = list(model.parameters())
    out = {**opt_state, "state": dict(opt_state.get("state", {}))}
    for i, st in out["state"].items():
        if not isinstance(i, int) or i >= len(params) or not isinstance(st, dict):
            continue
        p = params[i]
        out["state"][i] = {k: (_pad_cols(v, p.shape[1]) if torch.is_tensor(v) and v.dim() == 2 and p.dim() == 2
                               and v.shape[0] == p.shape[0] and v.shape[1] < p.shape[1] else v)
                           for k, v in st.items()}
    return out


def upgrade_checkpoint(ck: dict) -> dict:
    """A training checkpoint (``config`` / ``state`` / optional ``opt``) at the current widths:
    what ``ppo.py`` / ``bc.py`` resume needs after an obs / action layout change."""
    model = Policy(ModelConfig(**ck["config"]))
    out = {**ck, "config": asdict(model.cfg), "state": pad_state(ck["state"], model.cfg)}
    if isinstance(ck.get("opt"), dict):
        out["opt"] = upgrade_optimizer_state(ck["opt"], model)
    return out


class Actor:
    """CPU inference wrapper used by env actors and the live assistant."""

    def __init__(self, model: Policy, *, greedy: bool = False, temperature: float = 1.0, seed: int = 0) -> None:
        self.model = model.eval()
        self.greedy = greedy
        self.temperature = temperature
        self.gen = torch.Generator().manual_seed(seed)

    @torch.no_grad()
    def evaluate(self, packed: dict[str, np.ndarray]) -> tuple[np.ndarray, float, np.ndarray]:
        out = self.model(collate([packed]))
        logits = out["logits"][0, : len(packed["act_type"])]
        probs = torch.softmax(logits / max(1e-6, self.temperature), -1).numpy()
        return probs, float(out["value"][0]), torch.sigmoid(out["aux"][0]).numpy()

    @torch.no_grad()
    def choose(self, packed: dict[str, np.ndarray]) -> tuple[int, float, float]:
        """(index, log-prob, value)."""
        out = self.model(collate([packed]))
        logits = out["logits"][0, : len(packed["act_type"])] / max(1e-6, self.temperature)
        logp = F.log_softmax(logits, -1)
        if self.greedy:
            i = int(torch.argmax(logits))
        else:
            i = int(torch.multinomial(logp.exp(), 1, generator=self.gen))
        return i, float(logp[i]), float(out["value"][0])
