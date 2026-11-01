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
