"""Runtime-evidence localization: turn a failing test's traceback into a definition.

This is the first, pure-function layer of the runtime-evidence router.  It does
not run anything: it parses a saved pytest output, keeps the source frames (not
the test frames), resolves the innermost definition containing the last source
line, and renders a short report the repair prompt can consume.

The design is deliberately conservative: an unmapped frame stays a file:line
rather than a guessed symbol, and a missing test output produces an explicit
error string instead of an empty success.

    python tools/failure_prelocalize.py --help
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

FRAME = re.compile(r'File "(?P<path>[^"]+)", line (?P<line>\d+), in (?P<func>.+?)\s*$')
SHORT_FRAME = re.compile(r"^(?P<path>[^\s:]+\.py):(?P<line>\d+): in (?P<func>.+?)\s*$", re.M)
FAILED = re.compile(r"^FAILED\s+(?P<test>\S+)\s*(?:-\s*(?P<reason>.*))?$", re.M)
ERROR_BLOCK = re.compile(r"^E\s{2,}(?P<message>.+?)\s*$", re.M)
TEST_PATH = re.compile(r"(^|/)(tests?|testing)/|(^|/)test_[^/]*\.py$|_test\.py$|conftest\.py$")


@dataclass(frozen=True)
class Frame:
    path: str
    line: int
    func: str


@dataclass(frozen=True)
class FailureEvidence:
    tests: tuple[str, ...] = ()
    frames: tuple[Frame, ...] = ()
    message: str = ""


def parse_pytest_output(text: str) -> FailureEvidence:
    """Extract failing test ids, traceback frames, and the last E-block message.

    Supports both Python's ``File "...", line N, in f`` frames and pytest's
    short ``path.py:line: in f`` report lines; long-format frames win when both
    appear for the same location because the latter has no absolute path.
    """
    found: list[tuple[int, Frame]] = []
    for match in FRAME.finditer(text):
        found.append((match.start(), Frame(match.group("path"), int(match.group("line")),
                                           match.group("func").strip())))
    for match in SHORT_FRAME.finditer(text):
        found.append((match.start(), Frame(match.group("path"), int(match.group("line")),
                                           match.group("func").strip())))
    frames = tuple(frame for _, frame in sorted(found, key=lambda pair: pair[0]))
    tests = tuple(dict.fromkeys(match.group("test") for match in FAILED.finditer(text)))
    messages = [match.group("message").strip() for match in ERROR_BLOCK.finditer(text)]
    return FailureEvidence(tests=tests, frames=frames, message=messages[-1] if messages else "")


def is_test_path(path: str) -> bool:
    return bool(TEST_PATH.search(path.replace("\\", "/")))


def source_frames(evidence: FailureEvidence, root: str = "/workspace") -> list[Frame]:
    """Frames inside the workspace that are not test files, outermost-first.

    Pytest may print absolute paths or paths relative to the repository root;
    both are accepted, and the original spelling is preserved for the report.
    """
    prefix = root.rstrip("/") + "/"
    selected = []
    for frame in evidence.frames:
        path = frame.path.replace("\\", "/")
        candidate = path if path.startswith(prefix) else (prefix + path if not path.startswith("/") else path)
        if not candidate.startswith(prefix) or is_test_path(candidate):
            continue
        selected.append(frame)
    return selected


def module_name(path: str, root: str = "/workspace") -> str:
    relative = path.replace("\\", "/")
    prefix = root.rstrip("/") + "/"
    if relative.startswith(prefix):
        relative = relative[len(prefix):]
    return relative.removesuffix(".py").replace("/", ".")


def resolve_definition(source: str, line: int) -> dict[str, object] | None:
    """Innermost def/class containing `line`, using the repository's own parser."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from experiments.symbols import python_symbols, resolve  # noqa: PLC0415

    symbol = resolve(python_symbols(source), line)
    if symbol is None:
        return None
    return {
        "qualname": symbol.qualname,
        "kind": symbol.kind,
        "start_line": symbol.lineno,
        "end_line": symbol.end_lineno,
    }


