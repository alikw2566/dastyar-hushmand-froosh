param(
    [string]$PythonExecutable = $env:MOKALEMEBAN_PYTHON,
    [switch]$SkipWeb
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Failures = [System.Collections.Generic.List[string]]::new()
$Passed = [System.Collections.Generic.List[string]]::new()

function Resolve-Python {
    param([string]$Requested)
    $Candidates = [System.Collections.Generic.List[string]]::new()
    if ($Requested) { $Candidates.Add($Requested) }
    $Candidates.Add((Join-Path $ProjectRoot ".venv\Scripts\python.exe"))
    $Candidates.Add((Join-Path $ProjectRoot "backend\.venv\Scripts\python.exe"))
    $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($PythonCommand) { $Candidates.Add($PythonCommand.Source) }
    foreach ($Candidate in $Candidates) {
        if (-not $Candidate) { continue }
        try {
            & $Candidate -c "import sys; assert sys.version_info >= (3, 12)" 2>$null
            if ($LASTEXITCODE -eq 0) { return $Candidate }
        } catch { }
    }
    throw "Python 3.12 پیدا نشد. مسیر آن را با -PythonExecutable یا MOKALEMEBAN_PYTHON مشخص کنید."
}

function Invoke-CheckedStep {
    param(
        [string]$Name,
        [scriptblock]$Action
    )
    Write-Host "[$Name] شروع"
    try {
        & $Action
        if ($LASTEXITCODE -ne 0) { throw "exit code $LASTEXITCODE" }
        $Passed.Add($Name)
        Write-Host "[$Name] موفق"
    } catch {
        $Failures.Add("${Name}: $($_.Exception.Message)")
        Write-Host "[$Name] ناموفق: $($_.Exception.Message)" -ForegroundColor Red
    }
}

Push-Location $ProjectRoot
try {
    $Python = Resolve-Python $PythonExecutable
    Invoke-CheckedStep "backend-ruff" { & $Python -m ruff check backend }
    Invoke-CheckedStep "backend-pytest" { & $Python -m pytest backend/tests -q }
    Invoke-CheckedStep "evaluation-tests" { & $Python -m unittest discover -s evaluation/tests -v }
    Invoke-CheckedStep "evaluation-report" { & $Python evaluation/run_evaluation.py }
    Invoke-CheckedStep "backup-restore-tests" { & $Python -m unittest discover -s scripts/tests -v }
    Invoke-CheckedStep "load-harness-tests" { & $Python -m unittest discover -s load-tests/tests -v }
    Invoke-CheckedStep "load-harness-dry-run" { & $Python load-tests/run_load.py --scenario health --requests 1 --dry-run }

    if (-not $SkipWeb) {
        $Npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
        if (-not $Npm) { $Npm = Get-Command npm -ErrorAction SilentlyContinue }
        if (-not $Npm) {
            $Failures.Add("web: npm پیدا نشد")
        } else {
            Push-Location (Join-Path $ProjectRoot "web")
            try {
                Invoke-CheckedStep "web-lint" { & $Npm.Source run lint }
                Invoke-CheckedStep "web-typecheck" { & $Npm.Source exec tsc -- --noEmit }
                Invoke-CheckedStep "web-build-and-tests" { & $Npm.Source test }
            } finally {
                Pop-Location
            }
        }
    }
} catch {
    $Failures.Add($_.Exception.Message)
} finally {
    Pop-Location
}

$Summary = [ordered]@{
    passed = @($Passed)
    failed = @($Failures)
    release_gate = if ($Failures.Count -eq 0) { "PASS" } else { "FAIL" }
}
$Summary | ConvertTo-Json -Depth 4
if ($Failures.Count -gt 0) { exit 1 }
