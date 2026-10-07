param([switch]$RemoveArchive)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Net.Http
$projectRoot = [System.IO.Path]::GetFullPath($PSScriptRoot)
$rootPrefix = $projectRoot.TrimEnd([char[]]@('\', '/')) + [System.IO.Path]::DirectorySeparatorChar

function Get-SafeDataPath([string]$RelativePath) {
    if ([System.IO.Path]::IsPathRooted($RelativePath) -or $RelativePath -match '(^|[\\/])\.\.([\\/]|$)' -or
        $RelativePath -match ':') { throw '数据路径不安全。' }
    $candidate = [System.IO.Path]::GetFullPath((Join-Path $projectRoot $RelativePath))
    if (-not $candidate.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw '数据路径超出项目目录。'
    }
    $cursor = $candidate
    while ($cursor -and $cursor.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        if (Test-Path -LiteralPath $cursor) {
            $item = Get-Item -LiteralPath $cursor -Force
            if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
                throw '数据路径包含链接或目录联接，请使用普通项目目录。'
            }
        }
        $cursor = [System.IO.Path]::GetDirectoryName($cursor)
    }
    return $candidate
}

$archive = Get-SafeDataPath '.downloads/tcmp-300-release.tar.gz'
$imageRoot = Get-SafeDataPath 'TCMP-300/data/author_tcmp_300/images'
$expectedBytes = [long]12820492346
$expectedSha256 = 'f3d32fb003cccf817c735aaa0978a5381058aa77ec5d410a818b720b048d5739'
$source = 'https://huggingface.co/datasets/anzhulin/tcmp-300/resolve/7613f038f48e3ecc84076913a2f3bcd52599b0f2/tcmp-300-release.tar.gz'
Get-Command tar -ErrorAction Stop | Out-Null
New-Item -ItemType Directory -Path ([System.IO.Path]::GetDirectoryName($archive)) -Force | Out-Null
if (-not (Test-Path -LiteralPath $archive -PathType Leaf)) {
    Write-Output '正在下载作者数据集（12.82 GB）；解压时建议至少有 27 GB 可用空间。'
    $partial = $archive + '.download-' + [Guid]::NewGuid().ToString('N') + '.part'
    $client = [System.Net.Http.HttpClient]::new()
    $client.Timeout = [TimeSpan]::FromHours(24)
    $response = $null
    $incoming = $null
    $outgoing = $null
    try {
        $response = $client.GetAsync($source, [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
        if (-not $response.IsSuccessStatusCode) { throw "数据下载失败（HTTP $([int]$response.StatusCode)）。" }
        $incoming = $response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
        $outgoing = [System.IO.File]::Open($partial, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
        $incoming.CopyTo($outgoing)
        $outgoing.Dispose(); $outgoing = $null
        if ((Get-Item -LiteralPath $partial).Length -ne $expectedBytes) { throw '下载文件大小校验失败。' }
        if ((Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash -ne $expectedSha256) { throw '下载文件 SHA-256 校验失败。' }
        Get-SafeDataPath '.downloads/tcmp-300-release.tar.gz' | Out-Null
        Move-Item -LiteralPath $partial -Destination $archive
    } finally {
        if ($outgoing) { $outgoing.Dispose() }
        if ($incoming) { $incoming.Dispose() }
        if ($response) { $response.Dispose() }
        $client.Dispose()
        if (Test-Path -LiteralPath $partial) { Remove-Item -LiteralPath $partial -Force }
    }
} else {
    Write-Output '正在校验已有作者数据压缩包。'
    if ((Get-Item -LiteralPath $archive).Length -ne $expectedBytes -or
        (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $expectedSha256) {
        throw '已有压缩包大小或 SHA-256 不符；请检查 .downloads/tcmp-300-release.tar.gz 后重试。'
    }
}

Write-Output '正在检查压缩包目录；这一步需要完整读取压缩包。'
$members = @(& tar -tzf $archive)
if ($LASTEXITCODE -ne 0 -or -not $members.Count) { throw '无法列出作者压缩包内容。' }
$hasTrain = $false
$hasVal = $false
foreach ($member in $members) {
    $entry = $member -replace '^\./', ''
    if ([System.IO.Path]::IsPathRooted($entry) -or $entry -match ':' -or
        $entry -match '(^|[\\/])\.\.([\\/]|$)') { throw '压缩包包含超出目标目录的路径。' }
    if ($entry.StartsWith('tcmp-300/train/')) { $hasTrain = $true }
    if ($entry.StartsWith('tcmp-300/val/')) { $hasVal = $true }
}
if (-not $hasTrain -or -not $hasVal) { throw '压缩包目录结构与固定版本不符，预期为 tcmp-300/train 和 tcmp-300/val。' }
Get-SafeDataPath 'TCMP-300/data/author_tcmp_300/images' | Out-Null
New-Item -ItemType Directory -Path $imageRoot -Force | Out-Null
# The verified author archive has tcmp-300/ at its root. Extract that subtree only;
# root-level macOS metadata is excluded and catalogue CSV files remain separate.
Write-Output '目录检查通过，正在恢复 tcmp-300/train 与 tcmp-300/val。'
& tar -xzf $archive -C $imageRoot 'tcmp-300'
if ($LASTEXITCODE -ne 0) { throw '数据集解压失败；已校验的压缩包保留，可重新运行。' }
$files = @(Get-ChildItem -LiteralPath (Join-Path $imageRoot 'tcmp-300') -File -Recurse)
if ($files.Count -ne 52172) { throw "解压后的文件数为 $($files.Count)，预期 52172；请检查目录中的额外或缺失文件。" }
Write-Output '作者数据集恢复完成，共 52,172 个文件（含 83 个 GIF），可用于训练的非 GIF 图片为 52,089 张。'
if ($RemoveArchive) {
    Get-SafeDataPath '.downloads/tcmp-300-release.tar.gz' | Out-Null
    Remove-Item -LiteralPath $archive -Force
    Write-Output '已按 -RemoveArchive 选项删除通过校验的压缩包。'
} else {
    Write-Output '压缩包保留于 .downloads/tcmp-300-release.tar.gz；如需节省空间，下次运行可加 -RemoveArchive。'
}
