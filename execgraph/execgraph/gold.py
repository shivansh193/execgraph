"""Gold localisation labels: the functions a reference patch edits, as competition node ids.

A changed line maps to the innermost `def`/`class` containing it in the pre-patch file. An insertion maps to the
def containing the line it follows. Lines outside every def are module-level edits; functions that exist only
after the patch are new code. Both are recorded separately, since no ranking over existing nodes can find them.
"""
import ast
import re
from dataclasses import dataclass, field

from .ids import is_test_path, module_of

HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass
class FileEdit:
    path: str
    old_lines: set = field(default_factory=set)     # pre-patch line numbers removed or edited around
    added_after: set = field(default_factory=set)   # pre-patch line numbers that an insertion follows
    new_file: bool = False
    deleted: bool = False


def parse_patch(patch: str) -> dict:
    """Unified diff -> {path: FileEdit}, using pre-patch line numbers."""
    edits, cur, old_no, pending_add = {}, None, 0, False
    for line in patch.splitlines():
        if line.startswith("--- "):
            src = line[4:].split("\t")[0]
            cur_old = None if src == "/dev/null" else src[2:] if src.startswith("a/") else src
            continue
        if line.startswith("+++ "):
            dst = line[4:].split("\t")[0]
            new = None if dst == "/dev/null" else dst[2:] if dst.startswith("b/") else dst
            path = new or cur_old
            cur = edits.setdefault(path, FileEdit(path))
            cur.new_file = cur_old is None
            cur.deleted = new is None
            continue
        m = HUNK.match(line)
        if m:
            old_no, pending_add = int(m.group(1)), False
            if m.group(2) == "0":       # pure insertion after line `old_no`
                old_no += 1
            continue
        if cur is None or not line or line[0] not in " -+":
            continue
        if line[0] == " ":
            old_no += 1
        elif line[0] == "-":
            cur.old_lines.add(old_no)
            old_no += 1
        else:
            cur.added_after.add(max(old_no - 1, 1))
    return edits


def def_spans(source: str, module: str) -> list:
    """[(start, end, node id, kind)] for every def/class, nested defs folded into the outermost function."""
    out = []

    def visit(body, prefix, in_func):
        for n in body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                start = min([n.lineno] + [d.lineno for d in n.decorator_list])
                nid = f"{prefix}.{n.name}"
                if not in_func:
                    out.append((start, n.end_lineno, nid, "class" if isinstance(n, ast.ClassDef) else "function"))
                visit(n.body, nid if not in_func else prefix,
                      in_func or not isinstance(n, ast.ClassDef))
            elif hasattr(n, "body") and isinstance(getattr(n, "body"), list):
                # if/try/with at module or class level can hold defs
                for attr in ("body", "orelse", "finalbody", "handlers"):
                    sub = getattr(n, attr, None)
                    if isinstance(sub, list):
                        visit(sub, prefix, in_func)

    visit(ast.parse(source).body, module, False)
    return out


def innermost(spans, line):
    best = None
    for s, e, nid, kind in spans:
        if s <= line <= e and (best is None or e - s < best[1] - best[0]):
            best = (s, e, nid, kind)
    return best


@dataclass
class Gold:
    nodes: set            # existing functions/methods (and classes edited in their own body) the patch touches
    files: set            # non-test .py files edited
    module_level: set     # files with edits outside every def
    new_only: set         # files whose edits are all new files
    test_files: set


def gold_from_patch(patch: str, read_old) -> Gold:
    """`read_old(path)` returns the pre-patch source of `path`, or None."""
    g = Gold(set(), set(), set(), set(), set())
    for path, fe in parse_patch(patch).items():
        if not path.endswith(".py"):
            continue
        if is_test_path(path):
            g.test_files.add(path)
            continue
        g.files.add(path)
        if fe.new_file:
            g.new_only.add(path)
            continue
        src = read_old(path)
        if src is None:
            continue
        try:
            spans = def_spans(src, module_of(path))
        except SyntaxError:
            continue
        for line in fe.old_lines | fe.added_after:
            hit = innermost(spans, line)
            if hit is None:
                g.module_level.add(path)
            else:
                g.nodes.add(hit[2])
    return g
