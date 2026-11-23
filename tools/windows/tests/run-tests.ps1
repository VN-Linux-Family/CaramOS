# Tests for caramos-assess.ps1. They run on PowerShell 7 in Docker (Linux), with every
# Windows-only probe replaced by a mock; folder statistics run for real on a fake profile.
#
#   docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp \
#     -v "$PWD/tools/windows:/work:ro" -v "$SCRATCH:/out" \
#     mcr.microsoft.com/powershell:7.4-ubuntu-22.04 \
#     pwsh -NoProfile -File /work/tests/run-tests.ps1 -OutDir /out
#
# Run it as a normal user (not root): one test needs a folder that cannot be read.
param([string]$OutDir = '')

Set-StrictMode -Version 1.0
$ErrorActionPreference = 'Stop'

$TestsDir = $PSScriptRoot
$ToolDir = Split-Path -Parent $TestsDir
$ScriptPath = Join-Path $ToolDir 'caramos-assess.ps1'
$TablePath = Join-Path $ToolDir 'caramos-assess-programs.json'
$CmdPath = Join-Path $ToolDir 'caramos-assess.cmd'
$FixtureDir = Join-Path $TestsDir 'fixtures'
if (-not $OutDir) { $OutDir = Join-Path ([System.IO.Path]::GetTempPath()) 'caramos-assess-out' }
$null = New-Item -ItemType Directory -Force -Path $OutDir
$WorkRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('caramos-assess-test-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
$null = New-Item -ItemType Directory -Force -Path $WorkRoot

$script:Passed = 0
$script:Failed = 0
$script:FailedNames = New-Object System.Collections.Generic.List[string]

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw ('expected: ' + $Message) }
}

function Assert-Equal {
    param($Expected, $Actual, [string]$Message)
    if (($null -eq $Expected) -ne ($null -eq $Actual) -or -not ($Expected -eq $Actual)) {
        throw ($Message + ': expected [' + $Expected + '] but got [' + $Actual + ']')
    }
}

function Assert-Contains {
    param([string]$Text, [string]$Needle, [string]$Message)
    if ($Text.IndexOf($Needle, [System.StringComparison]::Ordinal) -lt 0) { throw ($Message + ': missing [' + $Needle + ']') }
}

function Assert-NotContains {
    param([string]$Text, [string]$Needle, [string]$Message)
    if ($Text.IndexOf($Needle, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) { throw ($Message + ': found [' + $Needle + ']') }
}

function Invoke-Test {
    param([string]$Name, [scriptblock]$Body)
    try {
        & $Body
        $script:Passed++
        Write-Host ('PASS  ' + $Name)
    }
    catch {
        $script:Failed++
        $script:FailedNames.Add($Name)
        $where = ''
        if ($_.InvocationInfo) { $where = ($_.InvocationInfo.PositionMessage -split "`n")[0] }
        Write-Host ('FAIL  ' + $Name + "`n      " + $_.Exception.Message + "`n      " + $where)
    }
}

function Read-Fixture {
    param([string]$Name)
    $text = [System.IO.File]::ReadAllText((Join-Path $FixtureDir $Name), [System.Text.Encoding]::UTF8)
    return , (ConvertFrom-Json -InputObject $text)
}

function Reset-Directory {
    param([string]$Path)
    if (-not $Path.StartsWith($OutDir) -and -not $Path.StartsWith($WorkRoot)) { throw ('refusing to reset ' + $Path) }
    if (Test-Path -LiteralPath $Path) { Remove-Item -LiteralPath $Path -Recurse -Force }
    $null = New-Item -ItemType Directory -Force -Path $Path
}

function New-File {
    param([string]$Path, [long]$Size)
    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent)) { $null = New-Item -ItemType Directory -Force -Path $parent }
    $stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::Create)
    try { $stream.SetLength($Size) } finally { $stream.Dispose() }
}

# ---------------------------------------------------------------------------
# Static checks on the files themselves
# ---------------------------------------------------------------------------

Invoke-Test 'caramos-assess.ps1 is UTF-8 with BOM' {
    $bytes = [System.IO.File]::ReadAllBytes($ScriptPath)
    Assert-True ($bytes.Length -gt 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) 'EF BB BF at the start'
    $strict = New-Object System.Text.UTF8Encoding -ArgumentList $false, $true
    $text = $strict.GetString($bytes, 3, $bytes.Length - 3)
    Assert-Contains $text 'Khảo sát chuyển sang CaramOS' 'Vietnamese literal decodes'
}

Invoke-Test 'caramos-assess.cmd is ASCII, CRLF, runs the script with Bypass and pauses' {
    $bytes = [System.IO.File]::ReadAllBytes($CmdPath)
    foreach ($b in $bytes) { if ($b -gt 127) { throw 'non-ASCII byte in .cmd' } }
    $text = [System.Text.Encoding]::ASCII.GetString($bytes)
    Assert-Contains $text 'powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0caramos-assess.ps1" %*' 'launcher line'
    Assert-True ($text -match '(?m)^pause\r$') 'pause line'
    Assert-True (-not ($text -match "[^\r]`n")) 'every line ends with CRLF'
}

Invoke-Test 'comment-based help is readable' {
    $help = Get-Help $ScriptPath -Full
    Assert-Contains ([string]$help.Synopsis) 'Khảo sát' 'synopsis'
    $names = @($help.parameters.parameter | ForEach-Object { $_.name })
    foreach ($name in @('OutputDirectory', 'NoOpen', 'HideComputerName')) { Assert-True ($names -contains $name) ('parameter ' + $name) }
    Assert-True (@($help.examples.example).Count -ge 2) 'examples'
}

Invoke-Test 'script parses and uses no PowerShell 6/7-only syntax (AST check)' {
    $tokens = $null
    $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile($ScriptPath, [ref]$tokens, [ref]$errors)
    Assert-Equal 0 @($errors).Count 'parse errors'
    $L = 'System.Management.Automation.Language'
    $bad = @($ast.FindAll({
                param($n)
                ($n.GetType().FullName -eq "$L.TernaryExpressionAst") -or
                ($n.GetType().FullName -eq "$L.PipelineChainAst") -or
                ($n -is [System.Management.Automation.Language.BinaryExpressionAst] -and [string]$n.Operator -eq 'QuestionQuestion') -or
                ($n -is [System.Management.Automation.Language.AssignmentStatementAst] -and [string]$n.Operator -eq 'QuestionQuestionEquals') -or
                ($n -is [System.Management.Automation.Language.MemberExpressionAst] -and $n.NullConditional) -or
                ($n -is [System.Management.Automation.Language.IndexExpressionAst] -and $n.NullConditional) -or
                ($n -is [System.Management.Automation.Language.VariableExpressionAst] -and @('IsWindows', 'IsLinux', 'IsMacOS', 'IsCoreCLR') -contains $n.VariablePath.UserPath) -or
                ($n -is [System.Management.Automation.Language.TypeDefinitionAst]) -or
                ($n -is [System.Management.Automation.Language.UsingStatementAst])
            }, $true))
    Assert-Equal 0 $bad.Count ('PS6+/PS5-only constructs: ' + (($bad | ForEach-Object { $_.Extent.Text }) -join ' | '))
    $newerCommands = @('Get-Error', 'Test-Json', 'Join-String', 'Get-Uptime', 'ConvertFrom-Markdown', 'Remove-Service', 'Get-ComputerInfo')
    $newerParameters = @('Parallel', 'AsHashtable', 'AsByteStream', 'NoEnumerate', 'AdditionalChildPath', 'SkipCertificateCheck', 'Depth')
    foreach ($command in $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.CommandAst] }, $true)) {
        $name = $command.GetCommandName()
        Assert-True ($newerCommands -notcontains $name) ('no ' + $name)
        $positional = 0
        foreach ($element in ($command.CommandElements | Select-Object -Skip 1)) {
            if ($element -is [System.Management.Automation.Language.CommandParameterAst]) {
                Assert-True ($newerParameters -notcontains $element.ParameterName) ('no -' + $element.ParameterName + ' on ' + $name)
            }
            else { $positional++ }
        }
        if ($name -eq 'Join-Path') { Assert-True ($positional -le 2) ('Join-Path with one child only: ' + $command.Extent.Text) }
        if ($name -eq 'Out-File' -or $name -eq 'Set-Content' -or $name -eq 'Add-Content') { throw ('file written with ' + $name + ' (encoding differs between versions)') }
    }
}