def format_report(evidence: FailureEvidence, frame: Frame | None, definition: dict[str, object] | None,
                  root: str = "/workspace") -> str:
    if not evidence.tests and not evidence.frames:
        return "runtime error: no failing-test evidence parsed"
    test = evidence.tests[0] if evidence.tests else "unknown test"
    lines = [f"runtime evidence: {test} failed"]
    if frame is not None:
        lines.append(f"last source frame: {frame.path}:{frame.line} in {frame.func}()")
        if definition is not None:
            qualname = definition["qualname"]
            lines.append(
                f"definition: {module_name(frame.path, root)}.{qualname} "
                f"({frame.path}:{definition['start_line']}-{definition['end_line']})"
            )
    if evidence.message:
        lines.append(f"error: {evidence.message[:400]}")
    return "\n".join(lines)


def build_test_command(test_ids: Sequence[str], log: str = "/tmp/failure-log.txt") -> str:
    """Run the selected FAIL_TO_PASS nodes and keep their failure output.

    The nodes are expected to fail before the repair; a non-zero exit is the
    normal outcome, so the command appends a marker instead of using ``set -e``.
    """
    nodes = [str(node).strip() for node in test_ids if str(node).strip()]
    if not nodes:
        raise ValueError("at least one FAIL_TO_PASS node id is required")
    return (
        "cd /workspace && python3 -m pytest -q --tb=long -p no:cacheprovider "
        + " ".join(shlex.quote(node) for node in nodes)
        + f" > {log} 2>&1; echo FAIL_EXIT:$?"
    )


def build_coverage_command(test_ids: Sequence[str], out: str = "/tmp/coverage.json") -> str:
    """Run FAIL_TO_PASS under pytest-cov so assertions in the test still execute source."""
    nodes = [str(node).strip() for node in test_ids if str(node).strip()]
    if not nodes:
        raise ValueError("at least one FAIL_TO_PASS node id is required")
    return (
        "cd /workspace && python3 -m pytest -q --tb=short -p no:cacheprovider "
        f"--cov=. --cov-report=json:{out} "
        + " ".join(shlex.quote(node) for node in nodes)
        + f" > /tmp/coverage-run.log 2>&1; echo COV_EXIT:$?"
    )


def parse_coverage_json(text: str) -> dict[str, set[int]]:
    """Executed line numbers per source file from a coverage.py JSON report."""
    payload = json.loads(text)
    executed: dict[str, set[int]] = {}
    for path, record in (payload.get("files") or {}).items():
        lines = {int(line) for line in (record.get("executed_lines") or [])}
        if lines:
            executed[path.replace("\\", "/")] = lines
    return executed


