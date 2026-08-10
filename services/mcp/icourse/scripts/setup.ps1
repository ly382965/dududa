param(
    [string]$Python = "python",
    [string]$VenvPath = ".venv"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

& $Python -m venv $VenvPath
& "$VenvPath\Scripts\python.exe" -m pip install --upgrade pip
& "$VenvPath\Scripts\python.exe" -m pip install -r requirements.txt
& "$VenvPath\Scripts\python.exe" -m pip install -e .

Write-Host "iCourse MCP environment is ready:"
Write-Host "  $Root\$VenvPath\Scripts\python.exe -m icourse_mcp.server"
