param(
    [int]$ApiPort = 8100,
    [int]$FrontendPort = 5273,
    [int]$FailureApiPort = 8101,
    [int]$FailureFrontendPort = 5274
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'platform-processes.ps1')
Assert-PlatformInspection
$testState = Join-Path $PSScriptRoot '.platform-test-processes.json'
$failureState = Join-Path $PSScriptRoot '.platform-failure-test-processes.json'
$startScript = Join-Path $PSScriptRoot 'start-platform.ps1'
$stopScript = Join-Path $PSScriptRoot 'stop-platform.ps1'
if ((Test-Path -LiteralPath $testState) -or (Test-Path -LiteralPath $failureState)) {
    throw '测试状态文件已存在，请先核对其运行实例。'
}
function Assert-Test {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw "FAILED: $Message" }
    Write-Output "PASS: $Message"
}
function Assert-PortFree {
    param([int]$Port)
    $deadline = (Get-Date).AddSeconds(5)
    do {
        $listeners = @(Get-PlatformListeners -Port $Port)
        if (-not $listeners.Count) { return }
        Start-Sleep -Milliseconds 100
    } while ((Get-Date) -lt $deadline)
    throw "FAILED: 测试端口 $Port 未被清理"
}
foreach ($port in $ApiPort,$FrontendPort,$FailureApiPort,$FailureFrontendPort) { Assert-PortFree $port }
$previousCheckpoint = $env:TCMP_CHECKPOINT
try {
    $env:TCMP_CHECKPOINT = Join-Path $PSScriptRoot 'TCMP-300\missing-test-checkpoint.pt'
    $failed = $false
    try {
        & $startScript -ApiPort $FailureApiPort -FrontendPort $FailureFrontendPort -StartupTimeoutSeconds 40 -StateFile $failureState
    } catch { $failed = $true }
    Assert-Test $failed '缺失模型时启动失败，不报告服务已就绪'
    Assert-PortFree $FailureApiPort
    Assert-PortFree $FailureFrontendPort
    Assert-Test (-not (Test-Path -LiteralPath $failureState)) '启动失败清理两个进程且不留下成功状态'
} finally { $env:TCMP_CHECKPOINT = $previousCheckpoint }
try {
    & $startScript -ApiPort $ApiPort -FrontendPort $FrontendPort -StateFile $testState
    $state = Read-PlatformState -StateFile $testState -ProjectRoot $PSScriptRoot
    Assert-Test ((Invoke-RestMethod -Uri "$($state.ApiUrl)/api/v1/health" -TimeoutSec 5).status -eq 'ready') '真实模型健康检查通过'
    Assert-Test ((Invoke-WebRequest -Uri $state.FrontendUrl -UseBasicParsing -TimeoutSec 15).StatusCode -eq 200) '前端页面就绪'
    $cors = Invoke-WebRequest -Uri "$($state.ApiUrl)/api/v1/predict" -Method Options -UseBasicParsing -Headers @{
        Origin = $state.FrontendUrl
        'Access-Control-Request-Method' = 'POST'
    } -TimeoutSec 5
    Assert-Test ([string]$cors.Headers['Access-Control-Allow-Origin'] -eq $state.FrontendUrl) '自定义端口的浏览器跨域配置正确'
    $duplicateBlocked = $false
    try { & $startScript -ApiPort $ApiPort -FrontendPort $FrontendPort -StateFile $testState }
    catch { $duplicateBlocked = $true }
    Assert-Test $duplicateBlocked '重复启动被阻止'
    $stale = $state.Processes[0] | Select-Object *
    $stale.StartTimeUtc = [DateTime]::UtcNow.AddYears(-1).ToString('o')
    Assert-Test ($null -eq (Get-VerifiedPlatformProcess -Record $stale -ProjectRoot $PSScriptRoot)) '旧PID记录不会匹配当前进程'
    $wrongExecutable = $state.Processes[0] | Select-Object *
    $wrongExecutable.Executable = 'C:\not-the-platform.exe'
    $mismatchBlocked = $false
    try { $null = Get-VerifiedPlatformProcess -Record $wrongExecutable -ProjectRoot $PSScriptRoot }
    catch { $mismatchBlocked = $true }
    Assert-Test $mismatchBlocked '程序身份不匹配时拒绝停止'
    Assert-Test ((Invoke-RestMethod -Uri "$($state.ApiUrl)/api/v1/health" -TimeoutSec 5).status -eq 'ready') '身份核对后服务仍正常运行'
} finally {
    if (Test-Path -LiteralPath $testState) { & $stopScript -StateFile $testState }
}
Assert-PortFree $ApiPort
Assert-PortFree $FrontendPort
Assert-Test (-not (Test-Path -LiteralPath $testState)) '停止脚本清理前后端及状态文件'
Write-Output '平台启动/失败回滚/停止检查全部通过。'
