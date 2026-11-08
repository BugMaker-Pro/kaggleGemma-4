"""Rebuild a definition + reference graph from a source snapshot.

The output deliberately uses the *same* JSON shape as the code graphs shipped
with the competition data -- `{"directed", "multigraph", "graph",
"nodes"[{id, name, text}], "edges"[{source, target, type, key}]}` -- so that one
reader and one coverage metric apply to both, and so this file can be used as a
drop-in replacement for the released assets.

Everything below is stdlib. No tree-sitter, no networkx.

Node ids are `<module>.<qualname>` where the module is the repo-relative path
without `.py`, i.e. exactly what `coverage.module_prefix` computes from a patch
header. A symbol in `sympy/core/expr.py` is `sympy.core.expr.Symbol`.

Reference edges carry a `resolution` field: local / import / unique / suffix are
real resolutions; external means the target lives outside the repository
(stdlib or a third-party dependency, not a defect); ambiguous and unresolved are
the two failure modes we report.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
import warnings
from pathlib import Path

try:
    from .symbols import Symbol, python_symbols
except ImportError:  # running as a script
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from experiments.symbols import Symbol, python_symbols

SKIP_DIRS = {
    ".git", ".hg", ".svn", ".tox", ".nox", ".venv", "venv", "env",
    "node_modules", "__pycache__", "build", "dist", ".eggs", "site-packages",
    ".mypy_cache", ".pytest_cache", "htmlcov", ".idea",
}

EDGE_DEFINES = "defines"
EDGE_IMPORTS = "imports"
EDGE_CALLS = "calls"
EDGE_INHERITS = "inherits"

# how a reference target was found
R_LOCAL = "local"
R_IMPORT = "import"
R_UNIQUE = "unique"
R_SUFFIX = "suffix"
R_EXTERNAL = "external"
R_AMBIGUOUS = "ambiguous"
R_UNRESOLVED = "unresolved"

STDLIB = set(sys.stdlib_module_names)

# Above this many nodes sharing a leaf name, name-based resolution is a guess.
MAX_AMBIGUOUS = 64


def _keep_python(name: str) -> bool:
    if not name.endswith(".py"):
        return False
    return not any(part in SKIP_DIRS for part in name.split("/")[:-1])


def iter_python_files(names: list[str]) -> list[str]:
    return sorted(name for name in names if _keep_python(name))


def module_of(path: str) -> str:
    stem = path[:-3] if path.endswith(".py") else path
    parts = [p for p in stem.split("/") if p not in ("", ".")]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _is_stdlib(dotted: str) -> bool:
    return dotted.split(".")[0] in STDLIB


class Graph:
    def __init__(self) -> None:
        self.nodes: dict[str, dict] = {}
        self.edges: list[dict] = []
        self.by_leaf: dict[str, list[str]] = {}

    def add_node(self, node_id: str, name: str, kind: str, file: str, lineno: int,
                 end_lineno: int, signature: str, doc: str, text: str | None) -> None:
        if node_id in self.nodes:
            return
        self.nodes[node_id] = {
            "id": node_id,
            "name": name,
            "kind": kind,
            "file": file,
            "lineno": lineno,
            "end_lineno": end_lineno,
            "signature": signature,
            "doc": doc,
            "text": text,
        }
        self.by_leaf.setdefault(name, []).append(node_id)

    def add_edge(self, source: str, target: str, kind: str, resolution: str) -> None:
        self.edges.append(
            {"source": source, "target": target, "type": kind, "key": 0,
             "resolution": resolution}
        )


def _signature(node: ast.AST, source: str) -> str:
    """`def f(a, b=1) -> int` -- the header, without the body."""
    if isinstance(node, ast.ClassDef):
        bases = [_dotted(b) for b in node.bases]
        return f"class {node.name}({', '.join(b for b in bases if b)})" if bases else f"class {node.name}"
    args = node.args
    parts = [a.arg for a in args.posonlyargs] + [a.arg for a in args.args]
    if args.vararg:
        parts.append("*" + args.vararg.arg)
    elif args.kwonlyargs:
        parts.append("*")
    parts += [a.arg for a in args.kwonlyargs]
    if args.kwarg:
        parts.append("**" + args.kwarg.arg)
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    return f"{prefix} {node.name}({', '.join(parts)})"


def _doc(node: ast.AST) -> str:
    try:
        doc = ast.get_docstring(node) or ""
    except (TypeError, ValueError):
        return ""
    return doc.strip().split("\n\n")[0][:400]


def _dotted(node: ast.AST) -> str:
    """Flatten `a.b.c` into 'a.b.c'; '' for anything else."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        left = _dotted(node.value)
        return f"{left}.{node.attr}" if left else node.attr
    return ""


