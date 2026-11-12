"""numba kernels for ``ExactSearch.enumerate`` (letter DFS), ``enumerate_subsets`` (node-set
DFS) and ``_np_advance``; bit-identical to the Python code in ``search.py`` (same visit
order, budgets, first-found spelling, ``stats``).

``search.py`` dispatches here unless ``CWS_NO_JIT=1`` (or ``search.USE_JIT = False``) or
numba is missing. ``tables`` returns None (-> Python) where the kernels cannot be exact:
Honeypot, multi-letter tokens (Queenie's "qu"), > 64 tiles, > 5 movement / letter item
classes scattered on the board. Callers also keep Python for deadline / cancel searches.
"""

from __future__ import annotations

import numba as nb
import numpy as np

from cursed_words_solver.engine import search as S
from cursed_words_solver.engine.model import G_FRACTION, G_ITEM, G_NUMBER

# ----------------------------------------------------------------------------- kernels


@nb.njit(cache=True, inline="always")
def _moves(idx, visited, tix, all_allowed, portal2, moon_off2, moon_dat, prim_off2, prim_dat, out):
    """``moves()`` of the Python DFS (table ``tix`` = path inventory); writes ``out``, returns count."""
    n = 0
    portal = portal2[tix]
    moon_off = moon_off2[tix]
    prim_off = prim_off2[tix]
    one = np.uint64(1)
    if portal[idx]:
        for a in range(all_allowed.shape[0]):
            j = all_allowed[a]
            if not (visited >> np.uint64(j)) & one:
                out[n] = j
                n += 1
    for a in range(moon_off[idx], moon_off[idx + 1]):
        j = moon_dat[a]
        if not (visited >> np.uint64(j)) & one:
            dup = False
            for b in range(n):
                if out[b] == j:
                    dup = True
                    break
            if not dup:
                out[n] = j
                n += 1
    if n:
        for a in range(prim_off[idx], prim_off[idx + 1]):
            j = prim_dat[a]
            if not (visited >> np.uint64(j)) & one:
                dup = False
                for b in range(n):
                    if out[b] == j:
                        dup = True
                        break
                if not dup:
                    out[n] = j
                    n += 1
        return n
    for a in range(prim_off[idx], prim_off[idx + 1]):
        j = prim_dat[a]
        if not (visited >> np.uint64(j)) & one:
            out[n] = j
            n += 1
    return n


@nb.njit(cache=True, inline="always")
def _child(starts, counts, childs, keys, node, code):
    """Child of ``node`` by letter ``code`` (0-25), or -1 (children sorted by letter)."""
    s = starts[node]
    for k in range(s, s + counts[node]):
        cc = keys[k] & 31
        if cc == code:
            return childs[k]
        if cc > code:
            break
    return -1


@nb.njit(cache=True)
def _grow(e_path, e_len, e_node, cap):
    cap2 = cap * 2
    p2 = np.empty((cap2, e_path.shape[1]), dtype=np.int32)
    p2[:cap] = e_path
    l2 = np.empty(cap2, dtype=np.int32)
    l2[:cap] = e_len
    n2 = np.empty(cap2, dtype=np.int32)
    n2[:cap] = e_node
    return p2, l2, n2


