# scripts/check_dev_db_untouched.ps1
# Verifies that pytest suite leaves the development database opsdesk.db 100% untouched.

$dbPath = "opsdesk.db"

if (-not (Test-Path $dbPath)) {
    Write-Error "Database file '$dbPath' does not exist."
    exit 1
}

$initialHash = (Get-FileHash -Path $dbPath -Algorithm SHA256).Hash
$initialMTime = (Get-Item $dbPath).LastWriteTimeUtc.ToString("o")

Write-Host "============================================================"
Write-Host "DEV DATABASE INTEGRITY PRE-CHECK"
Write-Host "Target DB: $dbPath"
Write-Host "Initial SHA256:      $initialHash"
Write-Host "Initial MTime (UTC): $initialMTime"
Write-Host "============================================================"

Write-Host "`nRunning Pytest Suite against isolated test database...`n"
$pyExe = "python"
if (Test-Path "$PSScriptRoot\..\..\opsdesk\.venv\Scripts\python.exe") {
    $pyExe = "$PSScriptRoot\..\..\opsdesk\.venv\Scripts\python.exe"
} elseif (Test-Path "C:\Users\yashp\projects\opsdesk\.venv\Scripts\python.exe") {
    $pyExe = "C:\Users\yashp\projects\opsdesk\.venv\Scripts\python.exe"
}
& $pyExe -m pytest -v
$pytestExitCode = $LASTEXITCODE

$postHash = (Get-FileHash -Path $dbPath -Algorithm SHA256).Hash
$postMTime = (Get-Item $dbPath).LastWriteTimeUtc.ToString("o")

Write-Host "`n============================================================"
Write-Host "DEV DATABASE INTEGRITY POST-CHECK"
Write-Host "Post SHA256:         $postHash"
Write-Host "Post MTime (UTC):    $postMTime"

if ($initialHash -eq $postHash) {
    Write-Host "`nRESULT: SUCCESS - opsdesk.db is 100% UNTOUCHED (Hashes Match)." -ForegroundColor Green
    Write-Host "============================================================"
    if ($pytestExitCode -ne 0) {
        exit $pytestExitCode
    }
    exit 0
} else {
    Write-Error "`nRESULT: FAILED - opsdesk.db was modified during test run! Initial: $initialHash, Post: $postHash"
    exit 1
}
