# SWE-bench Verified generality check (frozen v1/v2 params; AST graph in place of the competition graph)

Run: GCP e2-standard-16, official SWE-bench images via Epoch AI GHCR mirror, tracer with the Python<3.11 qualname fix (commit 72f4770). Pytest repos only (Django and SymPy excluded: not pytest ids).


# SWE-bench Verified (pytest repos): 194 tasks, {'ok': 192, 'error': 1, 'no_gold_in_graph': 1}, with failing trace 172
repos: {'astropy/astropy': 22, 'matplotlib/matplotlib': 33, 'mwaskom/seaborn': 2, 'pallets/flask': 1, 'psf/requests': 8, 'pydata/xarray': 22, 'pylint-dev/pylint': 9, 'pytest-dev/pytest': 19, 'scikit-learn/scikit-learn': 32, 'sphinx-doc/sphinx': 44}
gold executed by a failing test: 153 / 172

| ranker | n | hit@1 | hit@5 | hit@10 | MRR |
|---|---|---|---|---|---|
| bm25 | 192 | 0.182 [0.12,0.24] | 0.438 [0.36,0.51] | 0.542 [0.47,0.61] | 0.294 [0.24,0.34] |
| ochiai_F | 172 | 0.029 [0.01,0.05] | 0.134 [0.08,0.19] | 0.203 [0.15,0.27] | 0.088 [0.06,0.12] |
| prfl_F | 172 | 0.105 [0.06,0.16] | 0.285 [0.22,0.35] | 0.360 [0.29,0.44] | 0.201 [0.15,0.25] |
| rwg_F_v1 | 172 | 0.273 [0.21,0.34] | 0.622 [0.55,0.69] | 0.709 [0.64,0.78] | 0.426 [0.37,0.49] |
| rwg_F_v2 | 172 | 0.320 [0.25,0.39] | 0.657 [0.58,0.73] | 0.762 [0.70,0.83] | 0.465 [0.41,0.53] |
| rwg_F_v2_nowalk | 172 | 0.337 [0.27,0.41] | 0.669 [0.59,0.73] | 0.767 [0.70,0.83] | 0.484 [0.43,0.54] |
| rwg_Rp | 182 | 0.110 [0.07,0.15] | 0.335 [0.27,0.40] | 0.412 [0.34,0.48] | 0.224 [0.18,0.27] |
| rwg_S | 192 | 0.161 [0.11,0.21] | 0.443 [0.37,0.52] | 0.573 [0.51,0.64] | 0.292 [0.24,0.34] |
| text | 192 | 0.188 [0.13,0.24] | 0.469 [0.40,0.54] | 0.573 [0.51,0.65] | 0.313 [0.26,0.37] |
| text+failure+prfl_F | 172 | 0.320 [0.25,0.40] | 0.634 [0.56,0.70] | 0.762 [0.70,0.83] | 0.466 [0.41,0.53] |
| text+prfl_F | 172 | 0.297 [0.23,0.37] | 0.616 [0.54,0.69] | 0.721 [0.65,0.78] | 0.437 [0.38,0.50] |

| paired (tasks with a failing trace) | n | hit@5 diff | 95% CI | P(diff<=0) |
|---|---|---|---|---|
| rwg_F_v1 vs text | 172 | +0.169 | [+0.087, +0.244] | 0.000 |
| rwg_F_v1 vs ochiai_F | 172 | +0.488 | [+0.413, +0.570] | 0.000 |
| rwg_F_v1 vs prfl_F | 172 | +0.337 | [+0.256, +0.419] | 0.000 |
| rwg_F_v1 vs text+prfl_F | 172 | +0.006 | [-0.029, +0.041] | 0.435 |
| rwg_F_v2 vs rwg_F_v1 | 172 | +0.035 | [-0.017, +0.087] | 0.110 |
| rwg_F_v2 vs text+failure+prfl_F | 172 | +0.023 | [-0.029, +0.076] | 0.205 |
| rwg_F_v2 vs rwg_F_v2_nowalk | 172 | -0.012 | [-0.035, +0.012] | 0.907 |
| rwg_S vs text | 192 | -0.026 | [-0.057, +0.000] | 0.980 |
| rwg_Rp vs text | 182 | -0.121 | [-0.187, -0.055] | 1.000 |

D1: 340028 executed repo->repo edges between AST-graph nodes; in AST precise 42.1%, in AST any kind 51.1%
missed causes: {'property_descriptor': '19.8%', 'dunder_protocol': '18.9%', 'attribute_dispatch': '16.2%', 'indirect_via_library': '13.3%', 'inheritance_dispatch': '7.6%', 'reflection': '7.2%', 'decorator_wrapper': '4.6%', 'implicit_constructor': '3.8%', 'callback_parameter': '2.6%', 'unresolved_name': '2.1%', 'import_time': '1.7%', 'callback_reference': '1.3%', 'runtime_import': '0.9%'}
per repo precise: {'astropy/astropy': '30.3% of 16102', 'matplotlib/matplotlib': '41.0% of 138488', 'mwaskom/seaborn': '64.3% of 406', 'pallets/flask': '35.5% of 296', 'psf/requests': '65.8% of 1767', 'pydata/xarray': '38.1% of 50662', 'pylint-dev/pylint': '61.7% of 11140', 'pytest-dev/pytest': '47.0% of 4687', 'scikit-learn/scikit-learn': '65.2% of 18445', 'sphinx-doc/sphinx': '40.5% of 98035'}
