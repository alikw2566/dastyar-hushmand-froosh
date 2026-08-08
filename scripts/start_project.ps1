[CmdletBinding()]
param(
    [switch]$NoBrowser,
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$envPath = Join-Path $projectRoot ".env"

function Write-Step([string]$Text) {
    Write-Host "`n[$Text]" -ForegroundColor Cyan
}

function New-RandomSecret([int]$Bytes = 32) {
    $buffer = New-Object byte[] $Bytes
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($buffer) } finally { $rng.Dispose() }
    return [Convert]::ToBase64String($buffer).Replace("+", "-").Replace("/", "_")
}

function Get-DotEnvValue([string]$Name) {
    if (-not (Test-Path -LiteralPath $envPath)) { return $null }
    $line = Get-Content -LiteralPath $envPath -Encoding UTF8 |
        Where-Object { $_ -match "^$([regex]::Escape($Name))=" } |
        Select-Object -First 1
    if ($null -eq $line) { return $null }
    return ($line -replace "^[^=]+=", "")
}

function Set-DotEnvValue([string]$Name, [string]$Value) {
    $lines = [System.Collections.Generic.List[string]]::new()
    if (Test-Path -LiteralPath $envPath) {
        foreach ($line in (Get-Content -LiteralPath $envPath -Encoding UTF8)) { $lines.Add($line) }
    }
    $found = $false
    for ($index = 0; $index -lt $lines.Count; $index++) {
        if ($lines[$index] -match "^$([regex]::Escape($Name))=") {
            $lines[$index] = "$Name=$Value"
            $found = $true
            break
        }
    }
    if (-not $found) { $lines.Add("$Name=$Value") }
    [System.IO.File]::WriteAllLines($envPath, $lines, [System.Text.UTF8Encoding]::new($false))
}

function Find-Docker {
    $command = Get-Command docker -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    $bundled = Join-Path $env:ProgramFiles "Docker\Docker\resources\bin\docker.exe"
    if (Test-Path -LiteralPath $bundled) {
        $env:Path = "$(Split-Path $bundled);$env:Path"
        return $bundled
    }
    return $null
}

function Wait-ForDocker([int]$TimeoutSeconds = 120) {
    $desktop = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
    if (Test-Path -LiteralPath $desktop) {
        Write-Host "Docker Desktop در حال اجرا نیست؛ برنامه راه‌اندازی می‌شود..." -ForegroundColor Yellow
        Start-Process -FilePath $desktop -WindowStyle Hidden
    }
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        docker info *> $null
        if ($LASTEXITCODE -eq 0) { return $true }
        Start-Sleep -Seconds 3
    } while ((Get-Date) -lt $deadline)
    return $false
}

function Wait-ForUrl([string]$Url, [int]$TimeoutSeconds = 180) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 4
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300) { return $true }
        } catch { }
        Start-Sleep -Seconds 3
    } while ((Get-Date) -lt $deadline)
    return $false
}

Set-Location $projectRoot
Write-Host "مکالمه‌بان — راه‌اندازی ساده محیط کامل" -ForegroundColor Green

Write-Step "بررسی Docker"
$dockerPath = Find-Docker
if (-not $dockerPath) {
    Write-Host "Docker Desktop روی این سیستم نصب نیست." -ForegroundColor Red
    Write-Host "ابتدا Docker Desktop را نصب کنید و سپس دوباره START_PROJECT.cmd را اجرا کنید."
    Write-Host "دانلود: https://www.docker.com/products/docker-desktop/"
    exit 2
}
if (-not (Wait-ForDocker)) {
    Write-Host "Docker در زمان تعیین‌شده آماده نشد. Docker Desktop و WSL2 را بررسی کنید." -ForegroundColor Red
    exit 3
}
docker compose version
if ($LASTEXITCODE -ne 0) { throw "Docker Compose v2 در دسترس نیست." }

Write-Step "آماده‌سازی تنظیمات"
if (-not (Test-Path -LiteralPath $envPath)) {
    Copy-Item -LiteralPath (Join-Path $projectRoot ".env.example") -Destination $envPath
    Write-Host "فایل تنظیمات امن محلی ساخته شد." -ForegroundColor Green
}

$secretDefaults = @{
    POSTGRES_PASSWORD = New-RandomSecret 24
    S3_ACCESS_KEY = "mokalemeban-local"
    S3_SECRET_KEY = New-RandomSecret 32
    KEYCLOAK_ADMIN = "mokalemeban-admin"
    KEYCLOAK_ADMIN_PASSWORD = New-RandomSecret 24
    KEYCLOAK_DB_PASSWORD = New-RandomSecret 24
    SECRET_ENCRYPTION_KEY = New-RandomSecret 32
}
foreach ($name in $secretDefaults.Keys) {
    $current = Get-DotEnvValue $name
    if ([string]::IsNullOrWhiteSpace($current) -or $current -match "^change-me") {
        Set-DotEnvValue $name $secretDefaults[$name]
    }
}