def coverage_scores(source: str, executed: set[int]) -> list[dict[str, object]]:
    """Executed-span fraction for every def/class in one source file."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from experiments.symbols import python_symbols  # noqa: PLC0415

    scored = []
    for symbol in python_symbols(source):
        span = symbol.end_lineno - symbol.lineno + 1
        hit = sum(1 for line in executed if symbol.lineno <= line <= symbol.end_lineno)
        scored.append({
            "qualname": symbol.qualname,
            "kind": symbol.kind,
            "start_line": symbol.lineno,
            "end_line": symbol.end_lineno,
            "executed_lines": hit,
            "span_lines": span,
            "score": hit / span if span else 0.0,
        })
    scored.sort(key=lambda item: (-item["score"], -item["executed_lines"], item["start_line"]))
    return scored


def fuse_scores(static: Mapping[str, float], coverage: Mapping[str, float], weight: float = 0.5) -> dict[str, float]:
    """Min-max fuse two score families; one source alone contributes its normalized score."""
    if not 0.0 <= weight <= 1.0:
        raise ValueError("weight must be in [0, 1]")

    def normalize(values: Mapping[str, float]) -> dict[str, float]:
        if not values:
            return {}
        low, high = min(values.values()), max(values.values())
        if high <= low:
            return {key: 0.0 for key in values}
        return {key: (value - low) / (high - low) for key, value in values.items()}

    static_n, coverage_n = normalize(static), normalize(coverage)
    keys = set(static_n) | set(coverage_n)
    fused = {}
    for key in keys:
        if key in static_n and key in coverage_n:
            fused[key] = weight * static_n[key] + (1.0 - weight) * coverage_n[key]
        elif key in static_n:
            fused[key] = weight * static_n[key]
        else:
            fused[key] = (1.0 - weight) * coverage_n[key]
    return dict(sorted(fused.items(), key=lambda pair: -pair[1]))


def format_coverage_report(scored: list[dict[str, object]], limit: int = 5) -> str:
    if not scored:
        return "coverage error: no executed definitions parsed"
    lines = ["runtime coverage: definitions executed by the failing test"]
    for item in scored[:limit]:
        lines.append(
            f"{item['qualname']} {item['start_line']}-{item['end_line']} "
            f"executed {item['executed_lines']}/{item['span_lines']} ({item['score']:.2f})"
        )
    return "\n".join(lines)


def ochiai_score(fail_executed: int, pass_executed: int, span_lines: int) -> float:
    """Ochiai suspiciousness from executed-line counts in one definition.

    ``fail_executed`` lines are hit by the failing test, ``pass_executed`` by a
    passing control; ``span_lines`` is the definition length. An all-fail
    definition scores 1; one executed equally by both scores 0.5.
    """
    not_executed = max(span_lines - fail_executed, 0)
    denominator = ((fail_executed + not_executed) * (fail_executed + pass_executed)) ** 0.5
    return fail_executed / denominator if denominator else 0.0


def suspiciousness_scores(fail_coverage: Mapping[str, set[int]], pass_coverage: Mapping[str, set[int]],
                          source_reader) -> list[dict[str, object]]:
    """Definition-level Ochiai scores from failing and passing coverage maps."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from experiments.symbols import python_symbols  # noqa: PLC0415

    scored = []
    for path in sorted(set(fail_coverage) | set(pass_coverage)):
        source = source_reader(path)
        if not source:
            continue
        fail_lines = fail_coverage.get(path, set())
        pass_lines = pass_coverage.get(path, set())
        for symbol in python_symbols(source):
            span = symbol.end_lineno - symbol.lineno + 1
            fail_hits = sum(1 for line in fail_lines if symbol.lineno <= line <= symbol.end_lineno)
            pass_hits = sum(1 for line in pass_lines if symbol.lineno <= line <= symbol.end_lineno)
            if not fail_hits:
                continue
            scored.append({
                "qualname": symbol.qualname,
                "key": f"{module_name(path)}.{symbol.qualname}",
                "start_line": symbol.lineno,
                "end_line": symbol.end_lineno,
                "fail_executed": fail_hits,
                "pass_executed": pass_hits,
                "score": ochiai_score(fail_hits, pass_hits, span),
            })
    scored.sort(key=lambda item: (-item["score"], -item["fail_executed"], item["start_line"]))
    return scored


def test_name_prior(test_ids: Sequence[str], candidates: Mapping[str, float]) -> dict[str, float]:
    """Cheap always-available prior: overlap between test ids and definition keys.

    Tokens come from the test file stem and test name (parameter brackets
    stripped).  This is intentionally weaker than a traceback: it is a routing
    prior for the majority of tasks where the failure has no source frame.
    """
    stop = {"test", "tests", "py", "src", "and", "the"}

    def tokenize(text: str) -> set[str]:
        return {part.lower() for part in re.split(r"[^A-Za-z0-9]+", text)
                if part and part.lower() not in stop}

    query: set[str] = set()
    for node in test_ids:
        test_file, _, test_name = str(node).partition("::")
        query |= tokenize(Path(test_file).stem.removeprefix("test_"))
        query |= tokenize(test_name.split("[")[0])
    if not query:
        return {}
    scored = {}
    for key in candidates:
        candidate_tokens = tokenize(key)
        overlap = len(query & candidate_tokens)
        if overlap:
            scored[key] = overlap / (len(candidate_tokens) ** 0.5 if candidate_tokens else 1.0)
    return dict(sorted(scored.items(), key=lambda pair: -pair[1]))


