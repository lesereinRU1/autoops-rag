param([ValidateSet('semantic','fixed')][string]$Mode = 'semantic')
. "$PSScriptRoot\_utf8.ps1"
$ErrorActionPreference = 'Stop'
$Project = 'D:\autoops-rag'
Set-Location $Project
$PidPath = "$Project\storage\server.pid"
if (Test-Path $PidPath) {
    $ServerPid = [int](Get-Content $PidPath)
    Stop-Process -Id $ServerPid -Force -ErrorAction SilentlyContinue
    Remove-Item $PidPath -Force
    Start-Sleep -Seconds 1
}
$env:HF_HOME = "$Project\models\huggingface"
$env:FASTEMBED_CACHE_PATH = "$Project\models\fastembed"
& "$Project\.venv\Scripts\python.exe" scripts\ingest.py --mode $Mode
Write-Host 'Index rebuilt. Run .\scripts\start_background.ps1 to restart the service.'