Invoke-Test 'script makes no network calls and opens only the report' {
    $text = [System.IO.File]::ReadAllText($ScriptPath)
    $patterns = @('Invoke-WebRequest', 'Invoke-RestMethod', '\biwr\b', '\birm\b', '\bcurl\b', '\bwget\b', 'WebClient', 'WebRequest', 'HttpClient',
        'System\.Net\b', 'Net\.Sockets', 'Resolve-DnsName', 'Test-Connection', 'Test-NetConnection', 'Start-BitsTransfer', 'bitsadmin',
        'Send-MailMessage', 'New-PSSession', 'Enter-PSSession', 'Invoke-Command', 'DownloadString', 'DownloadFile', 'UploadString',
        '\bnslookup\b', '\bping\b', 'certutil', '(?<![A-Za-z])-ComputerName\b', 'New-CimSession', 'OpenRemoteBaseKey', 'Add-Type', 'Invoke-Expression', '\biex\b')
    foreach ($pattern in $patterns) {
        if ($text -match $pattern) { throw ('network or dynamic-code pattern found: ' + $pattern + ' -> ' + $Matches[0]) }
    }
    $starts = [regex]::Matches($text, 'Start-Process[^\r\n]*')
    Assert-Equal 1 $starts.Count 'one Start-Process'
    Assert-Contains $starts[0].Value 'Start-Process -FilePath $saved.HtmlPath' 'Start-Process opens the saved report'
}

# ---------------------------------------------------------------------------
# Load the script without running it, then replace the Windows probes.
# ---------------------------------------------------------------------------

. $ScriptPath
$CaramosConfig.Quiet = $true

$MockState = @{
    Fail         = @{}
    Entries      = 'uninstall-entries.json'
    ComputerName = 'PC-KETOAN-01'
    Known        = $null
    Desktop      = $null
    System       = 'system.json'
}

function Test-MockFailure {
    param([string]$Name)
    if ($MockState.Fail.ContainsKey($Name)) { throw ('mock failure: ' + $Name) }
}
function Get-CaramosComputerName { Test-MockFailure 'computer'; return $MockState.ComputerName }
function Get-CaramosDesktopPath { return $MockState.Desktop }
function Get-CaramosUninstallEntries { Test-MockFailure 'programs'; return , (Read-Fixture $MockState.Entries) }
function Get-CaramosPrinterData { Test-MockFailure 'printers'; return , (Read-Fixture 'printers.json') }
function Get-CaramosPnpDevices { Test-MockFailure 'pnp'; return , (Read-Fixture 'pnp-devices.json') }
function Get-CaramosOfficeRegistryData { Test-MockFailure 'office'; return (Read-Fixture 'office.json') }
function Get-CaramosSystemInfo { Test-MockFailure 'system'; return (Read-Fixture $MockState.System) }
function Get-CaramosKnownFolders { Test-MockFailure 'folders'; return $MockState.Known }
function Get-CaramosFontData { Test-MockFailure 'fonts'; return (Read-Fixture 'fonts.json') }

# A fake profile. Every name contains "BiMat" (secret) so the privacy test can look for it.
function New-FakeProfile {
    param([string]$Root)
    $userRoot = Join-Path $Root 'Users'
    $profileRoot = Join-Path $userRoot 'nguyenvana'
    $documents = Join-Path $profileRoot 'Documents'
    $desktop = Join-Path $profileRoot 'Desktop'
    $pictures = Join-Path $profileRoot 'Pictures'
    $downloads = Join-Path (Join-Path $Root 'O-D') 'Downloads'
    $zalo = Join-Path $documents 'Zalo Received Files'
    $outside = Join-Path $Root 'ngoai-BiMat'
    New-File (Join-Path $desktop 'BaoCao-Quy3-NguyenVanA-BiMat.xlsm') 1000
    New-File (Join-Path $desktop 'ghi-chu-rieng-tu-BiMat.txt') 500
    New-File (Join-Path $documents 'HopDong-KhachHangVIP-BiMat.docm') 2000
    New-File (Join-Path $documents 'BangLuong-2025-BiMat.xls') 3000
    New-File (Join-Path $documents 'CongVan-cu-BiMat.doc') 1500
    $sub = Join-Path $documents 'ThuMucCon-BiMat'
    $deep = Join-Path $sub 'Sau-Hon-BiMat'
    New-File (Join-Path $deep 'MauPhieu-BiMat.xltm') 100
    New-File (Join-Path $deep 'ThuVien-BiMat.xlam') 50
    New-File (Join-Path $sub 'SoLieu-BiMat.xlsb') 70
    New-File (Join-Path (Join-Path $documents 'Outlook Files') 'Thu-Rieng-BiMat.pst') 4096
    New-File (Join-Path $zalo 'Anh-CCCD-NguyenVanA-BiMat.jpg') 800
    New-File (Join-Path $zalo 'BaoGia-BiMat.xlsm') 300
    New-File (Join-Path $outside 'ngoai-BiMat.xlsm') 9999
    $null = New-Item -ItemType SymbolicLink -Path (Join-Path $documents 'vong-lap-BiMat') -Target $documents
    $null = New-Item -ItemType SymbolicLink -Path (Join-Path $documents 'lien-ket-ngoai-BiMat') -Target $outside
    $null = New-Item -ItemType SymbolicLink -Path (Join-Path $documents 'lien-ket-tep-BiMat.xlsm') -Target (Join-Path $desktop 'BaoCao-Quy3-NguyenVanA-BiMat.xlsm')
    $locked = Join-Path $documents 'KhongDocDuoc-BiMat'
    New-File (Join-Path $locked 'BiMat-trong.docm') 777
    & chmod 000 $locked
    New-File (Join-Path $pictures 'IMG-GiaDinh-BiMat.jpg') 5000
    New-File (Join-Path $downloads 'setup-PhanMem-BiMat.exe') 10000
    $zaloApp = Join-Path (Join-Path (Join-Path $profileRoot 'AppData') 'Local') 'ZaloPC'
    New-File (Join-Path $zaloApp 'cache-BiMat.dat') 12345
    New-File (Join-Path (Join-Path $zaloApp 'sub-BiMat') 'tin-nhan-BiMat.db') 655
    $outlook = Join-Path (Join-Path (Join-Path (Join-Path $profileRoot 'AppData') 'Local') 'Microsoft') 'Outlook'
    New-File (Join-Path $outlook 'nguyenvana@congty.vn-BiMat.ost') 8192

    $known = [ordered]@{
        Folders     = @(
            [ordered]@{ Key = 'Desktop'; Path = $desktop },
            [ordered]@{ Key = 'Documents'; Path = $documents },
            [ordered]@{ Key = 'Pictures'; Path = $pictures },
            [ordered]@{ Key = 'Downloads'; Path = $downloads },
            [ordered]@{ Key = 'Music'; Path = $pictures },
            [ordered]@{ Key = 'Videos'; Path = (Join-Path $profileRoot 'Videos-khong-co') },
            [ordered]@{ Key = 'ZaloReceived'; Path = $zalo }
        )
        ZaloApp     = @($zaloApp, (Join-Path $profileRoot 'khong-co-ZaloData'))
        Outlook     = @($outlook)
        CloudRoots  = @((Join-Path $profileRoot 'OneDrive'))
        ProfileRoot = $profileRoot
    }
    $secrets = New-Object System.Collections.Generic.List[string]
    foreach ($item in (Get-ChildItem -LiteralPath $Root -Recurse -Force -ErrorAction SilentlyContinue)) {
        if ($item.Name -match 'BiMat') { $secrets.Add($item.Name) }
    }
    foreach ($extra in @('BiMat-trong.docm', 'nguyenvana', 'NguyenVanA', 'congty.vn', $Root, $profileRoot)) { $secrets.Add($extra) }
    return [ordered]@{ Known = $known; Secrets = $secrets.ToArray(); Locked = $locked; Root = $Root }
}

$Fake = New-FakeProfile -Root (Join-Path $WorkRoot 'fake')
$MockState.Known = $Fake.Known

