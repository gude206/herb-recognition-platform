param(
    [ValidateRange(1024, 65535)][int]$ApiPort = 8000,
    [ValidateRange(1024, 65535)][int]$FrontendPort = 5173,
    [ValidateRange(5, 600)][int]$StartupTimeoutSeconds = 90,
    [string]$StateFile = (Join-Path $PSScriptRoot '.platform-processes.json')
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'platform-processes.ps1')
Assert-PlatformInspection
if ($ApiPort -eq $FrontendPort) { throw '前后端必须使用不同端口。' }
$backendDir = Join-Path $PSScriptRoot 'TCMP-300'
$frontendDir = Join-Path $PSScriptRoot '数据标签'
$apiPython = Join-Path $backendDir '.venv-api\Scripts\python.exe'
$viteEntry = Join-Path $frontendDir 'node_modules\vite\bin\vite.js'
$viteConfig = Join-Path $frontendDir 'vite.config.ts'
$nodeExe = (Get-Command node.exe -ErrorAction Stop).Source
if (-not (Test-Path -LiteralPath $apiPython) -or -not (Test-Path -LiteralPath $viteEntry)) {
    throw '请先按两个项目 README 的说明安装依赖。'
}
if (Test-Path -LiteralPath $StateFile) {
    $existing = Read-PlatformState -StateFile $StateFile -ProjectRoot $PSScriptRoot
    foreach ($record in $existing.Processes) {
        if (Get-VerifiedPlatformProcess -Record $record -ProjectRoot $PSScriptRoot) {
            throw '本状态文件已有运行中的平台，请先执行 stop-platform.ps1，或为独立实例指定其他 StateFile。'
        }
    }
}
foreach ($port in $ApiPort,$FrontendPort) {
    if (Get-PlatformListeners -Port $port) {
        throw "端口 $port 已占用；请先检查已有服务。"
    }
}
$apiUrl = "http://127.0.0.1:$ApiPort"
$frontendUrl = "http://127.0.0.1:$FrontendPort"
$apiLog = Join-Path $backendDir "api.$ApiPort.log"
$apiErrorLog = Join-Path $backendDir "api.$ApiPort.err.log"
$frontendLog = Join-Path $frontendDir "frontend.$FrontendPort.log"
$frontendErrorLog = Join-Path $frontendDir "frontend.$FrontendPort.err.log"
$records = [System.Collections.Generic.List[object]]::new()
$previousApiBase = $env:VITE_API_BASE_URL
$previousOrigin = $env:TCMP_FRONTEND_ORIGIN
try {
    $env:VITE_API_BASE_URL = $apiUrl
    $env:TCMP_FRONTEND_ORIGIN = $frontendUrl
    $backend = Start-Process -FilePath $apiPython -ArgumentList '-m','uvicorn','api:app','--app-dir',"`"$backendDir`"",'--host','127.0.0.1','--port',"$ApiPort" -WorkingDirectory $backendDir -WindowStyle Hidden -RedirectStandardOutput $apiLog -RedirectStandardError $apiErrorLog -PassThru
    $records.Add((Get-PlatformProcessRecord -Process $backend -Role 'backend'))
    $frontend = Start-Process -FilePath $nodeExe -ArgumentList "`"$viteEntry`"",'--config',"`"$viteConfig`"",'--host','127.0.0.1','--port',"$FrontendPort",'--strictPort' -WorkingDirectory $frontendDir -WindowStyle Hidden -RedirectStandardOutput $frontendLog -RedirectStandardError $frontendErrorLog -PassThru
    $records.Add((Get-PlatformProcessRecord -Process $frontend -Role 'frontend'))
    $deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
    $ready = $false
    Write-Output '正在等待模型加载和前端就绪…'
    while ((Get-Date) -lt $deadline) {
        $backend.Refresh(); $frontend.Refresh()
        if ($backend.HasExited) { throw "后端已退出，请检查 $apiErrorLog" }
        if ($frontend.HasExited) { throw "前端已退出，请检查 $frontendErrorLog" }
        try {
            $health = Invoke-RestMethod -Uri "$apiUrl/api/v1/health" -TimeoutSec 2
            $page = Invoke-WebRequest -Uri $frontendUrl -UseBasicParsing -TimeoutSec 2
            if ($health.status -eq 'ready' -and $page.StatusCode -eq 200) { $ready = $true; break }
        } catch { }
        Start-Sleep -Milliseconds 300
    }
    if (-not $ready) { throw "平台未在 $StartupTimeoutSeconds 秒内就绪，请检查 $apiErrorLog 和 $frontendErrorLog" }
    Save-PlatformServiceRecord -Record $records[0] -Port $ApiPort -ProjectRoot $PSScriptRoot
    Save-PlatformServiceRecord -Record $records[1] -Port $FrontendPort -ProjectRoot $PSScriptRoot
    $state = [ordered]@{ Version = 1; ProjectRoot = $PSScriptRoot; ApiUrl = $apiUrl; FrontendUrl = $frontendUrl; Processes = @($records.ToArray()) }
    $state | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $StateFile -Encoding UTF8
} catch {
    $failure = $_
    foreach ($record in $records) {
        $port = if ($record.Role -eq 'backend') { $ApiPort } else { $FrontendPort }
        try { Save-PlatformServiceRecord -Record $record -Port $port -ProjectRoot $PSScriptRoot }
        catch { Write-Warning "无法记录启动失败后的服务子进程：$($_.Exception.Message)" }
        try { Stop-PlatformProcess -Record $record -ProjectRoot $PSScriptRoot }
        catch { Write-Warning "启动失败后的进程清理未完成：$($_.Exception.Message)" }
    }
    throw $failure
} finally {
    $env:VITE_API_BASE_URL = $previousApiBase
    $env:TCMP_FRONTEND_ORIGIN = $previousOrigin
}
Write-Output "前端：$frontendUrl（PID $($frontend.Id)）"
Write-Output "后端：$apiUrl/docs（PID $($backend.Id)）"
Write-Output '健康检查通过，图片识别服务已就绪。'
Write-Output "停止本次平台：.\stop-platform.ps1 -StateFile '$StateFile'"
Write-Output "日志：$apiLog；$apiErrorLog；$frontendLog；$frontendErrorLog"
