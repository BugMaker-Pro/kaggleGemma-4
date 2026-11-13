# Novelty log: candidate directions and prior art

**Rule (2026-11-11, user):** before implementing any new direction, search for
published work that may duplicate it, already did it, or can inspire the design.
Record the search result, the overlap, and a verdict. Do not start coding a
direction whose core claim is already published.

## Closed directions

### 1. Runtime-evidence router (traceback/coverage → repair)

- SWE-bench Science already separates public diagnostic tests from private held-out
  tests and mounts private tests only after submission:
  [arXiv 2608.19799](https://arxiv.org/abs/2608.19799)
- Runtime-aware fault localization for code generation/debugging:
  [ANVIL-FL](https://ieeexplore.ieee.org/ielx8/6287639/11323511/11626650.pdf)
- Agent fault-localization framework:
  [ACM 3774748.3793627](https://dl.acm.org/doi/pdf/10.1145/3774748.3793627)
- Evidence/fact selection for repair:
  [ICSE 2025](https://dl.acm.org/doi/abs/10.1109/ICSE55347.2025.00162)
- **Verdict: closed.** Plus, on SWE-bench the hidden `test_patch` is applied only
  in the verification container, so running FAIL_TO_PASS pre-session is test
  leakage. Offline `prior+LTR +2.6` is a leakage diagnostic, not a gain.

### 2. Test visibility / hidden-test penalty

- SWE-bench Science measures the public/private gap (~49 points at the top):
  [arXiv 2608.19799](https://arxiv.org/abs/2608.19799)
- Visible vs held-out tests and reward hacking in multi-turn repair:
  [Zenodo 23485050](https://zenodo.org/records/23485050) (title/topic from search;
  full text not fetched)
- **Verdict: closed as a headline.** Only a small-12B + controlled router-effect
  study could be differentiated, and that needs executed runs.

### 3. Trace-level budget study ("why the 12B agent times out")

- Thought-action-result trajectory study of SE agents:
  [ASE 2025](https://dl.acm.org/doi/10.1109/ASE63991.2025.00234)
- Energy efficiency of agentic issue resolution with SLMs:
  [SWEnergy](https://dl.acm.org/doi/full/10.1145/3786167.3788406)
- Pattern-guided trajectory selection for coding agents on SWE-bench:
  [SHEPHERD](https://openreview.net/pdf?id=ZBOFr4ryBk)
- **Verdict: crowded.** A strict-3-minute, quantized-12B, paired-arm trace study
  could still be a competition-specific resource, but the method is not new.

### 4. Patch-intent / patch-shape prediction

- Programmer-intent guidance for bug fixing:
  [PATCH](https://dl.acm.org/doi/10.1145/3718739)
- Inferred program intent for repair:
  [AdverIntent-Agent](https://dl.acm.org/doi/10.1145/3728939)
- **Verdict: covered.**

### 5. Edit-span prediction

- Localized span-level error editing with energy-based localization:
  [LaSEr-Edit](https://arxiv.org/html/2407.00740v3)
- Controlled multi-span infilling/local editing:
  [SpanBench](https://neurips.cc/virtual/2026/loc/sydney/175930)
- Multi-hunk repair on SWE-bench Verified:
  [UBC thesis](https://open.library.ubc.ca/media/download/pdf/52966/1.0452541/6)
- **Verdict: covered.**

### 6. Patch voting / self-consistency / candidate fusion

- Deterministic fusion of repair candidates:
  ["A Single Patch Is Not Enough"](https://ar5iv.labs.arxiv.org/html/2607.01597)
- Adaptive-consistency for efficient sampling:
  [EMNLP 2023](https://aclanthology.org/2023.emnlp-main.761/)
- **Verdict: covered as an idea; an AST-aware variant needs a demonstrated gain
  and compute.**

## Inspirations kept

- SWE-bench Science's public/private protocol is the right vocabulary for any
  test-visibility claim; do not claim the gap as new.
- SWEnergy suggests reporting latency/energy alongside resolve rate for small
  models; our traces have wall-clock and tool-call data.
- The ASE trajectory study provides a failure-taxonomy template; our unique
  setting is the **Kaggle Gemma-4 12B timed competition**, not the taxonomy.

### 7. Competition-specific small-agent trace resource

- A local Gemma coding agent study on silent failures and interface-only
  specification review: [Zenodo 23537103](https://zenodo.org/records/23537103)
- A code localizer trained from the fixer's likelihood:
  [arXiv 2611.12164](https://browse-export.arxiv.org/pdf/2611.12164)
- Small coding agents and code graphs, 0.6B–32B scale curve (already cited by the
  submitted paper): [Bellam, arXiv 2610.33958](https://arxiv.org/html/2610.33958v1)
- The competition itself and its discussion:
  [Kaggle Gemma-4 Developer Agent](https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/743007)
- Human-agent planning traces (not code repair):
  [TraceML](https://arxiv.org/html/2608.26086v1)

**Verdict:** the "local Gemma agent" theme is partially covered. The only
remaining niche is the **timed 3-minute, quantized 12B, paired-arm trace set**
itself, which could be a small resource/technical report — not a top-venue
method paper, and not a fix-rate claim.

### 8. Retrieval-repair dissociation

- "Beyond Localization: Recoverable Headroom and Residual Frontier in
  Repository-Level RAG-APR": [arXiv 2603.29067](https://ar5iv.labs.arxiv.org/html/2603.29067)
- **Verdict: covered.**

### 9. Variance / reproducibility of coding agents

- Randomness in agentic evals: [arXiv 2602.07150](https://arxiv.org/html/2602.07150v1)
- Identical runs, different results on open-weight coding agents:
  [arXiv 2609.33812](https://browse-export.arxiv.org/abs/2609.33812)
- A hierarchy of reproducibility measures:
  [Zenodo 20285101](https://zenodo.org/records/20285101/files/suite_v0_paper.pdf?download=1)
- **Verdict: covered**, including open-weight models.

### 10. Flaky / non-idempotent tests

- Cost-bounded LLM invocation for flaky-test CI repair:
  [Zenodo 20804238](https://zenodo.org/records/20804238/files/Jadhav_K_2026_ATI_AdaptiveTestIntelligence.pdf?download=1)
- NIODebugger for non-idempotent-outcome tests:
  [ICSE 2025](https://dlnext.acm.org/doi/10.1109/ICSE55347.2025.00226)
- **Verdict: covered.**

### 11. Reachable-answer / leakage anti-pattern

- Answer-reachable eval environments:
  [agentpatterns](https://raw.githubusercontent.com/agentpatterns-ai/website/refs/heads/main/patterns/anti-patterns/answer-reachable-eval-environments.md)
- **Verdict: the leakage finding is a known anti-pattern, not a new
  contribution; useful only as a local audit.**

### 12. Dependency upgrade / breaking-change repair

- LLM agents for automated dependency upgrades (IEEE):
  [11334457](https://xplorestaging.ieee.org/document/11334457)
- BUMPTriage, migration mutants for update triage:
  [Zenodo 23611200](https://zenodo.org/records/23611200)
- DepRepair for dependency breaking changes:
  [arXiv 2607.17957](https://arxiv.org/html/2607.17957v1)
- **Verdict: covered.**

### 13. Security / prompt injection / vulnerability repair

- Privilege-escalation attacks on harness-protected coding agents:
  [arXiv 2610.22987](https://export.arxiv.org/pdf/2610.22987)
- "Comment and Control": GitHub AI agents as credential exfiltrators:
  [CSA lab note](https://labs.cloudsecurityalliance.org/research/csa-research-note-comment-control-github-prompt-injection-20/)
- Agentic vulnerability repair (MemRepair):
  [arXiv 2605.17444](https://export.arxiv.org/abs/2605.17444)
- Automated security patch backporting (ASE 2026):
  [ACM 3832783.3837542](https://dl.acm.org/doi/10.1145/3832783.3837542)
- **Verdict: covered on attack, defense, and patch-backport axes.**

### 14. CI / infra repair

- Self-healing CI/CD: [PyPI](https://pypi.org/project/self-healing-cicd/0.1.10/)
- CIdra CI debugging and repair agent: [PyPI](https://pypi.org/project/cidra/0.3.0/)
- **Verdict: covered at tooling level; no research gap visible.**

### 15. Agent memory / experience reuse

- TwinMem-Agent, episodic + semantic memory for repo-level repair:
  [ACM 3803437.3807664](https://dl.acm.org/doi/abs/10.1145/3803437.3807664)
- Structurally aligned subtask-level memory (ICML 2026):
  [poster 66605](https://icml.cc/virtual/2026/poster/66605)
- **Verdict: covered.**

### 16. Refactoring / unnecessary change radius

- RefAgent multi-agent refactoring:
  [ACM 3744916.3773153](https://dl.acm.org/doi/full/10.1145/3744916.3773153)
- BlastBench, change radius of coding agents:
  [Zenodo 23174628](https://zenodo.org/records/23174628)
- **Verdict: covered; also removes the "minimal patch" angle.**

### 17. Self-generated tests as proxy oracle

- "Building to the Test: Coding agents deliver what you check, not what you
  requested": [arXiv 2606.28430](https://arxiv.org/html/2606.28430)
- LLM-as-judge reliability for patch correctness (ESEM 2026):
  [Dagstuhl](https://drops.dagstuhl.de/entities/document/10.4230/LIPIcs.ESEM.2026.21)
- Human-in-the-loop LLM-judge patch evaluation:
  [ACM 3786175.3788348](https://dl.acm.org/doi/10.1145/3786175.3788348)
- **Verdict: covered; the "agent's own tests are a weak oracle" claim is
  already published.**

### 18. Benchmark contamination

- Cross-context verification for contamination detection:
  [arXiv 2603.21454](https://export.arxiv.org/abs/2603.21454)
- **Verdict: covered.**

### 19. Human trust / review of agent patches

- Explainable AI and trust in AI-assisted code review (FSE 2026):
  [ACM 3832184](https://dl.acm.org/doi/10.1145/3832184)
- **Verdict: covered.**

### 20. Performance-regression repair

- Software revival with coding agents (dead code to working engines):
  [Semantic Scholar](https://www.semanticscholar.org/reader/7f483617cb4742d6fcecd005036c04e13f597409)
- **Verdict: adjacent but thin; not a standalone gap, and it needs a new
  benchmark to be credible.**

## Conclusion (2026-11-11)

Nineteen adjacent lanes were checked. Every one of them has 2026 prior art,
including the two most recent ideas (self-written tests as oracle, change
radius). The competition's paper track has no defensible *method* lane left
that can be executed with the compute we have. The only assets that are not
reproducible by another team are the timed, quantized-12B, paired-arm traces
from the official harness (section 7), which support a resource/technical
report, not a new method.

## Not yet checked (candidates only)

- Any new algorithmic idea must pass the same check first. Given the density
  above, treat "new method" proposals as low-probability unless they come with
  new data or new compute.
- The featured leaderboard competition is a separate track (deadline
  2026-12-03) and is not covered by this log.
