# Paper draft (v5)

> Target: **3,000 words**, Kaggle Writeup, deadline 2026-11-13 07:59 (UTC+8).
> Mandatory sections (missing any = ineligible): Title + Subtitle, Abstract, Introduction, Research description (methods & experiments), Related works & citations.
> Protocol and changelog: [docs/paper-topic.md](../docs/paper-topic.md). Official rules: [docs/kaggle-paper-track-raw.md](../docs/kaggle-paper-track-raw.md).
>
> **Draft status**: §1–§5 are written against real numbers. Bracketed ⟨…⟩ marks text that still needs a decision, not a number.

---

## Title

**File-Level Is Not Symbol-Level: Measuring Where Code Graphs Help Repository Agents**

Subtitle: *A 300-task symbol-level benchmark, four graph strategies at equal context budget, and the arithmetic that caps them*

---

## Abstract (180 words)

Repository-level coding agents are evaluated on whether they resolve an issue, and the retrieval that feeds them is usually reported at file granularity. We measure the other granularity. On 300 SWE-bench Lite tasks spanning 12 Python repositories, we extract the **354 symbols the reference patches actually touch**, then ask how often a retriever surfaces them. The same ranking that recovers **62.4%** of gold files at rank 10 recovers **27.5%** of gold symbols, a 2.3× gap that we argue is the real frontier rather than an artefact.

We then test four ways of adding a code graph — reranking, slot substitution, score fusion, and fusion restricted to deterministically resolved edges — under an identical candidate pool and an identical context-character budget. **None improves symbol-level recall; the most aggressive variant significantly degrades file-level recall** (4.8 points, p = 0.004). The arithmetic explains why: only **22.1%** of gold symbols are one hop from a text-derived seed, so expansion has almost nothing to gain, and 54% of static call sites never resolve to a definite target. We release the gold-symbol benchmark and the harness.

---

## 1. Introduction (350 words)

An agent that cannot see a repository must search it. For small models on small budgets this is the binding step: the context window holds a few hundred symbols, the repository holds tens of thousands, and everything downstream — the patch, the tests, the verdict — depends on whether the right symbol is among the few.

The literature reports this step mostly at file granularity. LocAgent reports 92.7% file-level accuracy on SWE-bench style tasks; retrieval-augmented agent papers report which files a trajectory opened. Those numbers are real, and they are also easy. A file is a coarse target: 300 lines of a large module contain dozens of definitions, and an agent that opens the right file still has to find the one function the fix belongs in.

We measure the fine granularity. For each of 300 SWE-bench Lite tasks we take the reference patch, map every changed line to its enclosing definition, and record the set of symbols the fix touched. That set is the ground truth; a retriever either surfaces it or does not. The same ranking that finds 62.4% of gold files at rank 10 finds 27.5% of gold symbols. **The gap is 2.3×, and it is not a measurement artefact — it is the same list, scored two ways.**

⟨one concrete example: an issue where the described behaviour lives in one module but the edited symbol is a helper in another, with a name that shares no token with the issue⟩

Second, we test the standard remedy. Code graphs are the assumed answer to repository-scale retrieval: build a call graph, expand from a strong text hit, let structure carry the agent the rest of the way. We implement four variants of that idea and hold everything else fixed — same candidate pool, same character budget, same tasks. None of them improves symbol-level recall. The most aggressive one, which spends half the shortlist on graph neighbours, costs 4.8 points of file-level recall with p = 0.004.

The explanation is arithmetic, and we think it is the paper's actual contribution. Only 22.1% of gold symbols are one hop away from a strong text-derived seed. A one-hop expansion therefore has a ceiling of about one fifth, and paying for it with shortlist slots is a losing trade almost everywhere. Meanwhile 54% of static call sites in the same repositories do not resolve to a definite target at all, so the graph being expanded is itself half guess.

We release the 354-symbol benchmark, the graph builder, and the harness.

---

## 2. Related Work (250 words)

**Repository-level benchmarks.** SWE-bench and its Lite and Verified subsets score whether a patch makes the failing tests pass. They say nothing about whether the model could have found the code. Our target set is derived from SWE-bench Lite's patches, but the quantity we measure — symbol-level retrieval — is orthogonal to resolved rate, and we report it as such rather than as a proxy.

