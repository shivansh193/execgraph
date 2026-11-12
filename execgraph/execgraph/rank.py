"""Localisation rankers over competition node ids: RWG-PPR and the baselines it is compared with.

RWG-PPR (runtime-weighted code graph, personalised PageRank), in the HippoRAG pattern of seed -> graph walk:

1. Graph: one weighted directed graph over the competition's nodes with four edge types,
       static   competition `calls` edges (they also carry containment and inheritance)
       ast      precise edges from `static_ast` (resolved calls, constructors, self/super dispatch)
       runtime  caller -> callee pairs the tracer observed in the selected tests
       semantic k nearest neighbours by the provided code embeddings (cosine >= `sem_min`)
   every edge also gets a reverse edge at `reverse` times its weight: the fix can sit upstream or downstream.
2. Seeds (restart distribution): BM25 of the issue text over each node's id tokens and source, plus an
   exact-identifier bonus for names the issue quotes; with test evidence, multiplied by (1 + Ochiai).
3. Walk: personalised PageRank by power iteration; final score mixes the walk with the seeds (`mix`).

Evidence levels: S = static/ast/semantic only; R = + runtime edges and spectrum from existing tests near the
issue; F = + the real failing tests (an upper bound, since it uses the gold tests).
"""
import math
import random
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import numpy as np

from .ids import is_test_node

TOKEN = re.compile(r"[A-Za-z][a-z0-9]*|[A-Z]+(?![a-z])|\d+")
STOP = set("the a an of to in and or is are be it this that for on with as by at from not no but if then "
           "when should would could can will we i you they there their have has had was were do does did "
           "get set use used using also just like so any all some more most other into out up down".split())


def tokens(text):
    out = []
    for w in re.findall(r"[A-Za-z0-9_]+", text or ""):
        for p in w.split("_"):
            out += [t.lower() for t in TOKEN.findall(p)]
    return [t for t in out if len(t) > 1 and t not in STOP]


def quoted_identifiers(issue):
    """Identifiers the issue names explicitly: `code`, dotted.paths, CamelCase, snake_case, name()."""
    ids = set(re.findall(r"`([A-Za-z_][\w.]*)", issue or ""))
    ids |= set(re.findall(r"\b([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)\b", issue or ""))
    ids |= set(re.findall(r"\b([A-Z][a-z0-9]+(?:[A-Z][a-z0-9]*)+)\b", issue or ""))
    ids |= set(re.findall(r"\b([a-z0-9]+_[a-z0-9_]+)\b", issue or ""))
    ids |= set(re.findall(r"\b([A-Za-z_]\w*)\(", issue or ""))
    return {p for i in ids for p in i.split(".") if len(p) > 2}


class BM25:
    def __init__(self, docs: dict, k1=1.2, b=0.75):
        self.k1, self.b = k1, b
        self.tf = {k: Counter(v) for k, v in docs.items()}
        self.len = {k: len(v) for k, v in docs.items()}
        self.avg = sum(self.len.values()) / max(len(docs), 1)
        df = Counter(t for v in self.tf.values() for t in v)
        n = len(docs)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def scores(self, query_tokens):
        q = Counter(query_tokens)
        out = {}
        for k, tf in self.tf.items():
            s = 0.0
            for t, qn in q.items():
                f = tf.get(t)
                if f:
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.len[k] / self.avg))
            if s:
                out[k] = s
        return out


@dataclass
class Repo:
    """Everything static about one repo snapshot."""
    nodes: list                                  # competition node ids
    text: dict                                   # node id -> source text
    static_edges: list                           # competition edges
    ast_edges: list = field(default_factory=list)
    emb: object = None                           # np.ndarray [n, d], rows aligned with `nodes`, or None
    _bm25: object = None

    def bm25(self):
        if self._bm25 is None:
            self._bm25 = BM25({n: tokens(n) * 2 + tokens(self.text.get(n, "")[:4000]) for n in self.nodes})
        return self._bm25


