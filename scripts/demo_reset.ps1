# ==============================================================================
# OpsDesk Demo Reset Script (Windows PowerShell)
# Resets the local environment, seeds test database, and boots backend/frontend.
# ==============================================================================

[CmdletBinding()]
param(
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 3100
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot

Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host "OpsDesk Demo Environment Reset - TBO VoyageHack 4.0" -ForegroundColor Cyan
Write-Host "=================================================================" -ForegroundColor Cyan

# 1. Stop existing processes on target ports
Write-Host "`n[1/5] Stopping any running processes on ports $BackendPort and $FrontendPort..." -ForegroundColor Yellow
$ports = @($BackendPort, $FrontendPort)
foreach ($p in $ports) {
    try {
        $conns = Get-NetTCPConnection -LocalPort $p -ErrorAction SilentlyContinue
        if ($conns) {
            $pids = $conns | Select-Object -ExpandProperty OwningProcess -Unique
            foreach ($procId in $pids) {
                if ($procId -gt 4) {
                    Write-Host "  Stopping PID $procId listening on port $p..."
                    Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
                }
            }
        }
    } catch {
        # Ignore permission/not found
    }
}
Start-Sleep -Seconds 1

# 2. Backup current dev database if present
$DbPath = Join-Path $RepoRoot "opsdesk.db"
if (Test-Path $DbPath) {
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $BackupPath = Join-Path $RepoRoot "opsdesk.backup_$timestamp.db"
    Write-Host "`n[2/5] Backing up dev database to $BackupPath..." -ForegroundColor Yellow
    Copy-Item -Path $DbPath -Destination $BackupPath -Force
} else {
    Write-Host "`n[2/5] No existing dev database found at $DbPath." -ForegroundColor Yellow
}

# 3. Reseed dev database
Write-Host "`n[3/5] Reseeding database via backend.seed.seed_data --reset..." -ForegroundColor Yellow
$PythonExe = "python"
if (Test-Path "C:\Users\yashp\projects\opsdesk\.venv\Scripts\python.exe") {
    $PythonExe = "C:\Users\yashp\projects\opsdesk\.venv\Scripts\python.exe"
}
Push-Location $RepoRoot
try {
    & $PythonExe -m backend.seed.seed_data --reset --total 50
    & $PythonExe -m alembic stamp head
} finally {
    Pop-Location
}

# 4. Start backend and frontend
Write-Host "`n[4/5] Launching background services..." -ForegroundColor Yellow
Write-Host "  Starting FastAPI backend on port $BackendPort..."
$backendProc = Start-Process -FilePath $PythonExe -ArgumentList "-m uvicorn backend.app.main:app --host 127.0.0.1 --port $BackendPort" -WorkingDirectory $RepoRoot -PassThru

Write-Host "  Starting Next.js frontend on port $FrontendPort..."
$frontendDir = Join-Path $RepoRoot "frontend"
$frontendProc = Start-Process -FilePath "npm.cmd" -ArgumentList "run dev -- -p $FrontendPort" -WorkingDirectory $frontendDir -PassThru

Start-Sleep -Seconds 3

# 5. Verify connectivity and display credentials
Write-Host "`n[5/5] Verifying service connectivity..." -ForegroundColor Yellow
$backendReady = $false
for ($i = 0; $i -lt 15; $i++) {
    try {
        $res = Invoke-WebRequest -Uri "http://127.0.0.1:$BackendPort/health" -Method Get -TimeoutSec 2 -ErrorAction Stop
        if ($res.StatusCode -eq 200) { $backendReady = $true; break }
    } catch {
        Start-Sleep -Seconds 1
    }
}

if ($backendReady) {
    Write-Host "  Backend is ONLINE: http://127.0.0.1:$BackendPort/health" -ForegroundColor Green
} else {
    Write-Host "  Backend health check pending or starting..." -ForegroundColor DarkYellow
}

Write-Host "`n=================================================================" -ForegroundColor Cyan
Write-Host "OpsDesk Demo Environment Ready!" -ForegroundColor Green
Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host "Frontend URL:  http://localhost:$FrontendPort" -ForegroundColor White
Write-Host "Backend API:   http://localhost:$BackendPort" -ForegroundColor White
Write-Host "API Docs:      http://localhost:$BackendPort/docs" -ForegroundColor White
Write-Host "`nDemo Credentials (Password for all accounts: demo123):" -ForegroundColor Cyan
Write-Host "  - Agent:              aisha@travelops.example.com        (ID: USR-101, Role: Agent)" -ForegroundColor White
Write-Host "  - Escalation Mgr:     vikram.esc@travelops.example.com   (ID: USR-103, Role: EscalationManager)" -ForegroundColor White
Write-Host "  - Operations Lead:    priya@travelops.example.com        (ID: USR-104, Role: Lead)" -ForegroundColor White
Write-Host "  - Agency Requester:   agent@voyage.example.com           (ID: USR-201, Role: Requester, AGY-001)" -ForegroundColor White
Write-Host "=================================================================`n" -ForegroundColor Cyan
