"""Localisation metrics with task-level bootstrap CIs."""
import random


def first_hit(ranking, gold):
    for i, n in enumerate(ranking):
        if n in gold:
            return i + 1
    return None


def hit_at(ranking, gold, k):
    return float(any(n in gold for n in ranking[:k]))


def task_metrics(ranking, gold, ks=(1, 5, 10)):
    r = first_hit(ranking, gold)
    out = {f"hit@{k}": hit_at(ranking, gold, k) for k in ks}
    out["mrr"] = 1.0 / r if r else 0.0
    out["rank"] = r
    return out


def bootstrap(values, n=2000, seed=0, level=0.95):
    """Mean and percentile CI of per-task values."""
    vals = [v for v in values if v is not None]
    if not vals:
        return (None, None, None)
    rng = random.Random(seed)
    means = sorted(sum(rng.choice(vals) for _ in vals) / len(vals) for _ in range(n))
    lo, hi = means[int((1 - level) / 2 * n)], means[int((1 + level) / 2 * n) - 1]
    return (sum(vals) / len(vals), lo, hi)


def paired_bootstrap(a, b, n=2000, seed=0):
    """Mean difference a - b over tasks scored by both, with a 95% CI and the share of resamples where a <= b."""
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if not pairs:
        return (None, None, None, None)
    rng = random.Random(seed)
    diffs = sorted(sum(x - y for x, y in (rng.choice(pairs) for _ in pairs)) / len(pairs) for _ in range(n))
    mean = sum(x - y for x, y in pairs) / len(pairs)
    p = sum(d <= 0 for d in diffs) / n
    return (mean, diffs[int(0.025 * n)], diffs[int(0.975 * n) - 1], p)
