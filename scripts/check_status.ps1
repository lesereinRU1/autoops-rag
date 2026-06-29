. "$PSScriptRoot\_utf8.ps1"
$Project = 'D:\autoops-rag'
$Drive = Get-PSDrive D
$Folders = @('.venv','models','data\raw','data\processed','storage','.cache')
Write-Host "D drive free: $([math]::Round($Drive.Free/1GB,2)) GB"
foreach ($Folder in $Folders) {
    $Bytes = (Get-ChildItem "$Project\$Folder" -Recurse -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum
    Write-Host ("{0,-18} {1,8} MB" -f $Folder, [math]::Round($Bytes/1MB,1))
}
try {
    $Health = Invoke-RestMethod 'http://127.0.0.1:8000/health' -TimeoutSec 3
    Write-Host "Service: running; backend=$($Health.embedding_backend); chunks=$($Health.indexed_chunks)"
} catch {
    Write-Host 'Service: stopped. Start with .\scripts\start_background.ps1'
}