@nb.njit(cache=True)
def _letter_dfs(t_starts, t_counts, t_childs, t_keys, t_isword,
                start_list, all_allowed, portal, moon_off, moon_dat, prim_off, prim_dat,
                m_wild, m_mask, D, ngu, is_num, num_val,
                min_len, max_len, pickup_mask, budget0, T, inv_bit):
    """``enumerate`` without tokens / Honeypot / deadline (explicit stack).
    Returns (emitted paths, lengths, trie nodes, final budget, dfs calls)."""
    cap = 256
    e_path = np.empty((cap, max_len), dtype=np.int32)
    e_len = np.empty(cap, dtype=np.int32)
    e_node = np.empty(cap, dtype=np.int32)
    ne = 0
    budget = budget0
    calls = 0
    f_idx = np.zeros(max_len + 1, dtype=np.int64)
    f_node = np.zeros(max_len + 1, dtype=np.int64)
    f_vis = np.zeros(max_len + 1, dtype=np.uint64)
    f_inv = np.zeros(max_len + 1, dtype=np.int64)
    f_last = np.zeros(max_len + 1, dtype=np.float64)
    f_hasl = np.zeros(max_len + 1, dtype=np.bool_)
    f_asc = np.zeros(max_len + 1, dtype=np.bool_)
    f_mi = np.zeros(max_len + 1, dtype=np.int64)
    f_mn = np.zeros(max_len + 1, dtype=np.int64)
    # the move each frame is expanding: its trie children are walked one per child call
    c_active = np.zeros(max_len + 1, dtype=np.bool_)
    c_nxt = np.zeros(max_len + 1, dtype=np.int64)
    c_wild = np.zeros(max_len + 1, dtype=np.bool_)
    c_mask = np.zeros(max_len + 1, dtype=np.int64)
    c_k = np.zeros(max_len + 1, dtype=np.int64)  # wild: next edge; else next letter code
    c_last = np.zeros(max_len + 1, dtype=np.float64)
    c_hasl = np.zeros(max_len + 1, dtype=np.bool_)
    c_asc = np.zeros(max_len + 1, dtype=np.bool_)
    mv = np.zeros((max_len + 1, T + 1), dtype=np.int32)
    path = np.zeros(max_len + 1, dtype=np.int32)
    one = np.uint64(1)
    for si in range(start_list.shape[0]):
        i = start_list[si]
        a_idx = (i * D + 0) * 2 + 1
        wild0 = m_wild[a_idx]
        mask0 = m_mask[a_idx]
        path[0] = i
        s0 = t_starts[0]
        e0 = s0 + t_counts[0]
        kk = s0
        code = 0
        while True:  # root children in the Python loop's order
            child = -1
            if wild0:
                if kk >= e0:
                    break
                child = t_childs[kk]
                kk += 1
            else:
                while code < 26:
                    cd = code
                    code += 1
                    if (mask0 >> cd) & 1:
                        child = _child(t_starts, t_counts, t_childs, t_keys, 0, cd)
                        if child >= 0:
                            break
                if child < 0:
                    break
            L = 0
            f_idx[0] = i
            f_node[0] = child
            f_vis[0] = one << np.uint64(i)
            f_inv[0] = inv_bit[i]
            f_hasl[0] = is_num[i]
            f_last[0] = num_val[i]
            f_asc[0] = True
            entering = True
            while L >= 0:
                if entering:
                    entering = False
                    calls += 1
                    budget -= 1
                    if budget < 0:
                        L -= 1
                        continue
                    length = L + 1
                    node = f_node[L]
                    vis = f_vis[L]
                    if t_isword[node] and length >= min_len and (pickup_mask == 0 or (vis & pickup_mask) != 0):
                        if ne >= cap:
                            e_path, e_len, e_node = _grow(e_path, e_len, e_node, cap)
                            cap *= 2
                        for q in range(length):
                            e_path[ne, q] = path[q]
                        e_len[ne] = length
                        e_node[ne] = node
                        ne += 1
                    if length >= max_len:
                        L -= 1
                        continue
                    f_mn[L] = _moves(f_idx[L], vis, f_inv[L], all_allowed, portal, moon_off, moon_dat, prim_off, prim_dat, mv[L])
                    f_mi[L] = 0
                    c_active[L] = False
                length = L + 1
                pushed = False
                while True:
                    if not c_active[L]:
                        if f_mi[L] >= f_mn[L]:
                            break
                        nxt = mv[L, f_mi[L]]
                        f_mi[L] += 1
                        n_last = f_last[L]
                        n_hasl = f_hasl[L]
                        n_asc = f_asc[L]
                        if is_num[nxt]:
                            nv = num_val[nxt]
                            n_asc = n_asc and ((not n_hasl) or nv > n_last)
                            n_last = nv
                            n_hasl = True
                        a_idx = (nxt * D + length) * 2 + (1 if (n_asc or not ngu) else 0)
                        c_active[L] = True
                        c_nxt[L] = nxt
                        c_wild[L] = m_wild[a_idx]
                        c_mask[L] = m_mask[a_idx]
                        c_last[L] = n_last
                        c_hasl[L] = n_hasl
                        c_asc[L] = n_asc
                        c_k[L] = t_starts[f_node[L]] if c_wild[L] else 0
                        path[length] = nxt
                    node = f_node[L]
                    child = -1
                    if c_wild[L]:
                        if c_k[L] < t_starts[node] + t_counts[node]:
                            child = t_childs[c_k[L]]
                            c_k[L] += 1
                    else:
                        cd = c_k[L]
                        while cd < 26:
                            c = cd
                            cd += 1
                            if (c_mask[L] >> c) & 1:
                                child = _child(t_starts, t_counts, t_childs, t_keys, node, c)
                                if child >= 0:
                                    break
                        c_k[L] = cd
                    if child < 0:
                        # move done (path.pop); the Python loop checks the budget here
                        c_active[L] = False
                        if budget < 0:
                            break
                        continue
                    L2 = L + 1
                    nxt = c_nxt[L]
                    f_idx[L2] = nxt
                    f_node[L2] = child
                    f_vis[L2] = f_vis[L] | (one << np.uint64(nxt))
                    f_inv[L2] = f_inv[L] | inv_bit[nxt]
                    f_last[L2] = c_last[L]
                    f_hasl[L2] = c_hasl[L]
                    f_asc[L2] = c_asc[L]
                    L = L2
                    entering = True
                    pushed = True
                    break
                if not pushed:
                    L -= 1
        if budget < 0:  # no check between root children, only between start tiles
            break
    return e_path[:ne], e_len[:ne], e_node[:ne], budget, calls