@dataclass
class Evidence:
    """Test evidence for one task at one level."""
    runtime_edges: list = field(default_factory=list)
    failed: dict = field(default_factory=dict)   # node -> number of failing tests that ran it
    passed: dict = field(default_factory=dict)
    n_failed: int = 0
    crash_frames: list = field(default_factory=list)   # repo frames, outermost -> innermost
    direct: dict = field(default_factory=dict)         # node -> failing tests that call it straight from test code
    failure_text: str = ""                             # failing test ids, exception messages, failing source lines

    @classmethod
    def from_trace(cls, trace: dict, tests=None):
        """Evidence from a tracer JSON, optionally restricted to the test ids in `tests`."""
        ev = cls()
        edges = set()
        for tid, t in trace.get("tests", {}).items():
            if tests is not None and tid not in tests:
                continue
            edges |= {tuple(e) for e in t.get("edges") or t.get("calls") or []}
            if t["outcome"] == "failed":
                ev.n_failed += 1
                for n in t["funcs"]:
                    ev.failed[n] = ev.failed.get(n, 0) + 1
                for n in t.get("direct", []):
                    ev.direct[n] = ev.direct.get(n, 0) + 1
            elif t["outcome"] == "passed":
                for n in t["funcs"]:
                    ev.passed[n] = ev.passed.get(n, 0) + 1
        ev.runtime_edges = sorted(edges)
        text = []
        for f in trace.get("failures", []):
            if tests is None or f["test"] in tests:
                ev.crash_frames += [fr["node"] for fr in f.get("frames", [])]
                if f.get("type") != "CollectionError":
                    text.append(f["test"].split("::")[-1])
                text.append(f"{f.get('type', '')} {f.get('message', '')}")
                text += [fr.get("src", "") for fr in f.get("frames", [])]
        ev.failure_text = "\n".join(text)
        return ev


def with_contrast(ev: Evidence, other: Evidence):
    """Failing-test evidence plus passing tests from another trace (e.g. level R) as extra Ochiai contrast:
    with one failing test and few passing ones, every function the failing test ran ties."""
    if other is None:
        return ev
    passed = dict(ev.passed)
    for n, c in other.passed.items():
        passed[n] = passed.get(n, 0) + c
    return Evidence(runtime_edges=sorted(set(ev.runtime_edges) | set(other.runtime_edges)), failed=ev.failed,
                    passed=passed, n_failed=ev.n_failed, crash_frames=ev.crash_frames, direct=ev.direct,
                    failure_text=ev.failure_text)


def pseudo_spectrum(trace: dict, issue: str, top=3):
    """Evidence from passing tests only (level R): the `top` tests whose ids best match the issue (BM25 over test
    name tokens) stand in for failing tests, the rest are the passing contrast. Ochiai over this split says which
    functions the issue-relevant tests exercise and the others don't."""
    tests = {tid: t for tid, t in trace.get("tests", {}).items() if t.get("outcome") in ("passed", "failed")}
    if not tests:
        return Evidence.from_trace(trace)
    scores = BM25({tid: tokens(tid.replace("::", " ").replace("/", " ")) for tid in tests}).scores(tokens(issue))
    rel = [tid for tid, s in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:top]]
    real_failed = {tid for tid, t in tests.items() if t["outcome"] == "failed"}
    chosen = set(rel) | real_failed
    relabelled = {"tests": {tid: {**t, "outcome": "failed" if tid in chosen else "passed"} for tid, t in tests.items()},
                  "failures": trace.get("failures", [])}
    return Evidence.from_trace(relabelled)


def normalise(d):
    m = max(d.values(), default=0)
    return {k: v / m for k, v in d.items()} if m > 0 else {}


def ochiai(ev: Evidence):
    if not ev.n_failed:
        return {}
    out = {}
    for n, ef in ev.failed.items():
        ep = ev.passed.get(n, 0)
        out[n] = ef / math.sqrt(ev.n_failed * (ef + ep))
    return out


def text_seeds(repo: Repo, issue: str, exact_bonus=1.0):
    s = normalise(repo.bm25().scores(tokens(issue)))
    names = quoted_identifiers(issue)
    if names:
        for n in repo.nodes:
            parts = n.split(".")
            hit = sum(p in names for p in parts[-2:])
            if hit:
                s[n] = s.get(n, 0) + exact_bonus * hit / 2
    return s


def failure_seeds(repo: Repo, ev: Evidence, exec_only=True):
    """Seeds from what the failure itself says: names in the assertion / exception message, the failing source
    lines and the failing test's name. Exact identifier matches score 1, BM25 matches are normalised to <= 0.5.
    With `exec_only`, only functions the failing tests ran, or whose short name the failure text mentions, count:
    the message names an entry point, the walk carries the score to its executed callees."""
    text = ev.failure_text
    names = quoted_identifiers(text) | {w for w in re.findall(r"[A-Za-z_]\w{2,}", text) if "_" in w or w[0].isupper()}
    out = {}
    for n in repo.nodes:
        if is_test_node(n):
            continue
        parts = n.split(".")
        if parts[-1] in names or (len(parts) > 1 and parts[-2] in names and parts[-1] == "__init__"):
            out[n] = 1.0
    for n, s in normalise(repo.bm25().scores(tokens(text))).items():
        if not is_test_node(n):
            out[n] = max(out.get(n, 0), 0.5 * s)
    if exec_only:
        ran = set(ev.failed)
        out = {n: s for n, s in out.items() if n in ran or s >= 1.0}
    return out