**Agents over repositories.** SWE-agent fixes the interface and lets the model act; LocAgent and OrcaLoca navigate with graph structure and report file- or function-level accuracy; ARISE trains a retriever over call graphs and reports function recall. These systems co-design retrieval with a model. We hold the model out entirely and measure the retrieval layer alone, at a granularity finer than the file.

**Code graphs.** PyCG reports 99.2% precision and 69.9% recall on its own benchmark; CodexGraph and RepoGraph build graph indices for agents. These works treat the graph as an asset whose quality is established. We report the resolution rate of the graph we build (46% of call sites definite) and, more importantly, the ceiling that bounds what any one-hop expansion can contribute.

**Sparse retrieval.** BM25 is the strong, cheap baseline we do not beat. We make no claim to a better retriever; the claim is about where the remaining error lives.

---

## 3. Setup (350 words)

**Tasks.** All 300 instances of SWE-bench Lite, 12 repositories, dominated by django (114) and sympy (77). Each instance names a base commit; we fetch that exact tree as a tarball (297 distinct commits, 2.7 GB). We never execute the repositories, never install their dependencies, and never run their tests: the measurement is purely over source.

**Gold symbols.** For each task we parse the reference patch, take the line numbers the patch touches, and map each to the innermost definition containing it in the *pre-fix* tree: a deleted line anchors itself, an added line anchors the line before it, since the added text does not exist in the pre-fix file. The result is 354 definitions over 290 tasks; the remaining 10 tasks change only module-level statements and contribute no symbol. We record, rather than drop, the 87 changed lines that land outside any definition — module-level code, decorators, imports — because a benchmark that silently discards its hard cases reports inflated numbers.

**Granularity.** A symbol is identified as `<module>.<qualname>`, e.g. `sympy.core.expr.Symbol.__new__`. The module is the repository-relative path without `.py`, so a patch header and a graph node agree without a lookup table. File-level metrics group the same ranking by file.

**Query.** The issue text as given, with no rewrite, no file hints, no LLM preprocessing. This is deliberately the weakest defensible query: any improvement we report cannot be attributed to query engineering.

**Budget.** Every arm fills exactly 10 shortlist slots and we report the characters those ten symbols would contribute to a prompt. Arms that would otherwise win by retrieving more are visible as such.

---

## 4. Method (550 words)

**The graph builder.** We build a definition-and-reference graph from source with Python's `ast`, emitting the same JSON shape the competition's released assets use (`nodes[id, name, text]`, `edges[source, target, type, key]`), so that one reader and one metric apply to both.

Nodes are modules, classes, functions and methods, each carrying its signature, its docstring's first paragraph, and its source span. Edges come in four types: `defines` (parent to child), `imports`, `inherits`, `calls`.

**Resolution states.** The part that matters is not the edge list but what each edge means. We record seven states and never collapse them:

| state | meaning |
| --- | --- |
| `local` | target defined in the same module |
| `import` | target reached through an import alias |
| `unique` | leaf name occurs exactly once in the repository |
| `suffix` | target matched a dotted suffix (src/ layouts) |
| `external` | stdlib or third-party; not a defect |
| `ambiguous` | more than 64 same-named candidates; refused rather than guessed |
| `unresolved` | no target found |

On a django snapshot (2,715 files, 38,651 nodes, 209,502 edges, 10.8 s) the distribution is 34.1% unresolved, 19.2% local, 15.6% import, 15.0% ambiguous, 11.2% unique, 4.9% external. **Only 46% of call sites resolve to a definite in-repository target.** That number is not incidental: it is the quality of the artefact that the graph arms expand, and it is why `graph_fuse_precise` exists as a separate arm.

**The arms.** Five, all paired by task:

