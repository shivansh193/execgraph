import textwrap

import pytest

from execgraph import edge_causes, gold, metrics, rank, static_ast
from execgraph.ids import is_test_node, module_of


def write(root, files):
    for rel, src in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(src))


REPO = {
    "src/pkg/__init__.py": "from .core import Engine, helper\n",
    "src/pkg/core.py": """
        from . import util
        from .util import fmt

        def helper(x):
            return fmt(x)

        class Base:
            def run(self):
                return self.step()
            def step(self):
                return 0

        class Engine(Base):
            def __init__(self, n):
                self.n = n
            def step(self):
                return util.double(self.n)
            @property
            def size(self):
                return self.n
            def go(self, cb):
                e = Engine(1)
                e.step()
                obj.unknown_method()
                return cb(self.size)
    """,
    "src/pkg/util.py": """
        def fmt(x):
            return str(x)

        def double(x):
            return x * 2
    """,
    "src/pkg/api.py": """
        import pkg

        def make():
            return pkg.Engine(2).run()

        def register(app):
            app.add(make)
    """,
}


@pytest.fixture()
def sg(tmp_path):
    write(tmp_path, REPO)
    return static_ast.build(str(tmp_path))


def test_ids():
    assert module_of("src/pkg/__init__.py") == "pkg"
    assert module_of("docs_src/a/b.py") == "a.b"
    assert is_test_node("tests.test_x.test_y") and not is_test_node("pkg.core.helper")


def test_static_resolution(sg):
    e = sg.edges
    assert e[("pkg.core.helper", "pkg.util.fmt")] == "import"
    assert e[("pkg.core.Base.run", "pkg.core.Base.step")] == "self"
    assert e[("pkg.core.Engine.step", "pkg.util.double")] == "import"
    assert e[("pkg.core.Engine.go", "pkg.core.Engine.__init__")] == "constructor"
    assert e[("pkg.core.Engine.go", "pkg.core.Engine.step")] == "typed"
    # re-export through pkg/__init__ resolves to the defining module
    assert e[("pkg.api.make", "pkg.core.Engine")] == "constructor"
    assert ("pkg.core.Base.run", "pkg.core.Engine.step") not in e   # override dispatch is invisible statically


def test_edge_causes(sg):
    c = edge_causes.classify
    assert c(sg, "pkg.core.Base.run", "pkg.core.Engine.step") == "inheritance_dispatch"
    assert c(sg, "pkg.core.Engine.go", "pkg.core.Engine.size") == "property_descriptor"
    assert c(sg, "pkg.api.register", "pkg.api.make") == "callback_reference"
    assert c(sg, "pkg.core.Engine.go", "pkg.x.Other.unknown_method") == "attribute_dispatch"
    assert c(sg, "pkg.core.Engine.go", "pkg.x.Thing.__eq__") == "dunder_protocol"
    assert c(sg, "pkg.core", "pkg.core.helper") == "import_time"
    assert c(sg, "pkg.util.fmt", "pkg.x.y") == "indirect_via_library"
    assert edge_causes.missed([("a", "b"), ("c", "d")], [("b", "a")]) == [("c", "d")]


def test_gold(tmp_path):
    write(tmp_path, REPO)
    patch = textwrap.dedent("""\
        --- a/src/pkg/core.py
        +++ b/src/pkg/core.py
        @@ -17,3 +17,3 @@ class Engine(Base):
             def step(self):
        -        return util.double(self.n)
        +        return util.double(self.n) + 1
             @property
        --- a/src/pkg/util.py
        +++ b/src/pkg/util.py
        @@ -1,2 +1,4 @@
        +import os
        +
         def fmt(x):
             return str(x)
        --- /dev/null
        +++ b/src/pkg/new.py
        @@ -0,0 +1 @@
        +X = 1
        --- a/tests/test_core.py
        +++ b/tests/test_core.py
        @@ -1 +1 @@
        -a
        +b
    """)
    g = gold.gold_from_patch(patch, lambda p: (tmp_path / p).read_text() if (tmp_path / p).exists() else None)
    assert g.nodes == {"pkg.core.Engine.step"}
    assert g.files == {"src/pkg/core.py", "src/pkg/util.py", "src/pkg/new.py"}
    assert g.module_level == {"src/pkg/util.py"}
    assert g.new_only == {"src/pkg/new.py"} and g.test_files == {"tests/test_core.py"}


def test_ppr_follows_edges():
    nodes = ["a", "b", "c", "d"]
    s = rank.ppr(nodes, [("a", "b", 1.0), ("b", "c", 1.0)], {"a": 1.0}, 0.3, 100)
    assert s["a"] > s["b"] > s["c"] and "d" not in s
    assert abs(sum(s.values()) - 1) < 1e-6


def test_rwg_runtime_edge_lifts_callee():
    repo = rank.Repo(["pkg.api.parse_header", "pkg.core.split_value", "pkg.core.other"],
                     {"pkg.api.parse_header": "def parse_header(h): ...", "pkg.core.split_value": "def split_value(v): ...",
                      "pkg.core.other": "def other(): ..."}, [])
    issue = "parse_header breaks on quoted commas"
    no_rt = rank.rwg_ppr(repo, issue, rank.Evidence(), sem=[])
    ev = rank.Evidence(runtime_edges=[("pkg.api.parse_header", "pkg.core.split_value")])
    with_rt = rank.rwg_ppr(repo, issue, ev, sem=[])
    assert no_rt[0] == with_rt[0] == "pkg.api.parse_header"
    assert "pkg.core.split_value" not in no_rt and with_rt[1] == "pkg.core.split_value"


def test_evidence_and_spectrum_rankers():
    trace = {"tests": {
        "t1": {"outcome": "failed", "funcs": ["pkg.a", "pkg.b"], "direct": ["pkg.a"], "edges": [["pkg.a", "pkg.b"]]},
        "t2": {"outcome": "passed", "funcs": ["pkg.a"], "direct": ["pkg.a"], "edges": []}},
        "failures": [{"test": "t1", "frames": [{"node": "pkg.a"}, {"node": "pkg.b"}]}]}
    ev = rank.Evidence.from_trace(trace)
    assert ev.n_failed == 1 and ev.runtime_edges == [("pkg.a", "pkg.b")]
    assert rank.rank_ochiai(ev)[0] == "pkg.b"          # only the failing test ran b
    assert rank.rank_crash(ev) == ["pkg.b", "pkg.a"]   # innermost first
    assert rank.rank_test_files(None, ev) == ["pkg.a"]
    repo = rank.Repo(["pkg.a", "pkg.b"], {}, [])
    assert rank.rank_prfl(repo, ev)[0] == "pkg.b"


def test_metrics():
    m = metrics.task_metrics(["x", "g", "y"], {"g"})
    assert m["hit@1"] == 0 and m["hit@5"] == 1 and m["mrr"] == 0.5
    mean, lo, hi = metrics.bootstrap([1, 0, 1, 1])
    assert lo <= mean <= hi and mean == 0.75
    d, lo, hi, p = metrics.paired_bootstrap([1, 1, 1, 0], [0, 0, 1, 0])
    assert d == 0.5 and lo <= d <= hi and p < 0.1


def test_quoted_identifiers():
    ids = rank.quoted_identifiers("Calling `Response.set_cookie()` with SameSite fails in parse_header(x)")
    assert {"Response", "set_cookie", "SameSite", "parse_header"} <= ids