@nb.njit(cache=True)
def _subset_dfs(t_starts, t_counts, t_childs, t_keys, t_isword,
                start_list, all_allowed, portal, moon_off, moon_dat, prim_off, prim_dat,
                m_wild, m_mask, D, ngu, is_num, num_val,
                min_len, max_len, pickup_mask, budget0, T, inv_bit):
    """``enumerate_subsets`` without deadline: node sets live in one stack buffer.
    Returns (emitted paths, lengths, min word node, final budget)."""
    cap = 256
    e_path = np.empty((cap, max_len), dtype=np.int32)
    e_len = np.empty(cap, dtype=np.int32)
    e_node = np.empty(cap, dtype=np.int32)
    ne = 0
    budget = budget0
    buf = np.empty(4096, dtype=np.int32)
    nb_off = np.zeros(max_len + 2, dtype=np.int64)
    nb_len = np.zeros(max_len + 2, dtype=np.int64)
    f_idx = np.zeros(max_len + 1, dtype=np.int64)
    f_vis = np.zeros(max_len + 1, dtype=np.uint64)
    f_inv = np.zeros(max_len + 1, dtype=np.int64)
    f_last = np.zeros(max_len + 1, dtype=np.float64)
    f_hasl = np.zeros(max_len + 1, dtype=np.bool_)
    f_asc = np.zeros(max_len + 1, dtype=np.bool_)
    f_mi = np.zeros(max_len + 1, dtype=np.int64)
    f_mn = np.zeros(max_len + 1, dtype=np.int64)
    mv = np.zeros((max_len + 1, T + 1), dtype=np.int32)
    path = np.zeros(max_len + 1, dtype=np.int32)
    one = np.uint64(1)

    for si in range(start_list.shape[0]):
        i = start_list[si]
        a_idx = (i * D + 0) * 2 + 1
        wild = m_wild[a_idx]
        mask = m_mask[a_idx]
        n0 = 0
        if wild:
            s = t_starts[0]
            c = t_counts[0]
            if buf.shape[0] < c:
                buf = np.empty(c * 2, dtype=np.int32)
            for k in range(s, s + c):
                buf[n0] = t_childs[k]
                n0 += 1
        else:
            for code in range(26):
                if (mask >> code) & 1:
                    ch = _child(t_starts, t_counts, t_childs, t_keys, 0, code)
                    if ch >= 0:
                        buf[n0] = ch
                        n0 += 1
        if n0 == 0:
            continue
        nb_off[0] = 0
        nb_len[0] = n0
        path[0] = i
        L = 0
        f_idx[0] = i
        f_vis[0] = one << np.uint64(i)
        f_inv[0] = inv_bit[i]
        f_hasl[0] = is_num[i]
        f_last[0] = num_val[i]
        f_asc[0] = True
        entering = True
        while L >= 0:
            if entering:
                entering = False
                budget -= 1
                if budget < 0:
                    L -= 1
                    continue
                length = L + 1
                vis = f_vis[L]
                if length >= min_len and (pickup_mask == 0 or (vis & pickup_mask) != 0):
                    best = -1
                    off = nb_off[L]
                    for q in range(off, off + nb_len[L]):
                        nd = buf[q]
                        if t_isword[nd] and (best < 0 or nd < best):
                            best = nd
                    if best >= 0:
                        if ne >= cap:
                            e_path, e_len, e_node = _grow(e_path, e_len, e_node, cap)
                            cap *= 2
                        for q in range(length):
                            e_path[ne, q] = path[q]
                        e_len[ne] = length
                        e_node[ne] = best
                        ne += 1
                if length >= max_len:
                    L -= 1
                    continue
                f_mn[L] = _moves(f_idx[L], vis, f_inv[L], all_allowed, portal, moon_off, moon_dat, prim_off, prim_dat, mv[L])
                f_mi[L] = 0
            elif budget < 0:  # back from a child
                L -= 1
                continue
            length = L + 1
            pushed = False
            while f_mi[L] < f_mn[L]:
                nxt = mv[L, f_mi[L]]
                f_mi[L] += 1
                n_last = f_last[L]
                n_hasl = f_hasl[L]
                n_asc = f_asc[L]
                if is_num[nxt]:
                    nv = num_val[nxt]
                    n_asc = n_asc and ((not n_hasl) or nv > n_last)
                    n_last = nv
                    n_hasl = True
                a_idx = (nxt * D + length) * 2 + (1 if (n_asc or not ngu) else 0)
                wild = m_wild[a_idx]
                mask = m_mask[a_idx]
                off = nb_off[L]
                ln = nb_len[L]
                out0 = off + ln
                if wild:
                    tot = 0
                    for q in range(off, off + ln):
                        tot += t_counts[buf[q]]
                    need = out0 + tot
                else:
                    pc = 0
                    for code in range(26):
                        if (mask >> code) & 1:
                            pc += 1
                    need = out0 + ln * pc
                if need > buf.shape[0]:
                    b2 = np.empty(max(need, buf.shape[0] * 2), dtype=np.int32)
                    b2[:out0] = buf[:out0]
                    buf = b2
                m = 0
                if wild:
                    for q in range(off, off + ln):
                        nd = buf[q]
                        s = t_starts[nd]
                        for k in range(s, s + t_counts[nd]):
                            buf[out0 + m] = t_childs[k]
                            m += 1
                else:  # per letter, then per node: _np_advance's order
                    for code in range(26):
                        if (mask >> code) & 1:
                            for q in range(off, off + ln):
                                ch = _child(t_starts, t_counts, t_childs, t_keys, buf[q], code)
                                if ch >= 0:
                                    buf[out0 + m] = ch
                                    m += 1
                if m == 0:
                    continue
                L2 = L + 1
                nb_off[L2] = out0
                nb_len[L2] = m
                path[L2] = nxt
                f_idx[L2] = nxt
                f_vis[L2] = f_vis[L] | (one << np.uint64(nxt))
                f_inv[L2] = f_inv[L] | inv_bit[nxt]
                f_last[L2] = n_last
                f_hasl[L2] = n_hasl
                f_asc[L2] = n_asc
                L = L2
                entering = True
                pushed = True
                break
            if not pushed:
                L -= 1
        if budget < 0:
            break
    return e_path[:ne], e_len[:ne], e_node[:ne], budget


