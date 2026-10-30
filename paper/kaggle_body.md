## Abstract

Repository-level coding agents are evaluated on whether they resolve an issue, and the retrieval that feeds them is usually reported at file granularity. We measure the other granularity. On 300 SWE-bench Lite tasks across 12 Python repositories we extract the **354 symbols the reference patches actually touch** and ask how often retrieval surfaces them. The same ranking that recovers **62.4%** of gold files at rank 10 recovers **27.5%** of gold symbols: a 2.3× gap that is the real frontier, not an artefact.

We test five ways of adding a code graph — reranking, slot substitution at one and two hops, score fusion, fusion over only deterministically resolved edges, and personalised PageRank — under an identical candidate pool and character budget. **No graph arm improves symbol-level recall, and three significantly degrade file-level recall.** Then we repeat the measurement on all **2,232 scorable instances of the SWE-bench test split**. The gap does not move (2.28×) and the graph's file-level effect is still exactly zero, but two claims do: the best graph arm is worth **2.2 symbol-level points** once the sample can see it, and a hand-written evidence rule worth 2.9 points at 290 tasks is worth **nothing** at 2,232 — what we had read as a rule was a ranker short of training data. A ranker over sixteen cheap features reaches **36.1%** of symbols and **64.3%** of files.

## What we measured

**Gold symbols.** Each reference patch is parsed and every changed line maps to the innermost definition containing it in the *pre-fix* tree: a deleted line anchors itself, an added line the line before it. That gives 354 definitions over 290 tasks; the other 10 are dropped, 8 because they only add definitions and 2 because they change only module-level lines. A second, independent implementation — comparing each definition's own source text before and after the patch — reproduces 279 of the 300 keys exactly, and rescoring with it moves recall by at most 0.7 points.

**The instrument.** A BM25 pool of the top 200 symbols per task, documents made of path, qualified name, signature and docstring but deliberately *not* the body. Every arm fills exactly ten slots, and we report the characters those ten symbols would add to a prompt, so no arm wins by retrieving more.

## What we found

**The gap is the headline.** One ranking, scored two ways: 62.4% of gold files at rank 10, 27.5% of gold symbols. Line granularity agrees — 23.9% of the 1,010 changed lines — so the gap is not a matching artefact. At ten slots, no graph arm improves symbol-level recall, and the two that hurt file-level recall cost 4.8 and 4.5 points (p = 0.004 and p = 0.019).

**The graph is worth two points, once the sample can see it.** On all 2,232 scorable instances the best graph arm gains +0.022 of symbol recall (95% CI 0.013–0.031, 169 wins to 90) and exactly +0.000 of file recall. It is real and it is small, because it reorders symbols inside files text already found.

**The arithmetic explains why.** One-hop balls reach a gold symbol in 13.1% of tasks but hold 0.42% gold against 3.1% per text slot, and 54% of the call sites that would carry the hop resolve to no definite target. Perfect conversion is worth 11.9 points; diffusion converts 44% of what it reaches and still loses, 15 gained against 17 lost.

**What does work is reading the issue.** A traceback frame, a named path, a quoted line — the source an issue states — is where the margin is. The ranker that reads it reaches 36.1% of symbols and 64.3% of files; on tasks whose issue pastes a line from the gold body it gains 29.4 points at 290 tasks and 29.6 at 2,232, a finding that does not care about sample size.

![Figure 1](fig1.png)

*Figure 1 — top: symbol recall@k for BM25, the best graph arm, the learned ranker and the ranker with evidence. Bottom left: the same ranking by file and by symbol. Bottom right: the ranker's gain over BM25 by what the issue offers, at both scales.*

## Limitations

Python only. The eight-arm comparison uses one retriever, so the graph result is about its marginal value *given this ranking*. The learned ranker trains on six repositories and is tested on the other six, which bounds overfitting but leaves 290 tasks for the grid, re-checked on 2,232 for the three headline readings. The evidence channel does nothing on the 74% of issues that name no source, and pytest loses 12.5 points to tracebacks that point at test files. We measure retrieval, not resolution.

## Full paper and code

The complete paper — all seven tables, the two-scale tables, and the claim-to-evidence map — is the PDF in Project Links. Every number in it is re-derived from the released JSONL by a 210-assertion check script, so a claim that drifts from the data fails the build rather than the review. The harness, the gold symbols and the per-arm rankings are in the repository.
