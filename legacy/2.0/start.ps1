param(
    [ValidateSet('up', 'down', 'status', 'logs', 'build', 'credentials')]
    [string]$Action = 'up'
)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
function Invoke-Docker {
    & docker @args
    if ($LASTEXITCODE -ne 0) { throw "Docker failed (exit $LASTEXITCODE)." }
}
try {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw 'Install Docker Desktop: https://docs.docker.com/get-started/get-docker/'
    }
    & docker info *> $null
    if ($LASTEXITCODE -ne 0) { throw 'Start Docker Desktop and use Linux containers.' }
    Invoke-Docker compose version
    $envFile = if ($env:DUDUDA_QUICKSTART_ENV) { $env:DUDUDA_QUICKSTART_ENV } else { 'quickstart.env' }
    if (-not (Test-Path $envFile)) { Copy-Item deploy/quickstart/quickstart.env.example $envFile }
    $composeArgs = @('compose', '--project-directory', $PSScriptRoot, '--env-file', $envFile, '-f', 'deploy/quickstart/compose.yml')
    switch ($Action) {
        'down' { Invoke-Docker @composeArgs down; exit 0 }
        'status' { Invoke-Docker @composeArgs ps; exit 0 }
        'logs' { Invoke-Docker @composeArgs logs --tail=100 -f; exit 0 }
    }
    Invoke-Docker @composeArgs config --quiet
    $images = @('dududa/astrbot:submission-2b52593', 'dududa/web:submission-2b52593', 'dududa/napcat:submission-4.18.19')
    $missing = $false
    foreach ($ref in $images) {
        & docker image inspect $ref *> $null
        if ($LASTEXITCODE -ne 0) { $missing = $true }
    }
    if ($missing -and (Test-Path images/dududa-images-amd64.tar.gz)) {
        Write-Host 'Loading bundled Docker images (first launch only)...'
        Invoke-Docker load --input images/dududa-images-amd64.tar.gz
        $missing = $false
        foreach ($ref in $images) {
            & docker image inspect $ref *> $null
            if ($LASTEXITCODE -ne 0) { $missing = $true }
        }
    }
    if ($Action -eq 'build' -or $missing) { Invoke-Docker @composeArgs build init web napcat }
    if ($Action -eq 'credentials') { Invoke-Docker @composeArgs run --rm -T --no-deps init credentials; exit 0 }
    Invoke-Docker @composeArgs run --rm -T --no-deps init prepare
    Invoke-Docker @composeArgs up -d --wait --wait-timeout 240 astrbot mcp-console
    Invoke-Docker @composeArgs run --rm -T --no-deps init finish
    Invoke-Docker @composeArgs restart astrbot
    Invoke-Docker @composeArgs up -d --wait --wait-timeout 180 astrbot web napcat
    $login = Invoke-Docker @composeArgs run --rm -T --no-deps init credentials
    $login | Set-Content -Encoding UTF8 initial-login.txt
    Invoke-Docker @composeArgs ps
    Write-Host 'Ready. Open initial-login.txt for URLs and initial login credentials.'
    Write-Host 'Model and QQ setup: START_HERE.md. Stop: start.cmd down'
} catch {
    Write-Host "Startup failed: $_" -ForegroundColor Red
    exit 1
}
