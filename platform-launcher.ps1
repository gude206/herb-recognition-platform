param(
    [ValidateSet('start', 'stop')][string]$Action = 'start',
    [switch]$NoBrowser,
    [switch]$NoPause
)
$ErrorActionPreference = 'Stop'
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$env:PYTHONIOENCODING = 'utf-8'
$stateFile = Join-Path $PSScriptRoot '.platform-processes.json'
$frontendUrl = 'http://127.0.0.1:5173'
$apiUrl = 'http://127.0.0.1:8000'
$succeeded = $false

function Find-AvailablePlatformPort {
    param([int]$PreferredPort)
    foreach ($candidate in $PreferredPort..($PreferredPort + 9)) {
        if (-not (Get-PlatformListeners -Port $candidate)) { return $candidate }
    }
    throw "端口 $PreferredPort 起的 10 个端口均已占用，请检查已有服务。"
}

try {
    Write-Host '正在检查运行环境，请稍候…'
    Set-Location -LiteralPath $PSScriptRoot
    . (Join-Path $PSScriptRoot 'platform-processes.ps1')
    Assert-PlatformInspection

    if ($Action -eq 'stop') {
        & (Join-Path $PSScriptRoot 'stop-platform.ps1') -StateFile $stateFile
        $apiPython = Join-Path $PSScriptRoot 'TCMP-300/.venv-api/Scripts/python.exe'
        $backendEnv = Join-Path $PSScriptRoot 'TCMP-300/.env'
        $managedMysql = & $apiPython -c "from dotenv import dotenv_values; import os,sys; values={**dotenv_values(sys.argv[1]),**os.environ}; print(str(values.get('MYSQL_MANAGED_LOCAL','false')).lower())" $backendEnv
        if ($LASTEXITCODE -ne 0) { throw '无法读取数据库关闭配置。' }
        if ($managedMysql.Trim() -in @('true','1','yes')) {
            & (Join-Path $PSScriptRoot 'stop-mysql.ps1')
        }
        Write-Host "`n项目已关闭，数据库和上传文件已保留。" -ForegroundColor Green
    } else {
        $alreadyRunning = $false
        if (Test-Path -LiteralPath $stateFile) {
            $state = Read-PlatformState -StateFile $stateFile -ProjectRoot $PSScriptRoot
            $liveCount = 0
            foreach ($record in $state.Processes) {
                $live = Get-VerifiedPlatformProcess -Record $record -ProjectRoot $PSScriptRoot
                if ($record.Service) {
                    $service = Get-VerifiedPlatformProcess -Record $record.Service -ProjectRoot $PSScriptRoot
                    if ($service) { $live = $service }
                }
                if ($live) { $liveCount++ }
            }
            if ($liveCount -gt 0) {
                if ($liveCount -ne 2) {
                    throw '检测到已有平台实例或部分服务仍在运行，请先使用对应的关闭脚本，再重新启动。'
                }
                if ($state.ApiUrl -notmatch '^http://127\.0\.0\.1:([1-9]\d{3,4})$' -or
                    $state.FrontendUrl -notmatch '^http://127\.0\.0\.1:([1-9]\d{3,4})$') {
                    throw '平台状态中的地址无效，请核对 .platform-processes.json。'
                }
                $apiUrl = $state.ApiUrl
                $frontendUrl = $state.FrontendUrl
                $health = Invoke-RestMethod -Uri "$apiUrl/api/v1/health" -TimeoutSec 5
                $page = Invoke-WebRequest -Uri $frontendUrl -UseBasicParsing -TimeoutSec 5
                if ($health.status -ne 'ready' -or $page.StatusCode -ne 200) {
                    throw '已有平台尚未就绪，请稍候重试；持续失败时先双击一键关闭，再重新启动。'
                }
                $alreadyRunning = $true
                Write-Host '项目已在运行，直接打开首页。'
            }
        }
        if (-not $alreadyRunning) {
            $apiPort = Find-AvailablePlatformPort -PreferredPort 8000
            $frontendPort = Find-AvailablePlatformPort -PreferredPort 5173
            Write-Host '正在启动数据库、后端和前端，请稍候…'
            & (Join-Path $PSScriptRoot 'start-platform.ps1') -ApiPort $apiPort -FrontendPort $frontendPort -StateFile $stateFile
            $apiUrl = "http://127.0.0.1:$apiPort"
            $frontendUrl = "http://127.0.0.1:$frontendPort"
        }
        Write-Host "`n项目已就绪：$frontendUrl" -ForegroundColor Green
        if (-not $NoBrowser) { Start-Process -FilePath $frontendUrl }
        Write-Host '关闭此窗口不会停止项目；停止服务请双击“一键关闭.bat”。'
    }
    $succeeded = $true
} catch {
    Write-Host "`n操作失败：$($_.Exception.Message)" -ForegroundColor Red
    Write-Host '请检查 Node.js、Python 依赖和本机 MySQL 配置，以及 TCMP-300/api.<端口>.err.log、数据标签/frontend.<端口>.err.log。'
}

if (-not $NoPause) { $null = Read-Host "`n按 Enter 关闭窗口" }
if ($succeeded) { exit 0 }
exit 1
