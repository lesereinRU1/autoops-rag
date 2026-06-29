. "$PSScriptRoot\_utf8.ps1"
$ErrorActionPreference = 'Stop'
$Project = 'D:\autoops-rag'
Set-Location $Project
$env:PIP_CACHE_DIR = "$Project\.cache\pip"
$env:HF_HOME = "$Project\models\huggingface"
$env:FASTEMBED_CACHE_PATH = "$Project\models\fastembed"
$env:TEMP = "$Project\.tmp"
$env:TMP = "$Project\.tmp"
& "$Project\.venv\Scripts\python.exe" -m pip install fastembed==0.7.1
(Get-Content .env -Raw).Replace('EMBEDDING_BACKEND=hash', 'EMBEDDING_BACKEND=fastembed') | Set-Content .env -Encoding ascii
& "$Project\.venv\Scripts\python.exe" scripts\ingest.py --mode semantic
Write-Host 'BGE embeddings are enabled and the index has been rebuilt.'
