$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$apiPython = Join-Path $PSScriptRoot '.venv-api\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $apiPython)) {
    throw '请先按 README 的步骤创建 .venv-api 并安装 requirements-api.txt'
}
& $apiPython -m uvicorn api:app --host 127.0.0.1 --port 8000
