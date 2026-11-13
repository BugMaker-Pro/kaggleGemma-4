# Runtime evidence for repair: parser, signal audit, and scope

**Status 2026-11-11:** first layer built and tested; no executed fix-rate comparison yet.
This note records what the runtime-evidence router can and cannot see, so the next
pilot is not designed around an assumed signal that is not there.

## VALIDITY BLOCKER (2026-11-11): hidden tests are not available in SWE-bench

`swegemma/evaluate.py` runs the agent in **Container A** and applies the hidden
`test_patch` only in the **Phase 2 verification container** (Container B,
`verify_task`). The `FAIL_TO_PASS` tests therefore **do not exist in the agent's
workspace**. Running them before the session requires applying the hidden test
patch — that is test leakage, not runtime evidence.

Consequences:

- The traceback router cannot be deployed on SWE-bench without leakage.
- The test-id prior and the offline `prior + LTR` result (+2.6 points over the
  16-feature ranker) use hidden test names; they are **leakage diagnostics, not
  legitimate localization gains**, and must not enter a paper as improvements.
- The paired pilot is **cancelled**, not merely postponed.

Legitimate runtime evidence requires tests that are visible in the workspace:
existing repository tests, a user-provided reproduction, or a benchmark whose
protocol exposes the tests. On SWE-bench the only visible tests are the current
repository suite, which need not cover the issue's bug.

### Issue-visible evidence audit (2026-11-11)

To check whether the issue text itself supplies a usable reproduction, the
problem statements were scanned for fenced code, tracebacks, assertions, and
test functions:

| signal | Lite (300) | official main-track (129) |
| --- | ---: | ---: |
| fenced code block | 22 (7.3%) | 1 (0.8%) |
| traceback text | 64 (21.3%) | 0 (0.0%) |
| `assert` inside a code block | 0 (0.0%) | 0 (0.0%) |
| `def test_...` inside a code block | 0 (0.0%) | 0 (0.0%) |
| mentions `pytest` | 19 (6.3%) | 2 (1.6%) |
| says "reproduce"/"minimal example" | 61 (20.3%) | 4 (3.1%) |

The traceback text is static issue evidence already used by the issue-evidence
channel; it is not runtime evidence (nothing is executed). The visible-code
coverage (≤7.3% Lite, 0.8% official) is too low to support a runtime router.

**Conclusion (2026-11-11):** the runtime-evidence direction is closed for
SWE-bench. Hidden tests would be leakage; visible issue evidence is too sparse;
the paired pilot is cancelled. A legitimate successor would need a benchmark
whose tests are visible, or a different problem entirely.

## What was built

`tools/failure_prelocalize.py` (pure functions, 12 unit tests in
`tests/test_failure_prelocalize.py`):

- `parse_pytest_output` reads both Python's long traceback frames
  (`File "…", line N, in f`) and pytest's short report frames
  (`path.py:N: in f`), plus `FAILED` node ids and the last `E`-block message.
- `source_frames` keeps only workspace source frames and drops `tests/`,
  `testing/`, `test_*.py`, `*_test.py`, `conftest.py`.
- `resolve_definition` maps the last source line to the innermost def/class
  with the repository's own `python_symbols` + `resolve`; an unmapped line
  stays a `file:line` and is never guessed.
- `format_report` renders `runtime evidence / last source frame / definition /
  error`; empty output becomes `runtime error: …`, not a silent success.
- `build_test_command` runs the selected `FAIL_TO_PASS` nodes with
  `pytest -q --tb=long -p no:cacheprovider` and appends `FAIL_EXIT:$?`, since a
  pre-fix test is expected to fail.

### Coverage layer (added 2026-11-11)

- `build_coverage_command` runs the same nodes under `pytest-cov`
  (`--cov=. --cov-report=json:/tmp/coverage.json`), so an assertion inside the
  test file still executes source.
- `parse_coverage_json` returns executed lines per file.
- `coverage_scores` gives every def/class its executed-span fraction.
- `fuse_scores` min-max normalizes a static score family and the coverage
  family and fuses them with a fixed weight.
- `format_coverage_report` emits the top executed definitions.

Caveat: executed fraction is **not** spectrum-based fault localization. With
only the failing test, every definition the test touches looks suspect; a
proper Ochiai/DStar score needs passing-test contrast. The current layer is a
cheap prior to fuse with the static ranker, not a replacement for it.

### SBFL contrast (added 2026-11-11)

When a small passing-test control is available:

- `ochiai_score(fail_executed, pass_executed, span_lines)` computes
  `ef / sqrt((ef + nf) * (ef + ep))` at definition level.
- `suspiciousness_scores(fail_coverage, pass_coverage, source_reader)` scores
  every definition executed by the failing test, using the passing control as
  contrast.
- `build_runtime_report(..., pass_coverage=...)` switches the coverage section
  to `suspiciousness:` and fuses it with the static family.