Invoke-Test 'advice table parses, is complete, and every regex compiles' {
    $text = [System.IO.File]::ReadAllText($TablePath, (New-Object System.Text.UTF8Encoding -ArgumentList $false, $true))
    $data = ConvertFrom-Json -InputObject $text
    $kinds = @('windows-only', 'alternative', 'available', 'not-needed', 'check')
    $ids = @{}
    $options = [System.Text.RegularExpressions.RegexOptions]'IgnoreCase, CultureInvariant'
    foreach ($entry in $data.programs) {
        foreach ($field in @('id', 'name', 'kind', 'advice')) { Assert-True (-not [string]::IsNullOrWhiteSpace([string]$entry.$field)) ($field + ' on ' + $entry.id) }
        Assert-True ($kinds -contains $entry.kind) ('kind of ' + $entry.id)
        Assert-True (-not $ids.ContainsKey($entry.id)) ('unique id ' + $entry.id)
        $ids[$entry.id] = $true
        $patterns = @()
        foreach ($field in @('match', 'publisher', 'exclude')) {
            if ($entry.PSObject.Properties[$field]) { $patterns += @($entry.$field) }
        }
        Assert-True ($patterns.Count -gt 0) ('patterns on ' + $entry.id)
        foreach ($pattern in $patterns) { $null = New-Object System.Text.RegularExpressions.Regex -ArgumentList $pattern, $options }
    }
    foreach ($entry in $data.devices) {
        foreach ($pattern in @($entry.match) + @($entry.exclude | Where-Object { $_ })) { $null = New-Object System.Text.RegularExpressions.Regex -ArgumentList $pattern, $options }
    }
    Assert-True (@($data.programs).Count -ge 60) 'at least 60 program entries'
    $loaded = Import-CaramosAdviceTable -Path $TablePath
    Assert-Equal 0 @($loaded.Problems).Count ('regex problems: ' + (@($loaded.Problems) -join ', '))
    foreach ($phrase in @('đạt chuẩn', 'đủ bản quyền', 'tương thích 100', 'RDP Wrapper', 'crack', 'Chào mừng', 'miễn phí hoàn toàn')) {
        Assert-NotContains $text $phrase 'banned phrase in advice table'
    }
}

Invoke-Test 'advice table covers the programs the survey must know' {
    $table = Import-CaramosAdviceTable -Path $TablePath
    $expect = [ordered]@{
        'MISA SME.NET 2023' = 'windows-only'; 'MISA Mimosa.NET 2022' = 'windows-only'; 'HTKK' = 'windows-only'; 'iTaxViewer 2.4' = 'windows-only'
        'UltraViewer version 6.6' = 'alternative'; 'TeamViewer' = 'alternative'; 'AnyDesk' = 'alternative'
        'UniKey 4.6 RC2' = 'not-needed'; 'EVKey' = 'not-needed'; 'Vietkey 2007' = 'not-needed'
        'Zalo' = 'available'; 'Google Chrome' = 'available'; 'Cốc Cốc' = 'available'; 'CocCoc' = 'available'; 'Microsoft Edge' = 'available'
        'Mozilla Firefox (x64 vi)' = 'available'; 'Brave' = 'available'; 'Foxit PDF Reader' = 'alternative'; 'Foxit Reader' = 'alternative'
        'Foxit PDF Editor' = 'check'; 'Adobe Acrobat Reader DC' = 'alternative'; 'WinRAR 7.01 (64-bit)' = 'not-needed'; '7-Zip 23.01 (x64)' = 'not-needed'
        'Microsoft Office Professional Plus 2016' = 'alternative'; 'Microsoft 365 Apps for business - vi-vn' = 'alternative'
        'WPS Office (12.2.0.13431)' = 'available'; 'LibreOffice 7.6.4.1' = 'available'; 'Zoom Workplace' = 'available'; 'Microsoft Teams' = 'available'
        'Skype version 8.110' = 'not-needed'; 'Telegram Desktop' = 'available'; 'VLC media player' = 'available'; 'K-Lite Codec Pack 18.0.5 Basic' = 'not-needed'
        'Adobe Photoshop 2024' = 'alternative'; 'CorelDRAW Graphics Suite 2021 (64-Bit)' = 'alternative'; 'AutoCAD 2020 - English' = 'windows-only'
        'Kaspersky Free' = 'not-needed'; 'Bkav Pro Internet Security' = 'not-needed'; 'Avast Free Antivirus' = 'not-needed'; 'AVG AntiVirus FREE' = 'not-needed'
        'ESET Security' = 'not-needed'; 'McAfee LiveSafe' = 'not-needed'; 'Norton 360' = 'not-needed'
        'VNPT-CA Token Manager' = 'check'; 'Viettel-CA' = 'check'; 'FPT-CA Token' = 'check'; 'BkavCA Token Manager' = 'check'; 'EasyCA' = 'check'
        'NewCA Token' = 'check'; 'CA2 Token Manager' = 'check'; 'SmartSign' = 'check'; 'Token Manager' = 'check'
        'Canon LBP2900' = 'check'; 'HP LaserJet Pro M402-M403 PCL 6' = 'check'; 'Brother MFL-Pro Suite' = 'check'; 'EPSON L3150 Series Printer Uninstall' = 'check'
        'Microsoft Visual C++ 2015-2022 Redistributable (x64) - 14.38.33135' = 'not-needed'; 'Microsoft Edge WebView2 Runtime' = 'not-needed'
        'Microsoft Office Proofing Tools 2016 - Tiếng Việt' = 'not-needed'; 'Microsoft Teams Meeting Add-in for Microsoft Office' = 'not-needed'
        'Zoom Outlook Plugin' = 'not-needed'; 'HP Support Assistant' = 'not-needed'; 'Intel(R) Graphics Driver' = 'not-needed'
        'Microsoft SQL Server 2014 (64-bit)' = 'check'; 'Microsoft SQL Server 2014 Express LocalDB' = 'not-needed'
    }
    foreach ($name in $expect.Keys) {
        $advice = Find-CaramosProgramAdvice -Program ([pscustomobject]@{ Name = $name; Publisher = '' }) -Table $table
        Assert-True ($null -ne $advice) ('advice for ' + $name)
        Assert-Equal $expect[$name] $advice.Kind ('kind for ' + $name + ' (matched ' + $advice.Id + ')')
    }
    $taxTool = Find-CaramosProgramAdvice -Program ([pscustomobject]@{ Name = 'Ứng dụng hỗ trợ quyết toán'; Publisher = 'Tổng cục Thuế' }) -Table $table
    Assert-Equal 'tax-department' $taxTool.Id 'publisher-only entry'
    Assert-Equal $null (Find-CaramosProgramAdvice -Program ([pscustomobject]@{ Name = 'Phần mềm Quản lý Thư viện ABC'; Publisher = 'Công ty ABC' }) -Table $table) 'unknown stays unknown'
}

# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------

Invoke-Test 'dot-sourcing defines the functions without running the survey' {
    Assert-True ($null -ne (Get-Command Invoke-CaramosAssessment -ErrorAction SilentlyContinue)) 'Invoke-CaramosAssessment defined'
    Assert-Equal '1.0.0' $CaramosAssessVersion 'version variable'
}

Invoke-Test 'numbers and sizes use the Vietnamese format' {
    Assert-Equal '23.456' (Format-CaramosNumber 23456) 'thousands'
    Assert-Equal '1.234.567' (Format-CaramosNumber 1234567) 'millions'
    Assert-Equal '0 MB' (Format-CaramosSize 0) 'zero'
    Assert-Equal 'dưới 1 MB' (Format-CaramosSize 500KB) 'tiny'
    Assert-Equal '1,5 MB' (Format-CaramosSize 1.5MB) 'small MB'
    Assert-Equal '512 MB' (Format-CaramosSize 512MB) 'MB'
    Assert-Equal '1,5 GB' (Format-CaramosSize 1.5GB) 'GB'
    Assert-Equal '18,4 GB' (Format-CaramosSize (18.44 * 1GB)) 'GB one decimal'
    Assert-Equal '250 GB' (Format-CaramosSize 250GB) 'large GB'
}

Invoke-Test 'lists are joined the Vietnamese way' {
    Assert-Equal 'A' (Join-CaramosList -Items @('A')) 'one'
    Assert-Equal 'A và B' (Join-CaramosList -Items @('A', 'B')) 'two'
    Assert-Equal 'A, B và C' (Join-CaramosList -Items @('A', 'B', 'C')) 'three'
    Assert-Equal 'A, B và 2 chương trình khác' (Join-CaramosList -Items @('A', 'B', 'C', 'D') -Max 2 -MoreNoun 'chương trình') 'truncated'
    Assert-Equal 'có sẵn trong App Center' (ConvertTo-CaramosLowerFirst 'Có sẵn trong App Center') 'lower first keeps App Center'
    Assert-Equal 'USB' (ConvertTo-CaramosLowerFirst 'USB') 'acronym kept'
}

