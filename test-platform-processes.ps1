# Pure in-memory checks: all process lookup and termination commands are mocked.
# Run with: powershell -ExecutionPolicy Bypass -File .\test-platform-processes.ps1
& {
    $ErrorActionPreference = 'Stop'
    . (Join-Path $PSScriptRoot 'platform-processes.ps1')
    $projectRoot = $PSScriptRoot
    $script:mockBaseTime = [DateTime]::SpecifyKind([DateTime]'2026-10-01T00:00:00', [DateTimeKind]::Utc)

    function Reset-MockProcesses {
        $script:mockProcesses = @{}
        $script:mockDetails = [ordered]@{}
        $script:mockStopped = [System.Collections.Generic.List[int]]::new()
    }

    function Add-MockProcess {
        param([int]$Id, [int]$ParentId, [int]$CreatedMinutes)
        $created = $script:mockBaseTime.AddMinutes($CreatedMinutes)
        $executable = Join-Path $projectRoot 'TCMP-300\.venv-api\Scripts\python.exe'
        $script:mockProcesses[$Id] = [pscustomobject]@{
            Id = $Id; StartTime = $created; Path = $executable
        }
        $script:mockDetails["$Id"] = [pscustomobject]@{
            ProcessId = $Id; ParentProcessId = $ParentId; CreationDate = $created
            ExecutablePath = $executable
            CommandLine = "python -m uvicorn api:app --app-dir `"$(Join-Path $projectRoot 'TCMP-300')`""
        }
    }

    function New-MockRecord {
        param([int]$Id)
        $process = $script:mockProcesses[$Id]
        if (-not $process) { throw "No mock process $Id" }
        [pscustomobject]@{
            Id = $Id; Role = 'backend'; Executable = $process.Path
            StartTimeUtc = $process.StartTime.ToUniversalTime().ToString('o')
        }
    }

    # These local functions replace native commands for every production function
    # invoked below. No test can fall through to a real process stop.
    function Get-Process {
        param([int]$Id, [string]$ErrorAction)
        return $script:mockProcesses[$Id]
    }

    function Get-CimInstance {
        param([string]$ClassName, [string]$Filter, [string]$ErrorAction)
        if ($ClassName -ne 'Win32_Process') { throw "Unexpected CIM class $ClassName" }
        if ($Filter) {
            if ($Filter -notmatch '^ProcessId = (\d+)$') { throw "Unexpected CIM filter $Filter" }
            return $script:mockDetails[$Matches[1]]
        }
        return @($script:mockDetails.Values)
    }

    function Stop-Process {
        param([int]$Id, [switch]$Force, [string]$ErrorAction)
        if (-not $script:mockProcesses.ContainsKey($Id)) { throw "Attempted to stop unknown mock PID $Id" }
        $script:mockStopped.Add($Id)
        $script:mockProcesses.Remove($Id)
        $script:mockDetails.Remove("$Id")
    }

    function Get-PlatformListeners {
        param([int]$Port)
        [pscustomobject]@{ OwningProcess = $script:mockListenerOwner; LocalPort = $Port }
    }

    function Get-PlatformProcessRecord {
        param($Process, [string]$Role)
        New-MockRecord $Process.Id
    }

    function Assert-Mock {
        param([bool]$Condition, [string]$Message)
        if (-not $Condition) { throw "FAILED: $Message" }
        Write-Output "PASS: $Message"
    }

    function Assert-StopOrder {
        param([int[]]$Expected, [string]$Message)
        $actualText = $script:mockStopped -join ','
        $expectedText = $Expected -join ','
        Assert-Mock ($actualText -eq $expectedText) "$Message (expected $expectedText; actual $actualText)"
    }

    Reset-MockProcesses
    Add-MockProcess -Id 100 -ParentId 0 -CreatedMinutes 0
    Add-MockProcess -Id 200 -ParentId 100 -CreatedMinutes 20
    # PID 300 belonged to an earlier lifetime of parent PID 200, after root 100
    # started but BEFORE the current PID 200. It is not a current descendant.
    Add-MockProcess -Id 300 -ParentId 200 -CreatedMinutes 10
    Stop-PlatformProcess -Record (New-MockRecord 100) -ProjectRoot $projectRoot
    Assert-StopOrder @(200, 100) 'Reused parent PID does not include an older unrelated child'
    Assert-Mock ($script:mockProcesses.ContainsKey(300)) 'Unrelated PID 300 remains running'

    Reset-MockProcesses
    Add-MockProcess -Id 100 -ParentId 0 -CreatedMinutes 0
    Add-MockProcess -Id 200 -ParentId 100 -CreatedMinutes 10
    Add-MockProcess -Id 400 -ParentId 100 -CreatedMinutes 10
    Add-MockProcess -Id 300 -ParentId 200 -CreatedMinutes 20
    Stop-PlatformProcess -Record (New-MockRecord 100) -ProjectRoot $projectRoot
    Assert-StopOrder @(300, 400, 200, 100) 'Current descendants stop in reverse traversal order before the root'
    Assert-Mock ($script:mockProcesses.Count -eq 0) 'Normal process tree is fully cleaned'

    Reset-MockProcesses
    Add-MockProcess -Id 100 -ParentId 0 -CreatedMinutes 0
    Add-MockProcess -Id 200 -ParentId 100 -CreatedMinutes 10
    Add-MockProcess -Id 300 -ParentId 200 -CreatedMinutes 20
    $record = New-MockRecord 100
    $record | Add-Member -NotePropertyName Service -NotePropertyValue (New-MockRecord 200)
    $script:mockProcesses.Remove(100)
    $script:mockDetails.Remove('100')
    Stop-PlatformProcess -Record $record -ProjectRoot $projectRoot
    Assert-StopOrder @(300, 200) 'Saved service and its children stop when the launcher no longer exists'
    Assert-Mock ($script:mockProcesses.Count -eq 0) 'Orphaned saved service leaves no live process'

    Reset-MockProcesses
    Add-MockProcess -Id 100 -ParentId 0 -CreatedMinutes 0
    Add-MockProcess -Id 200 -ParentId 100 -CreatedMinutes 10
    $record = New-MockRecord 100
    $record.Executable = 'C:\not-the-recorded-python.exe'
    $rejected = $false
    try { Stop-PlatformProcess -Record $record -ProjectRoot $projectRoot }
    catch { $rejected = $true }
    Assert-Mock $rejected 'Executable mismatch rejects termination'
    Assert-StopOrder @() 'Executable mismatch stops neither root nor children'

    Reset-MockProcesses
    Add-MockProcess -Id 100 -ParentId 0 -CreatedMinutes 0
    $record = New-MockRecord 100
    # A newer process reused the recorded root PID; the saved creation time differs.
    Add-MockProcess -Id 100 -ParentId 0 -CreatedMinutes 30
    Stop-PlatformProcess -Record $record -ProjectRoot $projectRoot
    Assert-StopOrder @() 'Reused root PID is preserved when its creation time differs'

    Reset-MockProcesses
    Add-MockProcess -Id 100 -ParentId 0 -CreatedMinutes 0
    Add-MockProcess -Id 200 -ParentId 100 -CreatedMinutes 10
    $record = New-MockRecord 100
    $service = New-MockRecord 200
    $service.Executable = 'C:\not-the-recorded-service.exe'
    $record | Add-Member -NotePropertyName Service -NotePropertyValue $service
    $rejected = $false
    try { Stop-PlatformProcess -Record $record -ProjectRoot $projectRoot }
    catch { $rejected = $true }
    Assert-Mock $rejected 'Saved service executable mismatch rejects termination'
    Assert-StopOrder @() 'Invalid saved service prevents stopping any process'

    Reset-MockProcesses
    Add-MockProcess -Id 100 -ParentId 0 -CreatedMinutes 0
    Add-MockProcess -Id 500 -ParentId 999 -CreatedMinutes 10
    $script:mockListenerOwner = 500
    $record = New-MockRecord 100
    $rejected = $false
    try { Save-PlatformServiceRecord -Record $record -Port 8100 -ProjectRoot $projectRoot }
    catch { $rejected = $true }
    Assert-Mock $rejected 'A competing same-project listener is not claimed as this launcher service'
    Assert-Mock ($null -eq $record.Service) 'Competing service is not recorded for later termination'
    Assert-StopOrder @() 'Competing listener remains untouched'

    Reset-MockProcesses
    Add-MockProcess -Id 100 -ParentId 0 -CreatedMinutes 0
    Add-MockProcess -Id 200 -ParentId 100 -CreatedMinutes 10
    $script:mockListenerOwner = 200
    $record = New-MockRecord 100
    Save-PlatformServiceRecord -Record $record -Port 8100 -ProjectRoot $projectRoot
    Assert-Mock ($record.Service.Id -eq 200) 'A verified direct service child is saved'

    Write-Output 'All in-memory platform process checks passed; no native process was started or stopped.'
}
