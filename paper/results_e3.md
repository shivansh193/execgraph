| run | solved | with patch | median tool calls | errors |
|---|---|---|---|---|
| 31b-goldfile | 16/41 | 29 | 24 | 9 |
| 31b-none | 14/41 | 30 | 27 | 3 |
| 31b-rwgF | 14/41 | 32 | 27 | 8 |
| e4b-goldfile | 5/41 | 39 | 8 | 0 |
| e4b-none | 2/41 | 36 | 11 | 0 |

| model | arm vs none | solved | discordant (hint only : none only) | exact McNemar p | gained | lost |
|---|---|---|---|---|---|---|
| 31b | goldfile | 16 vs 14 /41 | 3:1 | 0.625 | fastapi_11194, fastapi_14430, rich_3278 | rich_3506 |
| 31b | rwgF | 14 vs 14 /41 | 2:2 | 1.000 | fastapi_14430, rich_3278 | fastapi_13207, fastapi_14851 |
| e4b | goldfile | 5 vs 2 /41 | 3:0 | 0.250 | fastapi_14616, fastapi_14851, requests_7309 |  |

## 31B by hint correctness (rwgF hint = RWG-PPR v2 top-5 with the failing tests)

37 of 41 dev tasks had an rwgF hint (4 had no failing-test trace and got none); 32 of the 37 hints contain a gold function.

| tasks | n | solved, no hint | solved, rwgF hint | solved, oracle files |
|---|---|---|---|---|
| hint contains a gold function | 32 | 12 | 12 | 12 |
| hint misses | 5 | 1 | 2 | 3 |
| no hint (no failing trace) | 4 | 1 | 0 | 1 |

Session timeouts (8 min): none 3, goldfile 9, rwgF 5 (+2 turn budget, +1 tool-call budget). The hint arms ran as
separate kernels at the same time as each other; the extra timeouts are not explained by the hint text alone.

Reading: a correct location in the prompt did not change 31B's fix rate on the tasks where it was correct (12 = 12).
For this agent and budget, localisation is not the bottleneck. E4B with oracle files: 2 -> 5 (3:0, p = 0.25).
The E4B rwgF, 31B rwg and all 12B arms were not run: the account's weekly GPU quota (30 h) ran out.
