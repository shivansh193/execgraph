"""A second static call graph, built from Python's `ast` with name resolution, on competition node ids.

Every edge carries how it was resolved, so a missing runtime edge can be blamed on a specific limit of static
analysis rather than on one tool:

    direct        f() where f is defined in the same module
    import        f() / mod.f() through an import (re-exports followed)
    constructor   C() -> the class node and the __init__ found in its MRO
    self          self.m() / cls.m() -> m in the enclosing class's MRO
    super         super().m() -> m in the MRO after the enclosing class
    typed         x.m() where x was assigned C(...) or annotated as C
    class_attr    C.m()
    name_match    obj.m() with an unknown receiver -> every repo method named m (at most MAX_NAME_MATCH);
                  imprecise, reported separately

Per-def facts (`DefInfo.sites`) are kept for `edge_causes.classify`.
"""
import ast
import os
from dataclasses import dataclass, field

from .ids import module_of

MAX_NAME_MATCH = 3
PRECISE = ("direct", "import", "constructor", "self", "super", "typed", "class_attr")


@dataclass
class Sites:
    name_calls: set = field(default_factory=set)       # f(...)
    attr_calls: list = field(default_factory=list)     # (receiver kind, attr): self | cls | super | module | name | expr
    attr_loads: set = field(default_factory=set)       # x.attr read without a call (properties, descriptors)
    refs: set = field(default_factory=set)             # names / attrs used as values (callbacks)
    called_params: set = field(default_factory=set)    # parameters that get called
    local_imports: bool = False
    reflection: bool = False                           # getattr / importlib / __dict__ / globals()
    instantiates: set = field(default_factory=set)     # resolved class ids it constructs
    inner_defs: bool = False


@dataclass
class DefInfo:
    id: str
    module: str
    kind: str                   # function | class
    cls: str = None             # enclosing class id for methods
    node: object = None
    params: list = field(default_factory=list)
    decorators: list = field(default_factory=list)   # decorator source text
    bases: list = field(default_factory=list)        # resolved base class ids (classes)
    sites: Sites = field(default_factory=Sites)


@dataclass
class Module:
    name: str
    path: str
    is_pkg: bool
    imports: dict = field(default_factory=dict)      # local alias -> dotted target
    tree: object = None


class StaticGraph:
    def __init__(self):
        self.modules, self.defs = {}, {}
        self.methods_named = {}  # method name -> [method ids], for name_match
        self.edges = {}         # (src, dst) -> kind (first, most precise kind wins)

    def add(self, s, d, kind):
        if s != d and (s, d) not in self.edges:
            self.edges[(s, d)] = kind

    def precise_edges(self):
        return {e for e, k in self.edges.items() if k in PRECISE}


def iter_py(root):
    skip = {".git", ".venv", "venv", "node_modules", "site-packages", "build", "dist", ".tox", "__pycache__"}
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in skip and not x.startswith(".")]
        for f in files:
            if f.endswith(".py"):
                p = os.path.join(d, f)
                yield os.path.relpath(p, root).replace(os.sep, "/"), p


def build(root: str, include=None) -> StaticGraph:
    """Static call graph of every .py file under `root` (`include(relpath)` filters files)."""
    g = StaticGraph()
    for rel, path in iter_py(root):
        if include and not include(rel):
            continue
        try:
            src = open(path, encoding="utf-8", errors="replace").read()
            tree = ast.parse(src)
        except (SyntaxError, ValueError):
            continue
        name = module_of(rel)
        m = Module(name, rel, rel.endswith("__init__.py"), tree=tree)
        g.modules[name] = m
        _collect_imports(m, tree.body)
        _collect_defs(g, m, tree.body, name, None)
    for d in g.defs.values():
        if d.kind == "class":
            d.bases = [b for b in (_resolve_expr(g, g.modules[d.module], x) for x in d.node.bases) if b in g.defs]
        elif d.cls:
            g.methods_named.setdefault(d.id.rsplit(".", 1)[1], []).append(d.id)
    for d in g.defs.values():
        if d.kind == "function":
            _CallVisitor(g, d).run()
    return g


def _pkg(m: Module):
    return m.name if m.is_pkg else m.name.rpartition(".")[0]


def _collect_imports(m: Module, body):
    for n in body:
        if isinstance(n, ast.Import):
            for a in n.names:
                if a.asname:
                    m.imports[a.asname] = a.name
                else:
                    m.imports.setdefault(a.name.split(".")[0], a.name.split(".")[0])
        elif isinstance(n, ast.ImportFrom):
            base = n.module or ""
            if n.level:
                pkg = _pkg(m).split(".") if _pkg(m) else []
                pkg = pkg[: len(pkg) - (n.level - 1)] if n.level > 1 else pkg
                base = ".".join(pkg + ([base] if base else []))
            for a in n.names:
                if a.name != "*":
                    m.imports[a.asname or a.name] = f"{base}.{a.name}" if base else a.name
        elif isinstance(n, (ast.If, ast.Try)):
            for attr in ("body", "orelse", "finalbody"):
                _collect_imports(m, getattr(n, attr, []) or [])
            for h in getattr(n, "handlers", []):
                _collect_imports(m, h.body)


