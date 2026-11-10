"""PPO self-improvement: CPU actor processes play runs with the current policy (sampled),
the GPU learner updates it, the anchor term (KL to the starting policy) is annealed so the
agent is free to find its own play. Every ``--eval-every`` updates the greedy policy plays the
gate seed set; it becomes the champion when it beats the current champion paired.

Pause / resume: rerun the same command (``command.txt``). State is checkpointed after every
update (model, optimiser, counters, RNG); episodes in flight at a kill are simply replayed
with new seeds. ``STOP`` file in the dir = checkpoint and exit.

    python -m cursed_words_solver.rl.ppo --dir ~/.cursed_words_solver/rl/ppo1 --init ~/.cursed_words_solver/rl/bc/best.pt
"""

from __future__ import annotations

import argparse
import io
import math
import random
import shutil
import time
from collections import deque
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn.functional as F

from cursed_words_solver.rl import store
from cursed_words_solver.rl.bc import VALUE_SCALE
from cursed_words_solver.rl.model import Policy, ModelConfig, collate, load_policy, save_policy
from cursed_words_solver.rl.teacher import CHARS

TRAIN_SEED0 = 50_000_000


def sample_job(rng: random.Random, n: int, quest_share: float, crown_weights: list[float]) -> dict[str, Any]:
    from cursed_words_solver.sim.game.challenges import QUESTS

    ch = CHARS[rng.randrange(len(CHARS))]
    if rng.random() < quest_share:
        return {"character": ch, "crown": 0, "quest": sorted(QUESTS)[rng.randrange(len(QUESTS))], "seed": TRAIN_SEED0 + n}
    cr = rng.choices(range(len(crown_weights)), weights=crown_weights)[0]
    return {"character": ch, "crown": cr, "quest": None, "seed": TRAIN_SEED0 + n}


def gae(rew: np.ndarray, val: np.ndarray, lam: float, gamma: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    n = len(rew)
    adv = np.zeros(n, np.float32)
    last = 0.0
    for t in range(n - 1, -1, -1):
        nv = val[t + 1] if t + 1 < n else 0.0
        delta = rew[t] + gamma * nv - val[t]
        last = delta + gamma * lam * last
        adv[t] = last
    return adv, adv + val


class DistillBuffer:
    """Look-ahead picks from ``rl.exit`` shards (expert iteration); newest ``cap`` decisions."""

    def __init__(self, root: Path, cap: int = 200_000) -> None:
        self.dir = Path(root) / "shards"
        self.cap = cap
        self.seen: set[str] = set()
        self.items: deque = deque(maxlen=cap)
        self.n_changed = 0

    def refresh(self) -> int:
        if not self.dir.is_dir():
            return 0
        new = 0
        for f in sorted(self.dir.glob("*.npz"), key=lambda p: p.stat().st_mtime):
            if f.name in self.seen:
                continue
            try:
                ep = store.load_episode(f)
            except Exception:
                continue   # being written
            self.seen.add(f.name)
            for i in range(len(ep["chosen"])):
                st = store.unpack_step(ep, i)
                if len(st["act_type"]) <= 1:
                    continue
                self.items.append({**st, "chosen": int(ep["chosen"][i])})
                new += 1
        return new

    def sample(self, n: int) -> list[dict]:
        k = len(self.items)
        return [self.items[i] for i in np.random.randint(0, k, size=min(n, k))] if k else []


def ppo_update(model: Policy, ref: Policy | None, opt, batch: list[dict], args, device,
               distill: DistillBuffer | None = None) -> dict:
    model.train()
    idx = np.arange(len(batch))
    stats: dict[str, list[float]] = {}
    beta = args.kl_coef
    for _ in range(args.epochs):
        np.random.shuffle(idx)
        for s in range(0, len(idx), args.mb):
            items = [batch[i] for i in idx[s:s + args.mb]]
            b = collate(items, device)
            chosen = torch.tensor([it["chosen"] for it in items], device=device)
            old_logp = torch.tensor([it["logp"] for it in items], device=device)
            adv = torch.tensor([it["adv"] for it in items], device=device)
            ret = torch.tensor([it["ret"] for it in items], device=device)
            out = model(b)
            # the actors sample from softmax(logits / T); learn that same distribution
            logp_all = F.log_softmax(out["logits"] / args.temperature, -1)
            logp = logp_all.gather(1, chosen.unsqueeze(1)).squeeze(1)
            ratio = torch.exp(logp - old_logp)
            pg = -torch.min(ratio * adv, ratio.clamp(1 - args.clip, 1 + args.clip) * adv).mean()
            vloss = F.smooth_l1_loss(out["value"], ret / VALUE_SCALE)
            p = logp_all.exp() * b["act_mask"]
            ent = -(p * logp_all.masked_fill(b["act_mask"] == 0, 0)).sum(-1).mean()
            loss = pg + args.vf_coef * vloss - args.ent_coef * ent
            kl_ref = torch.zeros((), device=device)
            if ref is not None and beta > 0:
                with torch.no_grad():
                    rl = F.log_softmax(ref(b)["logits"] / args.temperature, -1)
                kl_ref = (p * (logp_all - rl).masked_fill(b["act_mask"] == 0, 0)).sum(-1).mean()
                loss = loss + beta * kl_ref
            dist = torch.zeros((), device=device)
            if distill is not None and args.distill_coef > 0:
                ditems = distill.sample(args.distill_mb)
                if ditems:
                    db = collate(ditems, device)
                    dch = torch.tensor([it["chosen"] for it in ditems], device=device)
                    dist = F.cross_entropy(model(db)["logits"], dch)
                    loss = loss + args.distill_coef * dist
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), args.max_grad)
            opt.step()
            with torch.no_grad():
                approx_kl = (old_logp - logp).mean().item()
                clipfrac = ((ratio - 1).abs() > args.clip).float().mean().item()
            for k, v in (("pg", pg.item()), ("v", vloss.item()), ("ent", ent.item()), ("kl_ref", kl_ref.item()), ("distill", dist.item()),
                         ("approx_kl", approx_kl), ("clipfrac", clipfrac)):
                stats.setdefault(k, []).append(v)
        if np.mean(stats.get("approx_kl", [0])) > args.target_kl:
            break
    return {k: round(float(np.mean(v)), 4) for k, v in stats.items()}


