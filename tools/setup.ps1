# Restore the environment from uv.lock. Nothing binary is tracked: no wheel, no
# model weights, no repository snapshots -- uv rebuilds the Python side and the
# two fetch scripts rebuild the heavy inputs.
#
#   .\tools\setup.ps1            # dependencies + reranker weights
#   .\tools\setup.ps1 -Data      # also SWE-bench metadata and 18 GB of snapshots
#
# The exact-restore command is `uv sync --frozen --all-extras`; this script
# skips it when the environment already satisfies the pinned versions, because
# on this machine torch was installed from a locally assembled wheel and a sync
# would re-download the same build (2.6 GB) from the cu128 index.

param([switch]$Data)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root '.venv\Scripts\python.exe'

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw 'uv is not on PATH. Install it: https://docs.astral.sh/uv/'
}

Push-Location $root
try {
    $have = $null
    if (Test-Path $py) {
        $have = & $py -c 'import lightgbm, numpy, torch, transformers; print(lightgbm.__version__, numpy.__version__, torch.__version__, transformers.__version__)' 2>$null
    }

    if ($have) {
        Write-Output "environment already installed: $have"
        Write-Output 'exact restore, if you want it anyway: uv sync --frozen --all-extras'
    }
    else {
        if (-not (Test-Path $py)) {
            Write-Output 'creating .venv with Python 3.12'
            uv venv --python 3.12 .venv
        }
        Write-Output 'installing the locked dependency set (torch comes from the cu128 index)'
        uv sync --frozen --all-extras --inexact
    }

    Write-Output 'fetching the reranker weights (2.12 GB, resumable)'
    & $py tools\fetch_model.py

    if ($Data) {
        Write-Output 'fetching SWE-bench metadata'
        & $py tools\fetch_swebench.py
        Write-Output 'fetching base-commit snapshots (18 GB, resumable)'
        & $py tools\fetch_repos.py --jobs 6
    }

    Write-Output ''
    Write-Output 'verifying every number in the paper against the tracked JSONL'
    & $py tools\audit_numbers.py
}
finally {
    Pop-Location
}
