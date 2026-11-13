# Test-visibility study: hidden vs visible vs visible + runtime evidence

**Status 2026-11-11:** hook and three-arm builds are wired offline; no agent run
yet (GPU quota exhausted). This is the protocol; the offline signal audit is
below.

## Question

SWE-bench applies the hidden `test_patch` only in the verification container, so
the agent never sees the tests. How much repair performance is left on the table
by that protocol, and how much does a runtime-evidence router add once the tests
are visible?

## Novelty check (2026-11-11)

The visible-vs-hidden gap is **already published**, so it cannot be the paper's
headline:

- **SWE-bench Science** (arXiv 2608.19799, Aug 2026) gives agents a small set of
  public diagnostic tests and grades on private held-out tests mounted only after
  submission; the best agent reaches 96.64% on public tests and 47.90% Pass@1 on
  private ones (~49 points). The public/private split is a deliberate
  Chain-of-Evidence design, not a leak. [paper](https://arxiv.org/abs/2608.19799)
- **"Visible Tests, Held-Out Tests and a Judge"** (Zenodo 23485050) measures
  reward hacking in multi-turn code repair with visible vs held-out tests.
  [record](https://zenodo.org/records/23485050) (fetch failed here; title and
  topic are from the search result, not the full text)
- **SWE-ABS / SWE-bench+ / UTBoost** document inflated scores from weak or leaky
  tests; the "hidden tests understate capability" observation is part of that
  line of work.

A defensible contribution therefore has to be narrower than "the gap exists":

1. **Router effect**: does a pre-session traceback/coverage report help a small
   agent *on top of* visible tests? SWE-bench Science measures the gap; it does
   not isolate this intervention.
2. **Small/quantized model**: the prior study uses frontier models; a 12B QAT
   deployment may benefit (or overfit) differently.
3. **Controlled 3-arm design** on the Kaggle Gemma-4 agent with a hidden control.

If the router effect cannot be shown with executed runs, the topic is not novel
enough and should be dropped rather than written as another gap measurement.

### Second novelty check: the runtime router itself

The intervention is also not new in kind:

- **A Localization Framework for Reasoning Faults in LLM-based Code Agents** —
  a framework that uses agent reasoning plus fault evidence to localize faults.
  [ACM](https://dl.acm.org/doi/pdf/10.1145/3774748.3793627)
- **ANVIL-FL: Runtime-Aware Fault Localization for Code Generation and
  Debugging** — runtime-aware fault localization for LLM code generation.
  [IEEE](https://ieeexplore.ieee.org/ielx8/6287639/11323511/11626650.pdf)
- **The Fact Selection Problem in LLM-Based Program Repair** (ICSE 2025) —
  how to select the facts/evidence given to a repair model.
  [ICSE](https://dl.acm.org/doi/abs/10.1109/ICSE55347.2025.00162)

So the safe novelty space is narrow: a **small/quantized 12B model**, a
**controlled visible-vs-hidden-vs-visible+runtime** comparison, and an audited
trace-level analysis. If the executed router effect is absent, there is no paper
here that is both true and new; a "we measured the gap again" paper would
collide with SWE-bench Science.



| arm | tests in workspace | runtime report | purpose |
| --- | --- | --- | --- |
| **hidden** | no | no | SWE-bench control |
| **visible** | yes (`test_patch` applied before the session) | no | protocol effect |
| **visible+runtime** | yes | yes (traceback/coverage, fail tests run pre-session) | router effect on top of visibility |

Implementation:

- `tools/visible_test_prelocalize.py` applies `task.test_patch` in the agent's
  container before the session, gated by `visible-tests.txt` in the submission
  directory (the hidden baseline arm in the same notebook is untouched).
- `tools/runtime_prelocalize.py` runs up to three `FAIL_TO_PASS` tests and injects
  `runtime_report`; with `coverage=True` it also parses `pytest-cov` output.
- `build_ranker_agent_probe.py` flags: `--visible-tests`, `--runtime-evidence`,
  `--runtime-coverage`. Install order is preloc → runtime → visible, so the
  visible hook applies the patch before the runtime tests run.
- Offline probes: `vis2-control`, `vis2-visible`, `vis2-visible-runtime` (one
  task each; full runs use the 10-task subset below).

## Budget

Same model and sampling, but **10 minutes** per task, 60 tool calls, 80 turns,
120 s command timeout, concurrency 3. Model `gemma-4-12b-it-qat-w4a16-ct`.

Why not 5 minutes: the 60-call control (`opt-02`) showed that at 5 minutes every
remaining failure is a session timeout — raising calls from 30 to 60 only
converted call-cap failures into timeouts and changed no resolved count
(baseline 1/4, ranker 0/4; `opt-01` was 0/4 and 1/4). The visible and runtime
arms add pre-session work, so a 5-minute budget would confound the treatment with
the clock.

Compute estimate: 3 arms × 10 tasks ÷ 3 concurrency × 10 min ≈ 100 minutes plus
vLLM startup and verification, i.e. a fresh quota window rather than a short
pilot.

## Offline signal audit (10-task subset)

The 10 unique tasks with pre-fix `empty_control` verification logs (the test
patch is applied there, i.e. the visible-test state):

| task | source frame | gold patch file | hit |
| --- | --- | --- | --- |
| `requests_7433` | `src/requests/models.py:168` | same | yes |
| `requests_7502` | `src/requests/models.py:250` | same | yes |
| `fastapi_13713` | none | — | — |
| `fastapi_14463` | none | — | — |
| `fastapi_15661` | none | — | — |
| `httpx_3672` | none | — | — |
| `requests_7205` | none | — | — |
| `rich_3882` | none | — | — |
| `rich_3942` | none | — | — |
| `rich_4079` | none | — | — |

**2/10 tasks expose a source frame; both point at a gold-patch file.** Coverage
is 20% and precision 2/2; n is far too small for an effect estimate. The other
eight fail with an assertion inside the test file, so the traceback branch has
nothing to map — the coverage branch (executed definitions) is the reason to run
the visible+runtime arm at all.

## Outcomes and pre-registered interpretation

Primary: `resolved` per arm, with the raw 10×3 table and discordant tasks.
Secondary: tool calls, wall time, terminal error; whether the runtime report
named the gold file.

- Hidden vs visible isolates the **protocol effect**.
- Visible vs visible+runtime isolates the **router effect** with tests visible.
- n = 10 is exploratory: report counts and the raw table, do not compute or claim
  significance, and do not call a visible-test gain a SWE-bench leaderboard gain.
- If visible+runtime does not beat visible, report the null; keep the 2/10
  coverage finding as the reason.

## Confounds

- Visible tests change the task: the agent can read the assertions and may overfit
  them. That is the treatment, not a bug, but it must be stated.
- The test patch is the reference tests; exposing them is deliberate. The hidden
  arm in the same notebook must remain untouched.
- Runtime tests consume the 10-minute budget; a null can mean the hook stole time.
- The 10 tasks are requests/httpx/rich/fastapi only; not a stratified sample.

## Execution log

- 2026-11-11: three-arm builds wired and verified offline. No agent run; GPU
  quota exhausted. Nothing in this document is a fix-rate result yet.