def episode_items(res: dict, lam: float) -> list[dict]:
    tr = res["traj"]
    if not tr["steps"]:
        return []
    rew = np.asarray(tr["reward"], np.float32)
    val = np.asarray(tr["value"], np.float32) * VALUE_SCALE
    adv, ret = gae(rew, val, lam)
    items = []
    for i, st in enumerate(tr["steps"]):
        if len(st["act_type"]) <= 1:
            continue  # forced move: no gradient
        items.append({**st, "chosen": tr["chosen"][i], "logp": tr["logp"][i], "adv": float(adv[i]), "ret": float(ret[i])})
    return items


def save_ckpt(path: Path, model, opt, state: dict) -> None:
    buf = io.BytesIO()
    torch.save({"config": model.cfg.__dict__, "state": model.state_dict(), "opt": opt.state_dict(), **state,
                "py_rng": random.getstate(), "np_rng": np.random.get_state(), "torch_rng": torch.get_rng_state()}, buf)
    store.atomic_write_bytes(path, buf.getvalue())


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=str(store.RL_HOME / "ppo1"))
    ap.add_argument("--init", default=str(store.RL_HOME / "bc" / "best.pt"))
    ap.add_argument("--workers", type=int, default=7)
    ap.add_argument("--updates", type=int, default=100000, help="total updates (absolute)")
    ap.add_argument("--episodes", type=int, default=56, help="episodes per update")
    ap.add_argument("--lr", type=float, default=5e-5)
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--mb", type=int, default=512)
    ap.add_argument("--clip", type=float, default=0.15)
    ap.add_argument("--lam", type=float, default=0.95)
    ap.add_argument("--vf-coef", type=float, default=0.5)
    ap.add_argument("--ent-coef", type=float, default=0.003)
    ap.add_argument("--kl-coef", type=float, default=0.1, help="start of the anchor to the init policy")
    ap.add_argument("--kl-halflife", type=float, default=300.0, help="updates for the anchor to halve")
    ap.add_argument("--target-kl", type=float, default=0.03)
    ap.add_argument("--max-grad", type=float, default=0.5)
    ap.add_argument("--quest-share", type=float, default=0.1)
    ap.add_argument("--eval-every", type=int, default=25)
    ap.add_argument("--eval-per", type=int, default=2)
    ap.add_argument("--temperature", type=float, default=1.0)
    ap.add_argument("--distill-dir", default="", help="rl.exit dir: also learn the look-ahead's picks")
    ap.add_argument("--distill-coef", type=float, default=0.5)
    ap.add_argument("--distill-mb", type=int, default=128)
    ap.add_argument("--crown-weights", default="1,1,1,1,1,1,1,1,1",
                    help="sampling weight of crowns 0-8 for training runs (comma list)")
    args = ap.parse_args(argv)
    out = Path(args.dir).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    (out / "command.txt").write_text("python -m cursed_words_solver.rl.ppo " + " ".join(argv or __import__("sys").argv[1:]) + "\n")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    ck_path = out / "ckpt.pt"
    if ck_path.is_file():
        ck = torch.load(ck_path, map_location="cpu", weights_only=False)
        model = Policy(ModelConfig(**ck["config"])).to(device)
        model.load_state_dict(ck["state"])
        opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.0)
        opt.load_state_dict(ck["opt"])
        state = {k: ck[k] for k in ("update", "episodes_started", "episodes_done", "champion_update", "init")}
        state["pending_gate"] = ck.get("pending_gate", 0)
        random.setstate(ck["py_rng"])
        np.random.set_state(ck["np_rng"])
        torch.set_rng_state(ck["torch_rng"])
        print(f"resumed at update {state['update']}", flush=True)
    else:
        init = str(Path(args.init).expanduser())
        model, _ = load_policy(init, device=str(device))
        opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.0)
        state = {"update": 0, "episodes_started": 0, "episodes_done": 0, "champion_update": 0, "init": init,
                 "pending_gate": 0}
        shutil.copyfile(init, out / "init.pt")
        shutil.copyfile(init, out / "champion.pt")
        random.seed(1)
        np.random.seed(1)
    ref = None
    if args.kl_coef > 0:
        ref, _ = load_policy(out / "init.pt", device=str(device))
        for p in ref.parameters():
            p.requires_grad_(False)
    weights = out / "weights.pt"
    save_policy(model, weights, {"update": state["update"]})
    distill = DistillBuffer(Path(args.distill_dir).expanduser()) if args.distill_dir else None
    from cursed_words_solver.rl.evaluate import eval_jobs, paired, run_arm, summarize
    from cursed_words_solver.rl.play import init_worker, play
    from cursed_words_solver.sim.game.agent import spawn_pool

    pool = spawn_pool(args.workers, init_worker, ())
    gate_jobs = eval_jobs(per=args.eval_per, per_quest=1, block=1)
    eval_dir = out / "eval"
    # finish a promotion a crash interrupted (state is saved before the files are copied)
    cu = state["champion_update"]
    if cu and (out / f"cand_u{cu}.pt").is_file():
        shutil.copyfile(out / f"cand_u{cu}.pt", out / "champion.pt")
        if (eval_dir / f"u{cu}.jsonl").is_file():
            shutil.copyfile(eval_dir / f"u{cu}.jsonl", eval_dir / f"champion_u{cu}.jsonl")
        (out / f"cand_u{cu}.pt").unlink(missing_ok=True)
    # champion's gate results (the init policy at first)
    champ_arm = f"champion_u{state['champion_update']}"
    if state["update"] == 0 or not (eval_dir / f"{champ_arm}.jsonl").is_file():
        print("evaluating the starting champion on the gate set...", flush=True)
        run_arm(champ_arm, str(out / "champion.pt"), gate_jobs, out_dir=eval_dir, pool=pool, verbose=False)
    rng = random.Random(state["episodes_started"] * 7919 + 13)
    crown_w = [float(x) for x in args.crown_weights.split(",")]
    assert len(crown_w) == 9, "--crown-weights needs 9 values"
    in_flight: deque = deque()
    recent: deque = deque(maxlen=500)

    def submit() -> None:
        j = sample_job(rng, state["episodes_started"], args.quest_share, crown_w)
        state["episodes_started"] += 1
        in_flight.append(pool.apply_async(play, ({**j, "policy": str(weights), "record": True,
                                                   "temperature": args.temperature},)))

    def gate(u: int) -> None:
        """Paired eval of candidate cand_u{u}.pt vs the champion; resumable (run_arm appends)."""
        arm = f"u{u}"
        cand = out / f"cand_{arm}.pt"
        rows = run_arm(arm, str(cand), gate_jobs, out_dir=eval_dir, pool=pool, verbose=False)
        champ = store.read_jsonl(eval_dir / f"champion_u{state['champion_update']}.jsonl")
        champ = [r for r in champ if not r.get("error")]
        cmp = paired(rows, champ)
        promote = cmp.get("n", 0) > 0 and cmp["outcome_diff"] > 0 and cmp["t"] >= 1.0 and cmp["win_diff"] >= 0
        teacher = [r for r in store.read_jsonl(eval_dir / "teacher.jsonl") if not r.get("error")]
        grow = {"update": u, "eval": summarize(rows), "vs_champion": cmp, "promoted": promote,
                "champion_update": state["champion_update"],
                "vs_teacher": paired(rows, teacher) if teacher else None}
        print("GATE", grow, flush=True)
        store.append_jsonl(out / "gates.jsonl", grow)
        state["pending_gate"] = 0
        if promote:
            state["champion_update"] = u
            save_ckpt(ck_path, model, opt, state)   # commit the decision, then move files
            shutil.copyfile(eval_dir / f"{arm}.jsonl", eval_dir / f"champion_u{u}.jsonl")
            shutil.copyfile(cand, out / "champion.pt")
        else:
            save_ckpt(ck_path, model, opt, state)
        cand.unlink(missing_ok=True)

    if state.get("pending_gate"):
        u = state["pending_gate"]
        if (out / f"cand_u{u}.pt").is_file():
            print(f"finishing the interrupted gate of update {u}", flush=True)
            gate(u)
        else:
            state["pending_gate"] = 0

    for _ in range(args.workers * 2):
        submit()
    buf_items: list[dict] = []
    buf_eps: list[dict] = []
    t_last = time.time()
    try:
        while state["update"] < args.updates:
            # collect
            while len(buf_eps) < args.episodes:
                ready = [a for a in in_flight if a.ready()]
                if not ready:
                    time.sleep(0.05)
                    continue
                for a in ready:
                    in_flight.remove(a)
                    res = a.get()
                    submit()
                    if res.get("error"):
                        print("episode error:", res["error"], res.get("trace", "")[-400:], flush=True)
                        continue
                    buf_items.extend(episode_items(res, args.lam))
                    res.pop("traj", None)
                    buf_eps.append(res)
                    recent.append(res)
                    state["episodes_done"] += 1
            # learn
            args.kl_coef_now = args.kl_coef * 0.5 ** (state["update"] / max(1e-9, args.kl_halflife))
            a2 = argparse.Namespace(**{**vars(args), "kl_coef": args.kl_coef_now})
            if buf_items:
                advs = np.asarray([it["adv"] for it in buf_items], np.float32)
                mu, sd = float(advs.mean()), float(advs.std() + 1e-6)
                for it in buf_items:
                    it["adv"] = (it["adv"] - mu) / sd
                if distill is not None:
                    distill.refresh()
                st = ppo_update(model, ref, opt, buf_items, a2, device, distill)
                if distill is not None:
                    st["distill_n"] = len(distill.items)
            else:
                st = {}
            state["update"] += 1
            save_policy(model, weights, {"update": state["update"]})
            dt = time.time() - t_last
            t_last = time.time()
            row = {"update": state["update"], "episodes": state["episodes_done"], "steps": len(buf_items),
                   "secs": round(dt, 1), "eps_per_h": round(len(buf_eps) / max(1e-9, dt) * 3600),
                   **{f"train_{k}": v for k, v in summarize(buf_eps).items()},
                   "recent_win": round(float(np.mean([bool(r["won"]) for r in recent])), 4),
                   "recent_outcome": round(float(np.mean([r["outcome"] for r in recent])), 3),
                   "kl_coef": round(args.kl_coef_now, 4), **st}
            print(row, flush=True)
            due = state["update"] % args.eval_every == 0
            if due:
                shutil.copyfile(weights, out / f"cand_u{state['update']}.pt")
                state["pending_gate"] = state["update"]
            save_ckpt(ck_path, model, opt, state)
            # logs after the checkpoint: a crash can drop a row, never duplicate one
            store.append_jsonl(out / "history.jsonl", row)
            for r in buf_eps:
                store.append_jsonl(out / "episodes.jsonl", r)
            buf_items, buf_eps = [], []
            if due:
                gate(state["update"])
            if store.stop_requested(out):
                print("STOP file found: checkpointed, exiting", flush=True)
                break
    finally:
        pool.terminate()


if __name__ == "__main__":
    main()
