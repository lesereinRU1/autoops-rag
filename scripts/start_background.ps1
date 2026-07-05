. "$PSScriptRoot\_utf8.ps1"
$ErrorActionPreference = 'Stop'
$Project = 'D:\autoops-rag'
Set-Location $Project
$Existing = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($Existing) {
    $Existing.OwningProcess | Set-Content "$Project\storage\server.pid"
    Write-Host "Port 8000 is already listening. PID=$($Existing.OwningProcess)"
    exit 0
}
$env:PIP_CACHE_DIR = "$Project\.cache\pip"
$env:HF_HOME = "$Project\models\huggingface"
$env:FASTEMBED_CACHE_PATH = "$Project\models\fastembed"
$env:TEMP = "$Project\.tmp"
$env:TMP = "$Project\.tmp"
$Process = Start-Process -FilePath "$Project\.venv\Scripts\python.exe" `
    -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000' `
    -WorkingDirectory $Project `
    -RedirectStandardOutput "$Project\reports\server.out.log" `
    -RedirectStandardError "$Project\reports\server.err.log" `
    -WindowStyle Hidden -PassThru
$Listener = $null
for ($Index = 0; $Index -lt 60; $Index++) {
    $Listener = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
    if ($Listener) { break }
    if ($Process.HasExited) { break }
    Start-Sleep -Milliseconds 500
}
if (-not $Listener) {
    Write-Host 'Service failed to listen on port 8000. Check reports\server.err.log.'
    exit 1
}
$Ready = $false
for ($Index = 0; $Index -lt 60; $Index++) {
    try {
        $Response = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health/ready' -TimeoutSec 2
        if ($Response.status -eq 'ok') {
            $Ready = $true
            break
        }
    } catch {
        if ($Process.HasExited) { break }
    }
    Start-Sleep -Milliseconds 500
}
if (-not $Ready) {
    if (-not $Process.HasExited) { Stop-Process -Id $Process.Id -Force }
    Write-Host 'Service opened the port but did not become ready. Check reports\server.err.log.'
    exit 1
}
$Listener.OwningProcess | Set-Content "$Project\storage\server.pid"
Write-Host "Service started in the background. PID=$($Listener.OwningProcess); URL=http://127.0.0.1:8000"