@nb.njit(cache=True)
def _adv_kernel(starts, counts, childs, edge_keys, nodes, wild, mask):
    n = nodes.shape[0]
    if wild:
        tot = 0
        for q in range(n):
            tot += counts[nodes[q]]
        out = np.empty(tot, dtype=np.int32)
        m = 0
        for q in range(n):
            s = starts[nodes[q]]
            for k in range(s, s + counts[nodes[q]]):
                out[m] = childs[k]
                m += 1
        return out
    pc = 0
    for code in range(26):
        if (mask >> code) & 1:
            pc += 1
    out = np.empty(n * pc, dtype=np.int32)
    m = 0
    for code in range(26):
        if (mask >> code) & 1:
            for q in range(n):
                ch = _child(starts, counts, childs, edge_keys, nodes[q], code)
                if ch >= 0:
                    out[m] = ch
                    m += 1
    return out[:m]


# ----------------------------------------------------------------------------- tables


def _mask(codes: bytes) -> int:
    m = _MASKS.get(codes)
    if m is None:
        m = 0
        for c in codes:
            m |= 1 << (c - 97)
        _MASKS[codes] = m
    return m


_MASKS: dict[bytes, int] = {}


def tables(search, inv):
    """Static kernel inputs for (search, inv), or None when the kernels cannot be exact."""
    cache = search.__dict__.setdefault("_jit_tables", {})
    key = (id(inv), search.max_len, search.honeypot)
    hit = cache.get(key)
    if hit is not None:
        return hit[1]
    res = _build_tables(search, inv)
    cache[key] = (inv, res)  # holds inv so its id stays unique
    return res


