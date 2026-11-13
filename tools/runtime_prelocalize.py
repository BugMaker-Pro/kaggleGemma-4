"""Pre-session runtime-evidence hook: run the failing test, inject its frame.

**VALIDITY WARNING (2026-11-11).** On SWE-bench the `FAIL_TO_PASS` tests are
hidden: the harness applies `test_patch` only in the verification container,
after the agent. Running those tests before the session therefore requires the
hidden patch and is **test leakage**. Use this hook only when the task's tests
are visible in the agent workspace (existing tests, a user-provided
reproduction, or a benchmark whose protocol exposes them).

This is the harness-facing layer of the runtime-evidence router.  It mirrors
``tools/ranker_prelocalize.py``: before the repair session starts, it runs the
task's FAIL_TO_PASS tests in the sandbox, parses the failure log, resolves the
last source frame to a definition, and writes ``runtime_report`` into session
state.  The repair prompt opts in with ``{runtime_report}``; a failure produces
an explicit ``runtime error`` so the prompt can fall back to the static
localization report.

The pure parsing/resolution/report functions live in
``tools/failure_prelocalize.py`` and are unit-tested; this module only wires
them to the harness and is exercised on Kaggle.
"""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Any

from tools.failure_prelocalize import (
    build_coverage_command,
    build_test_command,
    coverage_scores,
    format_coverage_report,
    format_report,
    parse_coverage_json,
    parse_pytest_output,
    resolve_definition,
    source_frames,
)


MAX_FAIL_TO_PASS = 3


def report_from_failure_log(text: str, source_reader, root: str = "/workspace") -> str:
    """Parse one pytest log and render the traceback report (pure, testable)."""
    evidence = parse_pytest_output(text)
    frames = source_frames(evidence, root)
    frame = frames[-1] if frames else None
    definition = None
    if frame is not None:
        source = source_reader(frame.path)
        if source:
            definition = resolve_definition(source, frame.line)
    return format_report(evidence, frame, definition, root)


def install(work_dir: Path, coverage: bool = False) -> None:
    """Patch the harness in-process. Call once, before evaluation begins."""
    from google.adk.sessions import InMemorySessionService
    from swegemma.context import SwegemmaContext
    from swegemma.evaluate import Evaluator
    from swegemma.sandbox.base import sandbox_exec

    state: dict[str, Any] = {'arm_is_runtime': False, 'pending': {}}

    def _prompt_requests_runtime(submission: Path) -> bool:
        prompt = submission / 'prompts' / 'system.md'
        try:
            return '{runtime_report}' in prompt.read_text(encoding='utf-8')
        except OSError:
            return False

    async def _cat(context: Any, path: str) -> str | None:
        docker = getattr(context, 'docker', None)
        sandbox_id = getattr(context, 'container_id', None)
        if docker is None or sandbox_id is None:
            return None
        target = path if path.startswith('/') else '/workspace/' + path
        result = await sandbox_exec(docker, sandbox_id, f'cat {target}', timeout=60)
        return result.stdout or None

    async def _run_runtime(context: Any) -> str:
        task = getattr(context, 'task', None)
        test_ids = tuple(getattr(task, 'FAIL_TO_PASS', ()) or ())[:MAX_FAIL_TO_PASS]
        if not test_ids:
            return 'runtime error: task metadata has no FAIL_TO_PASS'
        docker = getattr(context, 'docker', None)
        sandbox_id = getattr(context, 'container_id', None)
        if docker is None or sandbox_id is None:
            return 'runtime error: sandbox not available before session start'
        try:
            command = build_coverage_command(test_ids) if coverage else build_test_command(test_ids)
            log_name = '/tmp/coverage-run.log' if coverage else '/tmp/failure-log.txt'
            await sandbox_exec(docker, sandbox_id, command, timeout=600)
            log = await _cat(context, log_name)
        except Exception as exc:  # noqa: BLE001 - must never block evaluation
            return f'runtime error: test run failed ({type(exc).__name__}: {exc})'
        if not log:
            return 'runtime error: no failure log captured'
        try:
            evidence = parse_pytest_output(log)
            frames = source_frames(evidence)
            frame = frames[-1] if frames else None
            definition = None
            if frame is not None:
                source = await _cat(context, frame.path)
                if source:
                    definition = resolve_definition(source, frame.line)
            traceback_report = format_report(evidence, frame, definition)
            if not coverage:
                return traceback_report
            payload = await _cat(context, '/tmp/coverage.json')
            if not payload:
                return traceback_report + '\nruntime coverage: no coverage json captured'
            scored = []
            for path, lines in parse_coverage_json(payload).items():
                source = await _cat(context, path)
                if source:
                    scored.extend(coverage_scores(source, lines))
            scored.sort(key=lambda item: -item['score'])
            return traceback_report + '\n' + format_coverage_report(scored)
        except Exception as exc:  # noqa: BLE001
            return f'runtime error: report failed ({type(exc).__name__}: {exc})'

    orig_run = Evaluator.run

    async def _run_with_flag(self: Any) -> Any:
        submission = Path(str(getattr(self.config, 'submission_dir', '')))
        state['arm_is_runtime'] = _prompt_requests_runtime(submission)
        return await orig_run(self)

    Evaluator.run = _run_with_flag

    orig_create_tools = SwegemmaContext.create_tools

    def _create_tools_with_context(self: Any) -> Any:
        problem = (getattr(self, 'problem_statement', '') or '').strip()
        if state['arm_is_runtime'] and problem:
            state['pending'][hashlib.sha256(problem.encode('utf-8')).hexdigest()] = self
        return orig_create_tools(self)

    SwegemmaContext.create_tools = _create_tools_with_context

    orig_create_session = InMemorySessionService.create_session

    async def _create_session_with_runtime(self: Any, **kwargs: Any) -> Any:
        session_state = dict(kwargs.get('state') or {})
        problem = (session_state.get('problem_description') or '').strip()
        key = hashlib.sha256(problem.encode('utf-8')).hexdigest()
        context = state['pending'].pop(key, None)
        if state['arm_is_runtime'] and problem and context is not None:
            try:
                report = await _run_runtime(context)
            except Exception as exc:  # noqa: BLE001
                report = f'runtime error: {type(exc).__name__}: {exc}'
            session_state['runtime_report'] = report
            status = 'ok' if report.startswith('runtime evidence') else 'error'
            print(f'runtime prelocalization {status}: {report[:200]}', flush=True)
            kwargs['state'] = session_state
        return await orig_create_session(self, **kwargs)

    InMemorySessionService.create_session = _create_session_with_runtime
    print('runtime prelocalization installed', flush=True)


if __name__ == '__main__':
    install(Path('WORKING_DIRPlaceholder'))
