# Reproducing the reported rankings

This distinguishes recomputing metrics from released outputs from rerunning retrieval and training. The initial November 1 revision changed reporting and build consistency. A later topology-control follow-up adds new experiment outputs without retraining models or replacing historical outputs; see `graph-control-reproduction.md`.

## Saved-output audit

```bash
uv sync --frozen
uv run python tools/audit_numbers.py
uv run python -m unittest discover -s tests
```

The audit reads tracked JSONL and checks published values. Passing it does not prove methodological validity or independently rerun every experiment. See `docs/gold-audit.md` for the separate gold-symbol derivation audit.

## Evaluation split

The twelve repository names are sorted and alternating names form two groups:

- A: astropy/astropy, matplotlib/matplotlib, pallets/flask, pydata/xarray, pytest-dev/pytest, sphinx-doc/sphinx.
- B: django/django, mwaskom/seaborn, psf/requests, pylint-dev/pylint, scikit-learn/scikit-learn, sympy/sympy.

Train on A and score B, then train on B and score A. Each task contributes once to the final mean. Each fold averages predictions from seeds 0, 1, 2. LightGBM uses lambdarank, 300 rounds, learning rate 0.05, 15 leaves, min_data_in_leaf 20. The full feature order is `ORDER` in `tools/run_combo_ltr.py`.

Lite has 290 scorable tasks out of 300. Full test has 2,232 out of 2,294; Lite is included. The benchmark was used during exploratory method development, so held-out repositories do not imply an untouched external benchmark.

File recall uses distinct gold files represented by the first ten **symbols**, not the first ten distinct retrieved files. Symbol recall divides by all of a task's gold symbols, including targets absent from the pool. The principal pool size is 200; the 500-candidate tail diagnostic is separate. The eight-arm comparison has one baseline and seven graph interventions, not eight graph interventions.

## Data and encoder inputs

Full retrieval requires metadata and base-commit snapshots, which are not all tracked. Use the fetching tools; metadata conversion also requires `pyarrow`:

```bash
uv pip install pyarrow
uv run python tools/fetch_swebench.py --dataset princeton-nlp/SWE-bench --split test --out data/swebench_full.jsonl
uv run python tools/fetch_repos.py --index data/swebench_full.jsonl --jobs 6
```

For encoder scoring install the model extra with `uv sync --frozen --extra model`. Fetch the paper's bi-encoder explicitly; the general setup script defaults to a different cross-encoder used in earlier experiments:

```bash
uv run python tools/fetch_model.py --model BAAI/bge-small-en-v1.5 --revision 5c38ec7c405ec4b44b94cc5a9bb96e735b38267a
```

The revision is recorded in this checkout's Hugging Face download metadata for both config.json and model.safetensors. Metadata's model SHA256 is `3c9f31665447c8911517620762200d2245a2518d6e7208acc78cd9db317e21ad`. This identifies the available checkpoint; historical score files do not embed a provenance manifest. It is not an independent proof of historical execution.

Scoring uses the first 1,200 issue characters prefixed with `Represent this query for retrieving code: `; each document contains path, symbol ID, and its first 800 body characters. Tokenization caps inputs at 512 tokens. CLS vectors are normalized and compared by cosine; saved scores are rounded to four decimals. Model inference uses fp16. This differs from the metadata-only BM25 input and must not be called an equal-input semantic ablation.

## Rerunning rankings

Run in a separate checkout or change output paths to preserve published outputs for comparison. Features are already released; rebuilding them is optional:

```bash
uv run python tools/features.py --tasks data/swebench_full.jsonl --out data/features_full.jsonl --jobs 6
uv run python tools/run_combo_ltr.py --rows data/features_full.jsonl --out data/combo_ltr_full.jsonl --orders-out data/combo_ltr_orders_full.jsonl
uv run python tools/embed_retrieve.py --model models/bge-small-en-v1.5 --rows data/features_full.jsonl --tasks data/swebench_full.jsonl --out data/embed_retrieval.jsonl
uv run python tools/body_rank_feature.py --rows data/features_full.jsonl --tasks data/swebench_full.jsonl --out data/body_rank_features.jsonl --jobs 5
uv run python tools/rank_with_dense.py --rows data/features_full.jsonl --embed data/embed_retrieval.jsonl --body-extra data/body_rank_features.jsonl --out data/dense_scores.jsonl
```

The dense script also evaluates the optional body-rank combination, so the body-rank feature file must be supplied for its current implementation. Expected full-scale macro recalls from saved outputs:

| arm | symbol | file |
| --- | ---: | ---: |
| metadata BM25 | 0.248 | 0.564 |
| graph rerank | 0.270 | 0.564 |
| 16-feature ranker | 0.361 | 0.643 |
| dense alone | 0.366 | 0.693 |
| ranker + dense | 0.447 | 0.727 |

Do not silently omit tasks with missing embeddings or snapshots; verify the expected 2,232 scored task IDs before comparison. The November 1 revision audited saved metrics and reviewed the configuration; it did not execute this entire training sequence anew.

## Publication build