def _build_tables(search, inv):
    tiles = search.tiles
    T = len(tiles)
    if T > 64 or search.honeypot:
        return None
    inv_bit = np.zeros(T, dtype=np.int64)
    if search.super_inv.classes - search.base_inv.classes:
        # Movement follows inventory_for(path): one table per subset of the board's item classes.
        rel = S._MOVE_CLASSES | S._LETTER_CLASSES
        tile_cls = {t.idx: S.ITEMS[t.item].cls for t in tiles
                    if t.glyph == G_ITEM and t.item in S.ITEMS and S.ITEMS[t.item].cls in rel}
        classes = sorted(set(tile_cls.values()))
        if len(classes) > 5:
            return None
        bit = {c: 1 << k for k, c in enumerate(classes)}
        for i, c in tile_cls.items():
            inv_bit[i] = bit[c]
        invs = []
        for m in range(1 << len(classes)):
            cs = frozenset(c for c in classes if m & bit[c])
            iv = search._inv_cache.get(cs)
            if iv is None:
                iv = S._Inventory(search.plan, cs)
                search._inv_cache[cs] = iv
            invs.append(iv)
    else:
        invs = [search.base_inv]
    tabs = [search.move_tables(iv) for iv in invs]
    D = max(1, search.max_len)
    ngu = bool(inv.number_go_up)
    m_wild = np.zeros(T * D * 2, dtype=np.bool_)
    m_mask = np.zeros(T * D * 2, dtype=np.int64)
    depth_inv = inv.flamingo_first is not None or inv.microscope
    for i, t in enumerate(tiles):
        sens = depth_inv or t.glyph in (G_NUMBER, G_FRACTION)
        for asc in ((False, True) if ngu else (True,)):
            base = None
            for d in range(D):
                if base is None or sens:
                    wild, codes, tokens = search._matcher(t, d, inv, asc if ngu else None)
                    if tokens:
                        return None
                    base = (wild, _mask(codes))
                for a in ((1,) if asc else (0,)) if ngu else (0, 1):
                    m_wild[(i * D + d) * 2 + a] = base[0]
                    m_mask[(i * D + d) * 2 + a] = base[1]
    NT = len(tabs)

    def csr(which):
        off = np.zeros((NT, T + 1), dtype=np.int64)
        dat: list[int] = []
        for ti, tb in enumerate(tabs):
            lists = tb[which]
            for i in range(T):
                off[ti, i] = len(dat)
                dat.extend(lists[i])
            off[ti, T] = len(dat)
        return off, np.array(dat, dtype=np.int32)

    moon_off, moon_dat = csr(1)
    prim_off, prim_dat = csr(2)
    return (
        np.array(search._available_allowed, dtype=np.int32),
        np.array([tb[0] for tb in tabs], dtype=np.bool_).reshape(NT, T),
        moon_off, moon_dat, prim_off, prim_dat, m_wild, m_mask, D, ngu,
        np.array([t.is_number() for t in tiles], dtype=np.bool_),
        np.array([t.number_float() if t.is_number() else 0.0 for t in tiles], dtype=np.float64),
    ), T, inv_bit


