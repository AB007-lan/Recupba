# Lance l'API et l'interface RECUPBA.
# Usage : clic droit > Executer avec PowerShell, ou : .\start-recupba.ps1 [-Port 8020]
param([int]$Port = 8020)

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$busy = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($busy) {
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$($busy[0].OwningProcess)"
    Write-Host "Le port $Port est deja utilise par : $($proc.Name) (PID $($proc.ProcessId))" -ForegroundColor Red
    Write-Host "Relancez avec un autre port, par exemple : .\start-recupba.ps1 -Port 8030"
    exit 1
}

$python = Join-Path $root "apps\api\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "Environnement Python introuvable : $python" -ForegroundColor Red
    exit 1
}

Write-Host "RECUPBA demarre sur http://127.0.0.1:$Port/  (CTRL+C pour arreter)" -ForegroundColor Green
& $python -m uvicorn main:app --app-dir apps\api --host 127.0.0.1 --port $Port
