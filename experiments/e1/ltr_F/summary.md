level F: 106 tasks, 23718 candidates; gold reachable in candidates for 105

| ranker (5-fold CV over tasks) | n | hit@1 | hit@5 | hit@10 | MRR |
|---|---|---|---|---|---|
| rwg (no learning) | 106 | 0.406 [0.31,0.50] | 0.783 [0.70,0.86] | 0.858 [0.79,0.92] | 0.555 [0.48,0.63] |
| text (no learning) | 106 | 0.208 [0.14,0.28] | 0.472 [0.38,0.57] | 0.528 [0.43,0.62] | 0.331 [0.27,0.40] |
| text+prfl (no learning) | 106 | 0.321 [0.24,0.41] | 0.660 [0.57,0.75] | 0.764 [0.68,0.85] | 0.475 [0.40,0.55] |
| rwg_frozen (no learning) | 106 | 0.396 [0.31,0.49] | 0.670 [0.58,0.75] | 0.783 [0.70,0.86] | 0.527 [0.45,0.60] |
| LTR all features | 106 | 0.425 [0.33,0.52] | 0.802 [0.72,0.88] | 0.840 [0.76,0.91] | 0.571 [0.50,0.64] |
| LTR without text | 106 | 0.377 [0.29,0.46] | 0.726 [0.64,0.80] | 0.830 [0.75,0.90] | 0.526 [0.45,0.60] |
| LTR without failure | 106 | 0.434 [0.34,0.53] | 0.755 [0.67,0.83] | 0.821 [0.75,0.89] | 0.563 [0.49,0.64] |
| LTR without spectrum | 106 | 0.425 [0.33,0.52] | 0.792 [0.72,0.87] | 0.858 [0.79,0.92] | 0.579 [0.51,0.65] |
| LTR without graph | 106 | 0.434 [0.34,0.53] | 0.745 [0.66,0.82] | 0.858 [0.78,0.92] | 0.568 [0.49,0.64] |
| LTR without node | 106 | 0.425 [0.33,0.52] | 0.717 [0.63,0.80] | 0.811 [0.74,0.88] | 0.537 [0.46,0.61] |

| paired vs LTR all (hit@5, CV) | diff | 95% CI | P(diff<=0) |
|---|---|---|---|
| LTR all - rwg | +0.019 | [-0.047,+0.085] | 0.331 |
| LTR all - text | +0.330 | [+0.236,+0.434] | 0.000 |
| LTR all - text+prfl | +0.142 | [+0.057,+0.226] | 0.001 |
| LTR all - rwg_frozen | +0.132 | [+0.057,+0.217] | 0.001 |
| LTR all - LTR without text | +0.075 | [+0.019,+0.132] | 0.004 |
| LTR all - LTR without failure | +0.047 | [+0.009,+0.094] | 0.006 |
| LTR all - LTR without spectrum | +0.009 | [-0.019,+0.047] | 0.399 |
| LTR all - LTR without graph | +0.057 | [+0.000,+0.113] | 0.032 |
| LTR all - LTR without node | +0.085 | [+0.038,+0.142] | 0.000 |

train on tune (36), test on eval (70):
| ranker | n | hit@1 | hit@5 | hit@10 | MRR |
|---|---|---|---|---|---|
| LTR all features | 70 | 0.457 [0.34,0.57] | 0.700 [0.59,0.80] | 0.871 [0.79,0.94] | 0.570 [0.48,0.67] |
| rwg (no learning) | 70 | 0.414 [0.30,0.54] | 0.771 [0.67,0.87] | 0.843 [0.74,0.93] | 0.549 [0.46,0.65] |
| text (no learning) | 70 | 0.186 [0.10,0.29] | 0.429 [0.31,0.54] | 0.514 [0.40,0.63] | 0.309 [0.23,0.40] |
| text+prfl (no learning) | 70 | 0.329 [0.23,0.44] | 0.643 [0.53,0.76] | 0.757 [0.66,0.86] | 0.474 [0.38,0.57] |
| rwg_frozen (no learning) | 70 | 0.371 [0.26,0.49] | 0.643 [0.53,0.76] | 0.757 [0.66,0.86] | 0.499 [0.41,0.60] |

feature importance (split counts, all tasks): n_len 356, g_emb 288, t_seed 264, t_bm25 257, g_walk_static 253, g_walk 223, g_deg_static 196, f_seed 179, s_ochiai 163, s_ep 138, g_hops_seed 125, g_deg_runtime 112, g_hops_crash 59, s_crash 48, s_ef 36, n_private 28, n_main_pkg 25, n_class 21, s_direct 10, n_dunder 10, t_exact 8, s_exec_fail 1