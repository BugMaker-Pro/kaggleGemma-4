# Project overview — not the full paper submission

**Beyond File Hits: Candidate Coverage and Graph Utility in Code Localization**

Use `kaggle_body_img.md`, `kaggle_body_full.md`, or the public `submission.pdf` for the actual paper. This overview omits the full methods and references required for submission.

The study separates three retrieval questions: whether a candidate pool contains the edited definition, whether a fixed-length shortlist selects it, and whether evaluation credits a file or symbol hit. On 290 scorable SWE-bench Lite tasks, one ranking covers 62.4% of gold files but 27.5% of gold symbols at ten slots.

Seven graph variants yield no statistically significant symbol improvement on Lite. The full split reveals a small positive graph-reranking effect (+2.2 points) and positive graph-feature value inside a learned ranker. Graph reach can add candidates, but replacing existing hits may erase that benefit. These are findings about one static retrieval setup, not graph-guided agents in general.

Index content matters: candidate bodies improve full-scale BM25 symbol recall by 3.8 points. Combining sixteen explicit features with a frozen dense score reaches 44.7% symbol and 72.7% file recall under repository-held-out evaluation.

The released resource includes patch-derived gold targets, an independent gold audit, per-task outputs and numerical verification. Limits include Python-only data, overlapping Lite/full splits, unequal character budgets, and no downstream repair evaluation. Prior work already studies function localization and graph-tool ablations; the contribution is the controlled diagnosis and audit.

Full protocol: `docs/reproduction.md`. Novelty assessment and proposed follow-up controls: `docs/novelty-review.md`.
