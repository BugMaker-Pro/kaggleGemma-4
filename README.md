# Symbol-level retrieval on SWE-bench: what a code graph is worth

Retrieval for coding agents is usually reported at file granularity. We measure
the granularity an agent actually edits — the definition — and ask what a code
graph buys there.

**[Paper (PDF)](paper/submission.pdf)** · Kaggle *Gemma 4 Developer Agent* Paper Track, 2026

![Top: symbol recall@k for BM25, the best graph arm, the learned ranker and the ranker with evidence. Bottom left: the same ranking by file and by symbol. Bottom right: the ranker's gain over BM25 by what the issue offers, at both scales.](paper/fig1.png)

## Findings

- **The gap.** One ranking, two granularities: 62.4% of gold files at rank 10,
  27.5% of gold symbols. 2.3×, and not a matching artefact — line-level coverage
  of the changed lines is 23.9%. At 2,232 tasks the same ratio is 2.28×.
- **A code graph buys two points, and only inside a file.** Eight arms — rerank,
  one- and two-hop substitution, score fusion, fusion over definite edges only,
  personalised PageRank, PPR + text — leave symbol-level recall at ten slots
  unchanged on 300 tasks, and gain +0.022 (95% CI 0.013–0.031) on 2,232 with
  exactly +0.000 at file level.
- **The arithmetic says why.** One-hop balls hold 0.42% gold against 3.1% per
  text slot, 54% of call sites resolve to no definite target, and even perfect
  conversion is worth 11.9 points.
- **Reading the issue beats inferring structure.** A ranker over sixteen cheap
  features reaches 36.1% of symbols and 64.3% of files. A hand-written evidence
  rule worth 2.9 points on 290 tasks is worth −0.002 on 2,232: it was a ranker
  short of training data.
- **What you index moves the gap.** Adding the candidate's own body to the index
  raises symbol recall from 0.248 to 0.286 (+3.8 points, CI 2.1–5.4) with file
  recall flat, so the 2.28× gap becomes 1.97× — and another symbol's body instead
  drops recall to 0.128, so the gain is the candidate's own text, not more text.
- **Most 300-task comparisons cannot see this.** Resampling the 2,232 paired
  differences: a true +2.2-point effect is detected at n = 290 in 39% of draws
  and at 800 in 87%, while a +11.3-point effect is detected at n = 100 in 88%.
  The usual sample size resolves five-point effects and no smaller.

## Reproduce the numbers

```bash
uv venv --python 3.12 .venv
uv sync --frozen
uv run python tools/audit_numbers.py     # 220 assertions, 0 failures
```

That is the whole check: every number in the paper is re-derived from the tracked
JSONL, so a claim that drifts from the data fails the run rather than the review.
It needs no GPU, no model and no repository snapshots.

For the full environment — the reranker weights and 18 GB of base-commit
snapshots — use the same script on any OS:

```bash
uv run python tools/setup.py           # + 2.12 GB reranker weights
uv run python tools/setup.py --data    # + SWE-bench metadata and snapshots
```

`uv.lock` is the environment: change `pyproject.toml` and re-lock rather than
pinning by hand. Nothing binary is tracked — no wheel, no weights, no snapshots.

## Layout

| path | contents |
| --- | --- |
| `experiments/` | gold-symbol extraction, `ast` graph builder, BM25 pool, snapshot reader |
| `tools/` | the eight arms, the ranker, ablations, the audit, the figure, the PDF |
| `data/` | the answer key and per-arm rankings (JSONL, tracked) |
| `paper/` | source, PDF, table figures |
| `docs/` | design notes, the answer-key audit, the scale check |

## The answer key has its own audit

Every number divides by the gold symbol set, so a second, independent
implementation re-derives it: apply the patch, then compare each definition's own
source text before and after. It reproduces 279 of 300 keys exactly; the 21
differences are added definitions, renamed classes, and patch hunk headers that
do not match the snapshot. Rescoring with the repaired key moves recall by at
most 0.7 points. Full table: [docs/gold-audit.md](docs/gold-audit.md).

## Scope

Python only. The eight-arm comparison uses one retriever, so the graph result is
about its marginal value *given this ranking*. We measure retrieval, not
resolution: a better shortlist is necessary for a better patch, not sufficient.

## Cite

> File-Level Is Not Symbol-Level: What Code Graphs Miss and the Issue Already
> States. Kaggle Gemma 4 Developer Agent Paper Track, 2026.
> <https://github.com/BugMaker-Pro/kaggleGemma-4>

Working notes — schedule, submission checklist, local environment quirks — are in
[docs/status.md](docs/status.md).
