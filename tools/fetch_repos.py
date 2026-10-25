"""One-off: download the exact source snapshot of every SWE-bench Lite instance.

    python tools/fetch_repos.py [--jobs 6] [--limit N]

Each instance is pinned to `base_commit` (the pre-fix tree), fetched as a GitHub
tarball rather than by cloning, because we only ever need "the files as the agent
would have seen them" and 297 one-commit clones would download the same history
297 times.

Saved as data/repos/<owner>__<name>@<sha12>.tar.gz. experiments/snapshot.py reads
them in place, without extracting.
"""

import argparse
import json
import os
import queue
import sys
import threading
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(ROOT, "data", "swebench_lite.jsonl")
DEST = os.path.join(ROOT, "data", "repos")

UA = {"User-Agent": "swebench-snapshot-fetch/1.0"}


def target_path(repo, sha):
    return os.path.join(DEST, f"{repo.replace('/', '__')}@{sha[:12]}.tar.gz")


def fetch(url, dest, tries=4):
    tmp = dest + ".part"
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=180) as r, open(tmp, "wb") as f:
                while True:
                    chunk = r.read(1 << 16)
                    if not chunk:
                        break
                    f.write(chunk)
            size = os.path.getsize(tmp)
            if size < 1024:
                raise IOError(f"suspiciously small: {size} B")
            os.replace(tmp, dest)
            return size
        except Exception as e:  # noqa: BLE001 - retry anything transient
            if os.path.exists(tmp):
                os.remove(tmp)
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))
    raise RuntimeError("unreachable")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args(argv)

    os.makedirs(DEST, exist_ok=True)
    seen, jobs = set(), []
    with open(INDEX, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            key = (r["repo"], r["base_commit"])
            if key in seen:
                continue
            seen.add(key)
            jobs.append(key)
    if args.limit:
        jobs = jobs[: args.limit]

    todo = [k for k in jobs if not os.path.exists(target_path(*k))]
    print(f"{len(jobs)} unique snapshots, {len(jobs) - len(todo)} cached, {len(todo)} to fetch", flush=True)
    if not todo:
        return 0

    q = queue.Queue()
    for k in todo:
        q.put(k)
    lock = threading.Lock()
    stats = {"ok": 0, "bytes": 0, "fail": []}

    def worker():
        while True:
            try:
                repo, sha = q.get_nowait()
            except queue.Empty:
                return
            url = f"https://codeload.github.com/{repo}/tar.gz/{sha}"
            try:
                n = fetch(url, target_path(repo, sha))
                with lock:
                    stats["ok"] += 1
                    stats["bytes"] += n
                    done = stats["ok"]
                if done % 10 == 0 or done == len(todo):
                    print(f"  {done}/{len(todo)}  {stats['bytes'] / 1e6:.0f} MB  {repo}@{sha[:8]}", flush=True)
            except Exception as e:  # noqa: BLE001
                with lock:
                    stats["fail"].append(f"{repo}@{sha}: {e}")
                print(f"  FAIL {repo}@{sha}: {e}", flush=True)
            finally:
                q.task_done()

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(min(args.jobs, len(todo)))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    print(f"\ndone: {stats['ok']} fetched, {stats['bytes'] / 1e6:.0f} MB, {len(stats['fail'])} failed")
    for line in stats["fail"]:
        print("  ", line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
