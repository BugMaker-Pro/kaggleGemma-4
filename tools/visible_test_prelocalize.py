"""Visible-test protocol: apply the task's hidden test patch before the session.

**This is the treatment under study, not a hidden-test claim.** SWE-bench applies
`test_patch` only in the verification container, so the agent never sees the
tests. This hook deliberately applies the patch to the agent workspace before
the session, making the tests visible; the hidden protocol remains the control
arm. The paper must report the protocol gap, not claim hidden-test gains.

The hook is gated by a `visible-tests.txt` file in the submission directory,
so the control arm in the same notebook stays hidden. It uses the same
`InMemorySessionService.create_session` patch point as the other pre-session
hooks; install it **after** the runtime hook so the test patch is applied before
the runtime tests run.
"""

from __future__ import annotations

import asyncio
import hashlib
import tempfile
from pathlib import Path
from typing import Any


def install(work_dir: Path) -> None:
    from google.adk.sessions import InMemorySessionService
    from swegemma.context import SwegemmaContext
    from swegemma.evaluate import Evaluator
    from swegemma.harness.container_setup import apply_patch_in_container

    state: dict[str, Any] = {'arm_is_visible': False, 'pending': {}, 'applied': set()}

    def _marker(submission: Path) -> bool:
        return (submission / 'visible-tests.txt').is_file()

    def _apply(context: Any) -> str:
        task = getattr(context, 'task', None)
        test_patch = str(getattr(task, 'test_patch', '') or '')
        if not test_patch.strip():
            return 'visible tests: task has no test_patch'
        docker = getattr(context, 'docker', None)
        sandbox_id = getattr(context, 'container_id', None)
        if docker is None or sandbox_id is None:
            return 'visible tests: sandbox not available'
        key = hashlib.sha256(test_patch.encode('utf-8')).hexdigest()
        if key in state['applied']:
            return 'visible tests: already applied'
        host = Path(tempfile.mkdtemp(prefix='visible-tests-')) / 'test.patch'
        host.write_text(test_patch if test_patch.endswith('\n') else test_patch + '\n', encoding='utf-8')
        try:
            docker.copy_to(sandbox_id, str(host), '/tmp/visible-test.patch')
            exit_code, stdout, stderr = apply_patch_in_container(
                docker, sandbox_id, '/tmp/visible-test.patch', workspace_dir='/workspace')
        finally:
            host.unlink(missing_ok=True)
        if exit_code != 0:
            return f'visible tests: apply failed ({stderr or stdout})'[:300]
        state['applied'].add(key)
        return 'visible tests: applied'

    orig_run = Evaluator.run

    async def _run_with_flag(self: Any) -> Any:
        submission = Path(str(getattr(self.config, 'submission_dir', '')))
        state['arm_is_visible'] = _marker(submission)
        return await orig_run(self)

    Evaluator.run = _run_with_flag

    orig_create_tools = SwegemmaContext.create_tools

    def _create_tools_with_context(self: Any) -> Any:
        problem = (getattr(self, 'problem_statement', '') or '').strip()
        if state['arm_is_visible'] and problem:
            state['pending'][hashlib.sha256(problem.encode('utf-8')).hexdigest()] = self
        return orig_create_tools(self)

    SwegemmaContext.create_tools = _create_tools_with_context

    orig_create_session = InMemorySessionService.create_session

    async def _create_session_with_visible_tests(self: Any, **kwargs: Any) -> Any:
        session_state = dict(kwargs.get('state') or {})
        problem = (session_state.get('problem_description') or '').strip()
        key = hashlib.sha256(problem.encode('utf-8')).hexdigest()
        context = state['pending'].pop(key, None)
        if state['arm_is_visible'] and problem and context is not None:
            try:
                report = await asyncio.to_thread(_apply, context)
            except Exception as exc:  # noqa: BLE001 - must not block the session
                report = f'visible tests: apply failed ({type(exc).__name__}: {exc})'
            session_state['visible_tests'] = report
            print(f'visible-test prelocalization: {report}', flush=True)
            kwargs['state'] = session_state
        return await orig_create_session(self, **kwargs)

    InMemorySessionService.create_session = _create_session_with_visible_tests
    print('visible-test prelocalization installed', flush=True)


if __name__ == '__main__':
    install(Path('WORKING_DIRPlaceholder'))