def _trie_args(trie):
    a = S._numpy_trie(trie)
    return a[0], a[1], a[2], a[3], a[4]


# node -> spelling per trie (identity-checked: ids of freed tries get reused)
_SPELL: dict[int, tuple] = {}


def _spell_cache(trie) -> dict:
    hit = _SPELL.get(id(trie))
    if hit is None or hit[0] is not trie:
        if len(_SPELL) > 16:
            _SPELL.clear()
        hit = _SPELL[id(trie)] = (trie, {})
    d = hit[1]
    if len(d) > 500_000:
        d.clear()
    return d


def _emits(trie, ep, el, en):
    """Kernel emits -> {path: spelling}, first emit of a path wins."""
    found: dict[tuple[int, ...], str] = {}
    if len(en):
        arrays = S._numpy_trie(trie)
        spell = _spell_cache(trie)
        for p, ln, nd in zip(ep.tolist(), el.tolist(), en.tolist()):
            key = tuple(p[:ln])
            if key in found:
                continue
            w = spell.get(nd)
            if w is None:
                w = spell[nd] = S._np_spell(arrays, nd)
            found[key] = w
    return found


def _pickup(require_pickup) -> np.uint64:
    m = 0
    for i in require_pickup:
        m |= 1 << i
    return np.uint64(m)


# ----------------------------------------------------------------------------- entry points


def letter_enum(search, inv, require_pickup, starts, node_budget):
    """``ExactSearch.enumerate`` (no deadline), or None when the kernel cannot be exact."""
    tab = tables(search, inv)
    if tab is None:
        return None
    args, T, inv_bit = tab
    start_tiles = search._available_allowed if starts is None else starts
    budget0 = search.exhaustive_node_budget if node_budget is None else node_budget
    ep, el, en, budget, calls = _letter_dfs(
        *_trie_args(search.trie), np.array(start_tiles, dtype=np.int32), *args,
        search.min_len, max(1, search.max_len), _pickup(require_pickup), budget0, T, inv_bit)
    stats = search.stats
    stats.nodes += int(calls)
    found = _emits(search.trie, ep, el, en)
    exhaustive = int(budget) >= 0
    stats.extra["exhaustive"] = exhaustive
    stats.timed_out = not exhaustive
    stats.paths = len(found)
    return found


def subset_enum(search, inv, require_pickup, starts, path_budget):
    """``ExactSearch.enumerate_subsets`` (no deadline), or None when the kernel cannot be exact."""
    tab = tables(search, inv)
    if tab is None:
        return None
    args, T, inv_bit = tab
    if path_budget is None:
        path_budget = search.subset_path_budget
    start_list = search._available_allowed if starts is None else starts
    ep, el, en, budget = _subset_dfs(
        *_trie_args(search.trie), np.array(start_list, dtype=np.int32), *args,
        search.min_len, max(1, search.max_len), _pickup(require_pickup), path_budget, T, inv_bit)
    found = _emits(search.trie, ep, el, en)
    budget = int(budget)
    extra = search.stats.extra
    extra["subset_paths_visited"] = extra.get("subset_paths_visited", 0) + path_budget - budget
    return found, not (budget < 0)


def advance(arrays, nodes, wild: bool, codes: bytes):
    """``_np_advance`` without tokens (non-empty dictionary)."""
    out = _adv_kernel(arrays[0], arrays[1], arrays[2], arrays[3], nodes, wild, _mask(codes))
    return out if out.size else None
