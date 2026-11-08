param([string]$PackageDirectory='artifacts/ranker-agent-v1',[string]$Slug='gemma4-complete-ranker-20261108-v1')
$ErrorActionPreference='Stop'
$rankerManifest=Get-Content -LiteralPath (Join-Path $PackageDirectory 'manifest.json') -Raw|ConvertFrom-Json
$rankerArchive=(Resolve-Path -LiteralPath (Join-Path $PackageDirectory 'ranker-agent.zip')).Path
if ((Get-FileHash -LiteralPath $rankerArchive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $rankerManifest.zip_sha256) {throw 'Archive hash differs'}
if (Test-Path -LiteralPath (Join-Path $PackageDirectory 'dataset-receipt.json')) {throw 'Dataset receipt already exists; refusing duplicate creation'}
$uploadCredentials=Get-Content -LiteralPath C:/Users/Administrator/.kaggle/credentials.json -Raw|ConvertFrom-Json
$uploadSession=Invoke-RestMethod -Method Post -Uri 'https://api.kaggle.com/v1/users.AccountService/GenerateAccessToken' -ContentType 'application/json' -Body (@{refreshToken=$uploadCredentials.refresh_token;apiVersion='API_VERSION_V1';expirationDuration='3600s'}|ConvertTo-Json -Compress) -TimeoutSec 30
$uploadHeaders=@{Authorization='Bearer '+$uploadSession.token}
$uploadSize=(Get-Item -LiteralPath $rankerArchive).Length
$blob=Invoke-RestMethod -Method Post -Uri 'https://api.kaggle.com/v1/blobs.BlobApiService/StartBlobUpload' -Headers $uploadHeaders -ContentType 'application/json' -Body (@{type='DATASET';name='ranker-agent.zip';contentLength=$uploadSize;contentType='application/zip'}|ConvertTo-Json -Compress) -TimeoutSec 30
if (-not $blob.token -or ([Uri]$blob.createUrl).Scheme -ne 'https') {throw 'Invalid upload session'}
# The signed storage upload receives no Kaggle authorization header.
$storageResult=Invoke-WebRequest -Method Put -Uri $blob.createUrl -InFile $rankerArchive -ContentType 'application/zip' -UseBasicParsing -TimeoutSec 180
if ($storageResult.StatusCode -notin @(200,201)) {throw 'Storage upload failed'}
$createBody=@{ownerSlug=$uploadSession.userName;slug=$Slug;title='Gemma4 complete ranker 20261108 v1';licenseName='Apache 2.0';isPrivate=$true;description='Private experimental localization skill. Trained ranker excludes all public competition repositories. BGE encoder quantized locally; no task labels or reference patches included. Runtime validation pending.';files=@(@{token=$blob.token})}|ConvertTo-Json -Depth 6 -Compress
$created=Invoke-RestMethod -Method Post -Uri 'https://api.kaggle.com/v1/datasets.DatasetApiService/CreateDataset' -Headers $uploadHeaders -ContentType 'application/json' -Body $createBody -TimeoutSec 45
if ($created.error) {throw $created.error}
$created|ConvertTo-Json -Depth 8|Set-Content -LiteralPath (Join-Path $PackageDirectory 'dataset-receipt.json') -Encoding UTF8
$created|Select-Object ref,status,error|Format-List