def _imports(tree: ast.AST, module: str) -> dict[str, str]:
    """Local alias -> dotted target, best effort.

    `from . import x` and `from .sub import y` are resolved against the current
    module's package. Star imports are ignored: guessing them would pollute the
    ambiguity statistics.
    """
    package = module.rsplit(".", 1)[0] if "." in module else ""
    aliases: dict[str, str] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    aliases[alias.asname] = alias.name
                else:
                    head = alias.name.split(".")[0]
                    aliases[head] = head
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parts = package.split(".") if package else []
                drop = node.level - 1
                if drop:
                    parts = parts[:-drop] if drop < len(parts) else []
                base = ".".join([p for p in parts if p] + ([base] if base else []))
            for alias in node.names:
                if alias.name == "*":
                    continue
                target = f"{base}.{alias.name}" if base else alias.name
                aliases[alias.asname or alias.name] = target
    return aliases


def build_graph(
    files: dict[str, str],
    module_root: str = "",
    keep_text: bool = False,
    text_limit: int = 1200,
) -> tuple[Graph, dict]:
    """Build the graph from a mapping of repo-relative path -> source text."""
    stats = {"files": 0, "parsed": 0, "syntax_error": 0, "nodes": 0, "edges": 0}

    parsed: dict[str, tuple[str, ast.AST, list[Symbol]]] = {}
    for path in sorted(files):
        stats["files"] += 1
        source = files[path]
        if source is None:
            stats["syntax_error"] += 1
            continue
        try:
            with warnings.catch_warnings():
                # legacy escape sequences in old source are not our business
                warnings.simplefilter("ignore", SyntaxWarning)
                tree = ast.parse(source)
        except (SyntaxError, ValueError):
            stats["syntax_error"] += 1
            continue
        module = module_of(path)
        if module_root and module.startswith(module_root + "."):
            module = module[len(module_root) + 1:]
        parsed[path] = (module, tree, python_symbols(source, tree))
        stats["parsed"] += 1

    graph = Graph()
    defs = {path: _def_index(tree) for path, (_, tree, _) in parsed.items()}

    # 1. nodes: one per def/class, plus one per module
    for path, (module, tree, symbols) in parsed.items():
        source = files[path]
        if module:
            graph.add_node(module, module.rsplit(".", 1)[-1], "module", path, 1,
                           len(source.splitlines()), "", _doc(tree),
                           source[:text_limit] if keep_text else None)
        for sym in symbols:
            node_id = f"{module}.{sym.qualname}" if module else sym.qualname
            text = None
            if keep_text:
                lines = source.splitlines()
                text = "\n".join(lines[sym.lineno - 1:sym.end_lineno])[:text_limit]
            ast_node = defs[path].get((sym.name, sym.lineno))
            graph.add_node(
                node_id, sym.name, sym.kind, path, sym.lineno, sym.end_lineno,
                _signature(ast_node, source) if ast_node is not None else sym.name,
                _doc(ast_node) if ast_node is not None else "", text,
            )
    stats["nodes"] = len(graph.nodes)

    # 2. parent -> child, so the graph is a real tree rather than a star
    for path, (module, tree, symbols) in parsed.items():
        for sym in symbols:
            target = f"{module}.{sym.qualname}" if module else sym.qualname
            if target in graph.nodes:
                graph.add_edge(target.rsplit(".", 1)[0], target, EDGE_DEFINES, R_LOCAL)

    # 3. imports, 4. inherits, 5. calls
    all_modules = {module for module, _, _ in parsed.values()}
    node_ids = set(graph.nodes)
    for path, (module, tree, symbols) in parsed.items():
        aliases = _imports(tree, module)

        for target in aliases.values():
            if target in node_ids or target in all_modules:
                graph.add_edge(module, target, EDGE_IMPORTS, R_IMPORT)
            elif _is_stdlib(target):
                graph.add_edge(module, target, EDGE_IMPORTS, R_EXTERNAL)
            else:
                graph.add_edge(module, target, EDGE_IMPORTS, R_UNRESOLVED)

        for sym in symbols:
            ast_node = defs[path].get((sym.name, sym.lineno))
            if ast_node is None:
                continue
            source_id = f"{module}.{sym.qualname}" if module else sym.qualname
            if isinstance(ast_node, ast.ClassDef):
                for base in ast_node.bases:
                    dotted = _dotted(base)
                    if not dotted:
                        continue
                    target, why = _resolve(dotted, module, aliases, all_modules,
                                           graph.by_leaf, node_ids)
                    graph.add_edge(source_id, target, EDGE_INHERITS, why)
            for call in _calls_in(ast_node):
                dotted = _dotted(call.func)
                if not dotted:
                    continue
                target, why = _resolve(dotted, module, aliases, all_modules,
                                       graph.by_leaf, node_ids)
                graph.add_edge(source_id, target, EDGE_CALLS, why)

    stats["edges"] = len(graph.edges)
    return graph, stats


