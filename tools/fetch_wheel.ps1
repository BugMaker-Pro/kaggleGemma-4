# Fetch the cu128 torch wheel as eight parallel ranges, verifying every part and
# retrying only the short ones. The SJTU mirror answers 206 for ranges; aliyun
# does not, which is why this script exists at all.
$ErrorActionPreference = 'Stop'
$url = 'https://mirror.sjtu.edu.cn/pytorch-wheels/cu128/torch-2.11.0+cu128-cp312-cp312-win_amd64.whl'
$size = 2753189216
$n = 8
$chunk = [math]::Ceiling($size / $n)
$dir = Join-Path $PSScriptRoot 'tmp_wheel'
New-Item -ItemType Directory -Force -Path $dir | Out-Null

function Expected([int]$i) {
    if ($i -eq $n - 1) { return $size - $i * $chunk }
    return $chunk
}

for ($round = 1; $round -le 6; $round++) {
    $short = @()
    for ($i = 0; $i -lt $n; $i++) {
        $path = Join-Path $dir ("p{0}" -f $i)
        $have = 0
        if (Test-Path $path) { $have = (Get-Item $path).Length }
        if ($have -ne (Expected $i)) { $short += $i }
    }
    if ($short.Count -eq 0) { Write-Output "all parts complete"; break }
    Write-Output ("round {0}: re-fetching parts {1}" -f $round, ($short -join ','))
    $procs = @()
    foreach ($i in $short) {
        $start = $i * $chunk
        $end = [math]::Min($start + $chunk - 1, $size - 1)
        $out = Join-Path $dir ("p{0}.new" -f $i)
        if (Test-Path $out) { Remove-Item $out -Force }
        $args = @('-sL', '-A', 'Mozilla/5.0', '-r', "$start-$end", '-o', $out, $url)
        $procs += Start-Process -FilePath 'curl.exe' -ArgumentList $args -NoNewWindow -PassThru
    }
    $t0 = Get-Date
    while ($procs | Where-Object { -not $_.HasExited }) {
        Start-Sleep -Seconds 5
        $sum = (Get-ChildItem $dir -File | Measure-Object Length -Sum).Sum
        Write-Output ("  {0:N0} MB  {1:N1} MB/s" -f ($sum / 1MB), (($sum / 1MB) / ((Get-Date) - $t0).TotalSeconds))
    }
    foreach ($i in $short) {
        $new = Join-Path $dir ("p{0}.new" -f $i)
        $path = Join-Path $dir ("p{0}" -f $i)
        if ((Test-Path $new) -and ((Get-Item $new).Length -eq (Expected $i))) {
            Move-Item -Force $new $path
        }
    }
}

$total = (Get-ChildItem $dir -File | Where-Object { $_.Name -match '^p\d$' } | Measure-Object Length -Sum).Sum
Write-Output ("total {0:N2} GB of {1:N2} GB" -f ($total / 1GB), ($size / 1GB))
if ($total -eq $size) {
    $target = Join-Path $PSScriptRoot 'torch-2.11.0+cu128-cp312-cp312-win_amd64.whl'
    if (Test-Path $target) { Remove-Item $target -Force }
    # concatenate in Python: copy /b silently produced nothing for eight sources
    & (Join-Path (Split-Path $PSScriptRoot -Parent) '.venv\Scripts\python.exe') -c @"
from pathlib import Path
parts = [Path(r'$dir') / f'p{i}' for i in range($n)]
target = Path(r'$target')
with target.open('wb') as out:
    for part in parts:
        out.write(part.read_bytes())
print('assembled', target.stat().st_size)
"@ | Out-Null
    Write-Output ("wheel {0:N2} GB -> {1}" -f ((Get-Item $target).Length / 1GB), $target)
} else {
    Write-Output "INCOMPLETE"
    exit 1
}
