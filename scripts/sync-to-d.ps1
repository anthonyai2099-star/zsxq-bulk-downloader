# 把工作区里导出的文件搬到 D 盘长期目录，并合并清单。
# 用法：pwsh -File scripts\sync-to-d.ps1
#      pwsh -File scripts\sync-to-d.ps1 -Source "D:\...\_exports\zsxq\系统技术" -Target "D:\知识星球下载\系统技术"

param(
    [string]$Source = "D:\CLAUDE-CODE\Text\_exports\zsxq\系统技术",
    [string]$Target = "D:\知识星球下载\系统技术"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $Source)) {
    Write-Host "源目录不存在，跳过：$Source"
    exit 0
}

New-Item -ItemType Directory -Path $Target -Force | Out-Null

# 只搬文件，不删除目标里已有的同名文件以外的任何东西
$copied = 0
Get-ChildItem $Source -Recurse -File | ForEach-Object {
    $rel = $_.FullName.Substring($Source.Length).TrimStart('\')
    $dest = Join-Path $Target $rel
    $destDir = Split-Path $dest -Parent
    if (-not (Test-Path $destDir)) { New-Item -ItemType Directory -Path $destDir -Force | Out-Null }
    Move-Item $_.FullName $dest -Force
    $copied++
}
Write-Host "已搬运 $copied 个文件 → $Target"

# 合并 _manifest.json：按 (folder, name) 去重，新状态覆盖旧状态
$srcManifest = Join-Path $Source "_manifest.json"
$dstManifest = Join-Path $Target "_manifest.json"
if (Test-Path $srcManifest) {
    $merged = @{}
    if (Test-Path $dstManifest) {
        foreach ($row in (Get-Content $dstManifest -Raw -Encoding UTF8 | ConvertFrom-Json)) {
            $merged["$($row.folder)|$($row.name)"] = $row
        }
    }
    foreach ($row in (Get-Content $srcManifest -Raw -Encoding UTF8 | ConvertFrom-Json)) {
        $merged["$($row.folder)|$($row.name)"] = $row
    }
    $merged.Values | Sort-Object folder, name | ConvertTo-Json -Depth 5 |
        Set-Content $dstManifest -Encoding UTF8
    Write-Host "清单已合并：$dstManifest（$($merged.Count) 条）"
}

# 清理空目录
Get-ChildItem $Source -Recurse -Directory |
    Sort-Object FullName -Descending |
    Where-Object { -not (Get-ChildItem $_.FullName -Force) } |
    Remove-Item -Force -ErrorAction SilentlyContinue