def _calls_in(node: ast.AST) -> list[ast.Call]:
    found: list[ast.Call] = []
    stack = [node]
    while stack:
        cur = stack.pop()
        for child in ast.iter_child_nodes(cur):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and child is not node:
                continue  # do not attribute a nested def's calls to its parent
            if isinstance(child, ast.Call):
                found.append(child)
            stack.append(child)
    return found


def _def_index(tree: ast.AST) -> dict[tuple[str, int], ast.AST]:
    """(name, lineno) -> def node, so symbol lookup is O(1) per symbol."""
    index: dict[tuple[str, int], ast.AST] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            index.setdefault((node.name, node.lineno), node)
    return index


def _find_def(tree: ast.AST, sym: Symbol) -> ast.AST | None:
    return _def_index(tree).get((sym.name, sym.lineno))


def _resolve(dotted: str, module: str, aliases: dict[str, str],
             all_modules: set[str], by_leaf: dict[str, list[str]],
             node_ids: set[str]) -> tuple[str, str]:
    """Return (target, resolution). Target may be a raw dotted name if external.

    Every membership test goes through a set or a dict: `by_leaf` buckets are
    sorted-by-popularity in practice (`__init__`, `update`, `save` have hundreds
    of candidates), so scanning them per call site turns a repository-wide build
    into a quadratic one.
    """
    head, _, rest = dotted.partition(".")
    leaf = dotted.rsplit(".", 1)[-1]

    # 1. an imported name
    base = aliases.get(head)
    if base is not None:
        target = f"{base}.{rest}" if rest else base
        if target in node_ids or target in all_modules:
            return target, R_IMPORT
        parent = target.rsplit(".", 1)[0] if rest else ""
        if parent and parent in all_modules:
            return target, R_IMPORT
        if _is_stdlib(base) or _is_stdlib(head):
            return target, R_EXTERNAL
        if _has_suffix(by_leaf, target, MAX_AMBIGUOUS):
            return target, R_IMPORT
        return target, R_UNRESOLVED

    # 2. a definition in this very module (function or class, possibly nested)
    local_id = f"{module}.{dotted}" if module else dotted
    if local_id in node_ids:
        return local_id, R_LOCAL

    # 3. a leaf name that exists exactly once in the repository
    candidates = by_leaf.get(leaf, [])
    if len(candidates) == 1:
        return candidates[0], R_UNIQUE
    if len(candidates) > MAX_AMBIGUOUS:
        return "", R_AMBIGUOUS
    if candidates:
        # prefer one inside the same top-level package (cheap, and right often)
        top = (module.split(".")[0] + ".") if "." in module else ""
        same = [c for c in candidates if top and c.startswith(top)]
        if len(same) == 1:
            return same[0], R_UNIQUE
        return "", R_AMBIGUOUS

    if _is_stdlib(head):
        return dotted, R_EXTERNAL
    return dotted, R_UNRESOLVED


def _has_suffix(by_leaf: dict[str, list[str]], dotted: str, cap: int = 64) -> bool:
    """True if some node id is `dotted`, or ends with `.dotted` (src/ layouts)."""
    leaf = dotted.rsplit(".", 1)[-1]
    candidates = by_leaf.get(leaf, [])
    if len(candidates) > cap:
        return False                       # too common to disambiguate; don't scan
    return any(c == dotted or c.endswith("." + dotted) for c in candidates)


def to_json(graph: Graph) -> dict:
    return {
        "directed": True,
        "multigraph": True,
        "graph": {"builder": "experiments.buildgraph", "schema": 1},
        "nodes": list(graph.nodes.values()),
        "edges": graph.edges,
    }


def read_snapshot(path: str | Path, module_root: str = "") -> dict[str, str]:
    try:
        from .snapshot import Snapshot
    except ImportError:
        from experiments.snapshot import Snapshot
    with Snapshot(path) as snap:
        return snap.read_all_text(_keep_python)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Rebuild a code graph from a snapshot")
    ap.add_argument("--snapshot", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--module-root", default="")
    ap.add_argument("--text", action="store_true", help="embed symbol source in nodes")
    args = ap.parse_args(argv)

    files = read_snapshot(args.snapshot, args.module_root)
    graph, stats = build_graph(files, args.module_root, keep_text=args.text)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    payload = to_json(graph)
    args.out.write_text(json.dumps(payload), encoding="utf-8")

    by_type: dict[str, int] = {}
    by_res: dict[str, int] = {}
    for e in graph.edges:
        by_type[e["type"]] = by_type.get(e["type"], 0) + 1
        by_res[e["resolution"]] = by_res.get(e["resolution"], 0) + 1
    print(json.dumps({"stats": stats, "edges_by_type": by_type,
                      "edges_by_resolution": by_res}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