Invoke-Test 'HTML escaping covers & < > " and quote' {
    Assert-Equal '&lt;script&gt;alert(1)&lt;/script&gt; &amp; Co' (ConvertTo-CaramosHtmlText '<script>alert(1)</script> & Co') 'script name'
    Assert-Equal '&quot;a&quot; &#39;b&#39;' (ConvertTo-CaramosHtmlText '"a" ''b''') 'quotes'
    Assert-Equal 'Cốc Cốc' (ConvertTo-CaramosHtmlText 'Cốc Cốc') 'Vietnamese untouched'
}

Invoke-Test 'VID:PID, PnP classes, printer connections, Office product names' {
    Assert-Equal '04a9:2759' (Get-CaramosVidPid 'USB\VID_04A9&PID_2759\5&1A2B') 'vid pid'
    Assert-Equal $null (Get-CaramosVidPid 'ACPI\PNP0303\4&1') 'no vid pid'
    Assert-Equal 'Image' (Resolve-CaramosPnpClass -Class '' -ClassGuid '{6BDD1FC6-810F-11D0-BEC7-08002BE2092F}') 'class from GUID (Windows 7)'
    Assert-Equal 'usb' (Get-CaramosPrinterConnection -Name 'Canon LBP2900' -DriverName 'Canon LBP2900' -PortName 'USB001' -IsConnection $false).Kind 'usb'
    $network = Get-CaramosPrinterConnection -Name 'HP' -DriverName 'HP PCL 6' -PortName 'IP_192.168.1.25' -IsConnection $false
    Assert-Equal 'network' $network.Kind 'network'
    Assert-Equal '192.168.1.25' $network.Address 'address'
    Assert-Equal 'virtual' (Get-CaramosPrinterConnection -Name 'Microsoft Print to PDF' -DriverName 'Microsoft Print To PDF' -PortName 'PORTPROMPT:' -IsConnection $false).Kind 'pdf printer'
    Assert-Equal 'virtual' (Get-CaramosPrinterConnection -Name 'OneNote (Desktop)' -DriverName 'Send to Microsoft OneNote 16 Driver' -PortName 'nul:' -IsConnection $false).Kind 'onenote'
    Assert-Equal 'shared' (Get-CaramosPrinterConnection -Name '\\SERVER\Ricoh' -DriverName 'RICOH PCL6' -PortName '\\SERVER\Ricoh' -IsConnection $true).Kind 'shared'
    Assert-Equal 'virtual' (Get-CaramosPrinterConnection -Name 'HP LaserJet (redirected 2)' -DriverName 'Remote Desktop Easy Print' -PortName 'TS001' -IsConnection $false).Kind 'RDP redirected'
    Assert-Equal 'Microsoft 365 Apps for business (thuê bao)' (ConvertTo-CaramosOfficeProductName 'O365BusinessRetail') 'M365'
    Assert-Equal 'Office Professional Plus 2021 (mua một lần)' (ConvertTo-CaramosOfficeProductName 'ProPlus2021Volume') 'LTSC'
    Assert-Equal 'Office Home & Student 2016 (mua một lần)' (ConvertTo-CaramosOfficeProductName 'HomeStudentRetail') '2016 retail'
}

Invoke-Test 'program list skips updates, system components, child entries and duplicates' {
    $programs = Select-CaramosPrograms -Entries (Read-Fixture 'uninstall-entries.json')
    Assert-Equal 12 $programs.Count 'program count'
    $names = @($programs | ForEach-Object { $_.Name })
    foreach ($skipped in @('Security Update for Microsoft Office 2016 (KB5002623) 32-Bit Edition', 'Microsoft Access MUI (English) 2016', 'Update for Windows 10 for x64-based Systems (KB5001716)')) {
        Assert-True ($names -notcontains $skipped) ('skipped ' + $skipped)
    }
    Assert-Equal 1 @($names | Where-Object { $_ -eq 'Google Chrome' }).Count 'Chrome once'
    $chrome = $programs | Where-Object { $_.Name -eq 'Google Chrome' }
    Assert-Equal 'Google LLC' $chrome.Publisher 'publisher kept from the fuller entry'
    Assert-Equal 'user' ($programs | Where-Object { $_.Name -eq 'Zalo' }).Scope 'HKCU entry is per-user'
}

Invoke-Test 'realistic program list is grouped by advice kind' {
    $table = Import-CaramosAdviceTable -Path $TablePath
    $items = ConvertTo-CaramosProgramItems -Programs (Select-CaramosPrograms -Entries (Read-Fixture 'uninstall-entries.json')) -Table $table
    $kinds = @{}
    foreach ($item in $items) { $kinds[$item.name] = $item.kind }
    $expected = [ordered]@{
        'MISA SME.NET 2023' = 'windows-only'; 'HTKK' = 'windows-only'
        'UltraViewer version 6.6.48' = 'alternative'; 'Foxit PDF Reader' = 'alternative'; 'Microsoft Office Professional Plus 2016' = 'alternative'
        'Zalo' = 'available'; 'Google Chrome' = 'available'; 'Cốc Cốc' = 'available'
        'UniKey 4.6 RC2' = 'not-needed'; 'WinRAR 7.01 (64-bit)' = 'not-needed'
        'Phần mềm Quản lý Thư viện ABC' = 'unknown'; '<script>alert(1)</script> & Co' = 'unknown'
    }
    foreach ($name in $expected.Keys) { Assert-Equal $expected[$name] $kinds[$name] ('kind of ' + $name) }
    Assert-Equal 12 $kinds.Count 'all programs classified'
    $unknown = $items | Where-Object { $_.name -eq 'Phần mềm Quản lý Thư viện ABC' }
    Assert-Equal $null $unknown.advice 'unknown program has no advice'
}

Invoke-Test 'printers, scanners and USB devices are summarised' {
    $table = Import-CaramosAdviceTable -Path $TablePath
    $printers = ConvertTo-CaramosPrinterItems -Printers (Read-Fixture 'printers.json') -Table $table
    $real = @($printers | Where-Object { -not $_.virtual })
    Assert-Equal 4 $real.Count 'real printers'
    Assert-Equal 3 @($printers | Where-Object { $_.virtual }).Count 'virtual printers'
    $canon = $printers | Where-Object { $_.name -eq 'Canon LBP2900' }
    Assert-Contains $canon.advice 'Kiểm tra driver của CaramOS hỗ trợ máy này' 'LBP2900 advice'
    Assert-Equal $null ($printers | Where-Object { $_.name -eq 'Microsoft Print to PDF' }).advice 'no advice for virtual printers'
    Assert-Contains ($printers | Where-Object { $_.name -eq 'HP LaserJet Pro M402dn' }).advice 'địa chỉ IP' 'network printer advice'
    Assert-Contains ($printers | Where-Object { $_.connection -eq 'shared' }).advice 'chia sẻ từ một máy Windows khác' 'shared printer advice'

    $devices = Read-Fixture 'pnp-devices.json'
    $scanners = Get-CaramosScannerItems -Devices $devices -Table $table
    Assert-Equal 2 $scanners.Count 'scanners (webcams excluded)'
    Assert-Equal '04a9:1913' ($scanners | Where-Object { $_.name -eq 'CanoScan LiDE 300' }).vidPid 'scanner vid:pid'
    Assert-Equal '04b8:1181' ($scanners | Where-Object { $_.name -eq 'EPSON L3150 Series' }).vidPid 'scanner found through class GUID'

    $usb = Get-CaramosUsbSummary -Devices $devices -Table $table
    Assert-Equal 2 $usb.keyboards 'keyboards (USB receiver and PS/2)'
    Assert-Equal 1 $usb.mice 'mice'
    $names = @($usb.items | ForEach-Object { $_.name })
    Assert-Equal 8 $names.Count ('USB rows: ' + ($names -join ' | '))
    foreach ($noise in @('USB Root Hub (USB 3.0)', 'Generic USB Hub', 'USB Composite Device', 'USB Input Device', 'USB Mass Storage Device', 'USB Printing Support', 'CanoScan LiDE 300')) {
        Assert-True ($names -notcontains $noise) ('dropped ' + $noise)
    }
    $nic = $usb.items | Where-Object { $_.name -eq 'Realtek USB GbE Family Controller' }
    Assert-Equal 2 $nic.quantity 'identical devices merged'
    Assert-Equal 'Camera' ($usb.items | Where-Object { $_.name -eq 'Logitech HD Webcam C270' }).class 'webcam in the Image class shown as a camera'
    Assert-Contains ($usb.items | Where-Object { $_.class -eq 'SmartCardReader' }).note 'chữ ký số' 'token note'
    Assert-Equal '2.0' (Find-CaramosTpmInPnp -Devices $devices) 'TPM 2.0 from the device list'
}