This is a real SBFL signal rather than a coverage prior, but it costs a second
test run (a small `PASS_TO_PASS` sample), so the hook does not use it yet. The
pilot protocol keeps the first treatment traceback+coverage; an ablation can add
the pass contrast after the basic effect is known.

### Combined report (added 2026-11-11)

`build_runtime_report` merges the three signals into one prompt-sized report:

```
runtime evidence: <test id> failed
traceback definition: <module>.<qualname> (<path>:<start>-<end>)   # when mapped
error: <last E-block message>
coverage: <top-3 executed definitions with fractions>
fused shortlist: <top-3 static+coverage definitions>
```

Each signal degrades independently: an unmapped frame stays a `file:line`, a
missing source file drops coverage, and no parsed evidence returns an explicit
`runtime error`. The report is capped at three items per section so it does not
consume the repair prompt.

## Signal audit (offline, no new runs)

**Saved verification logs** (132 files under `.cache/main-track/**/test_outputs/`,
not shipped with the repository):

| subset | logs | with parsed tests | with a non-test source frame |
| --- | ---: | ---: | ---: |
| all saved logs | 132 | 56 | 4 |
| pre-fix `empty_control` only | 19 | 16 | **3 (15.8%)** |
| post-agent baseline | 33 | 14 | 0 |
| post-agent ranker | 39 | 15 | 1 |

The pre-fix subset is the relevant one: it is the failing-test state the router
would see before repair. Only ~16% of those logs expose a source frame; the
common case is an assertion error inside the test file, which the router cannot
map to a source definition.

**Test-id signal** (`tools/audit_test_signal.py`, 290 Lite tasks with symbols):

| check | tasks | share |
| --- | ---: | ---: |
| has `FAIL_TO_PASS` | 290 | 100% |
| test file is under a package tree containing the gold module | 57 | 19.7% |
| test-name tokens overlap a gold qualname token | 145 | 50.0% |
| test-file stem equals the gold module's leaf (e.g. `test_separable.py`) | 58 | 20.0% |

Test ids are always present but weak alone: token overlap is broad and the
module relation is only ~20%.

### Main-track test-id prior (129 official tasks)

`tools/audit_official_test_signal.py` parses the hidden test patch and the gold
patch of each official task (the frozen `tasks.jsonl` is not in the public
clone):

| check | tasks | share |
| --- | ---: | ---: |
| has a test patch | 129 | 100% |
| test file stem overlaps a gold file stem | 55 | 42.6% |
| test-name tokens overlap gold file/def tokens | 39 | 30.2% |
| test file path contains a gold file stem | 65 | 50.4% |

`test_name_prior(test_ids, candidates)` turns the test id into a cheap,
always-available routing prior (token overlap with candidate definition keys).
It is weaker than a traceback but is available on 100% of tasks, unlike the
~16% traceback coverage.

### Traceback branch precision (offline, small n)

From the saved main-track logs, **4 runs across 3 unique tasks** exposed a
non-test source frame. Comparing the frame's file with the task's gold patch:

| task | frame | gold patch file | hit |
| --- | --- | --- | --- |
| `requests_7433` | `src/requests/models.py:168` | `src/requests/models.py` | yes |
| `requests_7502` | `src/requests/models.py:250` | `src/requests/models.py` | yes |
| `fastapi_15763` | `fastapi/applications.py:1553` | `fastapi/routing.py` | no (delegation) |

So **3/4 runs (2/3 unique tasks)** point at a gold-patch file. This is a
precision estimate, not coverage; the sample is tiny and the miss is a
delegation case (`include_router` calls into `routing`), which is exactly the
kind of near miss a fusion prior should fix.

## What this means

Traceback-only routing is **high precision, low coverage**. It cannot be the
whole contribution, and a pilot on arbitrary tasks would mostly show nulls. The
honest reading is:

1. A traceback-frame router should be evaluated as a **conditional** treatment
   on the tasks where a source frame exists, with the static ranker as the
   fallback for the rest.
2. To raise coverage, the next layer should be **coverage-guided** rather than
   traceback-only: run the failing test under coverage, score definitions by
   executed lines (and optionally a spectrum-based suspiciousness), and fuse
   with the static ranker. Coverage executes the code under test even when the
   failure is an assertion in the test file.
3. The test-id/name signal can be a cheap prior, not a standalone locator.

## Next steps (in order)

1. Add a coverage-report parser and a definition-level suspiciousness scorer
   (pure functions + tests, no GPU).
2. Combine traceback frames, coverage, and the static ranker into one
   `runtime evidence` report; keep the fallback explicit.
3. Integrate as a pre-session hook (the `ranker_prelocalize` pattern) and add a
   prompt key; unit-test the command/report path.
4. Only then run a paired pilot (static prelocalization vs runtime fusion) on a
   small task set, and report resolved rate, tool calls, and wall time.

No fix-rate claim is made until step 4 is executed. Negative or null coverage
results should be kept in the paper rather than dropped.