def semantic_edges(repo: Repo, k=5, sem_min=0.5):
    if repo.emb is None:
        return []
    e = repo.emb / (np.linalg.norm(repo.emb, axis=1, keepdims=True) + 1e-9)
    out = []
    for i0 in range(0, len(e), 1024):
        sims = e[i0:i0 + 1024] @ e.T
        for r, row in enumerate(sims):
            i = i0 + r
            row[i] = -1
            top = np.argpartition(-row, k)[:k]
            out += [(repo.nodes[i], repo.nodes[j], float(row[j])) for j in top if row[j] >= sem_min]
    return out


@dataclass
class Params:
    w_static: float = 1.0
    w_ast: float = 1.0
    w_runtime: float = 3.0
    w_sem: float = 0.5
    sem_k: int = 5
    sem_min: float = 0.5
    reverse: float = 0.7
    alpha: float = 0.3          # restart probability
    mix: float = 0.5            # final = mix * walk + (1 - mix) * seed
    exact_bonus: float = 1.0
    spectrum: bool = True
    iters: int = 50
    pseudo_top: int = 3         # level R: issue-relevant tests treated as failing
    w_fail: float = 0.0         # weight of seeds from the failure's own text (messages, failing lines, test names)
    fail_exec_only: bool = True # failure seeds only on functions the failing tests executed (or names they call)


def ppr(nodes, edges, seeds, alpha, iters):
    """Personalised PageRank; `edges` = [(src, dst, w)]. Dangling mass returns to the seeds."""
    idx = {n: i for i, n in enumerate(nodes)}
    n = len(nodes)
    p = np.zeros(n)
    for k, v in seeds.items():
        if k in idx:
            p[idx[k]] += v
    if p.sum() == 0:
        return {}
    p /= p.sum()
    src = np.array([idx[a] for a, b, w in edges], dtype=np.int64)
    dst = np.array([idx[b] for a, b, w in edges], dtype=np.int64)
    w = np.array([w for a, b, w in edges], dtype=float)
    out_w = np.bincount(src, weights=w, minlength=n)
    wn = w / np.where(out_w[src] > 0, out_w[src], 1)
    dangling = out_w == 0
    x = p.copy()
    for _ in range(iters):
        nxt = np.bincount(dst, weights=x[src] * wn, minlength=n)
        nxt = (1 - alpha) * (nxt + x[dangling].sum() * p) + alpha * p
        if np.abs(nxt - x).sum() < 1e-9:
            x = nxt
            break
        x = nxt
    return {nodes[i]: float(x[i]) for i in np.nonzero(x)[0]}


def rwg_ppr(repo: Repo, issue: str, ev: Evidence = None, prm: Params = Params(), sem=None, scores=False):
    nodes = list(repo.nodes)
    known = set(nodes)
    raw = defaultdict(float)

    def add(a, b, w):
        if a in known and b in known and a != b and w > 0:
            raw[(a, b)] += w
            raw[(b, a)] += w * prm.reverse

    for a, b in repo.static_edges:
        add(a, b, prm.w_static)
    for a, b in repo.ast_edges:
        add(a, b, prm.w_ast)
    for a, b, s in (sem if sem is not None else semantic_edges(repo, prm.sem_k, prm.sem_min)):
        add(a, b, prm.w_sem * s)
    seeds = text_seeds(repo, issue, prm.exact_bonus)
    if ev is not None and prm.w_fail and ev.failure_text:
        fs = failure_seeds(repo, ev, prm.fail_exec_only)
        seeds = {n: seeds.get(n, 0) + prm.w_fail * fs.get(n, 0) for n in set(seeds) | set(fs)}
    if ev is not None:
        for a, b in ev.runtime_edges:
            add(a, b, prm.w_runtime)
        if prm.spectrum and ev.n_failed:
            och = ochiai(ev)
            # executed-on-failure functions get a floor so a failing path with no text match still seeds
            seeds = {n: (seeds.get(n, 0) + 0.05) * (1 + 2 * och.get(n, 0)) if n in och else seeds.get(n, 0) * 0.5
                     for n in set(seeds) | set(och)}
    seeds = {k: v for k, v in normalise(seeds).items() if v > 0}
    walk = normalise(ppr(nodes, [(a, b, w) for (a, b), w in raw.items()], seeds, prm.alpha, prm.iters))
    score = {n: prm.mix * walk.get(n, 0) + (1 - prm.mix) * seeds.get(n, 0) for n in set(walk) | set(seeds)}
    if scores:
        return walk, score
    return order(score)


