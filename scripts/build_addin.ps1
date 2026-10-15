[CmdletBinding()]
param(
    [string]$Destination
)

$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$source = Join-Path $repositoryRoot 'fusion_addin\FusionCopilotMCP'
if ([string]::IsNullOrWhiteSpace($Destination)) {
    $Destination = Join-Path $repositoryRoot 'dist\FusionCopilotMCP'
}

$destinationPath = [IO.Path]::GetFullPath($Destination)
$repositoryPath = [IO.Path]::GetFullPath($repositoryRoot)
if (-not $destinationPath.StartsWith($repositoryPath, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'The add-in build destination must remain inside the repository.'
}

New-Item -ItemType Directory -Force -Path $destinationPath | Out-Null
Copy-Item -LiteralPath (Join-Path $source 'FusionCopilotMCP.py') -Destination $destinationPath -Force
Copy-Item -LiteralPath (Join-Path $source 'FusionCopilotMCP.manifest') -Destination $destinationPath -Force
Copy-Item -LiteralPath (Join-Path $source 'fusion_adapter.py') -Destination $destinationPath -Force
Copy-Item -LiteralPath (Join-Path $source 'palette.html') -Destination $destinationPath -Force

$vendorDestination = Join-Path $destinationPath 'vendor\fusion_copilot'
New-Item -ItemType Directory -Force -Path $vendorDestination | Out-Null
$vendorFiles = @(
    '__init__.py',
    'addin_bridge_server.py',
    'security_settings.py',
    'task_contract.py',
    'task_controller.py'
)
foreach ($file in $vendorFiles) {
    Copy-Item -LiteralPath (Join-Path $repositoryRoot "fusion_copilot\$file") -Destination $vendorDestination -Force
}

Write-Output $destinationPath