Invoke-Test 'TPM falls back to the device list without admin rights' {
    $found = Get-CaramosTpmInfo -PnpDevices (Read-Fixture 'pnp-devices.json') -PnpRead $true
    Assert-Equal 'found' $found.Status 'found through PnP'
    Assert-Equal '2.0' $found.Version 'version'
    $none = Get-CaramosTpmInfo -PnpDevices @([pscustomobject]@{ InstanceId = 'ACPI\PNP0303\1'; Name = 'Keyboard'; Class = 'Keyboard'; ClassGuid = '' }) -PnpRead $true
    Assert-Equal 'not-found-pnp' $none.Status 'not in the device list'
    $unread = Get-CaramosTpmInfo -PnpDevices @() -PnpRead $false
    Assert-Equal 'needs-admin' $unread.Status 'nothing readable'
}

Invoke-Test 'Office summary reads MSI keys and the program list' {
    $table = Import-CaramosAdviceTable -Path $TablePath
    $items = ConvertTo-CaramosProgramItems -Programs (Select-CaramosPrograms -Entries (Read-Fixture 'uninstall-entries.json')) -Table $table
    $office = Get-CaramosOfficeSummary -Registry (Read-Fixture 'office.json') -ProgramItems $items
    Assert-True $office.found 'Office found'
    Assert-Equal 'Office 2016' $office.msi[0].name 'MSI version name'
    Assert-Equal 4 @($office.msi[0].apps).Count 'apps'
    Assert-Equal 'Microsoft Office Professional Plus 2016 16.0.4266.1001' $office.editions[0] 'edition from the program list'
    $c2r = Get-CaramosOfficeSummary -Registry ([ordered]@{ ClickToRun = [ordered]@{ Version = '16.0.17928.20156'; ProductReleaseIds = 'O365BusinessRetail,VisioProRetail'; Platform = 'x64' }; Msi = @([ordered]@{ Version = '16.0'; Apps = @('Word') }) }) -ProgramItems @()
    Assert-Equal 2 @($c2r.clickToRun.products).Count 'C2R products'
    Assert-Equal 0 @($c2r.msi).Count 'MSI 16.0 hidden when Click-to-Run is present'
}

Invoke-Test 'fonts: legacy Vietnamese fonts and user fonts are counted' {
    $fonts = Get-CaramosFontSummary -FontData (Read-Fixture 'fonts.json')
    Assert-Equal 3 $fonts.legacyVietnamese 'TCVN3 and VNI fonts'
    Assert-Equal 2 $fonts.userInstalled 'per-user fonts'
}

