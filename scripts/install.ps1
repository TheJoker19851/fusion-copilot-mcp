[CmdletBinding()]
param(
    [string]$FusionAddInsDirectory,
    [string]$SidecarDirectory,
    [switch]$SkipSidecar
)

$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot

if ([string]::IsNullOrWhiteSpace($FusionAddInsDirectory)) {
    $FusionAddInsDirectory = Join-Path $env:APPDATA 'Autodesk\Autodesk Fusion 360\API\AddIns'
}
if ([string]::IsNullOrWhiteSpace($SidecarDirectory)) {
    $SidecarDirectory = Join-Path $env:LOCALAPPDATA 'FusionCopilotMCP\sidecar'
}

$fusionRoot = [IO.Path]::GetFullPath($FusionAddInsDirectory)
$targetAddin = [IO.Path]::GetFullPath((Join-Path $fusionRoot 'FusionCopilotMCP'))
if (-not $targetAddin.StartsWith($fusionRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Resolved Fusion add-in target escaped the configured add-ins directory.'
}

$builtAddin = & (Join-Path $PSScriptRoot 'build_addin.ps1')
New-Item -ItemType Directory -Force -Path $targetAddin | Out-Null
Copy-Item -Path (Join-Path $builtAddin '*') -Destination $targetAddin -Recurse -Force

$result = [ordered]@{
    addinPath = $targetAddin
    sidecarPath = $null
    codexConfigSnippet = $null
}

if (-not $SkipSidecar) {
    $sidecarPath = [IO.Path]::GetFullPath($SidecarDirectory)
    New-Item -ItemType Directory -Force -Path $sidecarPath | Out-Null
    $venvPath = Join-Path $sidecarPath '.venv'
    if (-not (Test-Path -LiteralPath (Join-Path $venvPath 'Scripts\python.exe'))) {
        python -m venv $venvPath
    }
    $python = Join-Path $venvPath 'Scripts\python.exe'
    & $python -m pip install --upgrade $repositoryRoot
    $command = Join-Path $venvPath 'Scripts\fusion-copilot-mcp.exe'
    $escapedCommand = $command.Replace('\', '\\')
    $snippet = @"
[mcp_servers.fusion_copilot]
command = "$escapedCommand"
args = ["--transport", "stdio"]
startup_timeout_sec = 20
tool_timeout_sec = 360
"@
    $snippetPath = Join-Path $env:LOCALAPPDATA 'FusionCopilotMCP\codex-config.toml'
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $snippetPath) | Out-Null
    Set-Content -LiteralPath $snippetPath -Value $snippet -Encoding utf8
    $result.sidecarPath = $sidecarPath
    $result.codexConfigSnippet = $snippetPath
}

[pscustomobject]$result
