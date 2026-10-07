param([string]$StateFile = (Join-Path $PSScriptRoot '.platform-processes.json'))
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'platform-processes.ps1')
if (-not (Test-Path -LiteralPath $StateFile)) {
    Write-Output '没有本脚本记录的运行实例。'
    return
}
Assert-PlatformInspection
$state = Read-PlatformState -StateFile $StateFile -ProjectRoot $PSScriptRoot
# Verify every live root before stopping any process.
foreach ($record in $state.Processes) {
    $null = Get-VerifiedPlatformProcess -Record $record -ProjectRoot $PSScriptRoot
    if ($record.Service) {
        $null = Get-VerifiedPlatformProcess -Record $record.Service -ProjectRoot $PSScriptRoot
    }
}
foreach ($record in $state.Processes) {
    Stop-PlatformProcess -Record $record -ProjectRoot $PSScriptRoot
}
Remove-Item -LiteralPath $StateFile
Write-Output '本次平台进程已停止；原有服务不受影响。'