`paper/main.md` is the source. `tools/make_submission.py` removes internal notes. Use its full-text count, including table text, rather than counting only the image-based writeup body.

PDF/table-image build additionally requires `python-docx`, Node, and LibreOffice Kit (`LIBREOFFICE_KIT_CLI`; optional `NODE_BIN`). Use a writable temporary directory. These build dependencies are separate from the locked experiment dependencies.

```bash
uv pip install python-docx==1.2.0
uv run python tools/make_submission.py
uv run python tools/make_pdf.py
uv run python tools/make_table_images.py
uv run python tools/make_kaggle_full.py
uv run python tools/make_kaggle_images.py
uv run python tools/make_html.py
uv run python tools/check_publication.py
```

The publication check detects source/PDF drift, required sections, reference/table numbering, word-limit violations, and stale unsupported phrases. It supplements numerical auditing; it does not verify scholarly novelty or replace visual review of the rendered PDF.

### Local PDF converter installation

The optional LibreOffice Kit runtime lives in `.tools/libreoffice-kit/`, outside
`tmp/`. `tools/make_pdf.py` and `tools/make_table_images.py` find its
`node_modules/@deepseek-ai/libreoffice-kit/lib/cli.js` automatically.
`LIBREOFFICE_KIT_CLI` remains an explicit override; `NODE_BIN` overrides Node.
The two local installer archives are retained in `.tools/libreoffice-kit/archives/`,
and the npm manifests use paths relative to this persistent directory. The runtime
and installers are ignored by Git; normal temporary-file cleanup must preserve
`.tools/`. Generated documents and rendering checks belong in temporary/cache
directories, not in the runtime installation.

---

<a id="graph-control-reproduction"></a>
## Reproducing the topology controls

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

An initial uncached run was stopped for runtime optimization. Its partial outputs are kept under local `experiments/runs/graph-controls-uncached-20261101/`; they are not treated as an additional replication or included twice. No outcomes from that run were interpreted or used to select parameters. The full run uses the fixed protocol and records the cached implementation hash.

## Limits of reproducibility

Saved dense score files identify candidates by indices in the historical feature pool; the audit verifies those permutations and score-derived outcomes. The original embedding execution did not record its own checkpoint manifest; see the provenance qualification in `reproduction.md`. The new follow-up manifest hashes the reused scores exactly.

The constrained edge-swap procedure preserves degrees but does not establish uniform sampling or mixing. Results must be interpreted alongside acceptance and edge-change diagnostics. Source reconstruction and score auditing do not establish scientific novelty or validate all causal interpretations.
## Cross-platform hashing

The execution manifest retains exact byte hashes from this Windows run. Some pre-existing JSONL inputs contain CRLF while Git enforces LF on checkout. After the run, a separate `graph_controls.portable.json` stores UTF-8/LF canonical hashes **only after verifying every raw execution hash**, and records the original execution manifest hash. The execution manifest itself stays unchanged. The audit accepts a canonical match solely for BOM/line-ending normalization and prints how many inputs used it. Manifest paths are interpreted with either separator. This preserves the recorded execution lineage without treating a normal Git checkout as a changed experiment.

`--resume` remains intentionally strict to the original byte manifest. On a checkout whose line endings changed, reproduce under a fresh output name; do not replace the original execution hashes. The full task metadata and reused dense scores are included in the release allowlist so the input-hash audit does not need a network download.

## Planned versus descriptive analysis

The five primary contrasts, randomization constraints, seeds, edge-swap attempt count, Holm correction, and repository-level inference were fixed in `graph-control-protocol.md` before new outcome inspection. A later descriptive diagnostic reports how much gold was already in the retained five seeds and the oracle headroom left in the common pool. This diagnostic was added while computation was running to guard against overinterpreting representation interactions; it is not an extra primary test, a new selection rule, or an equivalence claim.

## Strong dense-fusion graph-feature ablation (November 8)

The follow-up retrains the 16-feature-plus-dense ranker after removing in-degree,
out-degree, and seed adjacency. Pools, frozen dense inputs, folds, seeds and
training settings remain fixed. The original 4,464 per-task symbol/file metrics
must reproduce before fitting the ablation. One primary symbol-recall contrast
uses repository-cluster intervals and repository sign flips.

```bash
# Audit released rankings and statistics without fitting models.
uv run python tools/audit_dense_graph_ablation.py
# Retrain in a fresh destination; existing run directories are never overwritten.
uv run python tools/ablate_dense_graph.py --out experiments/runs/dense-graph-ablation-reproduction
uv run python tools/audit_dense_graph_ablation.py --run-dir experiments/runs/dense-graph-ablation-reproduction
```

The released run is `experiments/runs/dense-graph-ablation-20261108-v1/`.
Its original frozen manifest is preserved. `portable-inputs.json` additionally
records verified UTF-8/LF equivalents so Git's CRLF/LF conversion does not produce
false lineage errors. Removing topology-derived columns retains AST symbol
extraction; this is a conditional feature ablation, not graph-free parsing or an
agent repair comparison. Complete results are in [retrieval experiments](experiments/retrieval.md).
