param(
    [ValidateSet('Launch','Status','Logs','Fetch','Live')][string]$Action = 'Status',
    [string]$CredentialsPath = 'C:/Users/Administrator/.kaggle/credentials.json',
    [string]$BuildDirectory = '.cache/main-track/build',
    [switch]$AllowNetworkSetup,
    [switch]$EvidenceOnly
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$kernelCredentials = Get-Content -LiteralPath $CredentialsPath -Raw | ConvertFrom-Json
$kernelSession = Invoke-RestMethod -Method Post -Uri 'https://api.kaggle.com/v1/users.AccountService/GenerateAccessToken' -ContentType 'application/json' -Body (@{refreshToken=$kernelCredentials.refresh_token;apiVersion='API_VERSION_V1';expirationDuration='3600s'} | ConvertTo-Json -Compress) -TimeoutSec 30
$kernelHeaders = @{Authorization='Bearer '+$kernelSession.token}
$kernelRequest = Get-Content -LiteralPath (Join-Path $BuildDirectory 'kernel-request.json') -Raw | ConvertFrom-Json
$kernelSlug = ($kernelRequest.slug -split '/')[-1]
$launchReceiptPath = Join-Path $BuildDirectory 'kernel-launch.json'
if ($Action -ne 'Launch' -and (Test-Path -LiteralPath $launchReceiptPath)) {
    $savedLaunch = Get-Content -LiteralPath $launchReceiptPath -Raw | ConvertFrom-Json
    if ($savedLaunch.ref) { $kernelSlug = ($savedLaunch.ref -split '/')[-1] }
}
if ($Action -eq 'Launch') {
    if (Test-Path -LiteralPath $launchReceiptPath) { throw 'This build already has a launch receipt; refusing to launch it again' }
    if (-not $kernelRequest.isPrivate -or $kernelRequest.sessionTimeoutSeconds -gt 14400) { throw 'Unexpected notebook privacy/runtime settings' }
    if ($kernelRequest.enableInternet -and (-not $AllowNetworkSetup -or $kernelRequest.enableGpu -or $kernelRequest.modelDataSources.Count)) { throw 'Network is permitted only for explicitly requested CPU dependency setup without model inputs' }
    if ($kernelRequest.enableGpu) {
        $runManifest = Get-Content -LiteralPath (Join-Path $BuildDirectory 'manifest.json') -Raw | ConvertFrom-Json
        if ($runManifest.ranker_asset_dataset) {
            $rankerProofPath = Join-Path $BuildDirectory 'ranker-tool-validation.json'
            if (-not (Test-Path -LiteralPath $rankerProofPath)) { throw 'Full ranker requires completed official skill integration proof' }
            $rankerProof = Get-Content -LiteralPath $rankerProofPath -Raw | ConvertFrom-Json
            if (-not $rankerProof.passed -or -not $rankerProof.full_pipeline_executed -or -not $rankerProof.repository_unchanged -or $rankerProof.dataset -ne $runManifest.ranker_asset_dataset -or $rankerProof.package_zip_sha256 -ne $runManifest.ranker_asset_zip_sha256) { throw 'Ranker asset proof differs from run manifest' }
            if ($kernelRequest.datasetDataSources -notcontains $runManifest.ranker_asset_dataset) { throw 'Ranker dataset not attached' }
        }
        $expectedTasks = if ($runManifest.engineering_task_ids) { @($runManifest.engineering_task_ids) } elseif ($runManifest.engineering_task_id) { @($runManifest.engineering_task_id) } else { @($runManifest.split.smoke_task_id) }
        foreach ($expectedTask in $expectedTasks) {
        $gateName = if ($expectedTasks.Count -gt 1) { 'verification-gate-'+$expectedTask+'.json' } else { 'verification-gate.json' }
        $gatePath = Join-Path $BuildDirectory $gateName
        if (-not (Test-Path -LiteralPath $gatePath)) { throw ('GPU run requires saved reference-pass/empty-fail controls for '+$expectedTask) }
        $gate = Get-Content -LiteralPath $gatePath -Raw | ConvertFrom-Json
        if (-not $gate.passed -or $gate.task_id -ne $expectedTask) { throw 'Verification controls failed or belong to a different task' }
        $gateNotebook = $kernelRequest.text | ConvertFrom-Json
        $setupHashes = @()
        foreach ($gateCell in $gateNotebook.cells) {
            $gateCode = $gateCell.source -join ''
            if ($gateCell.cell_type -eq 'code' -and ($gateCode.Contains('WHEELHOUSE_DIR = Path(') -or $gateCode.Contains('pytest_before=md.version') -or $gateCode.Contains('original_environment_builder=') -or $gateCode.Contains('additional_test_dependency:'))) {
                $gateHasher = [Security.Cryptography.SHA256]::Create()
                try { $setupHashes += ([BitConverter]::ToString($gateHasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($gateCode)))).Replace('-','').ToLowerInvariant() } finally { $gateHasher.Dispose() }
            }
        }
        if (($setupHashes -join ',') -ne ($gate.environment_setup_sha256 -join ',')) { throw 'Verification and model smoke use different environment setup code' }
        foreach ($environmentKey in @('dockerImage','datasetDataSources','competitionDataSources','kernelDataSources','enableInternet')) {
            $leftEnvironment = ConvertTo-Json -InputObject @($gate.environment.$environmentKey | Where-Object { $null -ne $_ }) -Compress
            $rightValues = @($kernelRequest.$environmentKey | Where-Object { $null -ne $_ })
            if ($environmentKey -eq 'datasetDataSources' -and $runManifest.ranker_asset_dataset) {
                # A hash-verified skill asset input adds no host dependencies.
                $rightValues = @($rightValues | Where-Object { $_ -ne $runManifest.ranker_asset_dataset })
            }
            $rightEnvironment = ConvertTo-Json -InputObject $rightValues -Compress
            if ($leftEnvironment -ne $rightEnvironment) { throw ('Verification environment differs: '+$environmentKey) }
        }
        }
    }
    $existingKernels = Invoke-RestMethod -Method Post -Uri 'https://api.kaggle.com/v1/kernels.KernelsApiService/ListKernels' -Headers $kernelHeaders -ContentType 'application/json' -Body (@{user=$kernelSession.userName;search=$kernelRequest.newTitle;pageSize=100} | ConvertTo-Json -Compress) -TimeoutSec 30
    if ($existingKernels.kernels | Where-Object { $_.ref -eq ($kernelSession.userName+'/'+$kernelSlug) }) { throw 'Notebook already exists; refusing to overwrite it' }
    # Match the official CLI: fully qualified slug, and string cell sources.
    $kernelRequest.slug = $kernelSession.userName+'/'+$kernelSlug
    $kernelNotebook = $kernelRequest.text | ConvertFrom-Json
    if (-not $kernelNotebook.metadata.kernelspec.name) { throw 'Notebook kernelspec.name is required before launch' }
    foreach ($kernelCell in $kernelNotebook.cells) {
        if ($kernelCell.source -is [array]) { $kernelCell.source = $kernelCell.source -join '' }
    }
    $kernelRequest.text = $kernelNotebook | ConvertTo-Json -Depth 50 -Compress
    try {
        $kernelSaved = Invoke-RestMethod -Method Post -Uri 'https://api.kaggle.com/v1/kernels.KernelsApiService/SaveKernel' -Headers $kernelHeaders -ContentType 'application/json' -Body ($kernelRequest | ConvertTo-Json -Depth 55 -Compress) -TimeoutSec 45
    } catch {
        $saveError = $_.Exception.Message
        $saveErrorBody = $_.ErrorDetails.Message
        if (-not $saveErrorBody -and $_.Exception.Response) {
            $saveErrorReader = New-Object IO.StreamReader($_.Exception.Response.GetResponseStream())
            try { $saveErrorBody = $saveErrorReader.ReadToEnd() } finally { $saveErrorReader.Dispose() }
        }
        if ($saveErrorBody) {
            $safeSaveBody = $saveErrorBody.Replace($kernelSession.token,'[redacted]').Replace($kernelCredentials.refresh_token,'[redacted]')
            $saveError += ' ' + $safeSaveBody.Substring(0,[Math]::Min(1400,$safeSaveBody.Length))
        }
        throw $saveError
    }
    $kernelSaved | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $BuildDirectory 'kernel-launch.json') -Encoding UTF8
    if ($kernelSaved.error) { throw $kernelSaved.error }
    if (-not $kernelSaved.ref) { throw 'No notebook reference returned' }
    $kernelSaved | Select-Object ref,versionNumber,kernelId,error | Format-List
} elseif ($Action -eq 'Live') {
    Add-Type -AssemblyName System.Net.Http
    $liveClient = New-Object System.Net.Http.HttpClient
    $liveClient.Timeout = [TimeSpan]::FromSeconds(25)
    $liveRequest = New-Object System.Net.Http.HttpRequestMessage([System.Net.Http.HttpMethod]::Post,'https://api.kaggle.com/v1/kernels.KernelsApiService/GetKernelSessionLogsStream')
    $liveRequest.Headers.Authorization = New-Object System.Net.Http.Headers.AuthenticationHeaderValue('Bearer',$kernelSession.token)
    $liveBody = @{userName=$kernelSession.userName;kernelSlug=$kernelSlug;waitForLogsUrlSeconds=1} | ConvertTo-Json -Compress
    $liveRequest.Content = New-Object System.Net.Http.StringContent($liveBody,[Text.Encoding]::UTF8,'application/json')
    $liveBuffer = New-Object byte[] 8192
    $liveCollected = New-Object IO.MemoryStream
    try {
        $liveResponse = $liveClient.SendAsync($liveRequest,[System.Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
        $liveResponse.EnsureSuccessStatusCode() | Out-Null
        $liveStream = $liveResponse.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
        $liveWatch = [Diagnostics.Stopwatch]::StartNew()
        while ($liveWatch.Elapsed.TotalSeconds -lt 12 -and $liveCollected.Length -lt 500000) {
            $liveRead = $liveStream.ReadAsync($liveBuffer,0,$liveBuffer.Length)
            if (-not $liveRead.Wait(3000)) { break }
            $liveCount = $liveRead.Result
            if ($liveCount -eq 0) { break }
            $liveCollected.Write($liveBuffer,0,$liveCount)
        }
        $liveText = [Text.Encoding]::UTF8.GetString($liveCollected.ToArray())
        $liveText | Set-Content -LiteralPath (Join-Path $BuildDirectory 'live-log.txt') -Encoding UTF8
        Write-Output ('Captured '+$liveCollected.Length+' bytes of logs')
    } finally { $liveCollected.Dispose();$liveRequest.Dispose();$liveClient.Dispose() }
} elseif ($Action -in @('Logs','Fetch')) {
    $outputFiles = @()
    $outputPageToken = $null
    $outputLog = $null
    $outputPageCount = 0
    do {
        $outputPayload = @{userName=$kernelSession.userName;kernelSlug=$kernelSlug;pageSize=100}
        if ($outputPageToken) { $outputPayload.pageToken = $outputPageToken }
        $outputPage = Invoke-RestMethod -Method Post -Uri 'https://api.kaggle.com/v1/kernels.KernelsApiService/ListKernelSessionOutput' -Headers $kernelHeaders -ContentType 'application/json' -Body ($outputPayload | ConvertTo-Json -Compress) -TimeoutSec 30
        $outputFiles += @($outputPage.files)
        if ($null -eq $outputLog -and $outputPage.log) { $outputLog = $outputPage.log }
        $outputPageToken = $outputPage.nextPageToken
        $outputPageCount++
        if ($outputPageCount -ge 30 -and $outputPageToken) { throw 'Output pagination exceeds bound; refusing partial download' }
    } while ($outputPageToken)
    $kernelOutput = [PSCustomObject]@{files=$outputFiles;log=$outputLog}
    $kernelOutput.log | Set-Content -LiteralPath (Join-Path $BuildDirectory 'kernel.log') -Encoding UTF8
    if ($Action -eq 'Logs') { $kernelOutput.files | Select-Object fileName | Format-Table -AutoSize } else { Write-Output ('Available output files: '+$outputFiles.Count) }
    if ($Action -eq 'Logs') { Write-Output $kernelOutput.log }
    if ($Action -eq 'Fetch') {
        $outputRoot = [IO.Path]::GetFullPath((Join-Path $BuildDirectory 'output'))
        New-Item -ItemType Directory -Force -Path $outputRoot | Out-Null
        $outputReceipts = @()
        foreach ($outputFile in $kernelOutput.files) {
            if ($EvidenceOnly -and $outputFile.fileName -match '^(agents/|.*_submission\.zip$)') { continue }
            if ($outputFile.fileName -notmatch '^(agents/|results/|smoke_results\.jsonl$|verification_results\.jsonl$|environment-repair\.json$|source-import-probes\.json$|throughput-results\.json$|batch-results\.jsonl$|additional-test-dependency\.json$|ranker-tool-output\.json$|ranker-tool-probe\.json$|ranker-integration-manifest\.json$|dependency-manifest\.json$|frozen_split\.json$|(?:baseline|evidence|evidence_graph|ranker)_submission\.zip$)') { continue }
            $outputTarget = [IO.Path]::GetFullPath((Join-Path $outputRoot $outputFile.fileName))
            if (-not $outputTarget.StartsWith($outputRoot+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe output path' }
            $outputUri = [Uri]$outputFile.url
            if ($outputUri.Scheme -ne 'https') { throw 'Output URL must use HTTPS' }
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $outputTarget) | Out-Null
            Invoke-WebRequest -Uri $outputFile.url -UseBasicParsing -OutFile $outputTarget -TimeoutSec 45
            $outputReceipts += [PSCustomObject]@{path=$outputFile.fileName;bytes=(Get-Item -LiteralPath $outputTarget).Length;sha256=(Get-FileHash -LiteralPath $outputTarget -Algorithm SHA256).Hash.ToLowerInvariant()}
        }
        $receiptName = if ($EvidenceOnly) { 'output-evidence-receipts.json' } else { 'output-receipts.json' }
        $outputReceipts | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $BuildDirectory $receiptName) -Encoding UTF8
        Write-Output ('Downloaded '+$outputReceipts.Count+' output files')
    }
} else {
    $kernelStatus = Invoke-RestMethod -Method Post -Uri 'https://api.kaggle.com/v1/kernels.KernelsApiService/GetKernelSessionStatus' -Headers $kernelHeaders -ContentType 'application/json' -Body (@{userName=$kernelSession.userName;kernelSlug=$kernelSlug} | ConvertTo-Json -Compress) -TimeoutSec 30
    $kernelStatus | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $BuildDirectory 'kernel-status.json') -Encoding UTF8
    $kernelStatus | Select-Object status,failureMessage | Format-List
}
