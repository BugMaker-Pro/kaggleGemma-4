# Reproducing the topology controls

See the frozen design in `graph-control-protocol.md`. All commands run from the repository root. Keep these outputs separate from historical experiment files.

## Audit the released experiment without snapshots or models

```bash
uv run python -m unittest tests.test_graph_controls -v
uv run python tools/audit_graph_controls.py
uv run python tools/analyse_graph_controls.py
uv run python tools/plot_graph_controls.py
```

The audit independently recomputes every saved shortlist metric, checks seed retention and candidate membership, checks dense scores and metadata graph ranks against historical results, verifies input hashes, and deterministically replays rewiring on one task per repository. No model is loaded. Analysis uses NumPy and plotting uses Matplotlib, already in the experiment environment.

`graph_controls_context.jsonl` contains candidate IDs, files, labels, projected edges, three base orders, body scores, base commits, and timing. `graph_controls.jsonl` contains every intervention's top-ten indices and metrics, plus rewiring mobility diagnostics. The manifest records the complete intended task population, code/data SHA256 hashes, random seeds and attempts budget. The summary records its analysis source and result-file hashes.

All randomized degrees are asserted in the runner. Five graph seeds are averaged within task; the inference unit for the main test is the repository, not the random graph. The first record encountered for each repository is replayed by the audit; the sample is not chosen by its effect size.

## Rebuild from base-commit snapshots

This requires the original `data/swebench_full.jsonl`, `data/repos/` snapshots, `features_full.jsonl`, and frozen `embed_retrieval.jsonl`. See `reproduction.md` for preparing those inputs. This follow-up reuses stored dense scores and does not train or call a model. Its dense baseline is the frozen cosine ranking, not the 44.7% learned fusion, which already includes graph features and would not be a graph-free baseline.

```bash
uv run python tools/run_graph_controls.py --jobs 6 --out data/graph_controls.jsonl
```

The runner refuses to overwrite an existing experiment without `--resume`. To run a separate replication, choose a new output path, then pass that file to the audit and analysis commands. `--resume` requires unchanged manifest code/input hashes and valid complete JSONL records. Do not hand-edit an incomplete last line or force a changed protocol into the same manifest.

```bash
uv run python tools/run_graph_controls.py --jobs 6 --out data/graph_controls.jsonl --resume
uv run python tools/run_graph_controls.py --out data/graph_controls.jsonl --replay
```

`--replay` recomputes cheap graph controls from cached contexts; it still verifies the original manifest inputs. It does not rerun AST parsing or body scoring.

## Computation-only optimization

`experiments/cached_graph.py` caches file-local parse descriptors and body token counts keyed by file path and source SHA256. It does **not** reuse resolved edges between revisions: all names are resolved against each snapshot's full node set again. It clears caches when changing repositories and removes absent paths.

Before the complete run, exact graph and body-score parity was checked on real astropy, django and sympy snapshots. Warm graph reconstruction took approximately 0.2–0.4 seconds there versus 8–16 seconds for the uncached implementation. Additionally, the first 36 completed contexts from the uncached trial exactly matched the cached run's candidate IDs, labels, edges, all three base orders and body scores. Fixture tests cover source changes, deleted files, syntax errors, imports and nested definitions.

An initial uncached run was stopped for runtime optimization. Its partial outputs are kept under local `tmp/review/graph-controls-uncached/`; they are not treated as an additional replication or included twice. No outcomes from that run were interpreted or used to select parameters. The full run uses the fixed protocol and records the cached implementation hash.

## Limits of reproducibility

Saved dense score files identify candidates by indices in the historical feature pool; the audit verifies those permutations and score-derived outcomes. The original embedding execution did not record its own checkpoint manifest; see the provenance qualification in `reproduction.md`. The new follow-up manifest hashes the reused scores exactly.

The constrained edge-swap procedure preserves degrees but does not establish uniform sampling or mixing. Results must be interpreted alongside acceptance and edge-change diagnostics. Source reconstruction and score auditing do not establish scientific novelty or validate all causal interpretations.
## Cross-platform hashing

The execution manifest retains exact byte hashes from this Windows run. Some pre-existing JSONL inputs contain CRLF while Git enforces LF on checkout. After the run, a separate `graph_controls.portable.json` stores UTF-8/LF canonical hashes **only after verifying every raw execution hash**, and records the original execution manifest hash. The execution manifest itself stays unchanged. The audit accepts a canonical match solely for BOM/line-ending normalization and prints how many inputs used it. Manifest paths are interpreted with either separator. This preserves the recorded execution lineage without treating a normal Git checkout as a changed experiment.

`--resume` remains intentionally strict to the original byte manifest. On a checkout whose line endings changed, reproduce under a fresh output name; do not replace the original execution hashes. The full task metadata and reused dense scores are included in the release allowlist so the input-hash audit does not need a network download.

## Planned versus descriptive analysis

The five primary contrasts, randomization constraints, seeds, edge-swap attempt count, Holm correction, and repository-level inference were fixed in `graph-control-protocol.md` before new outcome inspection. A later descriptive diagnostic reports how much gold was already in the retained five seeds and the oracle headroom left in the common pool. This diagnostic was added while computation was running to guard against overinterpreting representation interactions; it is not an extra primary test, a new selection rule, or an equivalence claim.
