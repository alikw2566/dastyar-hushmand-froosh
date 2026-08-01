param(
    [int]$DurationSeconds = 3600,
    [ValidateRange(1, 60)]
    [int]$IntervalSeconds = 30,
    [string]$OutputPath = "",
    [string]$ApiDetailsUrl = "http://localhost:8000/health/details",
    [string]$WatcherMetricsUrl = "http://localhost:8010/metrics"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if ($DurationSeconds -lt 1) { throw "DurationSeconds must be positive" }
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw "docker command was not found" }
if (-not $OutputPath) {
    $Timestamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
    $OutputPath = Join-Path $PSScriptRoot "results\compose-metrics-$Timestamp.ndjson"
}
$ResolvedOutput = [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot $OutputPath))
$OutputDirectory = Split-Path -Parent $ResolvedOutput
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
if (Test-Path $ResolvedOutput) { throw "Output already exists: $ResolvedOutput" }

function Invoke-SafeWebRequest {
    param([string]$Uri, [hashtable]$Headers = @{})
    try {
        return Invoke-RestMethod -Uri $Uri -Headers $Headers -TimeoutSec 10
    } catch {
        return [ordered]@{ error = $_.Exception.GetType().Name; message = $_.Exception.Message }
    }
}

Push-Location $ProjectRoot
try {
    $Started = Get-Date
    $Deadline = $Started.AddSeconds($DurationSeconds)
    while ((Get-Date) -lt $Deadline) {
        $Sample = [ordered]@{
            timestamp_utc = (Get-Date).ToUniversalTime().ToString("o")
            container_stats = @()
            database = $null
            redis = $null
            api = $null
            watcher_metrics = $null
            host_disk = $null
        }

        $ContainerIds = @(& docker compose ps -q 2>$null | Where-Object { $_ })
        if ($ContainerIds.Count -gt 0) {
            $RawStats = @(& docker stats --no-stream --format "{{json .}}" @ContainerIds 2>$null)
            $Sample.container_stats = @($RawStats | ForEach-Object {
                try { $_ | ConvertFrom-Json } catch { [ordered]@{ parse_error = $_ } }
            })
        }

        $DbRaw = @(& docker compose exec -T postgres psql -U mokalemeban -d mokalemeban -At -c "select count(*) from pg_stat_activity where datname=current_database(); select pg_database_size(current_database());" 2>$null)
        if ($LASTEXITCODE -eq 0 -and $DbRaw.Count -ge 2) {
            $Sample.database = [ordered]@{
                connections = [int64]$DbRaw[0]
                database_size_bytes = [int64]$DbRaw[1]
            }
        } else {
            $Sample.database = [ordered]@{ error = "postgres_metrics_unavailable" }
        }

        $QueueRaw = & docker compose exec -T redis redis-cli LLEN celery 2>$null
        $Sample.redis = if ($LASTEXITCODE -eq 0) {
            [ordered]@{ celery_queue_depth = [int64]$QueueRaw }
        } else {
            [ordered]@{ error = "redis_metrics_unavailable" }
        }

        $Headers = @{}
        if ($env:MOKALEMEBAN_TEST_TOKEN) { $Headers.Authorization = "Bearer $($env:MOKALEMEBAN_TEST_TOKEN)" }
        $Sample.api = Invoke-SafeWebRequest -Uri $ApiDetailsUrl -Headers $Headers
        try {
            $Sample.watcher_metrics = (Invoke-WebRequest -Uri $WatcherMetricsUrl -TimeoutSec 10).Content
        } catch {
            $Sample.watcher_metrics = [ordered]@{ error = $_.Exception.GetType().Name }
        }

        $Drive = Get-PSDrive -Name ([System.IO.Path]::GetPathRoot($ProjectRoot).TrimEnd('\').TrimEnd(':')) -ErrorAction SilentlyContinue
        if ($Drive) {
            $Sample.host_disk = [ordered]@{ free_bytes = [int64]$Drive.Free; used_bytes = [int64]$Drive.Used }
        }
        ($Sample | ConvertTo-Json -Depth 10 -Compress) | Add-Content -LiteralPath $ResolvedOutput -Encoding utf8

        $Remaining = [Math]::Max(0, ($Deadline - (Get-Date)).TotalSeconds)
        if ($Remaining -gt 0) { Start-Sleep -Seconds ([Math]::Min($IntervalSeconds, $Remaining)) }
    }
} finally {
    Pop-Location
}
Write-Output $ResolvedOutput
