# The answer key, audited

Every number in the paper divides by the gold symbol set, so the key is the one
thing worth attacking before a reviewer does. This note re-derives it a second
time, by a method that shares no code path with the first, and reports what
happens to the headline numbers when the second method wins.

Short version: **279 of 300 keys are reproduced exactly**; the 21 differences are
one added-definition case, five patches whose hunk headers do not match the
snapshot, and granularity disputes that never move a conclusion. Rescoring the
whole Lite study with a repaired key moves recall by **+0.2 to +0.7 points**, and
the arms keep their order.

## The rules being audited

`experiments/gold.py` + `experiments/patchfile.py` + `experiments/symbols.py`:

1. parse the reference patch, per file;
2. a deleted line anchors itself (old-side number); an added line anchors the
   old line *above* the insertion, because the added text does not exist yet;
3. resolve each anchor to the innermost `def`/`class` whose span contains it in
   the **pre-fix** tree;
4. gold = the set of `(path, qualname)` so found; a task with none contributes
   nothing and is dropped from the denominator.

## Three implementations

| | method | how it decides | shares with shipped |
| --- | --- | --- | --- |
| A | shipped | anchor → innermost pre-fix definition | — |
| C | repaired | A, with hunks re-located by matching their context lines, and a brand-new definition credited to the pre-fix parent it was inserted into | anchor logic |
| B3 | oracle | apply the patch, then compare **each definition's own text** (nested definitions cut out) before vs after; gold = own text changed, or definition gone | nothing |

B3 needs no line numbers, so a stale hunk header cannot break it; it also cannot
see an added definition (which does not exist before the fix) — that is a
property of the benchmark, not a defect of the method.

Code: `tools/verify_gold.py` (A vs B), `tools/gold_fix.py` (A, C, B3 together),
`tools/gold_summary.py` (the disagreement table), `tools/debug_gold.py` (one
task, every intermediate value). Data: `data/gold_fixed.jsonl` (Lite),
`data/gold_fixed_full_sample.jsonl` (every fifth task of the full split).

## What the audit found (300 Lite tasks)

```
tasks                        300
gold symbols, shipped (A)    354
gold symbols, oracle (B3)    340
gold symbols, repaired (C)   362
keys identical               279   (93.0%)
keys different                21
hunk headers that disagree     6 tasks (5 change the answer, 1 only adds the class)
```

The 21 differences, with an example each:

| kind | n | example | who is right |
| --- | --- | --- | --- |
| the patch inserts something inside an existing class; shipped also returns the class, the oracle does not | 13 | `pytest-dev__pytest-5413`: adds a `__str__` next to an edited one, so shipped = `{ExceptionInfo, ExceptionInfo.__str__}` | defensible either way: the insertion point is inside the class, the edit is in the method; the class costs one slot of denominator and is usually an easy hit |
| hunk headers do not line up with the snapshot | 5 | `matplotlib__matplotlib-24334`: the hunk says line 2029, the context is at 2021, so the shipped key scores `_get_tick_boxes_siblings` instead of `set_ticks` | repaired (C): the change is a docstring edit in `set_ticks` |
| shipped returns nothing, oracle finds a changed class | 1 | `django__django-15400` | repaired |
| mixed | 2 | `sympy__sympy-11870`, `sympy__sympy-13773`: one symbol right, one missed | repaired is closer |

The ten tasks the shipped key drops entirely are **2 module-level-only, 8
add-new-definitions**. The paper used to call all ten "module-level", which was
wrong for eight of them. Seven of the eight add a method to an existing class, so
the repaired key can still name the class; `sympy__sympy-21055` adds a top-level
`refine_arg` and has no pre-fix symbol at all. Both keys being empty on nine of
the ten, these count as *identical* above — the fix is not a disagreement but a
hole in the benchmark, which is why §3 says so explicitly.

## Full split: does the rate hold?

`tools/gold_fix.py --tasks data/_full_sample.jsonl` (459 tasks, every fifth):

```
keys identical   402 / 459  (87.6%)
gold, shipped   1284
gold, oracle    1263
gold, repaired  1297
stale hunks       12 tasks
```

Same mechanisms, slightly higher rate of "shipped misses a definition" (9 of 459,
2.0%), and two of those are **the oracle's fault**: `astropy__astropy-12842`
renames `TimeInfo` → `TimeInfoBase` and a new class takes the name `TimeInfo`, so
B3 compares two unrelated definitions that happen to share a qualname.
`matplotlib__matplotlib-26160` (`_AxLine` → `AxLine`) is the same shape. The rest
are decorator-only edits: `pallets__flask-4544` changes four `@click.option(...)`
lines above `run_command`, and a decorator sits *before* `def`, so the shipped
anchor lands above the definition. `django__django-15161` puts six classes in that
bucket the same way.

## Does it move the numbers?

`tools/gold_impact.py` re-labels the existing pools with the repaired key and
recomputes recall@10 with the *same* rankings — no retraining, so the answer key
is the only thing that changes:

| arm | shipped key | repaired key | delta |
| --- | ---: | ---: | ---: |
| BM25 | 0.2750 | 0.2819 | +0.0069 |
| best graph arm | 0.3044 | 0.3079 | +0.0034 |
| 16-feature ranker | 0.3324 | 0.3341 | +0.0017 |
| ranker + evidence | 0.3611 | 0.3646 | +0.0034 |

Per-task effects go both ways: `sympy__sympy-13437` loses a point (the shipped key
credited `bell._bell_incomplete_poly`, the repaired one knows the change is in
`bell.eval`), `sympy__sympy-20049` gains one, `sympy__sympy-13971` gains half.

The seven rescued tasks are *easier* than average — their repaired gold is a class
name the issue text mentions, so BM25 ranks it first on two of them and in the top
ten on five: recall 0.714 over the seven (`tools/gold_rescued.py`). Scoring them
would lift every arm by about a point, which is why they stay out: a class target
is not the same question as "find the edited method", and mixing them would make
the benchmark easier and less comparable across arms.

## Decision

Keep the shipped key and the shipped numbers, because:

- the disagreement rate is 7% of tasks, and the metric effect is +0.7 points at
  worst, smaller than every interval the paper reports;
- re-running the key means re-extracting features for 2,232 tasks and retraining
  the ranker ladder, which changes every table for a shift no claim depends on;
- what *was* wrong was the description of the 10 dropped tasks, now fixed in §3.

The paper carries one sentence: *"A second implementation — each definition's own
text, before and after the patch — reproduces 279 of 300 keys; rescoring with it
moves recall by at most 0.7 points."*

Re-run this audit if the key ever changes, and treat a jump in the "shipped misses
a definition" bucket as a bug in the patch parser, not in the source.

## Reproducing

```powershell
python tools/gold_fix.py --limit 300                 # A, C and B3 for Lite
python tools/gold_summary.py                         # the disagreement table
python tools/verify_gold.py --limit 300              # A vs the B text-diff method
python tools/gold_impact.py                          # A key vs C key, same rankings
python tools/gold_summary.py data/gold_fixed_full_sample.jsonl
```
