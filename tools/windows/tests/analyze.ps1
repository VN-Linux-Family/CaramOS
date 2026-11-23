# PSScriptAnalyzer checks for caramos-assess.ps1: compatibility with Windows PowerShell 5.1
# (syntax, commands and .NET types, using the Windows 10 PowerShell 5.1 profile shipped with
# PSScriptAnalyzer) and the default rule set. Run in Docker:
#
#   docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp \
#     -v "$PWD/tools/windows:/work:ro" -v "$SCRATCH/psmodules:/psmodules" \
#     mcr.microsoft.com/powershell:7.4-ubuntu-22.04 \
#     pwsh -NoProfile -File /work/tests/analyze.ps1 -ModuleDirectory /psmodules
#
# Without a module directory that already holds PSScriptAnalyzer it is installed from PSGallery.
param([string]$ModuleDirectory = '', [string]$Version = '1.25.0')

$ErrorActionPreference = 'Stop'
$target = Join-Path (Split-Path -Parent $PSScriptRoot) 'caramos-assess.ps1'

if ($ModuleDirectory) {
    $env:PSModulePath = $ModuleDirectory + [System.IO.Path]::PathSeparator + $env:PSModulePath
    if (-not (Get-Module -ListAvailable -Name PSScriptAnalyzer | Where-Object { $_.Version -eq $Version })) {
        Save-Module -Name PSScriptAnalyzer -RequiredVersion $Version -Path $ModuleDirectory -Repository PSGallery -Force
    }
}
elseif (-not (Get-Module -ListAvailable -Name PSScriptAnalyzer)) {
    Install-Module -Name PSScriptAnalyzer -RequiredVersion $Version -Scope CurrentUser -Repository PSGallery -Force
}
Import-Module PSScriptAnalyzer -RequiredVersion $Version
Write-Host ('PSScriptAnalyzer ' + (Get-Module PSScriptAnalyzer).Version)

$profile51 = 'win-48_x64_10.0.17763.0_5.1.17763.316_x64_4.0.30319.42000_framework'
$compatibility = @{
    IncludeRules = @('PSUseCompatibleSyntax', 'PSUseCompatibleCommands', 'PSUseCompatibleTypes')
    Rules        = @{
        PSUseCompatibleSyntax   = @{ Enable = $true; TargetVersions = @('3.0', '4.0', '5.1') }
        PSUseCompatibleCommands = @{ Enable = $true; TargetProfiles = @($profile51) }
        PSUseCompatibleTypes    = @{ Enable = $true; TargetProfiles = @($profile51) }
    }
}

function Show-Findings {
    param([string]$Title, [object[]]$Findings)
    Write-Host ''
    Write-Host ('== ' + $Title + ': ' + @($Findings).Count + ' finding(s)')
    foreach ($finding in $Findings) {
        Write-Host ('{0} {1} line {2}: {3}' -f $finding.Severity, $finding.RuleName, $finding.Line, $finding.Message)
    }
}

$compat = @(Invoke-ScriptAnalyzer -Path $target -Settings $compatibility)
Show-Findings -Title ('Compatibility (syntax 3.0/4.0/5.1, commands and types for ' + $profile51 + ')') -Findings $compat

$default = @(Invoke-ScriptAnalyzer -Path $target -Severity @('Error', 'Warning', 'Information'))
Show-Findings -Title 'Default rules' -Findings $default

if ($compat.Count -gt 0) { exit 1 }
exit 0
