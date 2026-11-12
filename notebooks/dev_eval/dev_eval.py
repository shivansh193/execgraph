# Dev eval: run a submission bundle on the public tasks with a scorer-like sandbox.
#
# Built by notebooks/build.py, which embeds submission/ into SUBMISSION_FILES below.
# vLLM + Evaluator setup follows ryanholbrook/getting-started-gemma-4-developer-agent.
# The scorer-like environment (setup_env) is adapted from
# zbigniewkirchner/gemma-4-agent-do-gold-patches-pass-locally (127/129 gold patches pass).
import asyncio, contextvars, glob, importlib, json, logging, os, re, shutil, subprocess, sys, tarfile, threading, time, tomllib, zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SUBMISSION_FILES = {}  # filled in by build.py
RUN_TAG = 'dev'        # filled in by build.py
# --hints: task id -> text appended to the problem statement; --tasks: exact ids instead of the N_TASKS subset
HINTS = {}             # filled in by build.py
TASK_IDS = []          # filled in by build.py
N_TASKS = int(os.environ.get('DEV_N_TASKS', 40))
CONCURRENCY = int(os.environ.get('DEV_CONCURRENCY', 1))
# Required tests contradict each other on every Python (see the gold-patch notebook).
IMPOSSIBLE = {'rich_3486', 'fastapi_14186'}

for k, v in {
    'TRANSFORMERS_NO_TF': '1', 'TRANSFORMERS_NO_FLAX': '1', 'TRANSFORMERS_OFFLINE': '1',
    'VLLM_NO_USAGE_STATS': '1', 'VLLM_WORKER_MULTIPROC_METHOD': 'spawn', 'VLLM_ENGINE_READY_TIMEOUT_S': '1200',
    'VLLM_MEMORY_PROFILER_ESTIMATE_CUDAGRAPHS': '1', 'NCCL_DEBUG': 'WARN', 'LITELLM_LOCAL_MODEL_COST_MAP': 'True',
    'LITELLM_TELEMETRY': 'False', 'LITELLM_LOG': 'WARNING', 'OPENAI_API_KEY': 'EMPTY', 'LOCAL_API_KEY': 'EMPTY',
    'PYTORCH_CUDA_ALLOC_CONF': 'expandable_segments:True', 'OTEL_SDK_DISABLED': 'true',
}.items():
    os.environ.setdefault(k, v)

COMP = Path(glob.glob('/kaggle/input/**/tasks.jsonl', recursive=True)[0]).parent
WHEELHOUSE = Path(glob.glob('/kaggle/input/**/swegemma-*.whl', recursive=True)[0]).parent
EXTRA = Path(glob.glob('/kaggle/input/**/inline_snapshot-*.whl', recursive=True)[0]).parent
PYDS = Path(glob.glob('/kaggle/input/**/cpython-3.12-linux.tgz.bin', recursive=True)[0]).parent
WORK = Path('/kaggle/working')

# ---------------------------------------------------------------- 1. harness install
for pth in glob.glob('/usr/local/lib/python*/*-packages/*cutlass*.pth'):
    os.unlink(pth)
tmp_whl = Path('/tmp/wheelhouse'); tmp_whl.mkdir(exist_ok=True)
for w in WHEELHOUSE.glob('*.whl'):  # Kaggle strips '+cu128' from wheel names
    if 'cutlass' in w.name.lower():
        continue
    name = w.name.replace('cu128', '+cu128') if ('cu128' in w.name and '+' not in w.name) else w.name
    if not (tmp_whl / name).exists():
        os.symlink(w, tmp_whl / name)
subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', '--no-deps', '--force-reinstall',
                *map(str, tmp_whl.glob('*.whl'))], check=True)
importlib.invalidate_caches()
logging.getLogger().setLevel(logging.ERROR)
for name in ('LiteLLM', 'litellm', 'httpx', 'httpcore', 'openai', 'urllib3', 'opentelemetry'):
    logging.getLogger(name).setLevel(logging.WARNING)

import litellm, torch, pandas as pd
from packaging.requirements import Requirement
from packaging.version import Version
from adk_submission import VllmConfig, VllmServer, discover_adapters, validate_directory
from adk_submission.discovery import discover_declared_models
from google.adk.agents.context_cache_config import ContextCacheConfig
from google.adk.apps._configs import EventsCompactionConfig
from swegemma.config import ALLOWED_ADAPTER_EXTENSIONS, EvalConfig, build_submission_limits
from swegemma.evaluate import Evaluator
from swegemma.models import load_tasks
from swegemma.sandbox.subprocess import SubprocessManager
import swegemma.harness.agent_runner as agent_runner
import swegemma.harness.verification as verification
import yaml