def _collect_defs(g, m, body, prefix, cls):
    for n in body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            nid = f"{prefix}.{n.name}"
            a = n.args
            params = [x.arg for x in a.posonlyargs + a.args + a.kwonlyargs]
            g.defs[nid] = DefInfo(nid, m.name, "function", cls, n, params,
                                  [ast.unparse(x) for x in n.decorator_list])
        elif isinstance(n, ast.ClassDef):
            nid = f"{prefix}.{n.name}"
            g.defs[nid] = DefInfo(nid, m.name, "class", cls, n, decorators=[ast.unparse(x) for x in n.decorator_list])
            _collect_defs(g, m, n.body, nid, nid)
        elif isinstance(n, (ast.If, ast.Try, ast.With)):
            for attr in ("body", "orelse", "finalbody"):
                _collect_defs(g, m, getattr(n, attr, []) or [], prefix, cls)


def resolve_dotted(g: StaticGraph, target: str, depth=0):
    """Dotted import target -> def id or module name, following re-exports (`from .x import y` in __init__)."""
    if target in g.defs or target in g.modules or depth > 6:
        return target
    head, _, last = target.rpartition(".")
    while head:
        if head in g.modules:
            rest = target[len(head) + 1:]
            first, _, more = rest.partition(".")
            imp = g.modules[head].imports.get(first)
            if imp:
                return resolve_dotted(g, imp + ("." + more if more else ""), depth + 1)
            return target
        head = head.rpartition(".")[0]
    return target


def _resolve_expr(g, m, e, local=None):
    """Name / Attribute chain -> resolved dotted id (def, module or external), or None."""
    parts = []
    while isinstance(e, ast.Attribute):
        parts.append(e.attr)
        e = e.value
    if not isinstance(e, ast.Name):
        return None
    root = e.id
    if local and root in local:
        return None
    if f"{m.name}.{root}" in g.defs:
        base = f"{m.name}.{root}"
    elif root in m.imports:
        base = m.imports[root]
    else:
        return None
    return resolve_dotted(g, ".".join([base] + parts[::-1]))


def mro(g, cls_id, seen=None):
    seen = seen or []
    if cls_id in seen or cls_id not in g.defs:
        return seen
    seen.append(cls_id)
    for b in g.defs[cls_id].bases:
        mro(g, b, seen)
    return seen


def lookup(g, cls_id, name, skip_first=False):
    for c in mro(g, cls_id)[1 if skip_first else 0:]:
        if f"{c}.{name}" in g.defs:
            return f"{c}.{name}"
    return None


def _owner_class(g, d):
    return d.cls if d.cls and g.defs[d.cls].kind == "class" else None