1. `text` — BM25 over a document per symbol (path, qualified name, signature, docstring). Baseline.
2. `graph_rerank` — take the top 200; promote anything one hop from the top 5 seeds, keeping the pool. Pure reordering, so it cannot add a candidate.
3. `graph_open` — keep the top 5 seeds, then fill slots 6–10 with their neighbours, drawn from the whole graph; pad from the text ranking if a seed has no neighbours. This is the only arm that can introduce a symbol BM25 never ranked.
4. `graph_fuse` — standard score fusion. Normalise BM25 to its top hit, let a candidate inherit λ = 0.5 of its best adjacent seed's score, rank. **λ was fixed before the run; we never tuned it on the test set.**
5. `graph_fuse_precise` — fusion over only the 46% of edges whose target is definite.

Neighbours are unioned over `calls` and `inherits` edges and treated as undirected: a caller and a callee are equally plausible next hops. Neighbours are drawn round-robin across seeds so a single hub cannot absorb the shortlist.

**Statistics.** Per-task differences, so the two arms are compared on the same issue and the same repository. We report the mean difference with a bootstrap 95% interval (2,000 resamples, fixed seed) plus an exact sign test on win/loss counts. Ties dominate — most tasks are missed by both arms — which is why the sign test, not the interval alone, decides.

**Diagnostics.** Three quantities bound the arms before any of them run: the pool recall (how often a gold symbol enters the top 200 at all), the headroom (how often a gold symbol is one hop from a top-5 seed), and the oracle (the best a perfect reranker could achieve over pool plus seed neighbours).

---

## 5. Results (800 words)

**Coverage is a sanity check, not a finding.** All 354 gold symbols resolve to nodes in the graph we build (354/354). This is expected — the gold extraction and the builder share the `<module>.<qualname>` convention — and we report it only to establish that the denominator and the numerator agree. It says nothing about anyone else's graph.

**The granularity gap is the headline.** Table 1, one ranking, two ways of scoring it.

*Table 1 — symbol vs file granularity (n = 290 scored tasks)*

| granularity | recall@1 | recall@5 | recall@10 |
| --- | ---: | ---: | ---: |
| symbol | 0.091 | 0.214 | **0.275** |
| file | — | 0.579 | **0.624** |

Two thirds of the remaining error at file granularity is not there; at symbol granularity it is.

**No graph arm helps symbol-level recall.** Table 2.

*Table 2 — five arms, paired, equal pool and equal character budget*

| arm | r@1 | r@5 | r@10 | file r@10 | Δr@10 (95% CI) | p |
| --- | ---: | ---: | ---: | ---: | --- | ---: |
| text | 0.091 | 0.214 | 0.275 | 0.624 | — | — |
| graph_rerank | 0.103 | 0.217 | 0.287 | 0.614 | +0.012 (−0.026, 0.050) | 0.50 |
| graph_open | 0.091 | 0.214 | 0.257 | 0.576 | −0.018 (−0.051, 0.013) | 0.46 |
| graph_fuse | 0.091 | 0.217 | 0.272 | 0.624 | −0.003 (−0.010, 0.000) | 1.00 |
| graph_fuse_precise | 0.091 | 0.217 | 0.275 | 0.624 | 0.000 | 1.00 |

Fusion at a principled weight is very nearly the identity, which is itself informative: the inherited score almost never beats the tenth text hit. The one arm that can add unseen candidates does add them, and pays for them.

**Aggressive expansion is significantly worse at file granularity.** `graph_open` trades slots 6–10 for neighbours; 18 tasks lose a gold file, 4 gain one, mean −4.8 points (p = 0.004). The interpretation is consistent with Table 1: at file granularity the text ranking is already good, so spending half the shortlist on structure discards value.

**The ceiling explains all of it.** Table 3.

*Table 3 — diagnostics that bound the arms*

| quantity | value | meaning |
| --- | ---: | --- |
| pool recall (top 200) | 0.600 | gold symbols that enter the candidate pool at all |
| headroom (1 hop from top 5) | **0.221** | most a one-hop expansion could ever touch |
| oracle@10 | 0.630 | best a perfect reranker could do over pool + seed neighbours |

Headroom of 22.1% is the decisive number. A one-hop graph expansion is not competing for 100% of the targets; it is competing for a fifth, and it pays for its slots out of a shortlist that already contains text hits. The arms are not badly implemented — they are bounded.

