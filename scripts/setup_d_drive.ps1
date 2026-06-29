param(
    [switch]$Minimal,
    [switch]$IncludeOptionalManual
)

. "$PSScriptRoot\_utf8.ps1"
$ErrorActionPreference = 'Stop'
$Project = 'D:\autoops-rag'
if (-not (Test-Path $Project)) { throw "Project not found: $Project" }

Set-Location $Project
New-Item -ItemType Directory -Force -Path "$Project\.cache\pip", "$Project\.tmp", "$Project\models\huggingface", "$Project\models\fastembed" | Out-Null
$env:PIP_CACHE_DIR = "$Project\.cache\pip"
$env:HF_HOME = "$Project\models\huggingface"
$env:FASTEMBED_CACHE_PATH = "$Project\models\fastembed"
$env:TEMP = "$Project\.tmp"
$env:TMP = "$Project\.tmp"

$Python = 'D:\electron\Python\python.exe'
if (-not (Test-Path $Python)) { $Python = (Get-Command python -ErrorAction Stop).Source }
if (-not (Test-Path "$Project\.venv\Scripts\python.exe")) {
    Write-Host '1/5 Creating the virtual environment on D drive...'
    & $Python -m venv "$Project\.venv"
}
$VenvPython = "$Project\.venv\Scripts\python.exe"

Write-Host '2/5 Installing dependencies; cache remains on D drive...'
& $VenvPython -m pip install --upgrade pip
if ($Minimal) {
    & $VenvPython -m pip install -r requirements-minimal.txt
    (Get-Content .env -Raw).Replace('EMBEDDING_BACKEND=fastembed', 'EMBEDDING_BACKEND=hash') | Set-Content .env -Encoding ascii
} else {
    & $VenvPython -m pip install -r requirements.txt
    (Get-Content .env -Raw).Replace('EMBEDDING_BACKEND=hash', 'EMBEDDING_BACKEND=fastembed') | Set-Content .env -Encoding ascii
}

Write-Host '3/5 Downloading official manuals to D drive...'
if ($IncludeOptionalManual) { & $VenvPython scripts\download_data.py --include-optional } else { & $VenvPython scripts\download_data.py }

Write-Host '4/5 Parsing, chunking, and indexing...'
& $VenvPython scripts\ingest.py --mode semantic

Write-Host '5/5 Running tests...'
& $VenvPython -m pytest
Write-Host 'Done. Next command: .\scripts\start_background.ps1'
