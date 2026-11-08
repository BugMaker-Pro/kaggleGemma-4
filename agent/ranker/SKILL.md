---
name: ranker
description: Localize a Python issue with BM25 candidates, AST/evidence features, a frozen dense encoder, and trained ranking trees. Returns ten symbols with source locations. Use before editing when the issue does not already identify a precise fix.
license: Apache-2.0
---

# Repository localization

Call `run_skill_script` with `skill_name: ranker`, `file_path: scripts/localize.py`, and `args: {"issue": "the complete original issue text"}`. The complete pipeline reads the current repository, ranks up to 200 BM25 candidates using 16 explicit features and one dense score, and returns ten source locations. Use the original issue without reference patches or hidden tests.

Read the most relevant returned definition and its necessary context before editing. The ranking supplies leads; it does not establish the root cause. Avoid repeatedly rerunning the same query. For module-level changes or new definitions, inspect surrounding code as needed.

If the script reports an error, continue with ordinary search. Full mode never silently substitutes a lexical ranking. `mode: lexical` is a separately labelled diagnostic alternative using a separately trained 16-feature model. All generated files are transient; the tool does not edit repository source.

The compact encoder is an INT8 deployment variant of the frozen BGE encoder. Its accuracy is measured separately from the paper's original floating-point encoder. The skill requires the numerical runtime documented in its build manifest; passing the local Kaggle notebook does not establish availability in the competition Docker sandbox.
