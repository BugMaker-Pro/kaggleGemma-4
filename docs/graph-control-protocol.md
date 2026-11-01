# Graph-control experiment protocol (frozen before new outcome inspection)

Date: 2026-11-01 (Asia/Shanghai). This is a prospective follow-up to an already inspected benchmark, not a preregistration of the original paper. No new control-arm outcomes were inspected when this protocol was written. The existing benchmark and its broad results have informed the question.

## Question and population

Does one-hop graph reranking add target-selection information beyond file proximity and matched degree structure, and does that effect change when retrieval uses bodies or dense scores?

Primary population: all 2,232 scored tasks in `features_full.jsonl`, across the same 12 repositories. Lite (290 scored tasks contained in the full population) is a descriptive subset, not independent validation. No task is removed based on an outcome. Missing snapshots, dense scores, mismatched candidate IDs, or graph-reproduction failures stop completion rather than silently reducing N.

## Common candidate set and representations

Hold each task's original metadata-BM25 pool of at most 200 symbol IDs fixed. Labels and the denominator (all gold symbols, including those outside the pool) come from the saved feature record. File recall uses the same first ten symbol slots and the saved gold files.

Three base orders:

1. `metadata`: original candidate order, preserving unrounded BM25 tie order.
2. `body`: metadata plus the candidate's first 80 source lines, with corpus-wide BM25 document frequencies and average length over all graph nodes, then ranking only the common pool. This isolates ordering conditional on the fixed pool; it cannot measure body-based candidate-generation gains.
3. `dense`: frozen saved cosine scores from `embed_retrieval.jsonl`, mapped back to pool indices. Preserve its recorded score order for ties. No model training or rescoring.

Document representation and tokenizer match `body_ablation.py`. Query terms are counted once as in the existing BM25 implementation. Corpus statistics must be computed from all indexed nodes even though only common-pool scores are needed. Unit tests compare the restricted scorer against the existing full BM25 scorer.

## Reranking intervention

Keep the top five seeds in place; among remaining candidates, promote those one hop from a seed, retaining the base order within the promoted and unpromoted groups. Return ten symbols. This matches the full-scale `features.py` graph-rerank convention. The older Lite `run_experiment.py` can move seeds; we do not combine these protocols.

Rebuild the existing AST graph from the exact base snapshot. Project undirected, deduplicated `calls`/`inherits` edges onto the common candidate pool. Ignore self-loops (irrelevant with retained seeds). Because only one-hop pool-internal reranking is tested, this projection preserves every edge that can affect the shortlist. Reproduce saved `rerank_top10` exactly on the metadata order before evaluating controls. No patch or label is passed to graph randomization or ranking.

Four intervention families for each base:

- `base`: unchanged ranking.
- `real`: actual projected topology.
- `file`: promote all candidates in a seed's file. This is a coarse proximity control, not a density-matched graph.
- `rewired`: degree-preserving double-edge swaps on the candidate-induced graph, keeping every node's within-file and cross-file degrees fixed. Within-file swaps remain in their original file; cross-file swaps must remain cross-file.
- `rewired_pair`: stricter sensitivity analysis; additionally preserve every node's degree to each partner file, by swapping only within the same unordered file-pair bucket.

The two randomization families use seeds **11, 23, 37, 51, 71**, combined with the task ID using SHA256 (not Python's randomized hash). Perform **20 attempted swaps per edge per applicable bucket**. Reject loops, duplicate edges, and null swaps. Preserve invariant checks for every randomized graph. The attempts budget is fixed, not chosen by outcome.

Edges outside the pool remain conceptually unchanged, so preserving each pool node's internal degrees also preserves its total degree in the full graph. We do not claim uniform sampling from the constrained graph space or demonstrate Markov-chain mixing. Record attempts, accepted swaps, changed-original-edge fraction, and seed-reach changes. Retain immobile graphs in the main analysis; additionally describe the graph-only subset with mean changed-edge fraction >= 0.25. Zero difference under an immobile null cannot establish absence of topology information.

This experiment addresses static, one-hop, pool-internal ranking. It does not evaluate multi-hop expansion, free candidate generation, graph construction quality, or downstream repair.

## Outcomes and inference

Primary outcome: macro symbol recall@10. Average the five randomized outcomes *within task* before paired inference; do not treat random seeds as additional tasks. Also report file recall, per-task wins/losses, gained/lost gold relative to the same base order, real promotion counts, and per-repository effects.

Five primary contrasts, all two-sided:

1. real minus rewired under metadata;
2. real minus rewired under body;
3. real minus rewired under dense;
4. (real minus rewired | body) minus (real minus rewired | metadata);
5. (real minus rewired | dense) minus (real minus rewired | metadata).

Use Holm correction across these five. Report repository-cluster bootstrap intervals (10,000 draws of 12 repositories with replacement, pooling their tasks, seed 20261101). For tests enumerate all 2^12 repository sign flips of paired effect sums, a weighted macro effect test. This relies on exchangeable/symmetric repository effects under the null; it is not an assumption-free guarantee with twelve heterogeneous repositories. Report ordinary task-level exact sign tests as secondary diagnostics, clearly distinguished from the mean-effect test.

Secondary contrasts: real minus base, real minus file, real minus rewired_pair, and their representation interactions. Report effect sizes and intervals as exploratory; do not promote a secondary significant result to the primary claim. Report seed sensitivity and the mobility subset even if they weaken the conclusion.

## Interpretation fixed in advance

- Real graph exceeding both file and randomized controls supports independent topology information under this setup.
- Real graph and a *mobile* matched null having similar performance weakens a topology-specific explanation but is not an equivalence result without an equivalence margin/test.
- A negative representation interaction supports smaller conditional topology advantage with stronger inputs; it does not prove a general compensation mechanism.
- A persistent positive effect supports complementarity in this setting.
- Failure to reproduce the existing full-scale metadata arm is a protocol/implementation issue to resolve before interpretation.

All outcomes, including reversals and null findings, will be retained. New controls should be reported separately from historical Lite arms. No paper headline will be changed until the full primary run and matching diagnostics have been inspected.

## Method references

- NetworkX double-edge swap documentation (degree-preserving operation): https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.swap.double_edge_swap.html
- SciPy permutation-test documentation (paired sign flips): https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.permutation_test.html

Our implementation adds file constraints and applies sign flips at repository level. These documents do not validate the resulting graph ensemble or repository exchangeability assumptions.