# ---- baselines ---------------------------------------------------------------------------------------------
def order(score: dict):
    return [n for n, s in sorted(score.items(), key=lambda kv: (-kv[1], kv[0])) if s > 0 and not is_test_node(n)]


def rank_random(repo: Repo, seed=0):
    nodes = [n for n in repo.nodes if not is_test_node(n)]
    random.Random(seed).shuffle(nodes)
    return nodes


def rank_bm25(repo: Repo, issue: str):
    return order(repo.bm25().scores(tokens(issue)))


def rank_text(repo: Repo, issue: str, exact_bonus=1.0):
    return order(text_seeds(repo, issue, exact_bonus))


def rank_embedding(repo: Repo, issue: str, anchors=5):
    """No query embedding exists offline, so the issue enters through its top BM25 nodes: rank by mean cosine
    to those anchors (how the harness's own search_similar_code is meant to be used)."""
    if repo.emb is None:
        return []
    top = rank_text(repo, issue)[:anchors]
    if not top:
        return []
    idx = {n: i for i, n in enumerate(repo.nodes)}
    e = repo.emb / (np.linalg.norm(repo.emb, axis=1, keepdims=True) + 1e-9)
    q = e[[idx[n] for n in top]].mean(0)
    sims = e @ q
    return order({n: float(sims[i]) + 1 for n, i in idx.items()})


def rank_khop(repo: Repo, issue: str, hops=2, decay=0.5, anchors=10):
    """Static neighbourhood of the text seeds, no walk: score = seed * decay^distance (best path)."""
    adj = defaultdict(set)
    for a, b in list(repo.static_edges) + list(repo.ast_edges):
        adj[a].add(b)
        adj[b].add(a)
    seeds = text_seeds(repo, issue)
    best = {}
    for s, v in sorted(seeds.items(), key=lambda kv: -kv[1])[:anchors]:
        frontier, seen = {s}, {s}
        for h in range(hops + 1):
            for n in frontier:
                best[n] = max(best.get(n, 0), v * decay ** h)
            frontier = {m for n in frontier for m in adj[n]} - seen
            seen |= frontier
    for s, v in seeds.items():
        best[s] = max(best.get(s, 0), v)
    return order(best)


def rank_ochiai(ev: Evidence):
    return order(ochiai(ev))


def rank_crash(ev: Evidence):
    """Repo frames of the failure, innermost first: what 'read the stack trace' gives."""
    seen = list(dict.fromkeys(reversed(ev.crash_frames)))
    return [n for n in seen if not is_test_node(n)]


def prfl_scores(repo: Repo, ev: Evidence, alpha=0.15):
    """PRFL-style (Zhang et al., ISSTA 2017), simplified: PageRank over the executed call graph seeded by
    failing-test coverage, then multiplied with the Ochiai score. No issue text."""
    och = ochiai(ev)
    if not och:
        return {}
    nodes = sorted(set(repo.nodes) | {x for e in ev.runtime_edges for x in e})
    pr = ppr(nodes, [(a, b, 1.0) for a, b in ev.runtime_edges] + [(b, a, 1.0) for a, b in ev.runtime_edges],
             {n: 1.0 for n in ev.failed}, alpha, 50)
    pr = normalise(pr)
    return {n: s * (1 + pr.get(n, 0)) for n, s in och.items()}


def rank_prfl(repo: Repo, ev: Evidence, alpha=0.15):
    return order(prfl_scores(repo, ev, alpha))


def rank_fused(repo: Repo, issue: str, spectrum: dict, w=1.0, exact_bonus=1.0):
    """Same-information baseline: normalised text score + w * normalised spectrum score, no graph walk."""
    t, s = normalise(text_seeds(repo, issue, exact_bonus)), normalise(spectrum)
    return order({n: t.get(n, 0) + w * s.get(n, 0) for n in set(t) | set(s)})


def rank_test_files(repo: Repo, ev: Evidence):
    """Sanity baseline: functions the failing tests call directly (the API under test), by failing count."""
    return order(dict(ev.direct))
