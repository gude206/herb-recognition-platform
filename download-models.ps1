param([switch]$All)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Net.Http
$projectRoot = [System.IO.Path]::GetFullPath($PSScriptRoot)
$rootPrefix = $projectRoot.TrimEnd([char[]]@('\', '/')) + [System.IO.Path]::DirectorySeparatorChar
$manifest = Get-Content -LiteralPath (Join-Path $projectRoot 'MODEL_MANIFEST.json') -Raw | ConvertFrom-Json
if ($manifest.schema_version -ne 1 -or $manifest.repository -ne 'gude206/herb-recognition-platform' -or
    $manifest.release_tag -ne 'models-20261007') { throw '模型清单仓库、版本或格式不正确。' }

function Get-SafeModelPath([string]$RelativePath) {
    if ([string]::IsNullOrWhiteSpace($RelativePath) -or [System.IO.Path]::IsPathRooted($RelativePath) -or
        $RelativePath -match '(^|[\\/])\.\.([\\/]|$)' -or $RelativePath -match ':') {
        throw '模型清单含不安全的相对路径。'
    }
    $candidate = [System.IO.Path]::GetFullPath((Join-Path $projectRoot $RelativePath))
    if (-not $candidate.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw '模型目标路径超出项目目录。'
    }
    $cursor = $candidate
    while ($cursor -and $cursor.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        if (Test-Path -LiteralPath $cursor) {
            $item = Get-Item -LiteralPath $cursor -Force
            if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
                throw '模型路径包含链接或目录联接，请使用普通项目目录。'
            }
        }
        $cursor = [System.IO.Path]::GetDirectoryName($cursor)
    }
    return $candidate
}

function Test-VerifiedModel([string]$Path, $Model) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
    if ((Get-Item -LiteralPath $Path).Length -ne [long]$Model.bytes) { return $false }
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash -eq $Model.sha256
}

function Get-GitHubToken {
    if ($env:GH_TOKEN) { return $env:GH_TOKEN.Trim() }
    if ($env:GITHUB_TOKEN) { return $env:GITHUB_TOKEN.Trim() }
    if (Get-Command git -ErrorAction SilentlyContinue) {
        $previousPrompt = $env:GIT_TERMINAL_PROMPT
        $credentialLines = $null
        try {
            $env:GIT_TERMINAL_PROMPT = '0'
            $credentialLines = "protocol=https`nhost=github.com`nusername=gude206`n`n" | & git credential fill 2>$null
            if ($LASTEXITCODE -eq 0) {
                foreach ($line in $credentialLines) {
                    if ($line.StartsWith('password=')) { return $line.Substring(9) }
                }
            }
        } catch { }
        finally {
            $env:GIT_TERMINAL_PROMPT = $previousPrompt
            $credentialLines = $null
        }
    }
    throw '需要私有仓库读取凭据：登录 Git Credential Manager，或在当前会话提供 GH_TOKEN / GITHUB_TOKEN。脚本不会显示或保存凭据。'
}

$selected = @($manifest.models | Where-Object { $All -or $_.default })
if (-not $selected.Count) { throw '模型清单没有可恢复的模型。' }
$pending = @(
    foreach ($model in $selected) {
        if ($model.sha256 -notmatch '^[a-fA-F0-9]{64}$' -or [long]$model.bytes -le 0 -or
            $model.asset_name -notmatch '^[a-zA-Z0-9_.-]+$') { throw '模型清单含无效校验信息。' }
        $destination = Get-SafeModelPath $model.path
        if (Test-VerifiedModel $destination $model) {
            Write-Output "已校验，跳过：$($model.path)"
        } else {
            [pscustomobject]@{ Model = $model; Destination = $destination }
        }
    }
)
if (-not $pending.Count) { Write-Output '选定模型均已恢复。'; return }

$client = [System.Net.Http.HttpClient]::new()
$client.Timeout = [TimeSpan]::FromHours(6)
$token = $null
try {
    $token = Get-GitHubToken
    $client.DefaultRequestHeaders.Authorization = [System.Net.Http.Headers.AuthenticationHeaderValue]::new('Bearer', $token)
    $client.DefaultRequestHeaders.UserAgent.ParseAdd('herb-recognition-platform-model-restorer')
    $client.DefaultRequestHeaders.Add('X-GitHub-Api-Version', '2022-11-28')
    $releaseUri = "https://api.github.com/repos/$($manifest.repository)/releases/tags/$($manifest.release_tag)"
    $request = [System.Net.Http.HttpRequestMessage]::new([System.Net.Http.HttpMethod]::Get, $releaseUri)
    $request.Headers.Accept.ParseAdd('application/vnd.github+json')
    $response = $null
    try {
        $response = $client.SendAsync($request).GetAwaiter().GetResult()
        if (-not $response.IsSuccessStatusCode) {
            throw "无法读取私有模型 Release（HTTP $([int]$response.StatusCode)），请检查仓库权限及 Release 是否已发布。"
        }
        $release = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult() | ConvertFrom-Json
    } finally { if ($response) { $response.Dispose() }; $request.Dispose() }

    foreach ($item in $pending) {
        $model = $item.Model
        $assets = @($release.assets | Where-Object name -eq $model.asset_name)
        if ($assets.Count -ne 1 -or [long]$assets[0].size -ne [long]$model.bytes) {
            throw "Release 资源缺失、重复或大小不符：$($model.asset_name)"
        }
        $destination = Get-SafeModelPath $model.path
        $parent = [System.IO.Path]::GetDirectoryName($destination)
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
        $partial = $destination + '.download-' + [Guid]::NewGuid().ToString('N') + '.part'
        $assetUri = "https://api.github.com/repos/$($manifest.repository)/releases/assets/$($assets[0].id)"
        $request = [System.Net.Http.HttpRequestMessage]::new([System.Net.Http.HttpMethod]::Get, $assetUri)
        $request.Headers.Accept.ParseAdd('application/octet-stream')
        $response = $null
        $incoming = $null
        $outgoing = $null
        try {
            Write-Output "正在恢复：$($model.path)"
            $response = $client.SendAsync($request, [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
            if (-not $response.IsSuccessStatusCode) {
                throw "模型下载失败（HTTP $([int]$response.StatusCode)）：$($model.asset_name)"
            }
            $incoming = $response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
            $outgoing = [System.IO.File]::Open($partial, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
            $incoming.CopyTo($outgoing)
            $outgoing.Dispose(); $outgoing = $null
            if (-not (Test-VerifiedModel $partial $model)) { throw "模型大小或 SHA-256 校验失败：$($model.asset_name)" }
            Get-SafeModelPath $model.path | Out-Null
            Move-Item -LiteralPath $partial -Destination $destination -Force
            Write-Output "恢复并校验完成：$($model.path)"
        } finally {
            if ($outgoing) { $outgoing.Dispose() }
            if ($incoming) { $incoming.Dispose() }
            if ($response) { $response.Dispose() }
            $request.Dispose()
            if (Test-Path -LiteralPath $partial) { Remove-Item -LiteralPath $partial -Force }
        }
    }
} finally {
    $client.DefaultRequestHeaders.Authorization = $null
    $client.Dispose()
    $token = $null
}
Write-Output '选定模型均已恢复，文件大小与 SHA-256 校验通过。'
