param(
    [string]$CredentialsPath = 'C:/Users/Administrator/.kaggle/credentials.json',
    [string]$Competition = 'gemma-4-developer-agent',
    [string]$OutputDirectory = '.cache/main-track/official',
    [string[]]$Files = @('HARNESS_README.md'),
    [switch]$IncludeSample
)
$ErrorActionPreference = 'Stop'
$competitionRoot = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Force -Path $competitionRoot | Out-Null
$competitionCredentials = Get-Content -LiteralPath $CredentialsPath -Raw | ConvertFrom-Json
# Follow kagglesdk's GenerateAccessToken flow. Never print or persist tokens.
$competitionRefresh = @{
    refreshToken = $competitionCredentials.refresh_token
    apiVersion = 'API_VERSION_V1'
    expirationDuration = '3600s'
} | ConvertTo-Json -Compress
try {
    $competitionSession = Invoke-RestMethod -Method Post -Uri 'https://api.kaggle.com/v1/users.AccountService/GenerateAccessToken' -ContentType 'application/json' -Body $competitionRefresh -TimeoutSec 30
} catch { throw ('Kaggle token refresh failed: ' + $_.Exception.Message) }
if (-not $competitionSession.token) { throw 'Kaggle did not return an access token' }
$competitionHeaders = @{Authorization = 'Bearer ' + $competitionSession.token}
function Read-CompetitionApi([string]$Method, [hashtable]$Payload) {
    try {
        Invoke-RestMethod -Method Post -Uri ('https://api.kaggle.com/v1/competitions.CompetitionApiService/' + $Method) -Headers $competitionHeaders -ContentType 'application/json' -Body ($Payload | ConvertTo-Json -Compress) -TimeoutSec 30
    } catch {
        $competitionApiFailure = $_.Exception.Message
        $competitionErrorBody = $_.ErrorDetails.Message
        if (-not $competitionErrorBody -and $_.Exception.Response) {
            $competitionReader = New-Object IO.StreamReader($_.Exception.Response.GetResponseStream())
            try { $competitionErrorBody = $competitionReader.ReadToEnd() } finally { $competitionReader.Dispose() }
        }
        if ($competitionErrorBody) {
            try {
                $competitionApiError = $competitionErrorBody | ConvertFrom-Json
                if ($competitionApiError.message -and $competitionApiError.message -notmatch 'token|secret|credential') {
                    $competitionApiFailure += ' ' + $competitionApiError.message
                }
            } catch { }
        }
        throw ('Kaggle ' + $Method + ' failed: ' + $competitionApiFailure)
    }
}
# DownloadDataFile returns HTTP 302, not a JSON HttpRedirect object.
# Disable automatic redirects so PowerShell cannot carry bearer auth to storage.
Add-Type -AssemblyName System.Net.Http
function Save-CompetitionFile([string]$Name, [string]$Target) {
    $downloadHandler = New-Object System.Net.Http.HttpClientHandler
    $downloadHandler.AllowAutoRedirect = $false
    $downloadClient = New-Object System.Net.Http.HttpClient($downloadHandler)
    $downloadClient.Timeout = [TimeSpan]::FromSeconds(45)
    $downloadRequest = New-Object System.Net.Http.HttpRequestMessage([System.Net.Http.HttpMethod]::Post, 'https://api.kaggle.com/v1/competitions.CompetitionApiService/DownloadDataFile')
    $downloadRequest.Headers.Authorization = New-Object System.Net.Http.Headers.AuthenticationHeaderValue('Bearer', $competitionSession.token)
    $downloadBody = @{competitionName=$Competition;fileName=$Name} | ConvertTo-Json -Compress
    $downloadRequest.Content = New-Object System.Net.Http.StringContent($downloadBody, [Text.Encoding]::UTF8, 'application/json')
    $downloadResponse = $null
    $storageResponse = $null
    try {
        $downloadResponse = $downloadClient.SendAsync($downloadRequest).GetAwaiter().GetResult()
        if ([int]$downloadResponse.StatusCode -in @(301,302,303,307,308)) {
            $downloadLocation = $downloadResponse.Headers.Location
            if (-not $downloadLocation -or -not $downloadLocation.IsAbsoluteUri -or $downloadLocation.Scheme -ne 'https') { throw 'Invalid official redirect' }
            # No default authorization header is set on this client.
            $storageResponse = $downloadClient.GetAsync($downloadLocation).GetAwaiter().GetResult()
            $storageResponse.EnsureSuccessStatusCode() | Out-Null
            $downloadBytes = $storageResponse.Content.ReadAsByteArrayAsync().GetAwaiter().GetResult()
        } else {
            $downloadResponse.EnsureSuccessStatusCode() | Out-Null
            $downloadBytes = $downloadResponse.Content.ReadAsByteArrayAsync().GetAwaiter().GetResult()
        }
        if ($downloadBytes.Length -gt 2000000) { throw 'Downloaded content exceeds 2 MB limit' }
        [IO.File]::WriteAllBytes($Target, $downloadBytes)
    } finally {
        if ($storageResponse) { $storageResponse.Dispose() }
        if ($downloadResponse) { $downloadResponse.Dispose() }
        $downloadRequest.Dispose()
        $downloadClient.Dispose()
    }
}
$competitionInfo = Read-CompetitionApi 'GetCompetition' @{competitionName=$Competition}
$competitionInfo | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath (Join-Path $competitionRoot 'competition.json') -Encoding UTF8
$competitionAllFiles = @()
$competitionPageToken = $null
$competitionPages = 0
do {
    $competitionPayload = @{competitionName=$Competition;pageSize=1000}
    if ($competitionPageToken) { $competitionPayload.pageToken=$competitionPageToken }
    $competitionPage = Read-CompetitionApi 'ListDataFiles' $competitionPayload
    $competitionAllFiles += @($competitionPage.files | Select-Object name,totalBytes,creationDate)
    $competitionPageToken = $competitionPage.nextPageToken
    $competitionPages++
    if ($competitionPages -ge 30 -and $competitionPageToken) { throw 'File listing exceeded 30 pages; no incomplete inventory will be saved' }
} while ($competitionPageToken)
$competitionAllFiles | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $competitionRoot 'files.json') -Encoding UTF8
Write-Output ('Listed ' + $competitionAllFiles.Count + ' official files')
$competitionSelected = @($competitionAllFiles | Where-Object {
    ($Files -contains $_.name) -or ($IncludeSample -and $_.name.StartsWith('sample_submission/'))
})
foreach ($competitionRequested in $Files) {
    if ($competitionRequested -notin $competitionAllFiles.name) { throw ('Requested file missing: ' + $competitionRequested) }
}
$competitionReceipts = @()
foreach ($competitionFile in $competitionSelected) {
    if ([long]$competitionFile.totalBytes -gt 2000000) { throw ('Selected file exceeds 2 MB safety limit: ' + $competitionFile.name) }
    $competitionTarget = [IO.Path]::GetFullPath((Join-Path $competitionRoot $competitionFile.name))
    if (-not $competitionTarget.StartsWith($competitionRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid official file path' }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $competitionTarget) | Out-Null
    Save-CompetitionFile $competitionFile.name $competitionTarget
    $competitionActualBytes = (Get-Item -LiteralPath $competitionTarget).Length
    if ($competitionActualBytes -ne [long]$competitionFile.totalBytes) { throw ('Downloaded size differs from inventory: ' + $competitionFile.name) }
    $competitionReceipts += [PSCustomObject]@{name=$competitionFile.name;bytes=$competitionActualBytes;sha256=(Get-FileHash -LiteralPath $competitionTarget -Algorithm SHA256).Hash.ToLowerInvariant()}
    Write-Output ('Fetched ' + $competitionFile.name + ' (' + $competitionActualBytes + ' bytes)')
}
[PSCustomObject]@{competition=$Competition;fetched_at_utc=[DateTime]::UtcNow.ToString('o');files=$competitionReceipts} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $competitionRoot 'download-receipt.json') -Encoding UTF8
