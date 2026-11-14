$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'TCMP-300/.venv-api/Scripts/python.exe') (Join-Path $PSScriptRoot 'TCMP-300/tools/local_mysql.py') start
if ($LASTEXITCODE -ne 0) { throw '项目 MySQL 启动失败。' }
