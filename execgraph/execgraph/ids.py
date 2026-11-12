"""Node ids in the competition graph format: dotted `module.Class.method`, module from the repo-relative path.

Same rules as the skill's tracer (`submission/skills/exec-graph/scripts/_tracer.py`): `src/`, `lib/` and
`docs_src/` prefixes dropped, `__init__` dropped, nested functions folded into their enclosing function.
"""
import posixpath


def module_of(relpath: str) -> str:
    rel = relpath.replace("\\", "/")
    if rel.endswith(".py"):
        rel = rel[:-3]
    parts = rel.split("/")
    if parts[0] in ("src", "lib", "docs_src") and len(parts) > 1:
        parts = parts[1:]
    if parts[-1] == "__init__" and len(parts) > 1:
        parts = parts[:-1]
    return ".".join(parts)


def is_test_path(relpath: str) -> bool:
    rel = relpath.replace("\\", "/")
    base = posixpath.basename(rel)
    parts = rel.split("/")
    return (base.startswith("test_") or base.endswith("_test.py") or base == "conftest.py"
            or any(p in ("tests", "test", "testing") for p in parts[:-1]))


def is_test_node(node_id: str) -> bool:
    parts = node_id.split(".")
    return any(p in ("tests", "test", "conftest") or p.startswith("test_") for p in parts)
