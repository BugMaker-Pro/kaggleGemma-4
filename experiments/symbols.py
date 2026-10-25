"""Resolve a source line to its enclosing Python symbol.

Used as the denominator of every coverage number in the paper, so it is
deliberately conservative: unknown means None, never a guess.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass


@dataclass(frozen=True)
class Symbol:
    name: str
    qualname: str
    kind: str  # "function" | "async_function" | "class" | "method"
    lineno: int
    end_lineno: int
    depth: int


_KIND = {
    ast.FunctionDef: "function",
    ast.AsyncFunctionDef: "async_function",
    ast.ClassDef: "class",
}


def python_symbols(source: str, tree: ast.AST | None = None) -> list[Symbol]:
    """Return every def/class in the file, innermost-last. Empty on syntax error.

    Pass `tree` when the caller already parsed the file; the graph builder does,
    and on a 3,000-file repository parsing twice is the difference between a
    five-second and a ten-second build.
    """
    if tree is None:
        try:
            tree = ast.parse(source)
        except (SyntaxError, ValueError):
            return []

    found: list[Symbol] = []

    def walk(node: ast.AST, prefix: str, depth: int, in_class: bool) -> None:
        for child in ast.iter_child_nodes(node):
            kind = _KIND.get(type(child))
            if kind is None:
                walk(child, prefix, depth, in_class)
                continue

            name = getattr(child, "name", "")
            qualname = f"{prefix}.{name}" if prefix else name
            if kind != "class" and in_class:
                kind = "method"
            end = getattr(child, "end_lineno", None) or child.lineno
            found.append(Symbol(name, qualname, kind, child.lineno, end, depth))
            walk(child, qualname, depth + 1, kind == "class")

    walk(tree, "", 0, False)
    found.sort(key=lambda s: (s.lineno, -s.depth))
    return found


def resolve(symbols: list[Symbol], line: int) -> Symbol | None:
    """Innermost symbol whose body contains `line`."""
    best: Symbol | None = None
    for sym in symbols:
        if sym.lineno <= line <= sym.end_lineno:
            if best is None or (sym.depth, sym.lineno) >= (best.depth, best.lineno):
                best = sym
    return best


def language_of(path: str) -> str:
    lowered = path.lower()
    if lowered.endswith(".py"):
        return "python"
    if lowered.endswith((".pyx", ".pxd")):
        return "cython"
    return "other"
