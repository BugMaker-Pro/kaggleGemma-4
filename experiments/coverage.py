"""Match gold symbols against the node ids of a shipped code graph.

Three outcomes matter, and they are not interchangeable:
  exact        the symbol is in the graph, under its full dotted path
  suffix       the graph has it under a different module prefix
  module_only  the file is represented, but this symbol is missing
  miss         nothing from this module is in the graph at all

Collapsing these into one "coverage" number would hide the interesting part.
"""

from __future__ import annotations

MATCH_EXACT = "exact"
MATCH_SUFFIX = "suffix"
MATCH_MODULE_ONLY = "module_only"
MATCH_MISS = "miss"


def module_prefix(file_path: str) -> str:
    """'pkg/__init__.py' -> 'pkg'; 'pkg/mod.py' -> 'pkg.mod'."""
    path = file_path.replace("\\", "/").strip().strip("/")
    if path.endswith(".py"):
        path = path[:-3]
    parts = [part for part in path.split("/") if part not in ("", ".")]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def candidate_ids(file_path: str, qualname: str | None) -> list[str]:
    """Plausible fully-qualified ids for a gold symbol, most specific first."""
    module = module_prefix(file_path)
    out: list[str] = []
    if qualname:
        out.append(f"{module}.{qualname}" if module else qualname)
        leaf = qualname.split(".")[-1]
        if leaf != qualname:
            out.append(f"{module}.{leaf}" if module else leaf)
    elif module:
        out.append(module)
    return list(dict.fromkeys(out))


def nodes_in_module(node_ids: set[str], module: str) -> int:
    if not module:
        return 0
    return sum(1 for node_id in node_ids if node_id == module or node_id.startswith(module + "."))


def classify(
    file_path: str,
    qualname: str | None,
    node_ids: set[str],
) -> tuple[str, int]:
    """Return (match kind, nodes present in this module)."""
    module = module_prefix(file_path)
    in_module = nodes_in_module(node_ids, module)
    candidates = candidate_ids(file_path, qualname)

    if any(candidate in node_ids for candidate in candidates):
        return MATCH_EXACT, in_module

    if qualname:
        for candidate in candidates:
            if "." not in candidate:
                continue
            needle = "." + candidate
            if any(node_id.endswith(needle) for node_id in node_ids):
                return MATCH_SUFFIX, in_module

    if in_module:
        return MATCH_MODULE_ONLY, in_module
    return MATCH_MISS, in_module
