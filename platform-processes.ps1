function Get-PlatformProcessRecord {
    param([System.Diagnostics.Process]$Process, [string]$Role)
    $Process.Refresh()
    if ($Process.HasExited) { throw "$Role 进程已退出，请检查启动日志。" }
    $details = Get-CimInstance Win32_Process -Filter "ProcessId = $($Process.Id)" -ErrorAction Stop
    if (-not $details -or -not $details.ExecutablePath) { throw "无法记录 $Role 进程的程序路径。" }
    [pscustomobject]@{
        Role = $Role
        Id = $Process.Id
        StartTimeUtc = $Process.StartTime.ToUniversalTime().ToString('o')
        Executable = $details.ExecutablePath
    }
}

function Get-VerifiedPlatformProcess {
    param($Record, [string]$ProjectRoot)
    if ($Record.Role -notin @('backend', 'frontend')) { throw '进程状态中的角色无效。' }
    $details = Get-CimInstance Win32_Process -Filter "ProcessId = $($Record.Id)" -ErrorAction Stop
    if (-not $details) { return $null }
    $process = Get-Process -Id $Record.Id -ErrorAction Stop
    if ($process.StartTime.ToUniversalTime().ToString('o') -ne $Record.StartTimeUtc) { return $null }
    if (-not $details -or -not $details.ExecutablePath -or
        -not [string]::Equals($details.ExecutablePath, [string]$Record.Executable, [StringComparison]::OrdinalIgnoreCase)) {
        throw "无法核实进程 $($Record.Id) 的程序路径；未停止该进程。"
    }
    $expected = if ($Record.Role -eq 'backend') {
        Join-Path $ProjectRoot 'TCMP-300'
    } else {
        Join-Path $ProjectRoot '数据标签\node_modules\vite\bin\vite.js'
    }
    if (-not $details.CommandLine -or $details.CommandLine.IndexOf($expected, [StringComparison]::OrdinalIgnoreCase) -lt 0 -or
        ($Record.Role -eq 'backend' -and $details.CommandLine -notmatch 'uvicorn\s+api:app')) {
        throw "无法核实进程 $($Record.Id) 属于本项目；未停止该进程。"
    }
    return $process
}

function Stop-PlatformProcess {
    param($Record, [string]$ProjectRoot)
    # The service can outlive a venv launcher. Stop only its saved identity.
    if ($Record.Service) {
        Stop-PlatformProcess -Record $Record.Service -ProjectRoot $ProjectRoot
    }
    $process = Get-VerifiedPlatformProcess -Record $Record -ProjectRoot $ProjectRoot
    if (-not $process) { return }
    # Capture descendants before stopping the launcher, including a venv Python child.
    $snapshot = @(Get-CimInstance Win32_Process -ErrorAction Stop)
    $descendants = [System.Collections.Generic.List[object]]::new()
    $parents = @([pscustomobject]@{ Id = $process.Id; Created = $process.StartTime.ToUniversalTime() })
    while ($parents.Count -gt 0) {
        $parentTimes = @{}
        foreach ($parent in $parents) { $parentTimes[[int]$parent.Id] = $parent.Created }
        $children = @($snapshot | Where-Object {
            $parentTimes.ContainsKey([int]$_.ParentProcessId) -and
            $_.CreationDate.ToUniversalTime() -ge $parentTimes[[int]$_.ParentProcessId]
        })
        foreach ($child in $children) { $descendants.Add($child) }
        $parents = @($children | ForEach-Object {
            [pscustomobject]@{ Id = [int]$_.ProcessId; Created = $_.CreationDate.ToUniversalTime() }
        })
    }
    for ($index = $descendants.Count - 1; $index -ge 0; $index--) {
        $child = $descendants[$index]
        $current = Get-CimInstance Win32_Process -Filter "ProcessId = $($child.ProcessId)" -ErrorAction SilentlyContinue
        if ($current -and $current.CreationDate -eq $child.CreationDate -and $current.ParentProcessId -eq $child.ParentProcessId) {
            try { Stop-Process -Id $child.ProcessId -Force -ErrorAction Stop }
            catch {
                $stillPresent = Get-CimInstance Win32_Process -Filter "ProcessId = $($child.ProcessId)" -ErrorAction Stop
                if ($stillPresent -and $stillPresent.CreationDate -eq $child.CreationDate) { throw }
            }
        }
    }
    # Recheck the identity because process IDs can be reused.
    $verified = Get-VerifiedPlatformProcess -Record $Record -ProjectRoot $ProjectRoot
    if ($verified) { Stop-Process -Id $verified.Id -Force -ErrorAction Stop }
}

function Save-PlatformServiceRecord {
    param($Record, [int]$Port, [string]$ProjectRoot)
    if (-not (Get-VerifiedPlatformProcess -Record $Record -ProjectRoot $ProjectRoot)) { return }
    $owners = @(Get-PlatformListeners -Port $Port |
        Select-Object -ExpandProperty OwningProcess -Unique)
    if ($owners.Count -eq 0) { return }
    if ($owners.Count -ne 1) { throw "无法唯一核实端口 $Port 的服务进程。" }
    if ($owners[0] -eq $Record.Id) { return }
    $serviceDetails = Get-CimInstance Win32_Process -Filter "ProcessId = $($owners[0])" -ErrorAction Stop
    if (-not $serviceDetails -or $serviceDetails.ParentProcessId -ne $Record.Id -or
        $serviceDetails.CreationDate.ToUniversalTime() -lt [DateTime]::Parse($Record.StartTimeUtc).ToUniversalTime()) {
        throw "端口 $Port 的服务不属于本次启动进程，未记录或停止该服务。"
    }
    $service = Get-PlatformProcessRecord -Process (Get-Process -Id $owners[0] -ErrorAction Stop) -Role $Record.Role
    $null = Get-VerifiedPlatformProcess -Record $service -ProjectRoot $ProjectRoot
    $Record | Add-Member -NotePropertyName Service -NotePropertyValue $service -Force
}

function Assert-PlatformInspection {
    # Fail before launch if Windows process/network inspection is unavailable.
    $current = Get-CimInstance Win32_Process -Filter "ProcessId = $PID" -ErrorAction Stop
    if (-not $current) { throw '无法核实当前进程，请在可访问 Windows 系统查询的 PowerShell 中运行。' }
    $null = Get-NetTCPConnection -ErrorAction Stop
}

function Get-PlatformListeners {
    param([int]$Port)
    # Absent listeners must not mask an access error from Windows inspection.
    Get-NetTCPConnection -ErrorAction Stop | Where-Object { $_.State -eq 'Listen' -and $_.LocalPort -eq $Port }
}

function Read-PlatformState {
    param([string]$StateFile, [string]$ProjectRoot)
    $state = Get-Content -LiteralPath $StateFile -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($state.Version -ne 1 -or
        -not [string]::Equals([string]$state.ProjectRoot, $ProjectRoot, [StringComparison]::OrdinalIgnoreCase) -or
        @($state.Processes).Count -ne 2) {
        throw '进程状态文件不属于本项目或内容不完整。'
    }
    return $state
}