class _CallVisitor(ast.NodeVisitor):
    def __init__(self, g, d):
        self.g, self.d, self.m = g, d, g.modules[d.module]
        self.cls = _owner_class(g, d)
        self.params = set(d.params)
        self.local = set(d.params)       # names that shadow module scope
        self.types = {}                  # local name -> class id
        self.call_funcs = set()          # id() of expressions in call position
        a = d.node.args
        for arg in a.posonlyargs + a.args + a.kwonlyargs:
            t = self._class_of(arg.annotation) if arg.annotation is not None else None
            if t:
                self.types[arg.arg] = t

    def run(self):
        for stmt in self.d.node.body:
            for n in ast.walk(stmt):
                if isinstance(n, (ast.Assign, ast.AnnAssign, ast.For, ast.With, ast.comprehension)):
                    self._note_assign(n)
        for stmt in self.d.node.body:
            self.visit(stmt)

    def _class_of(self, e):
        if isinstance(e, ast.Subscript):     # Optional[C], Annotated[C, ...]
            e = e.slice.elts[0] if isinstance(e.slice, ast.Tuple) else e.slice
        if isinstance(e, ast.Constant) and isinstance(e.value, str):
            try:
                e = ast.parse(e.value, mode="eval").body
            except SyntaxError:
                return None
        r = _resolve_expr(self.g, self.m, e)
        return r if r in self.g.defs and self.g.defs[r].kind == "class" else None

    def _note_assign(self, n):
        targets = []
        if isinstance(n, ast.Assign):
            targets, value = n.targets, n.value
        elif isinstance(n, ast.AnnAssign):
            targets, value = [n.target], n.value
            t = self._class_of(n.annotation)
            if t and isinstance(n.target, ast.Name):
                self.types[n.target.id] = t
        elif isinstance(n, (ast.For, ast.comprehension)):
            targets, value = [n.target], None
        else:
            for item in n.items:
                if item.optional_vars is not None:
                    targets.append(item.optional_vars)
            value = None
        for t in targets:
            for x in ast.walk(t):
                if isinstance(x, ast.Name):
                    self.local.add(x.id)
        if value is not None and isinstance(value, ast.Call) and len(targets) == 1 and isinstance(targets[0], ast.Name):
            c = self._class_of(value.func)
            if c:
                self.types[targets[0].id] = c

    def visit_FunctionDef(self, n):          # nested defs are folded into this one
        self.d.sites.inner_defs = True
        self.local.add(n.name)
        self.generic_visit(n)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, n):
        self.local.add(n.name)
        self.generic_visit(n)

    def visit_Import(self, n):
        self.d.sites.local_imports = True

    visit_ImportFrom = visit_Import

    def visit_Call(self, n):
        self.call_funcs.add(id(n.func))
        self._call(n)
        self.generic_visit(n)

    def visit_Attribute(self, n):
        if id(n) not in self.call_funcs and isinstance(n.ctx, ast.Load):
            self.d.sites.attr_loads.add(n.attr)
            self.d.sites.refs.add(n.attr)
            if n.attr == "__dict__":
                self.d.sites.reflection = True
        self.generic_visit(n)

    def visit_Name(self, n):
        if id(n) not in self.call_funcs and isinstance(n.ctx, ast.Load):
            self.d.sites.refs.add(n.id)
        self.generic_visit(n)

    def _edge_class(self, cls_id, kind):
        g, s = self.g, self.d.id
        g.add(s, cls_id, kind)
        self.d.sites.instantiates.add(cls_id)
        init = lookup(g, cls_id, "__init__")
        if init:
            g.add(s, init, kind)

    def _call(self, n):
        g, s, f, sites = self.g, self.d.id, n.func, self.d.sites
        if isinstance(f, ast.Name):
            sites.name_calls.add(f.id)
            if f.id in ("getattr", "globals", "locals", "vars", "__import__", "eval", "exec"):
                sites.reflection = True
            if f.id in self.params:
                sites.called_params.add(f.id)
            if f.id in self.local:
                return
            local_def = f"{self.m.name}.{f.id}" in g.defs
            r = _resolve_expr(g, self.m, f)
            if r in g.defs:
                kind = "direct" if local_def else "import"
                if g.defs[r].kind == "class":
                    self._edge_class(r, "constructor")
                else:
                    g.add(s, r, kind)
            return
        if not isinstance(f, ast.Attribute):
            return
        recv, attr = f.value, f.attr
        if isinstance(recv, ast.Call) and isinstance(recv.func, ast.Name) and recv.func.id == "super":
            sites.attr_calls.append(("super", attr))
            if self.cls:
                t = lookup(g, self.cls, attr, skip_first=True)
                if t:
                    g.add(s, t, "super")
            return
        if isinstance(recv, ast.Name) and recv.id in ("self", "cls") and self.cls and self.d.params[:1] == [recv.id]:
            sites.attr_calls.append((recv.id, attr))
            t = lookup(g, self.cls, attr)
            if t:
                g.add(s, t, "self")
            return
        if isinstance(recv, ast.Name) and recv.id in self.types:
            sites.attr_calls.append(("name", attr))
            t = lookup(g, self.types[recv.id], attr)
            if t:
                g.add(s, t, "typed")
                return
        if isinstance(recv, ast.Name) and recv.id in ("importlib",):
            sites.reflection = True
        r = _resolve_expr(g, self.m, f, self.local)
        if r in g.defs:
            owner = r.rpartition(".")[0]
            if g.defs[r].kind == "class":
                self._edge_class(r, "constructor")
            else:
                g.add(s, r, "class_attr" if owner in g.defs and g.defs[owner].kind == "class" else "import")
            sites.attr_calls.append(("module", attr))
            return
        if r is not None and r.rpartition(".")[0] in g.defs:   # C.m where m comes from a base class
            owner, _, name = r.rpartition(".")
            t = lookup(g, owner, name)
            if t:
                g.add(s, t, "class_attr")
                sites.attr_calls.append(("module", attr))
                return
        sites.attr_calls.append(("name" if isinstance(recv, ast.Name) else "expr", attr))
        if attr.startswith("__") and attr.endswith("__"):
            return
        cands = g.methods_named.get(attr, ())
        if 0 < len(cands) <= MAX_NAME_MATCH:
            for t in cands:
                g.add(s, t, "name_match")
