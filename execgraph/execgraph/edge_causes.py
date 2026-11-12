"""Why a static graph misses a runtime call edge.

`classify(sg, caller, callee)` looks at the caller's source (via `static_ast` facts) and names the first cause
that explains the edge, in this order:

    import_time            caller is a module or class body (decorators, registrations, class creation)
    implicit_constructor   callee is __init__/__new__/__post_init__ and the caller builds an instance
    dunder_protocol        callee is another dunder: operators, `with`, iteration, attribute hooks, __call__
    inheritance_dispatch   caller calls self.<name>/cls.<name>/super().<name>; the callee is an override elsewhere
    attribute_dispatch     caller calls <expr>.<name> on a receiver of unknown type
    unresolved_name        caller calls <name>(...) but the name didn't resolve (star/conditional imports)
    runtime_import         caller imports inside its body
    property_descriptor    caller reads .<name> without calling it and the callee is a property/descriptor
    callback_reference     caller passes <name> as a value (argument, registration, stored callable)
    callback_parameter     caller calls one of its own parameters
    reflection             getattr / importlib / __dict__ / eval in the caller
    decorator_wrapper      callee is decorated, or the caller is a decorator's wrapper
    indirect_via_library   no trace of the callee in the caller: the call went through library code
                           (framework dispatch, pydantic validators, stdlib callbacks) that the tracer skips
"""
CONSTRUCTORS = {"__init__", "__new__", "__post_init__", "__init_subclass__", "__set_name__", "__class_getitem__"}
PROPERTY_DECOS = ("property", "cached_property", "setter", "getter", "computed_field")

CAUSES = ("import_time", "implicit_constructor", "dunder_protocol", "inheritance_dispatch", "attribute_dispatch",
          "unresolved_name", "runtime_import", "property_descriptor", "callback_reference", "callback_parameter",
          "reflection", "decorator_wrapper", "indirect_via_library")


def classify(sg, caller: str, callee: str) -> str:
    d = sg.defs.get(caller)
    short = callee.rsplit(".", 1)[-1]
    target = sg.defs.get(callee)
    if d is None or d.kind == "class":
        return "import_time"
    s = d.sites
    if short in CONSTRUCTORS:
        return "implicit_constructor"
    if short.startswith("__") and short.endswith("__"):
        return "dunder_protocol"
    recv = {k for k, a in s.attr_calls if a == short}
    if recv & {"self", "cls", "super"}:
        return "inheritance_dispatch"
    if recv:
        return "attribute_dispatch"
    if short in s.name_calls:
        return "runtime_import" if s.local_imports else "unresolved_name"
    if target is not None and target.kind == "class" and short in s.name_calls | {a for _, a in s.attr_calls}:
        return "implicit_constructor"
    if short in s.attr_loads and target is not None and any(
            x.split("(")[0].split(".")[-1] in PROPERTY_DECOS for x in target.decorators):
        return "property_descriptor"
    if short in s.refs:
        return "callback_reference"
    if s.called_params:
        return "callback_parameter"
    if s.reflection:
        return "reflection"
    if (target is not None and target.decorators) or (s.inner_defs and s.called_params):
        return "decorator_wrapper"
    if s.local_imports:
        return "runtime_import"
    return "indirect_via_library"


def missed(runtime_edges, static_edges, undirected=True):
    """Runtime edges absent from a static edge set (optionally ignoring direction, since the competition graph
    mixes call, containment and inheritance edges)."""
    st = set(static_edges)
    if undirected:
        st |= {(b, a) for a, b in st}
    return [e for e in runtime_edges if e not in st]
