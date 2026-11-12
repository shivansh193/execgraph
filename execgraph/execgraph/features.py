"""Per-candidate features for learned localisation (learning to rank over text, spectrum and graph signals).

Candidates for a task: the union of the top-K functions by text, by failure-text, by Ochiai and by the RWG walk,
so a candidate set has a few hundred nodes at most. Feature groups, so ablations can drop one group at a time:

    text      issue BM25 (normalised), exact identifier hit, text-seed score
    failure   failure-text seed score (message, failing lines, test names)
    spectrum  Ochiai, executed by a failing test, failing/passing counts, called directly by a failing test,
              crash-frame rank
    graph     RWG walk score (all edges), walk without runtime edges, hops from the nearest text/failure seed and
              from the crash frames over static+runtime edges, static and runtime degree, embedding similarity to
              the top text seed
    node      is a class, dunder, private, in the main package (vs docs/examples/scripts), source length
"""
import math
import re
from collections import deque

import numpy as np

from . import rank

GROUPS = {
    "text": ["t_bm25", "t_exact", "t_seed"],
    "failure": ["f_seed"],
    "spectrum": ["s_ochiai", "s_exec_fail", "s_ef", "s_ep", "s_direct", "s_crash"],
    "graph": ["g_walk", "g_walk_static", "g_hops_seed", "g_hops_crash", "g_deg_static", "g_deg_runtime", "g_emb"],
    "node": ["n_class", "n_dunder", "n_private", "n_main_pkg", "n_len"],
}
FEATURES = [f for g in GROUPS.values() for f in g]


def _bfs(adj, starts, limit=6):
    dist = {s: 0 for s in starts}
    q = deque(starts)
    while q:
        n = q.popleft()
        if dist[n] >= limit:
            continue
        for m in adj.get(n, ()):
            if m not in dist:
                dist[m] = dist[n] + 1
                q.append(m)
    return dist


def task_features(repo: rank.Repo, issue: str, ev: rank.Evidence, prm: rank.Params, sem, main_pkg: str, k=150):
    nodes = set(repo.nodes)
    bm = rank.normalise(repo.bm25().scores(rank.tokens(issue)))
    names = rank.quoted_identifiers(issue)
    tseed = rank.normalise(rank.text_seeds(repo, issue, prm.exact_bonus))
    fseed = rank.failure_seeds(repo, ev) if ev is not None and ev.failure_text else {}
    och = rank.ochiai(ev) if ev is not None else {}
    walk = rank.normalise(rank.rwg_ppr(repo, issue, ev, prm, sem, scores=True)[0])
    walk_static = rank.normalise(rank.rwg_ppr(repo, issue, rank.Evidence(
        failed=ev.failed, passed=ev.passed, n_failed=ev.n_failed, failure_text=ev.failure_text) if ev else None,
        prm, sem, scores=True)[0])
    cands = set()
    for d in (tseed, fseed, och, walk):
        cands |= set(rank.order(d)[:k])
    cands = {c for c in cands if c in nodes}

    adj_s, adj_r = {}, {}
    for a, b in list(repo.static_edges) + list(repo.ast_edges):
        adj_s.setdefault(a, set()).add(b)
        adj_s.setdefault(b, set()).add(a)
    for a, b in (ev.runtime_edges if ev else []):
        adj_r.setdefault(a, set()).add(b)
        adj_r.setdefault(b, set()).add(a)
    adj = {n: adj_s.get(n, set()) | adj_r.get(n, set()) for n in set(adj_s) | set(adj_r)}
    seeds = [n for n in rank.order({**tseed, **{k2: v for k2, v in fseed.items() if v >= 1.0}})[:10]]
    d_seed = _bfs(adj, seeds) if seeds else {}
    crash = [n for n in reversed(ev.crash_frames) if not rank.is_test_node(n)][:1] if ev else []
    d_crash = _bfs(adj, crash) if crash else {}
    crash_rank = {n: i for i, n in enumerate(rank.rank_crash(ev))} if ev else {}

    emb_sim = {}
    if repo.emb is not None and tseed:
        idx = {n: i for i, n in enumerate(repo.nodes)}
        top = [n for n in rank.order(tseed)[:3] if n in idx]
        if top:
            e = repo.emb / (np.linalg.norm(repo.emb, axis=1, keepdims=True) + 1e-9)
            q = e[[idx[n] for n in top]].mean(0)
            for c in cands:
                emb_sim[c] = float(e[idx[c]] @ q)

    rows = []
    for c in sorted(cands):
        parts = c.split(".")
        rows.append({
            "node": c,
            "t_bm25": bm.get(c, 0.0), "t_exact": float(any(p in names for p in parts[-2:])), "t_seed": tseed.get(c, 0.0),
            "f_seed": fseed.get(c, 0.0),
            "s_ochiai": och.get(c, 0.0), "s_exec_fail": float(bool(ev and c in ev.failed)),
            "s_ef": float(ev.failed.get(c, 0)) if ev else 0.0, "s_ep": math.log1p(ev.passed.get(c, 0)) if ev else 0.0,
            "s_direct": float(bool(ev and c in ev.direct)),
            "s_crash": 1.0 / (1 + crash_rank[c]) if c in crash_rank else 0.0,
            "g_walk": walk.get(c, 0.0), "g_walk_static": walk_static.get(c, 0.0),
            "g_hops_seed": 1.0 / (1 + d_seed[c]) if c in d_seed else 0.0,
            "g_hops_crash": 1.0 / (1 + d_crash[c]) if c in d_crash else 0.0,
            "g_deg_static": math.log1p(len(adj_s.get(c, ()))), "g_deg_runtime": math.log1p(len(adj_r.get(c, ()))),
            "g_emb": emb_sim.get(c, 0.0),
            "n_class": float(parts[-1][:1].isupper()), "n_dunder": float(parts[-1].startswith("__")),
            "n_private": float(parts[-1].startswith("_") and not parts[-1].startswith("__")),
            "n_main_pkg": float(parts[0] == main_pkg), "n_len": math.log1p(len(repo.text.get(c, ""))),
        })
    return rows
