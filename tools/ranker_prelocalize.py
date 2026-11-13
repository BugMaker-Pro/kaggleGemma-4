"""Deterministic pre-localization: remove the LLM locator stage entirely.

The staged pipeline asked a 12B QAT model to invoke a deterministic script
through ``run_skill_script``. Traces from the 2026-11-08 development batch show
the model repeatedly failing to emit the nested argument structure
(``skill_name`` + ``file_path`` + ``args.issue``), burning ~60s of the shared
3-minute budget per retry (fastapi_14463: three INVALID_ARGUMENTS in a row, the
whole session gone, zero tool calls). The script itself is correct; the LLM
wrapper is pure liability.

This module instead runs the ranker in the sandbox after the snapshot is
extracted and before the agent session starts, then injects the report as
session state ``localization_report``, which the repair prompt templates with
``{localization_report}`` exactly as the old two-stage pipeline did.

Patching surface (all in-process, no harness files modified):
  * ``Evaluator.run``                -> records whether the current arm's
                                        submission declares the ranker skill
                                        (the matched baseline arm is untouched);
  * ``SwegemmaContext.create_tools`` -> records the per-task context keyed by
                                        problem statement (concurrency-safe);
  * ``InMemorySessionService.create_session`` -> runs the skill in the sandbox
                                        and injects the report into state.

The localization wall time still counts against the task budget clock (it
starts at context creation), so timing stays comparable with the staged arm.

Usage as a notebook cell (the build script inlines this file verbatim after
replacing the __main__ block with ``install(WORKING_DIR)``):

    python tools/build_ranker_agent_probe.py --prelocalize ...

Usage in tests: import the module; ``install()`` is NOT called on import.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from pathlib import Path
from typing import Any

SKILL_REMOTE = '/tmp/ranker-skill'
REPORT_REMOTE = '/tmp/ranker-report.json'
ERROR_REMOTE = '/tmp/ranker-error.txt'
LOCALIZE_TIMEOUT = 600


def format_report(payload: dict[str, Any]) -> str:
    """Render the localize.py JSON payload as compact report text for the prompt."""
    if not isinstance(payload, dict) or payload.get('status') != 'ok':
        detail = ''
        if isinstance(payload, dict):
            detail = str(payload.get('error') or payload.get('status') or 'unknown failure')
        return f"ranker error: {detail}"
    lines = [
        f"ranker ok, mode {payload.get('mode')}, {payload.get('candidate_count')} candidates, "
        f"{payload.get('seconds')}s"
    ]
    results = payload.get('results') or []
    for i, item in enumerate(results, 1):
        lines.append(
            f"{i}. {item.get('symbol')}  {item.get('path')}:"
            f"{item.get('start_line')}-{item.get('end_line')}  score {item.get('score')}"
        )
    for item in results[:3]:
        snippet = (item.get('snippet') or '').strip()
        if snippet:
            lines.append(f"snippet of {item.get('symbol')}:\n{snippet}")
    return '\n'.join(lines)


def build_command(issue_b64: str) -> str:
    """Shell command that runs localize.py in the sandbox.

    The issue travels base64-encoded so arbitrary text (quotes, newlines,
    unicode) survives the command line untouched.
    """
    return (
        'cd /workspace && python3 '
        f'{SKILL_REMOTE}/scripts/localize.py --root /workspace '
        f'--issue "$(printf %s {issue_b64} | base64 -d)" '
        f'> {REPORT_REMOTE} 2> {ERROR_REMOTE}; '
        'echo PRELOC_EXIT:$?'
    )


def install(work_dir: Path) -> None:
    """Patch the harness in-process. Call once, before evaluation starts."""
    from google.adk.sessions import InMemorySessionService
    from swegemma.context import SwegemmaContext
    from swegemma.evaluate import Evaluator
    from swegemma.sandbox.base import sandbox_exec

    skill_dir = Path(work_dir) / 'agents' / 'ranker' / 'skills' / 'ranker'
    state: dict[str, Any] = {'arm_is_ranker': False, 'pending': {}}

    async def _run_localization(context: Any, problem: str) -> str:
        docker = getattr(context, 'docker', None)
        sandbox_id = getattr(context, 'container_id', None)
        if docker is None or sandbox_id is None:
            return 'ranker error: sandbox not available before session start'
        issue_b64 = base64.b64encode(problem.encode('utf-8')).decode('ascii')
        await asyncio.to_thread(docker.copy_to, sandbox_id, str(skill_dir), SKILL_REMOTE)
        result = await sandbox_exec(docker, sandbox_id, build_command(issue_b64),
                                    timeout=LOCALIZE_TIMEOUT)
        marker = (result.stdout or '').strip()
        if 'PRELOC_EXIT:0' not in marker:
            stderr = ''
            try:
                err = await sandbox_exec(docker, sandbox_id, f'cat {ERROR_REMOTE}', timeout=60)
                stderr = (err.stdout or '').strip()[:600]
            except Exception:  # noqa: BLE001 - diagnostics only
                pass
            return f'ranker error: exit {marker[-40:] or "unknown"}; {stderr}'
        payload: dict[str, Any] = {}
        try:
            report = await sandbox_exec(docker, sandbox_id, f'cat {REPORT_REMOTE}', timeout=60)
            payload = json.loads((report.stdout or '').strip())
        except Exception as exc:  # noqa: BLE001 - surfaced to the repair agent
            return f'ranker error: unreadable report ({type(exc).__name__}: {exc})'
        return format_report(payload)

    orig_run = Evaluator.run

    async def _run_with_arm_flag(self: Any) -> Any:
        submission = Path(str(getattr(self.config, 'submission_dir', '')))
        state['arm_is_ranker'] = (submission / 'skills' / 'ranker' / 'SKILL.md').exists()
        return await orig_run(self)

    Evaluator.run = _run_with_arm_flag

    orig_create_tools = SwegemmaContext.create_tools

    def _create_tools_with_context(self: Any) -> Any:
        problem = (getattr(self, 'problem_statement', '') or '').strip()
        if state['arm_is_ranker'] and problem:
            state['pending'][hashlib.sha256(problem.encode('utf-8')).hexdigest()] = self
        return orig_create_tools(self)

    SwegemmaContext.create_tools = _create_tools_with_context

    orig_create_session = InMemorySessionService.create_session

    async def _create_session_with_report(self: Any, **kwargs: Any) -> Any:
        session_state = dict(kwargs.get('state') or {})
        problem = (session_state.get('problem_description') or '').strip()
        key = hashlib.sha256(problem.encode('utf-8')).hexdigest()
        context = state['pending'].pop(key, None)
        if state['arm_is_ranker'] and problem and context is not None:
            try:
                report = await _run_localization(context, problem)
            except Exception as exc:  # noqa: BLE001 - must never block evaluation
                report = f'ranker error: {type(exc).__name__}: {exc}'
            session_state['localization_report'] = report
            status = 'ok' if report.startswith('ranker ok') else 'error'
            print(f'prelocalization {status}: {report[:160]}', flush=True)
            kwargs['state'] = session_state
        return await orig_create_session(self, **kwargs)

    InMemorySessionService.create_session = _create_session_with_report
    print(f'prelocalization installed (skill: {skill_dir})', flush=True)


if __name__ == '__main__':
    install(Path('WORKING_DIRPlaceholder'))
