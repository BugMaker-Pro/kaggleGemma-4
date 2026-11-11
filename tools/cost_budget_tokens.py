"""Token-budget curves: the equal-token counterpart of cost_budget.py.

The paper's budget analysis charges presentations in characters, and the
Limitations section admits there is no equal-token comparison. This reruns the
same repricing with a real tokenizer (bge-small-en-v1.5, the model the dense
arm uses), so the symbol-versus-file presentation gap is measured in the unit
an agent actually pays. Retrieval is not rerun; saved rankings are repriced.

    python tools/cost_budget_tokens.py --jobs 2
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.cost_budget import BUDGETS as CHAR_BUDGETS  # noqa: E402
from tools.cost_budget import load, gold_symbols_of, module_variants, recall_at_budget  # noqa: E402

TOKEN_BUDGETS = (500, 1_000, 2_000, 4_000, 8_000)
_TOKENIZER = None


def _init() -> None:
    global _TOKENIZER
    from transformers import AutoTokenizer
    _TOKENIZER = AutoTokenizer.from_pretrained(str(ROOT / 'models' / 'bge-small-en-v1.5'))


def _tokens(text: str) -> int:
    return len(_TOKENIZER.encode(text, add_special_tokens=False))


def work(task: str) -> dict:
    import tarfile
    from experiments.snapindex import SnapshotIndex
    from experiments.symbols import python_symbols

    runs = {row['instance_id']: row for row in load('data/experiment_v3.jsonl')}
    issues = {row['instance_id']: row for row in load('data/swebench_lite.jsonl')}
    gold = {row['instance_id']: row for row in load('data/gold_symbols.jsonl')}
    run = runs.get(task)
    if not run or 'text' not in run.get('arms', {}):
        return {}
    top = run['arms']['text']['top'][:10]
    gold_keys = gold_symbols_of(gold[task])
    if not gold_keys:
        return {}

    index = SnapshotIndex(str(ROOT / 'data' / 'repos'))
    path = index.path_for(issues[task])
    if path is None:
        return {}

    pending = {symbol: None for symbol in top}
    file_items: list[dict] = []
    symbol_items: list[dict] = []
    seen: set[str] = set()
    with tarfile.open(path, 'r:gz') as archive:
        for info in archive:
            if not info.isfile() or not info.name.endswith('.py'):
                continue
            rel = info.name.lstrip('./')
            matched = [symbol for symbol in pending
                       if any(symbol.startswith(module + '.') for module in module_variants(rel))]
            if not matched:
                continue
            handle = archive.extractfile(info)
            if handle is None:
                continue
            text = handle.read().decode('utf-8', 'replace').replace('\r\n', '\n')
            lines = text.splitlines()
            parsed = python_symbols(text)
            for symbol in matched:
                qualname = next((m for m in module_variants(rel) if symbol.startswith(m + '.')), None)
                if qualname is None:
                    continue
                tail = symbol[len(qualname) + 1:]
                span = next((item for item in parsed if item.qualname == tail), None)
                if span is None:
                    continue
                start = max(0, span.lineno - 1)
                end = min(len(lines), span.end_lineno)
                symbol_items.append({'symbol': symbol, 'file': rel, 'rank': top.index(symbol),
                                     'tokens': _tokens('\n'.join(lines[start:end])),
                                     'gold': symbol in gold_keys})
                pending[symbol] = True
                if rel not in seen:
                    seen.add(rel)
                    file_items.append({'file': rel, 'rank': top.index(symbol), 'tokens': _tokens(text),
                                       'gold': sum(1 for key in gold_keys
                                                   if any(key.startswith(module + '.')
                                                          for module in module_variants(rel)))})
    if not symbol_items:
        return {}

    def curve(items: list[dict]) -> list[dict]:
        total = hits = 0
        points = []
        for item in items:
            total += item['tokens']
            hits += int(item['gold'])
            points.append({'rank': item['rank'] + 1, 'cost': total, 'hits': hits})
        return points

    symbol_items.sort(key=lambda item: item['rank'])
    file_items.sort(key=lambda item: item['rank'])
    return {'task': task, 'gold_total': len(gold_keys),
            'symbol_items': symbol_items, 'file_items': file_items,
            'symbol_curve': curve(symbol_items), 'file_curve': curve(file_items)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--out', default=str(ROOT / 'data' / 'cost_budget_tokens.jsonl'))
    args = parser.parse_args()

    gold = {row['instance_id']: row for row in load('data/gold_symbols.jsonl')}
    tasks = sorted(task for task, row in gold.items() if row.get('has_symbols'))
    if args.limit:
        tasks = tasks[:args.limit]
    started = time.perf_counter()
    rows = []
    with ProcessPoolExecutor(max_workers=args.jobs, initializer=_init) as pool:
        for index, row in enumerate(pool.map(work, tasks, chunksize=4), 1):
            if row:
                rows.append(row)
            if index % 50 == 0:
                print(f'  {index}/{len(tasks)} done in {time.perf_counter()-started:.0f}s', flush=True)
    with Path(args.out).open('w', encoding='utf-8', newline='\n') as handle:
        for row in rows:
            handle.write(json.dumps(row) + '\n')
    print(f'elapsed {time.perf_counter()-started:.0f}s  ->  {args.out}')

    print(f'tasks {len(rows)}')
    print(f"{'tokens':>8s}{'symbol R':>10s}{'file R':>8s}")
    for budget in TOKEN_BUDGETS:
        symbol = statistics.fmean(recall_at_budget(r['symbol_curve'], budget, r['gold_total']) for r in rows)
        files = statistics.fmean(recall_at_budget(r['file_curve'], budget, r['gold_total']) for r in rows)
        print(f"{budget:>8d}{symbol:>10.3f}{files:>8.3f}")
    symbol10 = statistics.fmean(r['symbol_curve'][-1]['cost'] for r in rows)
    file10 = statistics.fmean(r['file_curve'][-1]['cost'] for r in rows)
    print(f'ten slots cost: {symbol10:.0f} tokens as definitions, {file10:.0f} as whole files')


if __name__ == '__main__':
    main()