litellm.drop_params = True

# ---------------------------------------------------------------- 2. submission bundle
AGENT_DIR = WORK / 'submission'
shutil.rmtree(AGENT_DIR, ignore_errors=True)
for rel, text in SUBMISSION_FILES.items():
    (AGENT_DIR / rel).parent.mkdir(parents=True, exist_ok=True)
    (AGENT_DIR / rel).write_text(text, encoding='utf-8')
limits, gen_constraints = build_submission_limits()
validate_directory(AGENT_DIR, limits=limits)
(model_name,) = discover_declared_models(AGENT_DIR)
ev_cfg = yaml.safe_load((AGENT_DIR / 'eval_config.yaml').read_text()) if (AGENT_DIR / 'eval_config.yaml').exists() else {}
ev_cfg = ev_cfg.get('evaluation', ev_cfg)
print('model', model_name, 'budget', ev_cfg)

# ---------------------------------------------------------------- 3. scorer-like sandbox
def fits(w, tag='cp313'):
    py, abi, plat = w.name[:-4].split('-')[-3:]
    if plat != 'any' and 'linux' not in plat:
        return False
    if abi == 'abi3':
        return int(py.split('.')[0][2:]) <= int(tag[2:])
    return any(t.startswith('py3') for t in py.split('.')) or tag in py.split('.')


norm = lambda n: re.sub(r'[-_.]+', '_', n).lower()
WHEELS = {}
for w in [*(COMP / 'wheels').glob('*.whl'), *EXTRA.glob('*.whl'), *PYDS.glob('*.whl')]:
    name, ver = w.name.split('-')[:2]
    WHEELS.setdefault(norm(name), []).append((Version(ver), w))

OWN = {'fastapi/fastapi': 'fastapi', 'Textualize/rich': 'rich', 'psf/requests': 'requests', 'encode/httpx': 'httpx'}
ONLY_FOR = {'pytest_httpbin': {'psf/requests'}, 'httpbin': {'psf/requests'}, 'flasgger': {'psf/requests'},
            'brotlicffi': {'psf/requests', 'encode/httpx'}, 'brotli': {'encode/httpx'}, 'zstandard': {'encode/httpx'}}
# Calibration found by running gold patches; public tasks only, not something the agent could know.
CALIBRATION = {
    'rich_3064': {'pygments': '2.15.1'}, 'rich_3130': {'pygments': '2.15.1'}, 'rich_3296': {'pygments': '2.16.1'},
    'rich_3469': {'pygments': '2.18.0'}, 'rich_3782': {'pygments': '2.19.2'}, 'rich_4070': {'pygments': '2.19.2'},
    'rich_4079': {'pygments': '2.20.0'},
    'requests_6589': {'werkzeug': '2.3.8', 'flask': '2.3.3'}, 'requests_6592': {'werkzeug': '2.3.8', 'flask': '2.3.3'},
    'requests_6629': {'werkzeug': '2.3.8', 'flask': '2.3.3'},
}
TASK_PYTHON = {'requests_6757': 'cp312', 'rich_3472': 'cp312'}
ASYNC_SHIM = {'fastapi_15745', 'fastapi_15763', 'fastapi_15785'}
NO_CERT_TIME = {'requests_6757'}
# The pinned starter image runs 3.12 (the wheelhouse is cp312); task sandboxes need the scorer's 3.13,
# which python_for() unpacks from the local-eval-pythons dataset.
PY = {f'cp3{sys.version_info.minor}': Path(sys.executable)}
BASE = {}
_lock = threading.Lock()
# Task id of the task being evaluated. A ContextVar, not threading.local: the harness calls the
# dependency hook through asyncio.to_thread, which runs on a worker thread but copies the context.
_current = contextvars.ContextVar('task_id', default=None)

SHIM = WORK / 'shims'
(SHIM / 'swe_async_shim-0.1.dist-info').mkdir(parents=True, exist_ok=True)
(SHIM / 'swe_async_shim-0.1.dist-info' / 'METADATA').write_text('Metadata-Version: 2.1\nName: swe-async-shim\nVersion: 0.1\n')
(SHIM / 'swe_async_shim-0.1.dist-info' / 'entry_points.txt').write_text('[pytest11]\nswe_async_shim = swe_async_shim\n')
(SHIM / 'swe_async_shim.py').write_text('''import asyncio, inspect
import pytest


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem):
    if inspect.iscoroutinefunction(pyfuncitem.obj):
        args = {a: pyfuncitem.funcargs[a] for a in pyfuncitem._fixtureinfo.argnames}
        asyncio.run(pyfuncitem.obj(**args))
        return True
''')
(SHIM / 'swe_no_cert_time.py').write_text('''import ssl

_new = ssl.SSLContext.__new__


def _new_no_time(cls, *args, **kwargs):
    ctx = _new(cls, *args, **kwargs)
    ctx.verify_flags |= 0x200000
    return ctx


ssl.SSLContext.__new__ = staticmethod(_new_no_time)
''')


