# E1b: coverage-guided test retrieval (exploratory; kernel gda-e1b-full traces, scored by gda-analysis v4)

## split=eval: 78 tasks; an existing test runs a gold function in 75; a test_patch file already exists in 32
| test ranker | test@1 | test@3 | test@10 | file@1 | file@3 | file@10 |
|---|---|---|---|---|---|---|
| random (expected) | 0.236 | 0.407 | 0.615 | | | |
| name | 0.41 | 0.667 | 0.821 | 0.115 | 0.192 | 0.295 |
| file_R | 0.321 | 0.385 | 0.462 | 0.141 | 0.179 | 0.205 |
| cov | 0.615 | 0.731 | 0.846 | 0.038 | 0.051 | 0.09 |
| cov+name | 0.59 | 0.795 | 0.885 | 0.167 | 0.192 | 0.256 |

| localisation | n | hit@1 | hit@5 | hit@10 | MRR |
|---|---|---|---|---|---|
| rwg_R+cov | 78 | 0.141 | 0.308 | 0.423 | 0.23 |
| rwg_R+cov+name | 78 | 0.244 | 0.462 | 0.564 | 0.354 |
| rwg_R+name | 78 | 0.256 | 0.462 | 0.603 | 0.375 |
| rwg_Rp | 78 | 0.218 | 0.487 | 0.603 | 0.333 |
| rwg_S | 78 | 0.167 | 0.41 | 0.474 | 0.282 |
| text | 78 | 0.179 | 0.41 | 0.513 | 0.301 |
cov:test@3 - name:test@3 n=78: +0.064 [-0.038,+0.167] P<=0 0.141
cov+name:test@3 - name:test@3 n=78: +0.128 [+0.038,+0.218] P<=0 0.003
cov:test@3 - file_R:test@3 n=78: +0.346 [+0.218,+0.462] P<=0 0.000
cov+name:file@3 - name:file@3 n=78: +0.000 [-0.064,+0.064] P<=0 0.585
loc_rwg_R+cov+name:hit@5 - loc_text:hit@5 n=78: +0.051 [-0.038,+0.154] P<=0 0.177
loc_rwg_R+cov:hit@5 - loc_text:hit@5 n=78: -0.103 [-0.192,-0.026] P<=0 0.997
loc_rwg_R+cov+name:hit@5 - loc_rwg_Rp:hit@5 n=78: -0.026 [-0.141,+0.077] P<=0 0.718

## split=all: 116 tasks; an existing test runs a gold function in 111; a test_patch file already exists in 43
| test ranker | test@1 | test@3 | test@10 | file@1 | file@3 | file@10 |
|---|---|---|---|---|---|---|
| random (expected) | 0.215 | 0.393 | 0.614 | | | |
| name | 0.353 | 0.638 | 0.776 | 0.103 | 0.164 | 0.233 |
| file_R | 0.293 | 0.388 | 0.448 | 0.121 | 0.164 | 0.181 |
| cov | 0.621 | 0.733 | 0.853 | 0.034 | 0.052 | 0.086 |
| cov+name | 0.569 | 0.793 | 0.888 | 0.129 | 0.164 | 0.216 |

| localisation | n | hit@1 | hit@5 | hit@10 | MRR |
|---|---|---|---|---|---|
| rwg_R+cov | 116 | 0.155 | 0.328 | 0.44 | 0.249 |
| rwg_R+cov+name | 116 | 0.241 | 0.466 | 0.586 | 0.363 |
| rwg_R+name | 116 | 0.276 | 0.491 | 0.612 | 0.39 |
| rwg_Rp | 116 | 0.241 | 0.483 | 0.595 | 0.351 |
| rwg_S | 116 | 0.19 | 0.448 | 0.517 | 0.304 |
| text | 116 | 0.207 | 0.457 | 0.526 | 0.327 |
cov:test@3 - name:test@3 n=116: +0.095 [+0.000,+0.198] P<=0 0.027
cov+name:test@3 - name:test@3 n=116: +0.155 [+0.078,+0.250] P<=0 0.001
cov:test@3 - file_R:test@3 n=116: +0.345 [+0.241,+0.448] P<=0 0.000
cov+name:file@3 - name:file@3 n=116: +0.000 [-0.043,+0.043] P<=0 0.594
loc_rwg_R+cov+name:hit@5 - loc_text:hit@5 n=116: +0.009 [-0.069,+0.078] P<=0 0.455
loc_rwg_R+cov:hit@5 - loc_text:hit@5 n=116: -0.129 [-0.207,-0.060] P<=0 1.000
loc_rwg_R+cov+name:hit@5 - loc_rwg_Rp:hit@5 n=116: -0.017 [-0.103,+0.069] P<=0 0.694

