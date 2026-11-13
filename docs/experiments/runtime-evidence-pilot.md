# Runtime-evidence pilot: static prelocalization vs static + runtime evidence

> **CANCELLED 2026-11-11 — invalid under SWE-bench's hidden-test protocol.**
> The agent runs in Container A; the hidden `test_patch` is applied only in the
> Phase 2 verification container. `FAIL_TO_PASS` tests do not exist in the
> agent's workspace, so running them before the session is test leakage. Do not
> execute this pilot as a localization or fix-rate experiment on SWE-bench.
> It is kept as the protocol for a benchmark with visible tests.

**Status 2026-11-11:** protocol frozen offline; not executed (GPU quota exhausted).
This is an **exploratory paired pilot**, not a confirmatory or leaderboard run.

## Question

On the same tasks, model, sampling, time budget, tool-call cap, and turn cap, does
adding a pre-session **runtime-evidence report** to the static localization report
change repair outcomes?

- **Control:** static prelocalization only (`{localization_report}`).
- **Treatment:** static prelocalization plus runtime evidence (`{runtime_report}` +
  `{localization_report}`), where the runtime report is built from up to three
  `FAIL_TO_PASS` tests run before the session.

Both arms use the same ranker skill package; the only difference is the runtime
hook and its prompt section.

## Frozen inputs

| item | value |
| --- | --- |
| tasks | `fastapi_14246, requests_7427, rich_3130, fastapi_15030` (same as `opt-01`) |
| model | `gemma-4-12b-it-qat-w4a16-ct` |
| time budget | 5 minutes per task |
| tool calls | 60 per task |
| turns | 80 per task |
| command timeout | 120 s |
| concurrency | 3 |
| control build | `.cache/main-track/ranker-preloc-rt-control` |
| treatment build | `.cache/main-track/ranker-preloc-rt-treatment` |

The two builds were compared: task ids, eval config, model, sampling, and
num arms are identical; the treatment has one extra install cell and the
`{runtime_report}` prompt key. The manifest records `workflow:
prelocalize` vs `prelocalize+runtime`.

## Procedure

1. Push the control notebook, wait for terminal status, fetch outputs.
2. Push the treatment notebook, wait for terminal status, fetch outputs.
3. Do not change tasks, budget, model, or prompt text between the two runs.
4. Keep all failures; do not rerun a task because the control lost.

A single kernel per arm is enough; both arms contain the matched baseline so a
gross environment failure is visible in the baseline row.

## Outcomes (report all)

- `resolved` per task/arm (primary).
- `tool_calls`, `duration_seconds`, and the terminal error string.
- Whether the injected runtime report named the gold patch file (offline, from
  the logs; not used to filter tasks).
- The static report's top-1 file, for the same check.

## Analysis and interpretation (written before results)

- With n = 4, no p-value is meaningful. Report the raw 4×2 table, discordant
  tasks, and both arms' failure reasons.
- If the treatment resolves more tasks **and** the runtime reports named the gold
  file on those tasks, call it **exploratory evidence consistent with** a
  runtime benefit; do not call it significant, confirmed, or a general result.
- If the treatment does not improve, report it as a null/negative pilot and keep
  the coverage finding (runtime evidence exists on a minority of tasks).
- Do not claim a fix-rate gain from the offline precision audit (3/4 file hits on
  a tiny sample); that audit is a precision check, not an effect estimate.

## Variants not in the primary pilot

- **Coverage treatment** (`--runtime-coverage`): runs the same failing tests under
  `pytest-cov` and appends the executed-span list. Built offline as
  `.cache/main-track/ranker-preloc-rt-coverage-probe`; it costs a second test
  pass, so it is a follow-up, not part of the primary pair.
- **SBFL contrast** (`pass_coverage` in the report builder): needs a
  `PASS_TO_PASS` sample and is not wired into the hook yet. Use only after the
  traceback/coverage arms are separated.

## Known confounds

- The runtime tests consume the same 5-minute session budget; a null result may
  mean the hook steals time rather than that the evidence is unhelpful.
- Three `FAIL_TO_PASS` tests may not include the test that exposes the fault.
- The treatment prompt is longer; any token/latency effect is bundled with the
  evidence effect. A future ablation should inject a length-matched placebo.

## Execution log

- **2026-11-11 22:50**: the unrelated 60-call budget pilot (`opt-02`, no runtime
  evidence) was pushed as kernel v13. It stayed RUNNING for more than two hours
  with no outputs; `CancelKernelSession` returned 403, so it could not be stopped
  from here. Per the one-hour stop condition it is recorded as **hung**, and the
  queue poller was stopped. No result is reported from it.
- **Runtime-evidence control/treatment**: not executed (GPU quota exhausted).

## Stop conditions

- Quota/push failure: stop, do not retry in a loop.
- Kernel error before any task completes: record as infrastructure failure.
- More than one hour of RUNNING with no output: treat as hung; record and stop.
