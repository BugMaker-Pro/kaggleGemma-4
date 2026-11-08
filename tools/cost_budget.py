"""Character-budget curves: one ranking, two presentations.

For each scored Lite task, take the BM25 top-ten symbols and measure the source
text each presentation makes an agent read: the definition span (symbol) or the
whole file that contains it (file). Record gold coverage against cumulative
characters. Retrieval is not rerun; this only reprices saved rankings.

The snapshot is streamed once per task instead of building a random-access index,
because indexing a large tarball dominates the run time.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import tarfile
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BUDGETS = (2_000, 4_000, 8_000, 16_000, 32_000)


def load(name: str) -> list[dict]:
    with (ROOT / name).open(encoding='utf-8') as handle:
        return [json.loads(line) for line in handle if line.strip()]


def module_variants(path: str) -> list[str]:
    parts = path.removesuffix('.py').split('/')
    return ['.'.join(parts[index:]) for index in range(len(parts))]


def gold_symbols_of(record: dict) -> set[str]:
    found: set[str] = set()
    for file in record.get('files') or []:
        module = file['path'].removesuffix('.py').replace('/', '.')
        for symbol in file.get('symbols') or []:
            found.add(f"{module}.{symbol['qualname']}")
    return found


def work(task: str) -> dict:
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
                                     'chars': len('\n'.join(lines[start:end])),
                                     'gold': symbol in gold_keys})
                pending[symbol] = True
                if rel not in seen:
                    seen.add(rel)
                    file_items.append({'file': rel, 'rank': top.index(symbol), 'chars': len(text),
                                       'gold': sum(1 for key in gold_keys
                                                   if any(key.startswith(module + '.') for module in module_variants(rel)))})
    if not symbol_items:
        return {}

    def curve(items: list[dict]) -> list[dict]:
        total = hits = 0
        points = []
        for item in items:
            total += item['chars']
            hits += item['gold'] if isinstance(item['gold'], int) else int(item['gold'])
            points.append({'rank': item['rank'] + 1, 'cost': total, 'hits': hits})
        return points

    symbol_items.sort(key=lambda item: item['rank'])
    file_items.sort(key=lambda item: item['rank'])
    return {'task': task, 'gold_total': len(gold_keys), 'located': sum(1 for v in pending.values() if v),
            'symbol_items': symbol_items, 'file_items': file_items,
            'symbol_curve': curve(symbol_items), 'file_curve': curve(file_items)}


def recall_at_budget(curve: list[dict], budget: int, total: int) -> float:
    hits = 0
    for point in curve:
        if point['cost'] > budget:
            break
        hits = point['hits']
    return hits / total if total else 0.0


def summarise(rows: list[dict]) -> None:
    print(f'tasks {len(rows)}  located symbols '
          f'{statistics.fmean(row["located"] for row in rows):.1f}/10')
    print(f"{'budget':>8s}{'symbol R':>10s}{'file R':>8s}")
    for budget in BUDGETS:
        symbol = statistics.fmean(recall_at_budget(row['symbol_curve'], budget, row['gold_total']) for row in rows)
        files = statistics.fmean(recall_at_budget(row['file_curve'], budget, row['gold_total']) for row in rows)
        print(f"{budget:>8d}{symbol:>10.3f}{files:>8.3f}")
    print(f"\n{'slots':>6s}{'symbol R':>10s}{'sym chars':>11s}{'file R':>9s}{'file chars':>12s}")
    for k in (1, 5, 10):
        symbol = [(row['symbol_curve'][min(k, len(row['symbol_curve'])) - 1]['hits'] / row['gold_total'],
                   row['symbol_curve'][min(k, len(row['symbol_curve'])) - 1]['cost'])
                  for row in rows if row['symbol_curve']]
        files = [(row['file_curve'][min(k, len(row['file_curve'])) - 1]['hits'] / row['gold_total'],
                  row['file_curve'][min(k, len(row['file_curve'])) - 1]['cost'])
                 for row in rows if row['file_curve']]
        print(f"{k:>6d}{statistics.fmean(r for r, _ in symbol):>10.3f}"
              f"{statistics.fmean(c for _, c in symbol):>11.0f}"
              f"{statistics.fmean(r for r, _ in files):>9.3f}"
              f"{statistics.fmean(c for _, c in files):>12.0f}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=0)
    args = parser.parse_args()
    gold = {row['instance_id']: row for row in load('data/gold_symbols.jsonl')}
    tasks = sorted(task for task, row in gold.items() if row.get('has_symbols'))
    if args.limit:
        tasks = tasks[:args.limit]
    started = time.perf_counter()
    rows = []
    with ProcessPoolExecutor(max_workers=12) as pool:
        for index, row in enumerate(pool.map(work, tasks, chunksize=4), 1):
            if row:
                rows.append(row)
            if index % 25 == 0:
                print(f'  {index}/{len(tasks)} done in {time.perf_counter()-started:.0f}s', flush=True)
    with (ROOT / 'data/cost_budget.jsonl').open('w', encoding='utf-8', newline='\n') as handle:
        for row in rows:
            handle.write(json.dumps(row) + '\n')
    print(f'elapsed {time.perf_counter()-started:.0f}s')
    summarise(rows)


if __name__ == '__main__':
    main()
