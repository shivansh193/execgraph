
# ---------------------------------------------------------------- E1: localisation evidence for every task
# Appended by notebooks/e1/build.py after dev_eval.py's sections 1-3 (harness install, bundle, scorer-like env).
# Each task runs through the scorer's own verification with an empty agent patch (buggy code + test_patch).
# Two of its commands are intercepted:
#   - the first `git ls-tree` (workspace at base commit, env ready, test_patch not yet applied):
#     gold labels, AST call graph, and a trace of the 3 existing test files nearest the issue (level R);
#   - the scorer's pytest run on the task's test files: run under the tracer instead (level F).
EXECGRAPH_FILES = {}  # filled in by build.py
E1_TASK_SRC = ''      # filled in by build.py
TRACER_SRC = ''       # filled in by build.py
# build.py --agent: task id -> [{path, content, run}]; when set, only level A (agent-written repros) runs
AGENT_REPROS = {}     # filled in by build.py
# build.py --full: only E1b (each task's whole existing test suite) runs
FULL_SUITE = False    # filled in by build.py
E1_CONCURRENCY = int(os.environ.get('E1_CONCURRENCY', 4))

EG = WORK / 'eg'
for rel, text in EXECGRAPH_FILES.items():
    (EG / rel).parent.mkdir(parents=True, exist_ok=True)
    (EG / rel).write_text(text, encoding='utf-8')
(EG / 'e1_task.py').write_text(E1_TASK_SRC, encoding='utf-8')
TRACER = EG / '_tracer.py'
TRACER.write_text(TRACER_SRC, encoding='utf-8')
sys.path.insert(0, str(EG))
import e1_task

OUT = WORK / 'e1'
OUT.mkdir(exist_ok=True)
STATE = contextvars.ContextVar('e1_state', default=None)
_orig_exec = verification.sandbox_exec


class Runner:
    def __init__(self, docker, sid):
        self.docker, self.sid = docker, sid
        self.workspace = docker.exec(sid, 'cd /workspace && pwd -P').stdout.strip()

    def __call__(self, cmd, timeout):
        r = self.docker.exec(self.sid, f'cd /workspace && {cmd}', timeout=timeout)
        return r.exit_code, (r.stdout or '') + (getattr(r, 'stderr', '') or '')


async def hooked_exec(docker, sid, cmd, *a, **kw):
    st = STATE.get()
    if st is not None:
        if 'git ls-tree -r' in cmd and 'meta' not in st:
            try:
                run = Runner(docker, sid)
                if FULL_SUITE:
                    st['meta'] = {'full': await asyncio.to_thread(e1_task.level_full, run, run.workspace, TRACER,
                                                                   str(st['dir']))}
                elif AGENT_REPROS:
                    st['meta'] = {'A': await asyncio.to_thread(e1_task.level_agent, run, run.workspace,
                                                                AGENT_REPROS[st['task']['instance_id']], TRACER,
                                                                str(st['dir']))}
                else:
                    st['meta'], st['sg'] = await asyncio.to_thread(
                        e1_task.level_s_and_r, run, run.workspace, st['task'], TRACER, str(st['dir']))
            except Exception as e:
                st['meta'] = {'error_SR': repr(e)[:500]}
        elif '-m pytest' in cmd and '--junitxml' in cmd and not AGENT_REPROS and not FULL_SUITE:
            new = e1_task.f_command(cmd, TRACER, st['dir'] / 'trace_F.json')
            t0 = time.time()
            res = await _orig_exec(docker, sid, new or cmd, *a, **kw)
            st['F'] = {'exit': res.exit_code, 'seconds': round(time.time() - t0, 1),
                       'ok': (st['dir'] / 'trace_F.json').exists(), 'rewritten': new is not None,
                       'tail': ((res.stdout or '') + (getattr(res, 'stderr', '') or ''))[-1500:]}
            return res
    return await _orig_exec(docker, sid, cmd, *a, **kw)


verification.sandbox_exec = hooked_exec


class BuggyEvaluator(Evaluator):
    async def _run_agent_sandbox(self, task, snapshot_path, task_index, total_tasks, **kwargs):
        from adk_eval_core.tracing import SessionTrace
        return '', None, SessionTrace()