def python_for(tag):
    with _lock:
        if tag not in PY:
            ver = f'{tag[2]}.{tag[3:]}'
            dest = WORK / f'py{tag}'
            if not (dest / 'python' / 'bin' / f'python{ver}').exists():
                with tarfile.open(PYDS / f'cpython-{ver}-linux.tgz.bin', 'r:gz') as t:
                    t.extractall(dest)
            PY[tag] = dest / 'python' / 'bin' / f'python{ver}'
        return PY[tag]


def base_for(repo, tag):
    with _lock:
        if (repo, tag) in BASE:
            return BASE[(repo, tag)]
    sel = {}
    for name, opts in WHEELS.items():
        opts = [(v, w) for v, w in opts if fits(w, tag)]
        if not opts or name == OWN[repo] or (name in ONLY_FOR and repo not in ONLY_FOR[name]):
            continue
        comp = [(v, w) for v, w in opts if w.parent == COMP / 'wheels']
        if name in ('pytest', 'pytest_timeout'):
            sel[name] = next(w for v, w in opts if str(v) in ('8.4.2', '2.1.0'))
        elif comp:
            sel[name] = max(comp)[1]
        elif name != 'pygments':
            sel[name] = max(opts)[1]
    d = WORK / f'scorer_site_{OWN[repo]}_{tag}'
    shutil.rmtree(d, ignore_errors=True)
    subprocess.run([str(python_for(tag)), '-m', 'pip', 'install', '-q', '--no-index', '--no-deps',
                    '--ignore-requires-python', '--target', str(d), *map(str, sel.values())])
    for shim in ('imp.py', 'telnetlib.py'):
        shutil.copy(COMP / 'docker' / shim, d / shim)
    with _lock:
        BASE[(repo, tag)] = (d, sel)
    return BASE[(repo, tag)]


def poetry_to_pep440(spec):
    spec = spec if isinstance(spec, str) else spec.get('version', '')
    m = re.fullmatch(r'\^(\d+)(\.\d+)?(\.\d+)?', spec.strip())
    return f'>={spec.strip()[1:]},<{int(m.group(1)) + 1}' if m else ('' if spec.strip() == '*' else spec)