def build_runtime_report(failure_log: str, coverage: Mapping[str, set[int]] | None,
                         static: Mapping[str, float] | None, source_reader,
                         root: str = "/workspace", limit: int = 3,
                         pass_coverage: Mapping[str, set[int]] | None = None) -> str:
    """Merge traceback, executed-span coverage, and a static score family.

    `source_reader(path)` returns the source text or None; `static` keys are
    module-qualified definitions (``src.core.outer.inner``).  The report is
    deliberately short: one traceback definition, then the top coverage and
    fused definitions.  A missing signal degrades to the remaining signals
    rather than fabricating a location.
    """
    evidence = parse_pytest_output(failure_log)
    frames = source_frames(evidence, root)
    frame = frames[-1] if frames else None
    traceback_key = None
    traceback_text = None
    if frame is not None:
        source = source_reader(frame.path)
        if source:
            definition = resolve_definition(source, frame.line)
            if definition:
                key = f"{module_name(frame.path, root)}.{definition['qualname']}"
                traceback_key = key
                traceback_text = (f"{key} ({frame.path}:{definition['start_line']}-"
                                  f"{definition['end_line']})")

    coverage_map: dict[str, float] = {}
    label = "coverage"
    if coverage and pass_coverage:
        for item in suspiciousness_scores(coverage, pass_coverage, source_reader):
            coverage_map[str(item["key"])] = float(item["score"])
        label = "suspiciousness"
    elif coverage:
        for path, lines in coverage.items():
            source = source_reader(path)
            if not source:
                continue
            module = module_name(path, root)
            for item in coverage_scores(source, lines):
                coverage_map[f"{module}.{item['qualname']}"] = float(item["score"])

    fused = fuse_scores(static or {}, coverage_map) if (static or coverage_map) else {}

    lines = []
    if evidence.tests:
        lines.append(f"runtime evidence: {evidence.tests[0]} failed")
    else:
        lines.append("runtime evidence: no failing-test id parsed")
    if traceback_text:
        lines.append(f"traceback definition: {traceback_text}")
    elif frame is not None:
        lines.append(f"traceback frame: {frame.path}:{frame.line} in {frame.func}() (no definition mapped)")
    if evidence.message:
        lines.append(f"error: {evidence.message[:300]}")
    top_coverage = sorted(coverage_map.items(), key=lambda pair: -pair[1])[:limit]
    if top_coverage:
        lines.append(f"{label}: " + "; ".join(f"{key} {value:.2f}" for key, value in top_coverage))
    top_fused = list(fused.items())[:limit]
    if top_fused:
        lines.append("fused shortlist: " + "; ".join(f"{key} {value:.2f}" for key, value in top_fused))
    if not evidence.tests and not evidence.frames:
        return "runtime error: no failing-test evidence parsed"
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pytest-log", type=Path, required=True)
    ap.add_argument("--root", default="/workspace")
    args = ap.parse_args(argv)
    evidence = parse_pytest_output(args.pytest_log.read_text(encoding="utf-8", errors="replace"))
    frames = source_frames(evidence, args.root)
    frame = frames[-1] if frames else None
    definition = None
    if frame is not None:
        source_path = Path(frame.path)
        if source_path.is_file():
            definition = resolve_definition(source_path.read_text(encoding="utf-8", errors="replace"), frame.line)
    print(format_report(evidence, frame, definition, args.root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
