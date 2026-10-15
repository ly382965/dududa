param(
    [string]$DbPath = "data/icourse.sqlite3",
    [string]$RequestDelay = "1.0"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

& ".venv\Scripts\python.exe" -m icourse_mcp.server --db-path $DbPath --request-delay $RequestDelay
