. "$PSScriptRoot\_utf8.ps1"
$Project = 'D:\autoops-rag'
$PidPath = "$Project\storage\server.pid"
$Candidates = @()
if (Test-Path $PidPath) {
    $Candidates += [int](Get-Content $PidPath)
}
$Listener = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($Listener) {
    $Candidates += [int]$Listener.OwningProcess
}
$Stopped = @()
foreach ($ServerPid in ($Candidates | Select-Object -Unique)) {
    $ProcessInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$ServerPid" -ErrorAction SilentlyContinue
    if ($ProcessInfo -and $ProcessInfo.CommandLine -match 'uvicorn\s+app\.main:app') {
        Stop-Process -Id $ServerPid -Force -ErrorAction SilentlyContinue
        $Stopped += $ServerPid
    }
}
if (Test-Path $PidPath) {
    Remove-Item $PidPath -Force
}
if ($Stopped.Count) {
    Write-Host "AutoOps RAG stopped. PID=$($Stopped -join ',')"
} else {
    Write-Host 'No matching AutoOps RAG server process was found.'
}