**Where the graph does help.** The one repository with a clear gain is astropy (0.458 → 0.792 at rank 10, six tasks), where the graph is small and the issue text shares little vocabulary with the edited symbol. That is exactly the regime the headroom predicts, and we report it as a hypothesis with one data point, not as a result.

**The graph itself is half guess.** Table 4, from one django snapshot, is the reason `graph_fuse_precise` exists: if only 46% of edges are definite, an expansion that trusts all edges is expanding mostly noise. Restricting to the definite subgraph does not help either, which we read as evidence that the problem is structural rather than a noise artefact — an important distinction, because it rules out the obvious objection.

*Table 4 — edge resolution on django at one base commit*

| state | edges | share |
| --- | ---: | ---: |
| unresolved | 71,436 | 34.1% |
| local | 40,257 | 19.2% |
| import | 32,648 | 15.6% |
| ambiguous | 31,514 | 15.0% |
| unique | 23,365 | 11.2% |
| external | 10,282 | 4.9% |

**Per repository.** ⟨table: r@10 text vs graph_open for the 12 repositories⟩

---

## 6. Discussion (300 words)

The practical claim is a reprioritisation. If a team is choosing where to spend effort on repository-scale retrieval, one-hop graph expansion is not where the error is: 77.9% of gold symbols are more than one hop from a strong text seed, and half the call sites that would carry the hop do not resolve. Effort spent on candidate generation — better name matching, better issue-to-identifier alignment, more aggressive pool sizes — addresses the 40% of symbols that never enter the pool, which is a larger and more tractable share.

The measurement claim is about granularity. File-level retrieval numbers near 90% are routinely quoted as evidence that the hard part is over. Our numbers say the same ranking is at 62.4% on files and 27.5% on symbols, and that the difference is not a tighter definition of success but a different task. Benchmarks that stop at the file cannot see the remaining work.

For benchmark designers: the gold-symbol set is cheap to produce from any patch-based benchmark and gives a granularity that resolved rates cannot. We release ours.

⟨one paragraph on what would change our mind: an LLM reranker over the same pool, or a graph built with type inference rather than name matching⟩

---

## 7. Limitations (130 words)

Python only, though so are three quarters of the tasks in the benchmarks we compare against. One retriever: BM25 is a strong sparse baseline and we deliberately did not add a dense retriever or a cross-encoder, so the null result is about the graph's marginal value *given this ranking*, not about graphs in general. The 22.1% headroom is measured against top-5 seeds; a different seed count would move it, and we report the sensitivity in the appendix. Gold symbols come from patches and inherit their noise; we record rather than hide the 87 changed lines that land outside any definition. We measure retrieval, not resolution: a better shortlist is necessary for a better patch, not sufficient.

---

## 8. Conclusion (90 words)

Same ranking, two granularities: 62.4% of gold files, 27.5% of gold symbols. Four ways of folding a code graph into that ranking, none of which beats plain lexical retrieval, and one which significantly hurts at file level. The arithmetic that explains it — 22.1% one-hop reachability, 46% definite call resolution — is more useful than another graph variant, because it tells the next project where the missing two thirds actually lives.

---

## Claim → evidence

| # | claim | evidence | status |
| --- | --- | --- | --- |
| 1 | symbol-level is much harder than file-level | Table 1 | ✅ measured |
| 2 | four graph arms do not improve symbol recall | Table 2 | ✅ measured |
| 3 | aggressive expansion hurts file recall (p=0.004) | Table 2 | ✅ measured |
| 4 | headroom is 22.1%, which caps expansion | Table 3 | ✅ measured |
| 5 | only 46% of call sites resolve | Table 4 | ✅ measured on django |
| 6 | the gap is the remaining frontier for agents | — | ⬜ argument, §6 |
| 7 | precise-only edges do not rescue the arms | Table 2, row 5 | ✅ measured |

---

## Submission checklist

- [ ] **≤ 3,000 words** (count with a tool, not by eye)
- [ ] five mandatory sections present
- [ ] not previously published (Non-Archival permits posting only after submission)
- [ ] every number traceable to `data/experiment.jsonl` + `tools/analyse.py`
- [ ] figures legible at 50% scale
- [ ] submission confirmed well before the deadline
