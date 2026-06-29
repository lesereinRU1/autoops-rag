. "$PSScriptRoot\_utf8.ps1"
$ErrorActionPreference = 'Stop'
$Project = 'D:\autoops-rag'
Set-Location $Project
$env:PIP_CACHE_DIR = "$Project\.cache\pip"
$env:HF_HOME = "$Project\models\huggingface"
$env:FASTEMBED_CACHE_PATH = "$Project\models\fastembed"
$env:TEMP = "$Project\.tmp"
$env:TMP = "$Project\.tmp"
& "$Project\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