def setup_env(docker, sandbox_id, repo='', **kwargs):
    tid = _current.get()
    tag = TASK_PYTHON.get(tid, 'cp313')
    site = Path(docker.exec(sandbox_id, 'python -c "import site; print(site.getsitepackages()[0])"').stdout.strip())
    if python_for(tag) != Path(sys.executable):  # rebuild the sandbox venv on the task's interpreter
        venv_dir = site.parents[2]
        subprocess.run([str(python_for(tag)), '-m', 'venv', '--clear', '--without-pip', str(venv_dir)], check=True)
        site = next(venv_dir.glob('lib/python3*/site-packages'))
    ws = docker.exec(sandbox_id, 'pwd').stdout.strip()
    # pytest is only importable via the .pth below; without a launcher in venv/bin, a bare `pytest` from the agent
    # falls through PATH to the Kaggle image's own pytest (3.12, no test-only packages). The Docker scorer has one.
    venv_bin = site.parents[2] / 'bin'
    for exe in ('pytest', 'py.test'):
        (venv_bin / exe).write_text(f'#!/bin/sh\nexec "{venv_bin}/python" -m pytest "$@"\n')
        (venv_bin / exe).chmod(0o755)
    base, sel = base_for(repo, tag)
    (site / '00_src.pth').write_text(f'{ws}/src\n')
    (site / '01_scorer_base.pth').write_text(f'{base}\n')
    (site / 'zz_workspace_paths.pth').write_text('\n'.join(str(p) for p in Path(ws).iterdir()
                                                           if p.is_dir() and not p.name.startswith('.')) + '\n')
    if tid in ASYNC_SHIM:
        (site / '02_async_shim.pth').write_text(f'{SHIM}\n')
    if tid in NO_CERT_TIME:
        (site / '03_no_cert_time.pth').write_text(f'import sys; sys.path.insert(0, {str(SHIM)!r}); import swe_no_cert_time\n')
    try:
        data = tomllib.loads(Path(ws, 'pyproject.toml').read_text())
    except Exception:
        data = {}
    reqs = list(data.get('project', {}).get('dependencies', []))
    reqs += [n + poetry_to_pep440(s) for n, s in data.get('tool', {}).get('poetry', {}).get('dependencies', {}).items() if n != 'python']
    picks, queue, seen = {}, list(reqs), set()
    while queue:
        try:
            req = Requirement(queue.pop(0))
        except Exception:
            continue
        key = norm(req.name)
        if key in seen or key == OWN.get(repo) or (req.marker and not req.marker.evaluate({'extra': ''})):
            continue
        seen.add(key)
        options = [(v, w) for v, w in WHEELS.get(key, []) if fits(w, tag) and req.specifier.contains(v, prereleases=True)
                   and not (key in ONLY_FOR and repo not in ONLY_FOR[key])]
        if options:
            best = max(options)[1]
            if best != sel.get(key):
                picks[key] = best
            with zipfile.ZipFile(best) as z:
                meta = next(n for n in z.namelist() if n.endswith('.dist-info/METADATA'))
                queue += [l.split(':', 1)[1].strip() for l in z.read(meta).decode().splitlines() if l.startswith('Requires-Dist:')]
    for name, ver in CALIBRATION.get(tid, {}).items():
        picks[name] = next(w for v, w in WHEELS[name] if str(v) == ver and fits(w, tag))
    if picks:
        subprocess.run([str(python_for(tag)), '-m', 'pip', 'install', '-q', '--no-index', '--no-deps', '--upgrade',
                        '--ignore-requires-python', '--target', str(site), *map(str, picks.values())])


import swegemma.evaluate as sg_evaluate

verification.install_test_dependencies = setup_env
agent_runner.install_test_dependencies = setup_env
sg_evaluate.install_test_dependencies = setup_env

# ---------------------------------------------------------------- 3b. sanity check: gold patches must pass
class GoldEvaluator(Evaluator):
    async def _run_agent_sandbox(self, task, snapshot_path, task_index, total_tasks, **kwargs):
        from adk_eval_core.tracing import SessionTrace
        return task.patch, None, SessionTrace()


_all = {t.instance_id: t for t in load_tasks(COMP / 'tasks.jsonl')}
gold = GoldEvaluator(EvalConfig(
    tasks_path=COMP / 'tasks.jsonl', snapshots_dir=COMP / 'snapshots', results_dir=WORK / 'results_gold',
    submission_dir=AGENT_DIR, models=None, sandbox='subprocess', wheels_dir=COMP / 'wheels',
    graph_dir=str(COMP / 'graphs'), embeddings_dir=str(COMP / 'embeddings'),
    timeout_seconds=300, verification_timeout_seconds=300, display_mode='quiet'))
gold.sandbox = gold.docker = SubprocessManager(timeout_seconds=300, system_site_packages=False)
for tid in ('rich_3064', 'fastapi_15661', 'requests_6757'):  # calibrated, plain and cp312 cases
    _current.set(tid)
    res = asyncio.run(gold.evaluate_task(task=_all[tid]))
    print(f'gold {tid}: resolved={res.resolved} {(res.error or "")[:200]}', flush=True)
    assert res.resolved, f'scorer-like env broken: gold patch for {tid} fails\n{res.test_output[-3000:]}'

# ---------------------------------------------------------------- 4. vLLM
adapters = discover_adapters(str(AGENT_DIR), adapter_extensions=ALLOWED_ADAPTER_EXTENSIONS)
adapter_map = getattr(adapters, 'adapters', None) or {}
ranks = [r for info in adapter_map.values() if (r := getattr(info, 'rank', None))]
gpus = torch.cuda.device_count()
server = VllmServer(VllmConfig(
    model=glob.glob(f'/kaggle/input/**/{model_name}/*/config.json', recursive=True)[0].rsplit('/', 1)[0],
    port=8000, host='127.0.0.1', tool_call_parser='gemma4', reasoning_parser='gemma4', max_model_len=32768,
    dtype='bfloat16', gpu_memory_utilization=0.90, enable_auto_tool_choice=True,
    enable_lora=bool(adapter_map), max_loras=max(1, len(adapter_map)), max_lora_rank=max(ranks) if ranks else 128,
    scheduler_reserve_full_isl=False, tensor_parallel_size=4 if gpus >= 4 else (2 if gpus >= 2 else 1),
    startup_timeout=1200,
    extra_args=('--hf-overrides', '{"architectures": ["Gemma4ForCausalLM"], "model_type": "gemma4"}')
    if model_name == 'gemma-4-12b-it-qat-w4a16-ct' else (),
), adapter_manifest=adapters)
server.start()
models = server.create_model_registry(aliases=[model_name], model_prefix='openai/', api_key='EMPTY')