Invoke-Test 'JSON writer escapes, nests and round-trips' {
    $value = [ordered]@{ a = 'x<y>"z"\'; b = @(1, 2.5, $true, $null); c = [ordered]@{}; d = @(); e = 'Cốc Cốc'; f = [long]1234567890123; g = [pscustomobject]@{ h = 'i' } }
    $json = ConvertTo-CaramosJson -InputObject $value
    Assert-NotContains $json '<y>' 'angle brackets escaped'
    $back = ConvertFrom-Json -InputObject $json
    Assert-Equal 'x<y>"z"\' $back.a 'string round trip'
    Assert-Equal 2.5 $back.b[1] 'double'
    Assert-Equal 'Cốc Cốc' $back.e 'unicode kept'
    Assert-Equal 1234567890123 $back.f 'long'
    Assert-Equal 'i' $back.g.h 'object'
    Assert-Equal 0 @($back.d).Count 'empty array'
}

# ---------------------------------------------------------------------------
# Folder statistics on the fake profile
# ---------------------------------------------------------------------------

$script:Measured = $null
Invoke-Test 'folder plan resolves duplicates, missing folders and nesting' {
    $plan = New-CaramosFolderPlan -Known $Fake.Known
    $byKey = @{}
    foreach ($item in $plan.Items) { $byKey[$item.key] = $item }
    Assert-Equal 'scan' $byKey['Documents'].status 'Documents scanned'
    Assert-Equal 'same-as' $byKey['Music'].status 'Music same as Pictures'
    Assert-Equal 'Pictures' $byKey['Music'].sameAs 'sameAs key'
    Assert-Equal 'missing' $byKey['Videos'].status 'Videos missing'
    Assert-Equal 'ZaloReceived' (@($byKey['Documents'].excludes) -join ',') 'Zalo excluded from Documents'
    Assert-Equal 'default' $byKey['Desktop'].location 'Desktop in the profile'
    Assert-Equal 'other' $byKey['Downloads'].location 'Downloads elsewhere'
    Assert-Equal 1 @($plan.ZaloApp).Count 'existing Zalo data folders only'
    $script:Measured = Measure-CaramosFolders -Plan $plan
}

Invoke-Test 'folder statistics: counts, sizes, links skipped, nested folder counted once' {
    $m = $script:Measured
    Assert-True ($null -ne $m) 'measured'
    $rows = @{}
    foreach ($row in $m.Folders.items) { $rows[$row.key] = $row }
    Assert-Equal 2 $rows['Desktop'].files 'Desktop files'
    Assert-Equal 1500 $rows['Desktop'].bytes 'Desktop bytes'
    Assert-Equal 7 $rows['Documents'].files 'Documents files (no Zalo, no links, no locked folder)'
    Assert-Equal 10816 $rows['Documents'].bytes 'Documents bytes'
    Assert-Equal 3 $rows['Documents'].skippedLinks 'loop, outside link and file link skipped'
    Assert-Equal 1 $rows['Documents'].unreadableDirs 'locked folder tolerated'
    Assert-Equal 2 $rows['ZaloReceived'].files 'Zalo files'
    Assert-Equal 1100 $rows['ZaloReceived'].bytes 'Zalo bytes'
    Assert-Equal 1 $rows['Pictures'].files 'Pictures'
    Assert-Equal 10000 $rows['Downloads'].bytes 'Downloads'
    Assert-Equal 'same-as' $rows['Music'].status 'Music row'
    Assert-Equal $null $rows['Music'].files 'Music not counted twice'
    $total = $m.Folders.total
    Assert-Equal 13 $total.files 'total files'
    Assert-Equal 28416 $total.bytes 'total bytes'
    Assert-Equal 13000 $m.Folders.zaloAppData.bytes 'Zalo app data size'
    $types = Get-CaramosFileTypeSummary -ExtCount $m.ExtCount -ExtBytes $m.ExtBytes
    Assert-Equal 2 $types.counts['.xlsm'] '.xlsm (Desktop and Zalo, not the symlink, not outside)'
    Assert-Equal 5 $types.excelMacro 'Excel macro files'
    Assert-Equal 1 $types.wordMacro 'Word macro files (locked folder not read)'
    Assert-Equal 6 $types.macroTotal 'macro total'
    Assert-Equal 2 $types.oldTotal 'old formats'
    Assert-Equal 1 $types.counts['.pst'] 'pst'
    Assert-Equal 4096 $types.bytes['.pst'] 'pst size'
    Assert-Equal 1 $types.counts['.ost'] 'ost from the Outlook data folder'
}

Invoke-Test 'OneDrive placeholders are counted without being read, junctions skipped' {
    function Get-CaramosChildEntries { param([object]$Directory) return , ([object[]]$Directory.Children) }
    function New-FakeEntry {
        param([string]$Path, [int]$Attributes, [long]$Length = 0, [object]$LinkType = $null, [object[]]$Children = @())
        $extension = [System.IO.Path]::GetExtension($Path)
        return [pscustomobject]@{ FullName = $Path; Attributes = $Attributes; Length = $Length; Extension = $extension; LinkType = $LinkType; Children = $Children }
    }
    $odChildren = @(New-FakeEntry -Path '/fake/OneDrive/od/e.xls' -Attributes 0x20 -Length 42)
    $children = @(
        (New-FakeEntry -Path '/fake/OneDrive/a.xlsm' -Attributes 0x20 -Length 100),
        (New-FakeEntry -Path '/fake/OneDrive/b.docx' -Attributes (0x20 -bor 0x400 -bor 0x400000 -bor 0x100000) -Length 5000),
        (New-FakeEntry -Path '/fake/OneDrive/c.xlsm' -Attributes (0x20 -bor 0x400) -Length 200),
        (New-FakeEntry -Path '/fake/OneDrive/d.pst' -Attributes (0x20 -bor 0x1000) -Length 700),
        (New-FakeEntry -Path '/fake/OneDrive/cloud' -Attributes (0x10 -bor 0x400 -bor 0x400000)),
        (New-FakeEntry -Path '/fake/OneDrive/od' -Attributes (0x10 -bor 0x400) -Children $odChildren),
        (New-FakeEntry -Path '/fake/OneDrive/junction' -Attributes (0x10 -bor 0x400) -LinkType 'Junction' -Children @((New-FakeEntry -Path '/fake/x.xlsm' -Attributes 0x20 -Length 1))),
        (New-FakeEntry -Path '/fake/OneDrive/desktop.ini' -Attributes 0x26 -Length 282),
        (New-FakeEntry -Path '/fake/OneDrive/$RECYCLE.BIN' -Attributes 0x16)
    )
    $root = New-FakeEntry -Path '/fake/OneDrive' -Attributes 0x10 -Children $children
    function Get-CaramosDirectoryEntry { param([string]$Path) return $root }
    $stats = Measure-CaramosFolder -Path '/fake/OneDrive' -CloudRoots @('/fake/OneDrive')
    Assert-Equal 3 $stats.files 'local files (one is a hydrated OneDrive file)'
    Assert-Equal 342 $stats.bytes 'local bytes'
    Assert-Equal 2 $stats.cloudFiles 'online-only files'
    Assert-Equal 5700 $stats.cloudBytes 'online-only bytes'
    Assert-Equal 1 $stats.cloudDirs 'online-only folder not listed'
    Assert-Equal 1 $stats.skippedLinks 'junction skipped'
    Assert-Equal 2 $stats.ExtCount['.xlsm'] 'xlsm counted from placeholders too'
    Assert-Equal 1 $stats.ExtCount['.pst'] 'pst counted'

    $old = $CaramosConfig.HasLinkType
    $CaramosConfig.HasLinkType = $false
    try {
        $legacy = Measure-CaramosFolder -Path '/fake/OneDrive' -CloudRoots @('/fake/OneDrive')
        # PowerShell < 5 cannot tell a junction from a placeholder: under a OneDrive root both are walked.
        Assert-Equal 4 $legacy.files 'PowerShell < 5: reparse folders under OneDrive are walked'
        $outside = Measure-CaramosFolder -Path '/fake/OneDrive' -CloudRoots @('/elsewhere')
        Assert-Equal 2 $outside.files 'PowerShell < 5: unknown reparse folder outside OneDrive is skipped'
    }
    finally { $CaramosConfig.HasLinkType = $old }

    $late = Measure-CaramosFolder -Path '/fake/OneDrive' -Deadline ([datetime]::UtcNow.AddSeconds(-1))
    Assert-True $late.partial 'time budget stops the walk'
}

# ---------------------------------------------------------------------------
# Whole runs with mocks
# ---------------------------------------------------------------------------

function Invoke-MockedRun {
    param([string]$Name, [switch]$HideComputerName, [switch]$KeepDirectory)
    $dir = Join-Path $OutDir $Name
    if (-not $KeepDirectory) { Reset-Directory $dir }
    return Invoke-CaramosAssessment -OutputDirectory $dir -NoOpen -HideComputerName:$HideComputerName -ScriptDirectory $ToolDir
}

$script:Run = $null
Invoke-Test 'mocked run writes the HTML and JSON reports with the expected names' {
    $script:Run = Invoke-MockedRun -Name 'run-mocked'
    Assert-True (Test-Path -LiteralPath $script:Run.HtmlPath) 'HTML written'
    Assert-True (Test-Path -LiteralPath $script:Run.JsonPath) 'JSON written'
    Assert-True ((Split-Path -Leaf $script:Run.HtmlPath) -match '^khao-sat-caramos-\d{8}-\d{4}\.html$') 'HTML file name'
    Assert-True ((Split-Path -Leaf $script:Run.JsonPath) -match '^khao-sat-caramos-\d{8}-\d{4}\.json$') 'JSON file name'
    $again = Invoke-MockedRun -Name 'run-mocked' -KeepDirectory
    Assert-True ((Split-Path -Leaf $again.HtmlPath) -match '^khao-sat-caramos-\d{8}-\d{4}(-2)?\.html$') 'second run in the same minute gets a suffix'
    Assert-True ($again.HtmlPath -ne $script:Run.HtmlPath) 'no overwrite'
}

Invoke-Test 'HTML is UTF-8 with charset, self-contained, sections in order' {
    $bytes = [System.IO.File]::ReadAllBytes($script:Run.HtmlPath)
    Assert-True ($bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) 'HTML has a UTF-8 BOM'
    $needle = [System.Text.Encoding]::UTF8.GetBytes('Khảo sát chuyển sang CaramOS')
    $hex = [System.BitConverter]::ToString($bytes)
    Assert-True ($hex.Contains([System.BitConverter]::ToString($needle))) 'title bytes are UTF-8'
    $html = [System.IO.File]::ReadAllText($script:Run.HtmlPath, [System.Text.Encoding]::UTF8)
    Assert-Contains $html '<meta charset="utf-8">' 'meta charset'
    Assert-Contains $html '<html lang="vi">' 'lang'
    foreach ($forbidden in @('<script', '<link', 'src=', 'http://', 'https://', '@import', 'url(')) { Assert-NotContains $html $forbidden 'self-contained' }
    $order = @('<h1>Khảo sát chuyển sang CaramOS</h1>', '<h2>Tóm tắt</h2>', '<h2>Máy tính</h2>', '<h2>Chương trình đã cài</h2>', '<h2>Máy in và máy quét</h2>', '<h2>Thiết bị USB</h2>', '<h2>Microsoft Office</h2>', '<h2>Dữ liệu cần chép</h2>', '<h2>Tệp có macro và tệp cũ</h2>', '<div class="note">')
    $last = -1
    foreach ($marker in $order) {
        $index = $html.IndexOf($marker, [System.StringComparison]::Ordinal)
        Assert-True ($index -gt $last) ('section order at ' + $marker)
        $last = $index
    }
    foreach ($color in [regex]::Matches($html, '#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b')) {
        $c = $color.Value.ToLowerInvariant()
        if ($c -eq '#2b6a44') { continue }
        if ($c.Length -eq 4) { $c = '#' + $c[1] + $c[1] + $c[2] + $c[2] + $c[3] + $c[3] }
        Assert-True ($c.Substring(1, 2) -eq $c.Substring(3, 2) -and $c.Substring(3, 2) -eq $c.Substring(5, 2)) ('only grey plus one accent colour, found ' + $c)
    }
    Assert-Contains $html '@media print' 'print styles'
    Assert-Contains $html 'size: A4' 'A4 page'
}

Invoke-Test 'summary sentences carry the right numbers' {
    $html = [System.IO.File]::ReadAllText($script:Run.HtmlPath, [System.Text.Encoding]::UTF8)
    Assert-Contains $html 'Máy có 12 chương trình đã cài.' 'program count'
    Assert-Contains $html '2 chương trình chỉ chạy trên Windows: HTKK và MISA SME.NET 2023.' 'windows-only list'
    Assert-Contains $html '3 chương trình có bản thay thế, 3 chương trình có sẵn trong App Center, 2 chương trình không cần nữa và 2 chương trình chưa có gợi ý.' 'kind counts'
    Assert-Contains $html 'Cần chép dưới 1 MB dữ liệu (13 tệp) từ các thư mục người dùng.' 'data to copy'
    Assert-Contains $html 'Có 5 tệp Excel và 1 tệp Word có macro cần thử.' 'macro files'
    Assert-Contains $html 'Có 2 tệp Word, Excel, PowerPoint định dạng cũ (.doc, .xls, .ppt).' 'old formats'
    Assert-Contains $html 'Microsoft đã ngừng hỗ trợ Windows 10 từ ngày 14/10/2025.' 'Windows 10 end of support'
    Assert-Contains $html 'Máy in: Canon LBP2900 (USB), HP LaserJet Pro M402dn (mạng)' 'printer summary'
    Assert-Contains $html 'Máy PC-KETOAN-01, khảo sát ngày' 'computer name and date'
    Assert-Contains $html 'Office 2016 (bản cài MSI, 16.0): Word, Excel, PowerPoint và Outlook.' 'Office version'
    Assert-Contains $html 'Không thấy WPS Office, ONLYOFFICE hay LibreOffice trên máy.' 'other office suites'
    Assert-Contains $html 'Windows nhận 2 bàn phím và 1 chuột' 'keyboard and mouse counts'
    Assert-Contains $html 'Máy có TPM 2.0, là một điều kiện để lên Windows 11' 'TPM line'
    Assert-Contains $html 'Secure Boot</th><td>không đọc được (cần quyền quản trị)</td>' 'Secure Boot needs admin'
    Assert-Contains $html 'Ổ hệ thống (C:)</th><td>238 GB, còn trống 120 GB; ổ SSD, SATA</td>' 'disk line'
    Assert-Contains $html 'RAM</th><td>8 GB</td>' 'RAM line'
}

Invoke-Test 'every inserted value is escaped' {
    $html = [System.IO.File]::ReadAllText($script:Run.HtmlPath, [System.Text.Encoding]::UTF8)
    Assert-Contains $html '&lt;script&gt;alert(1)&lt;/script&gt; &amp; Co' 'program name escaped'
    Assert-Contains $html '&quot;Evil&quot; &lt;b&gt;Corp&lt;/b&gt;' 'publisher escaped'
    Assert-Contains $html 'Máy in &lt;i&gt;phòng&lt;/i&gt; họp' 'printer name escaped'
    Assert-Contains $html 'Thiết bị &lt;b&gt;lạ&lt;/b&gt; &amp; &quot;thử&quot;' 'device name escaped'
    Assert-NotContains $html '<script>' 'no raw script tag'
    Assert-NotContains $html '<b>Corp' 'no raw b tag'
    Assert-NotContains $html '<i>phòng' 'no raw i tag'
}

Invoke-Test 'no file or folder name from the profile appears in the HTML or JSON' {
    $html = [System.IO.File]::ReadAllText($script:Run.HtmlPath, [System.Text.Encoding]::UTF8)
    $json = [System.IO.File]::ReadAllText($script:Run.JsonPath, [System.Text.Encoding]::UTF8)
    foreach ($secret in $Fake.Secrets) {
        Assert-NotContains $html $secret 'HTML privacy'
        Assert-NotContains $json $secret 'JSON privacy'
    }
    foreach ($text in @($html, $json)) {
        Assert-NotContains $text $WorkRoot 'no temp path'
        Assert-NotContains $text 'Users/' 'no profile path'
        Assert-NotContains $text 'AppData/' 'no AppData path'
        Assert-NotContains $text 'AppData\' 'no AppData path'
    }
}

Invoke-Test 'JSON report parses and matches the HTML data' {
    $text = [System.IO.File]::ReadAllText($script:Run.JsonPath, (New-Object System.Text.UTF8Encoding -ArgumentList $false, $true))
    Assert-True ($text[0] -ne [char]0xFEFF) 'JSON without BOM'
    Assert-NotContains $text '<script' 'angle brackets escaped in JSON'
    $data = ConvertFrom-Json -InputObject $text
    Assert-Equal 'caramos-assess/1' $data.schema 'schema'
    Assert-Equal 'PC-KETOAN-01' $data.computerName 'computer name'
    Assert-Equal 12 $data.programs.count 'program count'
    Assert-Equal 'windows-only' ($data.programs.items | Where-Object { $_.name -eq 'HTKK' }).kind 'HTKK kind'
    Assert-Equal '<script>alert(1)</script> & Co' ($data.programs.items | Where-Object { $_.kind -eq 'unknown' -and $_.name -like '<script>*' }).name 'name survives JSON'
    Assert-Equal 13 $data.folders.total.files 'total files'
    Assert-Equal 6 $data.fileTypes.macroTotal 'macro total'
    Assert-Equal 'found' $data.machine.tpm.status 'TPM'
    Assert-Equal 'needs-admin' $data.machine.secureBoot 'Secure Boot'
    Assert-Equal 2 @($data.scanners.items).Count 'scanners'
    Assert-Equal 'ok' $data.adviceTable.status 'advice table loaded'
}

Invoke-Test 'a section that fails on odd data is replaced by one line, the rest stays' {
    function Add-CaramosUsbHtml {
        param($Html, $Report)
        $Html.Add('<h2>Thiết bị USB</h2>')
        $Html.Add('<p>half written')
        throw 'odd data'
    }
    $html = ConvertTo-CaramosReportHtml -Report $script:Run.Report
    Assert-Contains $html '<h2>Thiết bị USB</h2>' 'heading kept'
    Assert-Contains $html 'Không tạo được mục này của báo cáo.' 'fallback line'
    Assert-NotContains $html 'half written' 'partial output removed'
    Assert-Contains $html '<h2>Microsoft Office</h2>' 'next section still there'
    Assert-Equal 1 ([regex]::Matches($html, '<h2>Thiết bị USB</h2>')).Count 'heading once'
}

Invoke-Test '-HideComputerName leaves the computer name out of both files' {
    $run = Invoke-MockedRun -Name 'run-hidden' -HideComputerName
    $html = [System.IO.File]::ReadAllText($run.HtmlPath, [System.Text.Encoding]::UTF8)
    $json = [System.IO.File]::ReadAllText($run.JsonPath, [System.Text.Encoding]::UTF8)
    Assert-NotContains $html 'PC-KETOAN-01' 'HTML'
    Assert-NotContains $json 'PC-KETOAN-01' 'JSON'
    Assert-Contains $html 'Tên máy đã được ẩn.' 'hidden note'
    Assert-Equal $null (ConvertFrom-Json -InputObject $json).computerName 'computerName null'
}

Invoke-Test 'probes that need admin rights say so instead of failing' {
    $MockState.Fail['pnp'] = $true
    try { $run = Invoke-MockedRun -Name 'run-needs-admin' }
    finally { $MockState.Fail.Remove('pnp') }
    $html = [System.IO.File]::ReadAllText($run.HtmlPath, [System.Text.Encoding]::UTF8)
    Assert-Contains $html 'TPM</th><td>không đọc được (cần quyền quản trị)</td>' 'TPM needs admin'
    Assert-Contains $html 'Secure Boot</th><td>không đọc được (cần quyền quản trị)</td>' 'Secure Boot needs admin'
    Assert-Contains $html 'Chưa biết máy có TPM 2.0' 'Windows 11 line'
    Assert-Contains $html 'Không đọc được danh sách thiết bị.' 'device list unreadable'
}

Invoke-Test 'every probe failing still gives a complete report' {
    foreach ($name in @('computer', 'programs', 'printers', 'pnp', 'office', 'system', 'folders', 'fonts')) { $MockState.Fail[$name] = $true }
    try { $run = Invoke-MockedRun -Name 'run-failing' }
    finally { $MockState.Fail.Clear() }
    $html = [System.IO.File]::ReadAllText($run.HtmlPath, [System.Text.Encoding]::UTF8)
    foreach ($text in @('Không đọc được danh sách chương trình đã cài.', 'Không đọc được danh sách máy in.', 'Không đếm được dữ liệu trong các thư mục người dùng.', 'Không đọc được thông tin máy.', '<div class="note">')) {
        Assert-Contains $html $text 'graceful section'
    }
    $data = ConvertFrom-Json -InputObject ([System.IO.File]::ReadAllText($run.JsonPath, [System.Text.Encoding]::UTF8))
    Assert-Equal 'error' $data.programs.status 'programs status'
    Assert-Equal 'error' $data.folders.status 'folders status'
}

Invoke-Test 'a folder that cannot be written falls back to the Desktop' {
    $readOnly = Join-Path $OutDir 'run-readonly'
    $desktop = Join-Path $OutDir 'run-desktop'
    Reset-Directory $desktop
    if (Test-Path -LiteralPath $readOnly) { & chmod 755 $readOnly; Remove-Item -LiteralPath $readOnly -Recurse -Force }
    $null = New-Item -ItemType Directory -Path $readOnly
    & chmod 555 $readOnly
    $MockState.Desktop = $desktop
    try { $run = Invoke-CaramosAssessment -OutputDirectory $readOnly -NoOpen -ScriptDirectory $ToolDir }
    finally { $MockState.Desktop = $null; & chmod 755 $readOnly }
    Assert-Equal $desktop (Split-Path -Parent $run.HtmlPath) 'saved on the Desktop'
    Assert-Equal 0 @(Get-ChildItem -LiteralPath $readOnly).Count 'nothing in the read-only folder'
}

Invoke-Test 'missing advice table: programs listed without advice' {
    $emptyDir = Join-Path $WorkRoot 'no-table'
    Reset-Directory $emptyDir
    $out = Join-Path $OutDir 'run-no-table'
    Reset-Directory $out
    $run = Invoke-CaramosAssessment -OutputDirectory $out -NoOpen -ScriptDirectory $emptyDir
    $html = [System.IO.File]::ReadAllText($run.HtmlPath, [System.Text.Encoding]::UTF8)
    Assert-Contains $html 'Không đọc được bảng gợi ý' 'note about the table'
    Assert-Contains $html 'Chưa có gợi ý (12)' 'all programs without advice'
}

# ---------------------------------------------------------------------------
# Real runs in a child PowerShell (no mocks): entry point and dot-sourcing
# ---------------------------------------------------------------------------

function Invoke-Child {
    param([string[]]$Arguments, [string]$HomeDirectory)
    $oldHome = $env:HOME
    $env:HOME = $HomeDirectory
    try {
        $output = & pwsh @Arguments 2>&1
        return [pscustomobject]@{ Output = (@($output | ForEach-Object { [string]$_ }) -join "`n"); ExitCode = $LASTEXITCODE }
    }
    finally { $env:HOME = $oldHome }
}

Invoke-Test 'dot-sourcing in a fresh PowerShell does not start the survey' {
    $homeDir = Join-Path $WorkRoot 'home-dot'
    Reset-Directory $homeDir
    $child = Invoke-Child -HomeDirectory $homeDir -Arguments @('-NoProfile', '-Command', (". '" + $ScriptPath + "'; 'DOT-OK'; if (Get-Command Invoke-CaramosAssessment -ErrorAction SilentlyContinue) { 'FN-OK' }"))
    Assert-Equal 0 $child.ExitCode 'exit code'
    Assert-Equal "DOT-OK`nFN-OK" $child.Output.Trim() 'only the test output'
    Assert-Equal 0 @(Get-ChildItem -LiteralPath $homeDir -Recurse -Force -Filter 'khao-sat-caramos-*').Count 'no report written'
}

Invoke-Test 'running the script for real on Linux degrades gracefully and exits 0' {
    $homeDir = Join-Path $WorkRoot 'home-run'
    Reset-Directory $homeDir
    $out = Join-Path $OutDir 'run-direct'
    Reset-Directory $out
    $child = Invoke-Child -HomeDirectory $homeDir -Arguments @('-NoProfile', '-File', $ScriptPath, '-NoOpen', '-OutputDirectory', $out)
    Assert-Equal 0 $child.ExitCode ('exit code; output: ' + $child.Output)
    Assert-Contains $child.Output 'Đã lưu báo cáo' 'Vietnamese message with the path'
    $files = @(Get-ChildItem -LiteralPath $out -Filter 'khao-sat-caramos-*')
    Assert-Equal 2 $files.Count 'HTML and JSON'
    $html = [System.IO.File]::ReadAllText((@($files | Where-Object { $_.Extension -eq '.html' })[0]).FullName, [System.Text.Encoding]::UTF8)
    Assert-Contains $html 'Khảo sát chuyển sang CaramOS' 'title'
    Assert-Contains $html 'Không đọc được danh sách chương trình đã cài.' 'no registry on Linux'
}

# ---------------------------------------------------------------------------
# A fuller sample report to look at (not asserted in detail)
# ---------------------------------------------------------------------------

function New-SampleProfile {
    param([string]$Root)
    $profileRoot = Join-Path (Join-Path $Root 'Users') 'ketoan'
    $map = [ordered]@{
        Desktop   = @{ Count = 37; Bytes = 1.2GB; Extra = @{ '.xlsm' = 3; '.doc' = 4 } }
        Documents = @{ Count = 1820; Bytes = 6.4GB; Extra = @{ '.xlsm' = 9; '.xlsb' = 2; '.xlam' = 1; '.docm' = 3; '.doc' = 120; '.xls' = 58; '.ppt' = 5 } }
        Pictures  = @{ Count = 2400; Bytes = 9.8GB; Extra = @{} }
        Downloads = @{ Count = 410; Bytes = 3.1GB; Extra = @{ '.xls' = 5; '.doc' = 16 } }
        Music     = @{ Count = 0; Bytes = 0; Extra = @{} }
        Videos    = @{ Count = 12; Bytes = 4.4GB; Extra = @{} }
    }
    $folders = New-Object System.Collections.Generic.List[object]
    foreach ($key in $map.Keys) {
        $dir = Join-Path $profileRoot $key
        $null = New-Item -ItemType Directory -Force -Path $dir
        $spec = $map[$key]
        $made = 0
        foreach ($ext in $spec.Extra.Keys) {
            for ($i = 0; $i -lt $spec.Extra[$ext]; $i++) { New-File (Join-Path $dir ('f' + $made + $ext)) 40KB; $made++ }
        }
        if ($spec.Count -gt 0) {
            $rest = $spec.Count - $made
            $each = [long](($spec.Bytes - $made * 40KB) / $rest)
            for ($i = 0; $i -lt $rest; $i++) { New-File (Join-Path (Join-Path $dir ('d' + ($i % 7))) ('g' + $i + '.dat')) $each }
        }
        $folders.Add([ordered]@{ Key = $key; Path = $dir })
    }
    $zalo = Join-Path (Join-Path $profileRoot 'Documents') 'Zalo Received Files'
    for ($i = 0; $i -lt 860; $i++) { New-File (Join-Path $zalo ('z' + $i + '.jpg')) ([long](2.3GB / 860)) }
    for ($i = 0; $i -lt 2; $i++) { New-File (Join-Path $zalo ('bg' + $i + '.xlsm')) 30KB }
    New-File (Join-Path (Join-Path (Join-Path $profileRoot 'Documents') 'Outlook Files') 'a.pst') 1.2GB
    $folders.Add([ordered]@{ Key = 'ZaloReceived'; Path = $zalo })
    $zaloApp = Join-Path (Join-Path (Join-Path $profileRoot 'AppData') 'Local') 'ZaloPC'
    New-File (Join-Path $zaloApp 'z.db') 1.1GB
    $outlook = Join-Path (Join-Path (Join-Path (Join-Path $profileRoot 'AppData') 'Local') 'Microsoft') 'Outlook'
    New-File (Join-Path $outlook 'b.ost') 3.5GB
    $cloud = Join-Path $profileRoot 'OneDrive'
    return [ordered]@{ Folders = $folders.ToArray(); ZaloApp = @($zaloApp); Outlook = @($outlook); CloudRoots = @($cloud); ProfileRoot = $profileRoot }
}

Invoke-Test 'sample report for review is written' {
    $saved = @{ Entries = $MockState.Entries; Known = $MockState.Known }
    $MockState.Entries = 'sample-uninstall-entries.json'
    $MockState.Known = New-SampleProfile -Root (Join-Path $WorkRoot 'sample')
    try { $run = Invoke-MockedRun -Name 'sample' }
    finally { $MockState.Entries = $saved.Entries; $MockState.Known = $saved.Known }
    $html = [System.IO.File]::ReadAllText($run.HtmlPath, [System.Text.Encoding]::UTF8)
    Assert-Contains $html 'Máy có 48 chương trình đã cài.' 'sample program count'
    Assert-Contains $html 'rowspan="2"' 'programs sharing one advice share one cell'
    Write-Host ('      sample: ' + $run.HtmlPath)
}

# ---------------------------------------------------------------------------

& chmod 755 $Fake.Locked
Remove-Item -LiteralPath $WorkRoot -Recurse -Force -ErrorAction SilentlyContinue

Write-Host ''
Write-Host ('{0} passed, {1} failed' -f $script:Passed, $script:Failed)
if ($script:Failed -gt 0) {
    Write-Host ('Failed: ' + ($script:FailedNames -join '; '))
    exit 1
}
exit 0
