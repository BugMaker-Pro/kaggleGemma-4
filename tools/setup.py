"""Restore the environment, on any operating system, from the lockfile.

Nothing binary is tracked: no wheel, no model weights, no repository snapshots.
`uv sync` rebuilds the Python side and the two fetch scripts rebuild the heavy
inputs, so this runs the same on Linux, macOS and Windows.

    python tools/setup.py            # dependencies + the reranker weights
    python tools/setup.py --data     # also SWE-bench metadata and 18 GB of snapshots
    python tools/setup.py --core     # only what the audit needs (fast)

The exact restore command is `uv sync --frozen --all-extras`; this script skips
it when the environment already satisfies the pinned versions, because a machine
that installed torch from a locally assembled wheel would otherwise re-download
the same build from the index.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(command: list[str], **kwargs) -> int:
    print("$", " ".join(command), flush=True)
    return subprocess.call(command, cwd=ROOT, **kwargs)


def python_in_venv() -> Path:
    candidate = ROOT / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    return candidate


def installed(python: Path, modules: list[str]) -> str | None:
    """The versions already present, or None if the environment is not there yet."""
    if not python.exists():
        return None
    names = ", ".join(modules)
    printout = ", ".join(f"{module}.__version__" for module in modules)
    probe = f"import {names}; print({printout})"
    result = subprocess.run([str(python), "-c", probe], capture_output=True, text=True)
    return result.stdout.strip() or None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", action="store_true", help="also fetch the 18 GB of base-commit snapshots")
    ap.add_argument("--core", action="store_true", help="skip the model extra and the weights")
    args = ap.parse_args(argv)

    if shutil.which("uv") is None:
        print("uv is not on PATH: https://docs.astral.sh/uv/", file=sys.stderr)
        return 2

    python = python_in_venv()
    modules = ["lightgbm", "numpy"] if args.core else ["lightgbm", "numpy", "torch", "transformers"]
    have = installed(python, modules)
    if have:
        print(f"environment already installed: {have}")
        print("exact restore, if you want it anyway: uv sync --frozen --all-extras")
    else:
        if not python.exists():
            if run(["uv", "venv", "--python", "3.12", ".venv"]) != 0:
                return 1
        sync = ["uv", "sync", "--frozen", "--inexact"]
        if not args.core:
            sync.append("--all-extras")
        if run(sync) != 0:
            return 1
        python = python_in_venv()

    if not args.core and run([str(python), "tools/fetch_model.py"]) != 0:
        print("model download failed; the audit still runs without it", file=sys.stderr)

    if args.data:
        if run([str(python), "tools/fetch_swebench.py"]) != 0:
            return 1
        if run([str(python), "tools/fetch_repos.py", "--jobs", "6"]) != 0:
            return 1

    print()
    return run([str(python), "tools/audit_numbers.py"])


if __name__ == "__main__":
    raise SystemExit(main())