# ---------------------------------------------------------------- 5. task subset
tasks = [t for t in load_tasks(COMP / 'tasks.jsonl') if t.instance_id not in IMPOSSIBLE]
by_repo = {}
for t in sorted(tasks, key=lambda t: t.instance_id):
    by_repo.setdefault(t.repo, []).append(t)
picked = []  # repo-proportional, deterministic: every k-th task of each repo
for repo, ts in by_repo.items():
    n = max(1, round(N_TASKS * len(ts) / len(tasks)))
    step = len(ts) / n
    picked += [ts[int(i * step)] for i in range(n)]
if TASK_IDS:
    picked = [t for t in tasks if t.instance_id in TASK_IDS]
if HINTS:  # E3 hinted-control arms: the same tasks with a localisation hint appended to the issue
    import dataclasses
    picked = [dataclasses.replace(t, problem_statement=t.problem_statement + HINTS[t.instance_id])
              if t.instance_id in HINTS else t for t in picked]
print(f'{len(picked)} tasks ({len(HINTS)} hints):', ' '.join(t.instance_id for t in picked))

# ---------------------------------------------------------------- 6. evaluate
RESULTS = WORK / f'results_{RUN_TAG}'
cfg = EvalConfig(
    tasks_path=COMP / 'tasks.jsonl', snapshots_dir=COMP / 'snapshots', results_dir=RESULTS,
    submission_dir=AGENT_DIR, models=models, sandbox='subprocess',
    timeout_seconds=int(ev_cfg.get('timeout_seconds', 300)), verification_timeout_seconds=300,
    max_time_minutes=float(ev_cfg.get('max_time_minutes', 60.0)), max_tool_calls=int(ev_cfg.get('max_tool_calls', 100)),
    max_turns=ev_cfg.get('max_turns'), limits=limits, generation_constraints=gen_constraints,
    adapter_manifest=adapters,
    context_cache_config=ContextCacheConfig(min_tokens=2048, ttl_seconds=1800, cache_intervals=10),
    events_compaction_config=EventsCompactionConfig(compaction_interval=15, overlap_size=2,
                                                    token_threshold=14336, event_retention_size=5),
    graph_dir=str(COMP / 'graphs'), embeddings_dir=str(COMP / 'embeddings'), wheels_dir=COMP / 'wheels',
    display_mode='quiet',
)
evaluator = Evaluator(cfg)
evaluator.sandbox = evaluator.docker = SubprocessManager(timeout_seconds=300, system_site_packages=False)


def run_one(task):
    _current.set(task.instance_id)
    t0 = time.time()
    try:
        res = asyncio.run(evaluator.evaluate_task(task=task))
        row = dict(instance_id=task.instance_id, repo=task.repo, resolved=bool(res.resolved),
                   has_patch=bool((res.agent_patch or '').strip()), tool_calls=res.tool_calls,
                   error=(res.error or '')[:300])
    except Exception as e:
        row = dict(instance_id=task.instance_id, repo=task.repo, resolved=False, has_patch=False, tool_calls=None,
                   error=repr(e)[:300])
    row['seconds'] = round(time.time() - t0, 1)
    print(f"{row['instance_id']}: resolved={row['resolved']} patch={row['has_patch']} {row['seconds']}s", flush=True)
    return row


t_start = time.time()
with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
    rows = list(pool.map(run_one, picked))
df = pd.DataFrame(rows)
df.to_csv(WORK / f'dev_eval_{RUN_TAG}.csv', index=False)
summary = dict(run_tag=RUN_TAG, model=model_name, budget=ev_cfg, n=len(df), resolved=int(df.resolved.sum()),
               rate=round(df.resolved.mean(), 4), with_patch=int(df.has_patch.sum()),
               wall_minutes=round((time.time() - t_start) / 60, 1),
               by_repo=df.groupby('repo').resolved.agg(['sum', 'count']).to_dict('index'))
(WORK / f'dev_eval_{RUN_TAG}.json').write_text(json.dumps(summary, indent=2, default=str))
print(json.dumps(summary, indent=2, default=str))
server.stop()