ev1 = BuggyEvaluator(EvalConfig(
    tasks_path=COMP / 'tasks.jsonl', snapshots_dir=COMP / 'snapshots', results_dir=WORK / 'results_e1',
    submission_dir=AGENT_DIR, models=None, sandbox='subprocess', wheels_dir=COMP / 'wheels',
    graph_dir=str(COMP / 'graphs'), embeddings_dir=str(COMP / 'embeddings'),
    timeout_seconds=900, verification_timeout_seconds=900, display_mode='quiet'))
ev1.sandbox = ev1.docker = SubprocessManager(timeout_seconds=900, system_site_packages=False)


def e1_one(task):
    tid = task.instance_id
    d = OUT / tid
    d.mkdir(exist_ok=True)
    _current.set(tid)
    raw = dict(instance_id=tid, repo=task.repo, patch=task.patch, problem_statement=task.problem_statement)
    st = {'task': raw, 'dir': d}
    STATE.set(st)
    t0 = time.time()
    try:
        res = asyncio.run(ev1.evaluate_task(task=task))
        resolved, err = bool(res.resolved), (res.error or '')[:300]
    except Exception as e:
        resolved, err = None, repr(e)[:300]
    meta = st.get('meta', {})
    meta.update(F=st.get('F'), buggy_resolved=resolved, error=err, seconds=round(time.time() - t0, 1),
                test_files=extract_test_files_from_patch(task.test_patch))
    try:
        graphs = glob.glob(str(COMP / 'graphs' / f'*_{task.base_commit}.json'))
        meta['graph'] = os.path.basename(graphs[0]) if graphs else None
        if graphs and st.get('sg') is not None:
            rows = e1_task.missed_edges(st['sg'], json.load(open(graphs[0])), str(d))
            meta['runtime_edges'] = len(rows)
    except Exception as e:
        meta['error_edges'] = repr(e)[:300]
    (d / 'meta.json').write_text(json.dumps(meta, indent=1, default=str))
    if FULL_SUITE:
        f = meta.get('full', {})
        print(f"{tid}: full ok={f.get('ok')} tests={f.get('n_tests')} {f.get('outcomes')} {f.get('seconds')}s {err[:60]}", flush=True)
        (d / 'meta.json').write_text(json.dumps(meta, indent=1, default=str))
        return meta
    if AGENT_REPROS:
        print(f"{tid}: A={[(a.get('ok'), a.get('exit')) for a in meta.get('A', [])]} {meta['seconds']}s {err[:80]}", flush=True)
        (d / 'meta.json').write_text(json.dumps(meta, indent=1, default=str))
        return meta
    print(f"{tid}: R={meta.get('R', {}).get('ok')} F={(meta.get('F') or {}).get('ok')} "
          f"gold={len(meta.get('gold', {}).get('nodes', []))} edges={meta.get('runtime_edges')} "
          f"{meta['seconds']}s {err[:80]}", flush=True)
    return meta


from swegemma.models import extract_test_files_from_patch

e1_tasks = sorted(load_tasks(COMP / 'tasks.jsonl'), key=lambda t: t.instance_id)
if AGENT_REPROS:
    e1_tasks = [t for t in e1_tasks if t.instance_id in AGENT_REPROS]
if os.environ.get('E1_ONLY'):
    e1_tasks = [t for t in e1_tasks if t.instance_id in os.environ['E1_ONLY'].split(',')]
print(f'E1 on {len(e1_tasks)} tasks, concurrency {E1_CONCURRENCY}', flush=True)
t_start = time.time()
with ThreadPoolExecutor(max_workers=E1_CONCURRENCY) as pool:
    metas = list(pool.map(e1_one, e1_tasks))
summary = dict(n=len(metas), wall_minutes=round((time.time() - t_start) / 60, 1),
               R_ok=sum(bool((m.get('R') or {}).get('ok')) for m in metas),
               F_ok=sum(bool((m.get('F') or {}).get('ok')) for m in metas),
               errors=sum(bool(m.get('error') or m.get('error_SR')) for m in metas))
(WORK / 'e1_summary.json').write_text(json.dumps(summary, indent=2))
print(json.dumps(summary, indent=2))