$tenantId = Get-DotEnvValue "DEFAULT_TENANT_ID"
if ([string]::IsNullOrWhiteSpace($tenantId) -or $tenantId -eq "00000000-0000-4000-8000-000000000001") {
    $tenantId = [guid]::NewGuid().ToString()
    Set-DotEnvValue "DEFAULT_TENANT_ID" $tenantId
}
Set-DotEnvValue "ISSABEL_DEFAULT_TENANT_ID" $tenantId

$adminEmail = Get-DotEnvValue "FIRST_ADMIN_EMAIL"
if ([string]::IsNullOrWhiteSpace($adminEmail)) {
    do { $adminEmail = (Read-Host "ایمیل مدیر اولیه").Trim() } until ($adminEmail -match "^[^\s@]+@[^\s@]+\.[^\s@]+$")
    Set-DotEnvValue "FIRST_ADMIN_EMAIL" $adminEmail
}
$adminName = Get-DotEnvValue "FIRST_ADMIN_NAME"
if ([string]::IsNullOrWhiteSpace($adminName)) {
    do { $adminName = (Read-Host "نام مدیر اولیه").Trim() } until ($adminName.Length -ge 2)
    Set-DotEnvValue "FIRST_ADMIN_NAME" $adminName
}
$tenantName = Get-DotEnvValue "DEFAULT_TENANT_NAME"
if ([string]::IsNullOrWhiteSpace($tenantName) -or $tenantName -eq "شرکت پایلوت") {
    $enteredTenantName = (Read-Host "نام شرکت (Enter = شرکت پایلوت)").Trim()
    if (-not [string]::IsNullOrWhiteSpace($enteredTenantName)) { Set-DotEnvValue "DEFAULT_TENANT_NAME" $enteredTenantName }
}
$adminPassword = Get-DotEnvValue "FIRST_ADMIN_PASSWORD"
if ([string]::IsNullOrWhiteSpace($adminPassword)) {
    do {
        $securePassword = Read-Host "رمز مدیر اولیه (حداقل 10 کاراکتر و دارای عدد)" -AsSecureString
        $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
        try { $adminPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
    } until ($adminPassword.Length -ge 10 -and $adminPassword -match "\d")
    Set-DotEnvValue "FIRST_ADMIN_PASSWORD" $adminPassword
}
$openAiKey = Get-DotEnvValue "OPENAI_API_KEY"
if ([string]::IsNullOrWhiteSpace($openAiKey)) {
    $secureApiKey = Read-Host "کلید OpenAI برای رونویسی و تحلیل" -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureApiKey)
    try { $openAiKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
    if ([string]::IsNullOrWhiteSpace($openAiKey)) {
        Write-Host "بدون کلید OpenAI، ورود و داشبورد کار می‌کند اما پردازش صوت انجام نمی‌شود." -ForegroundColor Yellow
    } else {
        Set-DotEnvValue "OPENAI_API_KEY" $openAiKey
    }
}

Write-Step "اعتبارسنجی و اجرای سرویس‌ها"
docker compose config --quiet
if ($LASTEXITCODE -ne 0) { throw "تنظیمات Docker Compose معتبر نیست." }
if ($SkipBuild) { docker compose up -d } else { docker compose up -d --build }
if ($LASTEXITCODE -ne 0) { throw "اجرای سرویس‌ها ناموفق بود." }

Write-Step "انتظار برای آماده‌شدن سرویس‌ها"
if (-not (Wait-ForUrl "http://localhost:8000/health/ready" 240)) {
    docker compose ps
    docker compose logs --since 10m api
    throw "API آماده نشد. گزارش بالا را بررسی کنید."
}
if (-not (Wait-ForUrl "http://localhost:3000/auth" 120)) {
    docker compose logs --since 10m web
    throw "رابط وب آماده نشد."
}

Write-Step "ساخت مدیر اولیه"
docker compose run --rm api python -m app.bootstrap_admin
if ($LASTEXITCODE -ne 0) { throw "ساخت مدیر اولیه ناموفق بود." }

Write-Step "نتیجه"
docker compose ps
Write-Host "سامانه با موفقیت اجرا شد: http://localhost:3000" -ForegroundColor Green
Write-Host "برای توقف امن: docker compose stop"
if (-not $NoBrowser) { Start-Process "http://localhost:3000/auth" }
