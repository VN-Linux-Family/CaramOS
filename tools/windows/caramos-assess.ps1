<#
.SYNOPSIS
    Khảo sát một máy Windows trước khi chuyển sang CaramOS và ghi báo cáo HTML tiếng Việt.

.DESCRIPTION
    caramos-assess.ps1 đọc thông tin của máy Windows này rồi ghi một báo cáo HTML tiếng Việt:
    máy có những chương trình, máy in, máy quét, thiết bị USB nào, dùng Microsoft Office bản nào,
    cần chép bao nhiêu dữ liệu, có bao nhiêu tệp Office có macro, và nên làm gì với từng thứ khi
    chuyển sang CaramOS. Cùng dữ liệu được ghi thêm ra tệp .json để gộp kết quả của nhiều máy.

    Script chỉ đọc: không thay đổi gì trên máy, không cần quyền quản trị và không kết nối mạng.
    Chỗ nào cần quyền quản trị (TPM, Secure Boot) mà không đọc được thì báo cáo ghi
    "không đọc được (cần quyền quản trị)". Một phần đọc lỗi không làm dừng cả báo cáo.

    Script không thu thập tên tệp, đường dẫn trong thư mục người dùng, nội dung tài liệu,
    lịch sử duyệt web, thư hay tên người dùng Windows. Thư mục chỉ được đếm số tệp và dung lượng,
    theo thư mục và theo loại tệp. Thư mục nằm trên máy chủ mạng không được đếm.
    Tên máy được ghi để phân biệt các máy khi khảo sát nhiều máy; dùng -HideComputerName để ẩn.

    Cách dùng: chép cả thư mục (caramos-assess.cmd, caramos-assess.ps1,
    caramos-assess-programs.json) vào USB, cắm vào máy Windows rồi bấm đúp caramos-assess.cmd.
    Báo cáo được lưu cạnh script với tên khao-sat-caramos-<năm tháng ngày-giờ phút>.html, kèm một
    tệp JSON cùng tên. Nếu thư mục đó không ghi được (USB chống ghi) thì lưu ra Desktop.
    Khi xong, báo cáo tự mở trong trình duyệt.

    Thời gian chạy thường 1 đến 3 phút. Việc đếm tệp dừng sau 10 phút nếu thư mục quá lớn;
    khi đó báo cáo ghi rõ là chưa đếm hết.

.PARAMETER OutputDirectory
    Thư mục lưu báo cáo. Mặc định là thư mục chứa script; nếu không ghi được thì lưu ra Desktop.

.PARAMETER NoOpen
    Không tự mở báo cáo trong trình duyệt khi xong.

.PARAMETER HideComputerName
    Không ghi tên máy vào báo cáo HTML và tệp JSON.

.EXAMPLE
    Bấm đúp caramos-assess.cmd

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\caramos-assess.ps1 -NoOpen -HideComputerName

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\caramos-assess.ps1 -OutputDirectory E:\khao-sat

.NOTES
    caramos-assess.ps1 phiên bản 1.0.0, một phần của bộ công cụ chuyển từ Windows sang CaramOS.
    Viết cho Windows PowerShell 5.1 (có sẵn trên Windows 10 và 11).
    Bảng gợi ý cho từng chương trình nằm trong caramos-assess-programs.json cạnh script; thiếu tệp
    này thì báo cáo vẫn liệt kê chương trình nhưng không kèm gợi ý.
    Tệp .ps1 phải giữ mã hóa UTF-8 có BOM để Windows PowerShell 5.1 đọc đúng tiếng Việt.
#>
#Requires -Version 3.0
[CmdletBinding()]
param(
    [string]$OutputDirectory,
    [switch]$NoOpen,
    [switch]$HideComputerName
)

$CaramosAssessVersion = '1.0.0'
$CaramosAssessScriptDirectory = $PSScriptRoot

# Settings shared by the functions below. Tests change Quiet and ScanBudgetSeconds.
$CaramosConfig = @{
    Quiet             = $false
    ScanBudgetSeconds = 600
    MaxDepth          = 64
    HasLinkType       = ($PSVersionTable.PSVersion.Major -ge 5)
    UseLongPaths      = $null
    NumberFormat      = $null
}

# File types counted while walking the profile folders (value = canonical key).
$CaramosTrackedExtensions = @{
    '.xlsm' = '.xlsm'; '.xlsb' = '.xlsb'; '.xltm' = '.xltm'; '.xla' = '.xla'; '.xlam' = '.xlam'
    '.docm' = '.docm'; '.dotm' = '.dotm'; '.pptm' = '.pptm'
    '.doc' = '.doc'; '.xls' = '.xls'; '.ppt' = '.ppt'
    '.pst' = '.pst'; '.ost' = '.ost'
}

$CaramosKindOrder = @('windows-only', 'alternative', 'available', 'not-needed', 'check', 'unknown')
$CaramosKindLabels = @{
    'windows-only' = 'Chỉ chạy trên Windows'
    'alternative'  = 'Có bản thay thế'
    'available'    = 'Có sẵn trong App Center'
    'not-needed'   = 'Không cần nữa'
    'check'        = 'Cần kiểm tra'
    'unknown'      = 'Chưa có gợi ý'
}

$CaramosNeedsAdminText = 'không đọc được (cần quyền quản trị)'

# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

function Write-CaramosStatus {
    [Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSAvoidUsingWriteHost', '', Justification = 'Progress messages for the person running the survey.')]
    param([string]$Message)
    if (-not $CaramosConfig.Quiet) { Write-Host $Message }
}

function ConvertTo-CaramosArray {
    param([AllowNull()][object]$Value)
    if ($null -eq $Value) { return , ([object[]]@()) }
    if ($Value -is [string]) { return , ([object[]]@($Value)) }
    if ($Value -is [System.Collections.IDictionary]) { return , ([object[]]@($Value)) }
    if ($Value -is [System.Collections.IEnumerable]) {
        $list = New-Object System.Collections.Generic.List[object]
        foreach ($item in $Value) { $list.Add($item) }
        return , ($list.ToArray())
    }
    return , ([object[]]@($Value))
}

function Get-CaramosValue {
    param([AllowNull()][object]$Object, [string]$Name)
    if ($null -eq $Object) { return $null }
    if ($Object -is [System.Collections.IDictionary]) {
        if ($Object.Contains($Name)) { return , $Object[$Name] }
        return $null
    }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    return , $property.Value
}

function Get-CaramosString {
    param([AllowNull()][object]$Object, [string]$Name)
    $value = Get-CaramosValue -Object $Object -Name $Name
    if ($null -eq $value) { return '' }
    return ([string]$value).Trim()
}

function ConvertTo-CaramosHtmlText {
    param([AllowNull()][object]$Value)
    if ($null -eq $Value) { return '' }
    $text = [string]$Value
    return $text.Replace('&', '&amp;').Replace('<', '&lt;').Replace('>', '&gt;').Replace('"', '&quot;').Replace("'", '&#39;')
}

function Get-CaramosNumberFormat {
    if ($null -eq $CaramosConfig.NumberFormat) {
        $format = [System.Globalization.CultureInfo]::InvariantCulture.NumberFormat.Clone()
        $format.NumberDecimalSeparator = ','
        $format.NumberGroupSeparator = '.'
        $CaramosConfig.NumberFormat = $format
    }
    return $CaramosConfig.NumberFormat
}

function Format-CaramosNumber {
    param([double]$Value, [int]$Decimals = 0)
    return $Value.ToString('N' + $Decimals, (Get-CaramosNumberFormat))
}

function Format-CaramosSize {
    param([double]$Bytes)
    if ($Bytes -le 0) { return '0 MB' }
    $mb = $Bytes / 1MB
    if ($mb -lt 1) { return 'dưới 1 MB' }
    if ($mb -lt 10) { return (Format-CaramosNumber -Value $mb -Decimals 1) + ' MB' }
    if ($mb -lt 1000) { return (Format-CaramosNumber -Value ([math]::Round($mb)) -Decimals 0) + ' MB' }
    $gb = $Bytes / 1GB
    if ($gb -lt 100) { return (Format-CaramosNumber -Value $gb -Decimals 1) + ' GB' }
    return (Format-CaramosNumber -Value ([math]::Round($gb)) -Decimals 0) + ' GB'
}

function Join-CaramosList {
    param([AllowNull()][object]$Items, [int]$Max = 0, [string]$MoreNoun = 'mục')
    $list = New-Object System.Collections.Generic.List[string]
    foreach ($item in (ConvertTo-CaramosArray $Items)) {
        if (-not [string]::IsNullOrWhiteSpace([string]$item)) { $list.Add(([string]$item).Trim()) }
    }
    if ($list.Count -eq 0) { return '' }
    if ($Max -gt 0 -and $list.Count -gt $Max) {
        $extra = $list.Count - $Max
        $shown = $list.GetRange(0, $Max).ToArray()
        return ($shown -join ', ') + ' và ' + $extra + ' ' + $MoreNoun + ' khác'
    }
    if ($list.Count -eq 1) { return $list[0] }
    $head = $list.GetRange(0, $list.Count - 1).ToArray()
    return ($head -join ', ') + ' và ' + $list[$list.Count - 1]
}

function ConvertTo-CaramosLowerFirst {
    param([AllowNull()][string]$Text)
    # "Có sẵn trong App Center" -> "có sẵn trong App Center"; "USB" stays "USB".
    if ([string]::IsNullOrEmpty($Text)) { return '' }
    if ($Text.Length -gt 1 -and [char]::IsUpper($Text[1])) { return $Text }
    return $Text.Substring(0, 1).ToLowerInvariant() + $Text.Substring(1)
}

function ConvertTo-CaramosComparablePath {
    param([AllowNull()][string]$Path)
    if ([string]::IsNullOrEmpty($Path)) { return '' }
    $result = $Path
    if ($result.StartsWith('\\?\UNC\')) { $result = '\\' + $result.Substring(8) }
    elseif ($result.StartsWith('\\?\')) { $result = $result.Substring(4) }
    if ($result.Length -gt 1) { $result = $result.TrimEnd([char[]]@('\', '/')) }
    return $result
}

function Test-CaramosPathUnder {
    param([AllowNull()][string]$Path, [AllowNull()][object]$Roots)
    $candidate = ConvertTo-CaramosComparablePath $Path
    if ($candidate.Length -eq 0) { return $false }
    foreach ($root in (ConvertTo-CaramosArray $Roots)) {
        $rootPath = ConvertTo-CaramosComparablePath ([string]$root)
        if ($rootPath.Length -eq 0) { continue }
        if ($candidate.Equals($rootPath, [System.StringComparison]::OrdinalIgnoreCase)) { return $true }
        if ($candidate.StartsWith($rootPath + '\', [System.StringComparison]::OrdinalIgnoreCase)) { return $true }
        if ($candidate.StartsWith($rootPath + '/', [System.StringComparison]::OrdinalIgnoreCase)) { return $true }
    }
    return $false
}

# ---------------------------------------------------------------------------
# Registry access through .NET (fast, and reads the 64-bit and 32-bit views
# explicitly, so WOW6432Node is covered even from a 32-bit PowerShell).
# ---------------------------------------------------------------------------

function Get-CaramosRegistryValue {
    param([string]$Hive, [string]$View = 'Default', [string]$Path, [string]$Name)
    $base = $null
    $key = $null
    try {
        $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]$Hive, [Microsoft.Win32.RegistryView]$View)
        $key = $base.OpenSubKey($Path)
        if ($null -eq $key) { return $null }
        return $key.GetValue($Name)
    }
    catch { return $null }
    finally {
        if ($null -ne $key) { $key.Close() }
        if ($null -ne $base) { $base.Close() }
    }
}

function Get-CaramosRegistryValueNames {
    param([string]$Hive, [string]$View = 'Default', [string]$Path)
    $base = $null
    $key = $null
    try {
        $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]$Hive, [Microsoft.Win32.RegistryView]$View)
        $key = $base.OpenSubKey($Path)
        if ($null -eq $key) { return $null }
        return , ([object[]]$key.GetValueNames())
    }
    catch { return $null }
    finally {
        if ($null -ne $key) { $key.Close() }
        if ($null -ne $base) { $base.Close() }
    }
}

function Get-CaramosRegistrySubKeys {
    param([string]$Hive, [string]$View = 'Default', [string]$Path, [string[]]$ValueNames, [string]$Scope)
    $items = New-Object System.Collections.Generic.List[object]
    $base = $null
    $key = $null
    try {
        $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]$Hive, [Microsoft.Win32.RegistryView]$View)
        $key = $base.OpenSubKey($Path)
        if ($null -ne $key) {
            foreach ($subName in $key.GetSubKeyNames()) {
                $sub = $null
                try {
                    $sub = $key.OpenSubKey($subName)
                    if ($null -ne $sub) {
                        $entry = [ordered]@{ KeyName = $subName; Scope = $Scope }
                        foreach ($valueName in $ValueNames) { $entry[$valueName] = $sub.GetValue($valueName) }
                        $items.Add([pscustomobject]$entry)
                    }
                }
                catch { }
                finally { if ($null -ne $sub) { $sub.Close() } }
            }
        }
    }
    catch { }
    finally {
        if ($null -ne $key) { $key.Close() }
        if ($null -ne $base) { $base.Close() }
    }
    return , ($items.ToArray())
}

# ---------------------------------------------------------------------------
# Probes: each one reads one thing from Windows. They never write anything.
# Tests replace them with mocks. A probe that cannot read anything throws;
# the caller records the section as unreadable and goes on.
# ---------------------------------------------------------------------------

function Get-CaramosComputerName {
    $name = $env:COMPUTERNAME
    if ([string]::IsNullOrEmpty($name)) { $name = [System.Environment]::MachineName }
    return [string]$name
}

function Get-CaramosDesktopPath {
    return [System.Environment]::GetFolderPath('DesktopDirectory')
}

function Get-CaramosUninstallEntries {
    # HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall (64-bit view),
    # HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall (32-bit view),
    # HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall.
    $path = 'Software\Microsoft\Windows\CurrentVersion\Uninstall'
    $names = @('DisplayName', 'DisplayVersion', 'Publisher', 'SystemComponent', 'ParentKeyName', 'ReleaseType')
    $all = New-Object System.Collections.Generic.List[object]
    $sources = @(
        @{ Hive = 'LocalMachine'; View = 'Registry64'; Scope = 'HKLM' },
        @{ Hive = 'LocalMachine'; View = 'Registry32'; Scope = 'HKLM32' },
        @{ Hive = 'CurrentUser'; View = 'Default'; Scope = 'HKCU' }
    )
    foreach ($source in $sources) {
        foreach ($entry in (Get-CaramosRegistrySubKeys -Hive $source.Hive -View $source.View -Path $path -ValueNames $names -Scope $source.Scope)) {
            $all.Add($entry)
        }
    }
    if ($all.Count -eq 0) { throw 'uninstall-registry-unreadable' }
    return , ($all.ToArray())
}

function Get-CaramosPrinterData {
    $items = New-Object System.Collections.Generic.List[object]
    $done = $false
    if (Get-Command -Name Get-Printer -ErrorAction SilentlyContinue) {
        try {
            foreach ($printer in @(Get-Printer -ErrorAction Stop)) {
                $items.Add([pscustomobject]@{
                        Name         = [string]$printer.Name
                        DriverName   = [string]$printer.DriverName
                        PortName     = [string]$printer.PortName
                        IsConnection = ([string]$printer.Type -eq 'Connection')
                    })
            }
            $done = $true
        }
        catch { $items.Clear() }
    }
    if (-not $done) {
        foreach ($printer in @(Get-CimInstance -ClassName Win32_Printer -ErrorAction Stop)) {
            $items.Add([pscustomobject]@{
                    Name         = [string]$printer.Name
                    DriverName   = [string]$printer.DriverName
                    PortName     = [string]$printer.PortName
                    IsConnection = [bool]$printer.Network
                })
        }
    }
    return , ($items.ToArray())
}

function Get-CaramosPnpDevices {
    $list = New-Object System.Collections.Generic.List[object]
    $done = $false
    if (Get-Command -Name Get-PnpDevice -ErrorAction SilentlyContinue) {
        try {
            foreach ($device in @(Get-PnpDevice -PresentOnly -ErrorAction Stop)) {
                $name = [string]$device.FriendlyName
                if ([string]::IsNullOrWhiteSpace($name)) { $name = [string]$device.Name }
                $list.Add([pscustomobject]@{
                        InstanceId   = [string]$device.InstanceId
                        Name         = $name
                        Class        = [string]$device.Class
                        ClassGuid    = [string]$device.ClassGuid
                        Manufacturer = [string]$device.Manufacturer
                    })
            }
            $done = $true
        }
        catch { $list.Clear() }
    }
    if (-not $done) {
        foreach ($device in @(Get-CimInstance -ClassName Win32_PnPEntity -ErrorAction Stop)) {
            $class = ''
            if ($null -ne $device.PSObject.Properties['PNPClass']) { $class = [string]$device.PNPClass }
            $list.Add([pscustomobject]@{
                    InstanceId   = [string]$device.DeviceID
                    Name         = [string]$device.Name
                    Class        = $class
                    ClassGuid    = [string]$device.ClassGuid
                    Manufacturer = [string]$device.Manufacturer
                })
        }
    }
    return , ($list.ToArray())
}

function Get-CaramosOfficeRegistryData {
    $clickToRun = $null
    foreach ($view in @('Registry64', 'Registry32')) {
        foreach ($path in @('SOFTWARE\Microsoft\Office\ClickToRun\Configuration', 'SOFTWARE\Microsoft\Office\15.0\ClickToRun\Configuration')) {
            if ($null -ne $clickToRun) { break }
            $version = Get-CaramosRegistryValue -Hive LocalMachine -View $view -Path $path -Name 'VersionToReport'
            if ($version) {
                $clickToRun = [ordered]@{
                    Version           = [string]$version
                    ProductReleaseIds = [string](Get-CaramosRegistryValue -Hive LocalMachine -View $view -Path $path -Name 'ProductReleaseIds')
                    Platform          = [string](Get-CaramosRegistryValue -Hive LocalMachine -View $view -Path $path -Name 'Platform')
                }
            }
        }
    }
    $msi = New-Object System.Collections.Generic.List[object]
    foreach ($version in @('16.0', '15.0', '14.0', '12.0', '11.0')) {
        $apps = New-Object System.Collections.Generic.List[string]
        $common = $false
        foreach ($view in @('Registry64', 'Registry32')) {
            if (Get-CaramosRegistryValue -Hive LocalMachine -View $view -Path ('SOFTWARE\Microsoft\Office\' + $version + '\Common\InstallRoot') -Name 'Path') { $common = $true }
            foreach ($app in @('Word', 'Excel', 'PowerPoint', 'Outlook', 'Access', 'Publisher', 'OneNote')) {
                if ($apps.Contains($app)) { continue }
                if (Get-CaramosRegistryValue -Hive LocalMachine -View $view -Path ('SOFTWARE\Microsoft\Office\' + $version + '\' + $app + '\InstallRoot') -Name 'Path') { $apps.Add($app) }
            }
        }
        if ($common -or $apps.Count -gt 0) { $msi.Add([ordered]@{ Version = $version; Apps = $apps.ToArray() }) }
    }
    return [ordered]@{ ClickToRun = $clickToRun; Msi = $msi.ToArray() }
}

function ConvertTo-CaramosMediaType {
    param([AllowNull()][object]$MediaType, [AllowNull()][object]$BusType)
    $media = [string]$MediaType
    $bus = [string]$BusType
    if ($media -eq 'SSD' -or $media -eq '4' -or $media -eq 'SCM' -or $media -eq '5') { return 'SSD' }
    if ($media -eq 'HDD' -or $media -eq '3') { return 'HDD' }
    if ($bus -eq 'NVMe' -or $bus -eq '17') { return 'SSD' }
    return $null
}

function ConvertTo-CaramosBusType {
    param([AllowNull()][object]$BusType)
    $map = @{ '7' = 'USB'; '8' = 'RAID'; '10' = 'SAS'; '11' = 'SATA'; '12' = 'SD'; '13' = 'MMC'; '17' = 'NVMe' }
    $bus = [string]$BusType
    if ($map.ContainsKey($bus)) { return $map[$bus] }
    if ([string]::IsNullOrWhiteSpace($bus) -or $bus -eq '0' -or $bus -eq 'Unknown') { return $null }
    return $bus
}

function Get-CaramosSystemInfo {
    $info = [ordered]@{
        Manufacturer = $null; Model = $null
        WindowsCaption = $null; WindowsDisplayVersion = $null; WindowsBuild = $null; WindowsUbr = $null
        Is64BitOs = $null
        CpuName = $null; CpuCores = $null; CpuThreads = $null; CpuArchitecture = $null; Cpu64Bit = $null
        RamBytes = $null
        SystemDrive = $null; DiskSizeBytes = $null; DiskFreeBytes = $null; DiskMediaType = $null; DiskBusType = $null
        Firmware = $null; SecureBoot = 'unknown'
        FailedProbes = @()
    }
    $failed = New-Object System.Collections.Generic.List[string]
    $currentVersion = 'SOFTWARE\Microsoft\Windows NT\CurrentVersion'

    try {
        $os = Get-CimInstance -ClassName Win32_OperatingSystem -ErrorAction Stop | Select-Object -First 1
        $info.WindowsCaption = ([string]$os.Caption).Trim()
        if ($os.BuildNumber) { $info.WindowsBuild = [int]$os.BuildNumber }
    }
    catch { $failed.Add('os') }
    try { $info.Is64BitOs = [System.Environment]::Is64BitOperatingSystem } catch { }
    $displayVersion = Get-CaramosRegistryValue -Hive LocalMachine -View Registry64 -Path $currentVersion -Name 'DisplayVersion'
    if (-not $displayVersion) { $displayVersion = Get-CaramosRegistryValue -Hive LocalMachine -View Registry64 -Path $currentVersion -Name 'ReleaseId' }
    if ($displayVersion) { $info.WindowsDisplayVersion = [string]$displayVersion }
    $ubr = Get-CaramosRegistryValue -Hive LocalMachine -View Registry64 -Path $currentVersion -Name 'UBR'
    if ($null -ne $ubr) { $info.WindowsUbr = [int]$ubr }
    if (-not $info.WindowsCaption) {
        $productName = Get-CaramosRegistryValue -Hive LocalMachine -View Registry64 -Path $currentVersion -Name 'ProductName'
        if ($productName) { $info.WindowsCaption = [string]$productName }
    }
    if (-not $info.WindowsBuild) {
        $build = Get-CaramosRegistryValue -Hive LocalMachine -View Registry64 -Path $currentVersion -Name 'CurrentBuildNumber'
        if ($build) { $info.WindowsBuild = [int]$build }
    }

    try {
        $computer = Get-CimInstance -ClassName Win32_ComputerSystem -ErrorAction Stop | Select-Object -First 1
        $info.Manufacturer = ([string]$computer.Manufacturer).Trim()
        $info.Model = ([string]$computer.Model).Trim()
        if ($computer.TotalPhysicalMemory) { $info.RamBytes = [double]$computer.TotalPhysicalMemory }
    }
    catch { $failed.Add('computer') }
    try {
        $installed = 0.0
        foreach ($module in @(Get-CimInstance -ClassName Win32_PhysicalMemory -ErrorAction Stop)) {
            if ($module.Capacity) { $installed += [double]$module.Capacity }
        }
        if ($installed -gt 0) { $info.RamBytes = $installed }
    }
    catch { }

    try {
        $cores = 0
        $threads = 0
        $names = New-Object System.Collections.Generic.List[string]
        foreach ($cpu in @(Get-CimInstance -ClassName Win32_Processor -ErrorAction Stop)) {
            $cpuName = (([string]$cpu.Name) -replace '\s+', ' ').Trim()
            if ($cpuName -and -not $names.Contains($cpuName)) { $names.Add($cpuName) }
            if ($cpu.NumberOfCores) { $cores += [int]$cpu.NumberOfCores }
            if ($cpu.NumberOfLogicalProcessors) { $threads += [int]$cpu.NumberOfLogicalProcessors }
            if ($null -ne $cpu.DataWidth) { $info.Cpu64Bit = ([int]$cpu.DataWidth -eq 64) }
            if ($null -ne $cpu.Architecture) {
                switch ([int]$cpu.Architecture) {
                    0 { $info.CpuArchitecture = 'x86' }
                    5 { $info.CpuArchitecture = 'arm' }
                    9 { $info.CpuArchitecture = 'x64' }
                    12 { $info.CpuArchitecture = 'arm64' }
                }
            }
        }
        if ($names.Count -gt 0) { $info.CpuName = ($names.ToArray() -join '; ') }
        if ($cores -gt 0) { $info.CpuCores = $cores }
        if ($threads -gt 0) { $info.CpuThreads = $threads }
    }
    catch { $failed.Add('cpu') }

    $drive = [string]$env:SystemDrive
    if ([string]::IsNullOrEmpty($drive)) { $drive = 'C:' }
    $info.SystemDrive = $drive
    try {
        $logical = Get-CimInstance -ClassName Win32_LogicalDisk -Filter ("DeviceID='" + $drive + "'") -ErrorAction Stop | Select-Object -First 1
        if ($null -ne $logical) {
            $info.DiskSizeBytes = [double]$logical.Size
            $info.DiskFreeBytes = [double]$logical.FreeSpace
        }
    }
    catch { $failed.Add('disk') }
    try {
        if (Get-Command -Name Get-PhysicalDisk -ErrorAction SilentlyContinue) {
            $disks = @(Get-PhysicalDisk -ErrorAction Stop)
            $target = $null
            try {
                $partition = Get-Partition -DriveLetter ($drive.TrimEnd(':')) -ErrorAction Stop | Select-Object -First 1
                if ($null -ne $partition) {
                    foreach ($disk in $disks) {
                        if ([string]$disk.DeviceId -eq [string]$partition.DiskNumber) { $target = $disk; break }
                    }
                }
            }
            catch { }
            if ($null -eq $target) {
                $internal = @($disks | Where-Object { (ConvertTo-CaramosBusType $_.BusType) -ne 'USB' })
                if ($internal.Count -eq 1) { $target = $internal[0] }
            }
            if ($null -ne $target) {
                $info.DiskMediaType = ConvertTo-CaramosMediaType -MediaType $target.MediaType -BusType $target.BusType
                $info.DiskBusType = ConvertTo-CaramosBusType $target.BusType
            }
        }
    }
    catch { }

    # Firmware: cmd.exe knows %firmware_type% on Windows 8 and later.
    $firmware = $null
    try {
        $type = [string]$env:firmware_type
        if (-not $type -and $env:SystemRoot) {
            $cmd = Join-Path ([string]$env:SystemRoot) 'System32\cmd.exe'
            if (Test-Path -LiteralPath $cmd) { $type = [string](& $cmd /d /c 'echo %firmware_type%' 2>$null | Select-Object -First 1) }
        }
        if ($type -match 'UEFI') { $firmware = 'UEFI' }
        elseif ($type -match 'Legacy|BIOS') { $firmware = 'BIOS' }
    }
    catch { }
    $secureBootRegistry = Get-CaramosRegistryValue -Hive LocalMachine -View Registry64 -Path 'SYSTEM\CurrentControlSet\Control\SecureBoot\State' -Name 'UEFISecureBootEnabled'
    if (-not $firmware -and $null -ne $secureBootRegistry) { $firmware = 'UEFI' }
    $info.Firmware = $firmware

    $secureBoot = 'unknown'
    if ($firmware -eq 'BIOS') { $secureBoot = 'unsupported' }
    else {
        if (Get-Command -Name Confirm-SecureBootUEFI -ErrorAction SilentlyContinue) {
            try {
                if (Confirm-SecureBootUEFI -ErrorAction Stop) { $secureBoot = 'on' } else { $secureBoot = 'off' }
            }
            catch {
                $errorText = [string]$_.FullyQualifiedErrorId + ' ' + $_.Exception.GetType().Name + ' ' + [string]$_.Exception.Message
                if ($errorText -match 'UnauthorizedAccess|Access') { $secureBoot = 'needs-admin' }
                elseif ($errorText -match 'NotSupported|not supported|undefined|0xC0000100') { $secureBoot = 'unsupported' }
                else { $secureBoot = 'needs-admin' }
            }
        }
        if (($secureBoot -eq 'needs-admin' -or $secureBoot -eq 'unknown') -and $null -ne $secureBootRegistry) {
            if ([int]$secureBootRegistry -eq 1) { $secureBoot = 'on' } else { $secureBoot = 'off' }
        }
    }
    $info.SecureBoot = $secureBoot
    $info.FailedProbes = $failed.ToArray()
    return $info
}

function Find-CaramosTpmInPnp {
    param([AllowNull()][object]$Devices)
    foreach ($device in (ConvertTo-CaramosArray $Devices)) {
        $name = Get-CaramosString $device 'Name'
        $class = Get-CaramosString $device 'Class'
        $match = [regex]::Match($name, 'Trusted Platform Module\s*(\d\.\d)')
        if ($match.Success) { return $match.Groups[1].Value }
        if ($class -eq 'SecurityDevices' -and $name -match 'TPM|Trusted Platform') { return '' }
    }
    return $null
}

function Get-CaramosTpmInfo {
    param([AllowNull()][object]$PnpDevices, [bool]$PnpRead = $false)
    $result = [ordered]@{ Status = 'unknown'; Version = $null; Source = $null }
    try {
        # Win32_Tpm needs administrator rights; a normal user gets "access denied".
        $tpm = Get-CimInstance -Namespace 'root/cimv2/Security/MicrosoftTpm' -ClassName Win32_Tpm -ErrorAction Stop | Select-Object -First 1
        $result.Source = 'Win32_Tpm'
        if ($null -eq $tpm) {
            $result.Status = 'not-found'
        }
        else {
            $result.Status = 'found'
            $spec = [string]$tpm.SpecVersion
            if ($spec) { $result.Version = ($spec -split ',')[0].Trim() }
        }
        return $result
    }
    catch { }
    $fromPnp = Find-CaramosTpmInPnp -Devices $PnpDevices
    if ($null -ne $fromPnp) {
        $result.Status = 'found'
        $result.Source = 'PnP'
        if ($fromPnp) { $result.Version = $fromPnp }
        return $result
    }
    if ($PnpRead -and (ConvertTo-CaramosArray $PnpDevices).Count -gt 0) {
        $result.Status = 'not-found-pnp'
        $result.Source = 'PnP'
        return $result
    }
    $result.Status = 'needs-admin'
    return $result
}

function Get-CaramosKnownFolders {
    $folders = New-Object System.Collections.Generic.List[object]
    $userShellFolders = 'Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders'
    $specs = @(
        @{ Key = 'Desktop'; Special = 'DesktopDirectory'; Registry = 'Desktop' },
        @{ Key = 'Documents'; Special = 'MyDocuments'; Registry = 'Personal' },
        @{ Key = 'Pictures'; Special = 'MyPictures'; Registry = 'My Pictures' },
        @{ Key = 'Downloads'; Special = $null; Registry = '{374DE290-123F-4565-9164-39C4925E467B}' },
        @{ Key = 'Music'; Special = 'MyMusic'; Registry = 'My Music' },
        @{ Key = 'Videos'; Special = 'MyVideos'; Registry = 'My Video' }
    )
    $profileRoot = [string]$env:USERPROFILE
    $paths = @{}
    foreach ($spec in $specs) {
        $path = $null
        if ($spec.Special) {
            try { $path = [System.Environment]::GetFolderPath($spec.Special) } catch { $path = $null }
        }
        if ([string]::IsNullOrEmpty($path)) {
            $value = Get-CaramosRegistryValue -Hive CurrentUser -Path $userShellFolders -Name $spec.Registry
            if ($value) { $path = [System.Environment]::ExpandEnvironmentVariables([string]$value) }
        }
        if ([string]::IsNullOrEmpty($path) -and $spec.Key -eq 'Downloads' -and $profileRoot) { $path = Join-Path $profileRoot 'Downloads' }
        $paths[$spec.Key] = $path
        $folders.Add([ordered]@{ Key = $spec.Key; Path = $path })
    }

    # Zalo PC saves received files in Documents\Zalo Received Files by default.
    $zaloCandidates = New-Object System.Collections.Generic.List[string]
    if ($paths['Documents']) { $zaloCandidates.Add((Join-Path $paths['Documents'] 'Zalo Received Files')) }
    if ($profileRoot) { $zaloCandidates.Add((Join-Path (Join-Path $profileRoot 'Documents') 'Zalo Received Files')) }
    $zalo = $null
    foreach ($candidate in $zaloCandidates) {
        if (Test-Path -LiteralPath $candidate -PathType Container) { $zalo = $candidate; break }
    }
    if ($null -eq $zalo -and $zaloCandidates.Count -gt 0) { $zalo = $zaloCandidates[0] }
    $folders.Add([ordered]@{ Key = 'ZaloReceived'; Path = $zalo })

    $zaloApp = New-Object System.Collections.Generic.List[string]
    if ($env:LOCALAPPDATA) { $zaloApp.Add((Join-Path ([string]$env:LOCALAPPDATA) 'ZaloPC')) }
    if ($env:APPDATA) { $zaloApp.Add((Join-Path ([string]$env:APPDATA) 'ZaloData')) }

    $outlook = New-Object System.Collections.Generic.List[string]
    if ($env:LOCALAPPDATA) { $outlook.Add((Join-Path (Join-Path ([string]$env:LOCALAPPDATA) 'Microsoft') 'Outlook')) }
    if ($env:APPDATA) { $outlook.Add((Join-Path (Join-Path ([string]$env:APPDATA) 'Microsoft') 'Outlook')) }

    $cloud = New-Object System.Collections.Generic.List[string]
    foreach ($value in @($env:OneDrive, $env:OneDriveCommercial, $env:OneDriveConsumer)) {
        if ($value -and -not $cloud.Contains([string]$value)) { $cloud.Add([string]$value) }
    }
    foreach ($account in (Get-CaramosRegistrySubKeys -Hive CurrentUser -Path 'Software\Microsoft\OneDrive\Accounts' -ValueNames @('UserFolder') -Scope 'HKCU')) {
        $folder = [string]$account.UserFolder
        if ($folder -and -not $cloud.Contains($folder)) { $cloud.Add($folder) }
    }

    return [ordered]@{
        Folders     = $folders.ToArray()
        ZaloApp     = $zaloApp.ToArray()
        Outlook     = $outlook.ToArray()
        CloudRoots  = $cloud.ToArray()
        ProfileRoot = $profileRoot
    }
}

function Get-CaramosFontData {
    $system = Get-CaramosRegistryValueNames -Hive LocalMachine -View Registry64 -Path 'SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts'
    $user = Get-CaramosRegistryValueNames -Hive CurrentUser -Path 'SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts'
    if ($null -eq $system -and $null -eq $user) { throw 'fonts-unreadable' }
    return [ordered]@{ System = (ConvertTo-CaramosArray $system); User = (ConvertTo-CaramosArray $user) }
}

# ---------------------------------------------------------------------------
# Programs and the advice table
# ---------------------------------------------------------------------------

function Select-CaramosPrograms {
    param([AllowNull()][object]$Entries)
    $seen = @{}
    $result = New-Object System.Collections.Generic.List[object]
    foreach ($entry in (ConvertTo-CaramosArray $Entries)) {
        $name = Get-CaramosString $entry 'DisplayName'
        if ($name.Length -eq 0) { continue }
        if ((Get-CaramosString $entry 'SystemComponent') -eq '1') { continue }
        if ((Get-CaramosString $entry 'ParentKeyName').Length -gt 0) { continue }
        if ($name -match '\bKB\d{6,8}\b' -or (Get-CaramosString $entry 'KeyName') -match '^KB\d{6,8}$') { continue }
        if ((Get-CaramosString $entry 'ReleaseType') -match '^(Security Update|Update|Hotfix|Update Rollup|Service Pack)$') { continue }
        $version = Get-CaramosString $entry 'DisplayVersion'
        $publisher = Get-CaramosString $entry 'Publisher'
        $scopeValue = Get-CaramosString $entry 'Scope'
        $scope = 'machine'
        if ($scopeValue -eq 'HKCU') { $scope = 'user' }
        $key = $name.ToLowerInvariant() + '|' + $version.ToLowerInvariant()
        if ($seen.ContainsKey($key)) {
            $existing = $seen[$key]
            if (-not $existing.Publisher -and $publisher) { $existing.Publisher = $publisher }
            continue
        }
        $program = [pscustomobject]@{ Name = $name; Version = $version; Publisher = $publisher; Scope = $scope }
        $seen[$key] = $program
        $result.Add($program)
    }
    $sorted = @($result.ToArray() | Sort-Object -Property @{ Expression = { $_.Name.ToLowerInvariant() } }, Version)
    return , ([object[]]$sorted)
}

function New-CaramosRegexList {
    param([AllowNull()][object]$Patterns, [System.Collections.Generic.List[string]]$Problems, [string]$Id)
    $options = [System.Text.RegularExpressions.RegexOptions]::IgnoreCase -bor [System.Text.RegularExpressions.RegexOptions]::CultureInvariant
    $list = New-Object System.Collections.Generic.List[object]
    foreach ($pattern in (ConvertTo-CaramosArray $Patterns)) {
        if ([string]::IsNullOrEmpty([string]$pattern)) { continue }
        try {
            $text = ([string]$pattern).Normalize([System.Text.NormalizationForm]::FormC)
            $list.Add((New-Object System.Text.RegularExpressions.Regex -ArgumentList $text, $options))
        }
        catch { if ($null -ne $Problems) { $Problems.Add($Id + ': ' + [string]$pattern) } }
    }
    return , ($list.ToArray())
}

function Import-CaramosAdviceTable {
    param([Parameter(Mandatory = $true)][string]$Path)
    $text = [System.IO.File]::ReadAllText($Path, (New-Object System.Text.UTF8Encoding -ArgumentList $false))
    if ($text.Length -gt 0 -and $text[0] -eq [char]0xFEFF) { $text = $text.Substring(1) }
    $data = ConvertFrom-Json -InputObject $text
    $problems = New-Object System.Collections.Generic.List[string]
    $programs = New-Object System.Collections.Generic.List[object]
    foreach ($entry in (ConvertTo-CaramosArray (Get-CaramosValue $data 'programs'))) {
        $programs.Add([pscustomobject]@{
                Id        = Get-CaramosString $entry 'id'
                Name      = Get-CaramosString $entry 'name'
                Kind      = Get-CaramosString $entry 'kind'
                Advice    = Get-CaramosString $entry 'advice'
                Match     = New-CaramosRegexList -Patterns (Get-CaramosValue $entry 'match') -Problems $problems -Id (Get-CaramosString $entry 'id')
                Publisher = New-CaramosRegexList -Patterns (Get-CaramosValue $entry 'publisher') -Problems $problems -Id (Get-CaramosString $entry 'id')
                Exclude   = New-CaramosRegexList -Patterns (Get-CaramosValue $entry 'exclude') -Problems $problems -Id (Get-CaramosString $entry 'id')
            })
    }
    $devices = New-Object System.Collections.Generic.List[object]
    foreach ($entry in (ConvertTo-CaramosArray (Get-CaramosValue $data 'devices'))) {
        $devices.Add([pscustomobject]@{
                Id        = Get-CaramosString $entry 'id'
                AppliesTo = ConvertTo-CaramosArray (Get-CaramosValue $entry 'appliesTo')
                Advice    = Get-CaramosString $entry 'advice'
                Match     = New-CaramosRegexList -Patterns (Get-CaramosValue $entry 'match') -Problems $problems -Id (Get-CaramosString $entry 'id')
                Exclude   = New-CaramosRegexList -Patterns (Get-CaramosValue $entry 'exclude') -Problems $problems -Id (Get-CaramosString $entry 'id')
            })
    }
    $defaults = Get-CaramosValue $data 'defaults'
    $usbNotes = @{}
    $notes = Get-CaramosValue $data 'usbClassNotes'
    if ($null -ne $notes) {
        foreach ($property in $notes.PSObject.Properties) { $usbNotes[$property.Name] = [string]$property.Value }
    }
    return [pscustomobject]@{
        Updated  = Get-CaramosString $data 'updated'
        Programs = $programs.ToArray()
        Devices  = $devices.ToArray()
        Defaults = [pscustomobject]@{
            Printer        = Get-CaramosString $defaults 'printer'
            NetworkPrinter = Get-CaramosString $defaults 'networkPrinter'
            SharedPrinter  = Get-CaramosString $defaults 'sharedPrinter'
            Scanner        = Get-CaramosString $defaults 'scanner'
        }
        UsbNotes = $usbNotes
        Problems = $problems.ToArray()
    }
}

function Test-CaramosAnyMatch {
    param([AllowNull()][object]$Regexes, [string]$Text)
    foreach ($regex in (ConvertTo-CaramosArray $Regexes)) {
        if ($regex.IsMatch($Text)) { return $true }
    }
    return $false
}

function Find-CaramosProgramAdvice {
    param([Parameter(Mandatory = $true)][object]$Program, [AllowNull()][object]$Table)
    if ($null -eq $Table) { return $null }
    $name = ([string]$Program.Name).Normalize([System.Text.NormalizationForm]::FormC)
    $publisher = ([string]$Program.Publisher).Normalize([System.Text.NormalizationForm]::FormC)
    foreach ($entry in $Table.Programs) {
        $hasName = ($entry.Match.Count -gt 0)
        $hasPublisher = ($entry.Publisher.Count -gt 0)
        if (-not $hasName -and -not $hasPublisher) { continue }
        if ($hasName -and -not (Test-CaramosAnyMatch -Regexes $entry.Match -Text $name)) { continue }
        if ($hasPublisher -and -not (Test-CaramosAnyMatch -Regexes $entry.Publisher -Text $publisher)) { continue }
        if ($entry.Exclude.Count -gt 0 -and (Test-CaramosAnyMatch -Regexes $entry.Exclude -Text $name)) { continue }
        return $entry
    }
    return $null
}

function ConvertTo-CaramosProgramItems {
    param([AllowNull()][object]$Programs, [AllowNull()][object]$Table)
    $items = New-Object System.Collections.Generic.List[object]
    foreach ($program in (ConvertTo-CaramosArray $Programs)) {
        $advice = Find-CaramosProgramAdvice -Program $program -Table $Table
        $kind = 'unknown'
        $adviceId = $null
        $adviceName = $null
        $adviceText = $null
        if ($null -ne $advice -and $CaramosKindLabels.ContainsKey($advice.Kind)) {
            $kind = $advice.Kind
            $adviceId = $advice.Id
            $adviceName = $advice.Name
            $adviceText = $advice.Advice
        }
        $items.Add([ordered]@{
                name       = $program.Name
                version    = $program.Version
                publisher  = $program.Publisher
                scope      = $program.Scope
                kind       = $kind
                adviceId   = $adviceId
                adviceName = $adviceName
                advice     = $adviceText
            })
    }
    return , ($items.ToArray())
}

# ---------------------------------------------------------------------------
# Printers, scanners, USB devices, TPM
# ---------------------------------------------------------------------------

function Get-CaramosVidPid {
    param([AllowNull()][string]$InstanceId)
    if ([string]::IsNullOrEmpty($InstanceId)) { return $null }
    $match = [regex]::Match($InstanceId, 'VID_([0-9A-Fa-f]{4})&PID_([0-9A-Fa-f]{4})')
    if ($match.Success) { return ($match.Groups[1].Value + ':' + $match.Groups[2].Value).ToLowerInvariant() }
    return $null
}

function Resolve-CaramosPnpClass {
    param([AllowNull()][string]$Class, [AllowNull()][string]$ClassGuid)
    if (-not [string]::IsNullOrWhiteSpace($Class)) { return $Class.Trim() }
    $guids = @{
        '{6bdd1fc6-810f-11d0-bec7-08002be2092f}' = 'Image'
        '{ca3e7ab9-b4c3-4ae6-8251-579ef933890f}' = 'Camera'
        '{4d36e96b-e325-11ce-bfc1-08002be10318}' = 'Keyboard'
        '{4d36e96f-e325-11ce-bfc1-08002be10318}' = 'Mouse'
        '{4d36e979-e325-11ce-bfc1-08002be10318}' = 'Printer'
        '{36fc9e60-c465-11cf-8056-444553540000}' = 'USB'
        '{745a17a0-74d3-11d0-b6fe-00a0c90f57da}' = 'HIDClass'
        '{50dd5230-ba8a-11d1-bf5d-0000f805f530}' = 'SmartCardReader'
        '{990a2bd7-e738-46c7-b26f-1cf8fb9f1391}' = 'SmartCard'
        '{53d29ef7-377c-4d14-864b-eb3a85769359}' = 'Biometric'
        '{e0cbf06c-cd8b-4647-bb8a-263b43f0f974}' = 'Bluetooth'
        '{4d36e972-e325-11ce-bfc1-08002be10318}' = 'Net'
        '{4d36e96c-e325-11ce-bfc1-08002be10318}' = 'MEDIA'
        '{eec5ad98-8080-425f-922a-dabf3de3f69a}' = 'WPD'
        '{4d36e978-e325-11ce-bfc1-08002be10318}' = 'Ports'
        '{4d36e967-e325-11ce-bfc1-08002be10318}' = 'DiskDrive'
        '{d94ee5d8-d189-4994-83d2-f68d7d41b0e6}' = 'SecurityDevices'
        '{4d36e96d-e325-11ce-bfc1-08002be10318}' = 'Modem'
    }
    $key = ([string]$ClassGuid).Trim().ToLowerInvariant()
    if ($guids.ContainsKey($key)) { return $guids[$key] }
    return ''
}

function Get-CaramosClassLabel {
    param([string]$Class)
    $labels = @{
        'Image' = 'Máy quét, máy ảnh'; 'Camera' = 'Camera'; 'Printer' = 'Máy in'; 'USB' = 'USB'
        'HIDClass' = 'Thiết bị nhập'; 'Keyboard' = 'Bàn phím'; 'Mouse' = 'Chuột'
        'SmartCardReader' = 'Đầu đọc thẻ, USB token'; 'SmartCard' = 'Thẻ, USB token'
        'Biometric' = 'Đầu đọc vân tay'; 'Bluetooth' = 'Bluetooth'; 'Net' = 'Mạng'
        'MEDIA' = 'Âm thanh'; 'AudioEndpoint' = 'Âm thanh'; 'WPD' = 'Điện thoại, máy nghe nhạc'
        'Ports' = 'Cổng COM'; 'DiskDrive' = 'Ổ đĩa'; 'CDROM' = 'Ổ đĩa quang'; 'Modem' = 'Modem'
        'SecurityDevices' = 'Bảo mật'
    }
    if ($labels.ContainsKey($Class)) { return $labels[$Class] }
    if ([string]::IsNullOrWhiteSpace($Class)) { return 'Khác' }
    return $Class
}

function Test-CaramosCameraName {
    param([AllowNull()][string]$Name)
    return ([string]$Name -match '(?i)camera|webcam|\bcam\b|\buvc\b')
}

function Find-CaramosDeviceAdvice {
    param([string]$Text, [string]$Kind, [AllowNull()][object]$Table)
    if ($null -eq $Table) { return $null }
    $normalized = $Text.Normalize([System.Text.NormalizationForm]::FormC)
    foreach ($entry in $Table.Devices) {
        if (@($entry.AppliesTo) -notcontains $Kind) { continue }
        if ($entry.Match.Count -eq 0) { continue }
        if (-not (Test-CaramosAnyMatch -Regexes $entry.Match -Text $normalized)) { continue }
        if ($entry.Exclude.Count -gt 0 -and (Test-CaramosAnyMatch -Regexes $entry.Exclude -Text $normalized)) { continue }
        return $entry.Advice
    }
    return $null
}

function Get-CaramosPrinterConnection {
    param([string]$Name, [string]$DriverName, [string]$PortName, [bool]$IsConnection)
    $virtualPattern = '(?i)Microsoft Print to PDF|Microsoft XPS Document Writer|OneNote|\bFax\b|Adobe PDF|Foxit (PDF|Reader PDF|PhantomPDF)|PDF24|PDFCreator|doPDF|CutePDF|Bullzip|novaPDF|Nitro PDF|Snagit|WPS PDF|Document Image Writer|Print to Evernote|Root Print Queue|\(redirected \d+\)'
    $virtualPorts = '(?i)^(PORTPROMPT:|nul:?|SHRFAX:|XPSPort:|FILE:|PDF:|TS\d+|Ne\d\d:|.*OneNote.*|.*\.pdf)$'
    if (($Name + ' ' + $DriverName) -match $virtualPattern -or $PortName -match $virtualPorts) {
        return @{ Kind = 'virtual'; Label = 'Máy in ảo'; Address = $null }
    }
    if ($Name.StartsWith('\\')) { return @{ Kind = 'shared'; Label = 'Dùng chung từ máy khác'; Address = $null } }
    if ($PortName -match '(?i)^(USB\d+|DOT4|USBPRINT)') { return @{ Kind = 'usb'; Label = 'USB'; Address = $null } }
    $ip = [regex]::Match($PortName, '(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})')
    if ($ip.Success) { return @{ Kind = 'network'; Label = 'Mạng'; Address = $ip.Groups[1].Value } }
    if ($PortName -match '(?i)^(WSD|IP_|https?://|LPR)') { return @{ Kind = 'network'; Label = 'Mạng'; Address = $null } }
    if ($IsConnection) { return @{ Kind = 'shared'; Label = 'Dùng chung từ máy khác'; Address = $null } }
    if ($PortName -match '(?i)^LPT\d') { return @{ Kind = 'lpt'; Label = 'Cổng LPT'; Address = $null } }
    if ($PortName -match '(?i)^COM\d') { return @{ Kind = 'com'; Label = 'Cổng COM'; Address = $null } }
    return @{ Kind = 'other'; Label = 'Khác'; Address = $null }
}

function ConvertTo-CaramosPrinterItems {
    param([AllowNull()][object]$Printers, [AllowNull()][object]$Table)
    $items = New-Object System.Collections.Generic.List[object]
    $seen = @{}
    foreach ($printer in (ConvertTo-CaramosArray $Printers)) {
        $name = Get-CaramosString $printer 'Name'
        if ($name.Length -eq 0 -or $seen.ContainsKey($name.ToLowerInvariant())) { continue }
        $seen[$name.ToLowerInvariant()] = $true
        $driver = Get-CaramosString $printer 'DriverName'
        $port = Get-CaramosString $printer 'PortName'
        $connection = Get-CaramosPrinterConnection -Name $name -DriverName $driver -PortName $port -IsConnection ([bool](Get-CaramosValue $printer 'IsConnection'))
        $isVirtual = ($connection.Kind -eq 'virtual')
        $advice = $null
        if (-not $isVirtual) {
            $advice = Find-CaramosDeviceAdvice -Text ($name + ' ' + $driver) -Kind 'printer' -Table $Table
            if (-not $advice -and $null -ne $Table) {
                if ($connection.Kind -eq 'network') { $advice = $Table.Defaults.NetworkPrinter }
                elseif ($connection.Kind -eq 'shared' -and $Table.Defaults.SharedPrinter) { $advice = $Table.Defaults.SharedPrinter }
                else { $advice = $Table.Defaults.Printer }
            }
        }
        $items.Add([ordered]@{
                name            = $name
                driver          = $driver
                connection      = $connection.Kind
                connectionLabel = $connection.Label
                address         = $connection.Address
                virtual         = $isVirtual
                advice          = $advice
            })
    }
    return , ($items.ToArray())
}

function Get-CaramosScannerItems {
    param([AllowNull()][object]$Devices, [AllowNull()][object]$Table)
    $items = New-Object System.Collections.Generic.List[object]
    $seen = @{}
    foreach ($device in (ConvertTo-CaramosArray $Devices)) {
        $class = Resolve-CaramosPnpClass -Class (Get-CaramosString $device 'Class') -ClassGuid (Get-CaramosString $device 'ClassGuid')
        if ($class -ne 'Image') { continue }
        $name = Get-CaramosString $device 'Name'
        if ($name.Length -eq 0 -or (Test-CaramosCameraName $name)) { continue }
        $vidPid = Get-CaramosVidPid (Get-CaramosString $device 'InstanceId')
        $key = ($name + '|' + $vidPid).ToLowerInvariant()
        if ($seen.ContainsKey($key)) { continue }
        $seen[$key] = $true
        $advice = Find-CaramosDeviceAdvice -Text $name -Kind 'scanner' -Table $Table
        if (-not $advice -and $null -ne $Table) { $advice = $Table.Defaults.Scanner }
        $items.Add([ordered]@{ name = $name; vidPid = $vidPid; advice = $advice })
    }
    return , ($items.ToArray())
}

function Get-CaramosUsbSummary {
    param([AllowNull()][object]$Devices, [AllowNull()][object]$Table)
    $noise = '(?i)^(USB Root Hub.*|Generic (SuperSpeed )?USB Hub|USB Hub|.*Root Hub.*|USB Composite Device|USB Input Device|.*Host Controller.*|USB Mass Storage Device|USB Attached SCSI.*|USB Printing Support|HID-compliant .*|USB Device|Unknown USB Device.*|Generic Bluetooth Radio)$'
    $keyboards = @{}
    $mice = @{}
    $rows = New-Object System.Collections.Generic.List[object]
    $index = @{}
    foreach ($device in (ConvertTo-CaramosArray $Devices)) {
        $instance = Get-CaramosString $device 'InstanceId'
        $name = Get-CaramosString $device 'Name'
        $class = Resolve-CaramosPnpClass -Class (Get-CaramosString $device 'Class') -ClassGuid (Get-CaramosString $device 'ClassGuid')
        $vidPid = Get-CaramosVidPid $instance
        $identity = $vidPid
        if (-not $identity) { $identity = $instance }
        if ($class -eq 'Keyboard') { $keyboards[$identity] = $true; continue }
        if ($class -eq 'Mouse') { $mice[$identity] = $true; continue }
        if (-not $instance.StartsWith('USB\', [System.StringComparison]::OrdinalIgnoreCase)) { continue }
        if ($instance -match '(?i)^USB\\ROOT_HUB') { continue }
        if ($name.Length -eq 0 -or $name -match $noise) { continue }
        if ($class -eq 'USB' -and $name -match '(?i)hub|composite') { continue }
        if ($class -eq 'Printer') { continue }
        if ($class -eq 'Image') {
            if (-not (Test-CaramosCameraName $name)) { continue }
            $class = 'Camera'
        }
        $key = ($name + '|' + $class + '|' + $vidPid).ToLowerInvariant()
        if ($index.ContainsKey($key)) { $index[$key].quantity = $index[$key].quantity + 1; continue }
        $note = $null
        if ($null -ne $Table -and $Table.UsbNotes.ContainsKey($class)) { $note = $Table.UsbNotes[$class] }
        $row = [ordered]@{ name = $name; class = $class; classLabel = (Get-CaramosClassLabel $class); vidPid = $vidPid; quantity = 1; note = $note }
        $index[$key] = $row
        $rows.Add($row)
    }
    $sorted = @($rows.ToArray() | Sort-Object -Property @{ Expression = { $_.classLabel } }, @{ Expression = { $_.name } })
    return [ordered]@{
        status    = 'ok'
        keyboards = $keyboards.Count
        mice      = $mice.Count
        items     = [object[]]$sorted
    }
}

# ---------------------------------------------------------------------------
# Microsoft Office
# ---------------------------------------------------------------------------

function ConvertTo-CaramosOfficeProductName {
    param([string]$Id)
    $specials = @{
        'O365ProPlusRetail' = 'Microsoft 365 Apps for enterprise'
        'O365BusinessRetail' = 'Microsoft 365 Apps for business'
        'O365HomePremRetail' = 'Microsoft 365 Family hoặc Personal'
        'O365SmallBusPremRetail' = 'Microsoft 365 Business'
    }
    if ($specials.ContainsKey($Id)) { return $specials[$Id] + ' (thuê bao)' }
    if ($Id -match '^O365') { return 'Microsoft 365 (thuê bao)' }
    $core = $Id -replace '(Retail|Volume)$', ''
    $year = '2016'
    $yearMatch = [regex]::Match($core, '(\d{4})$')
    if ($yearMatch.Success) {
        $year = $yearMatch.Groups[1].Value
        $core = $core.Substring(0, $core.Length - 4)
    }
    $families = @{
        'ProPlus' = 'Office Professional Plus'; 'Standard' = 'Office Standard'; 'Professional' = 'Office Professional'
        'HomeStudent' = 'Office Home & Student'; 'HomeBusiness' = 'Office Home & Business'; 'Home' = 'Office Home'
        'Personal' = 'Office Personal'; 'VisioPro' = 'Visio Professional'; 'VisioStd' = 'Visio Standard'
        'ProjectPro' = 'Project Professional'; 'ProjectStd' = 'Project Standard'; 'Access' = 'Access'
        'Word' = 'Word'; 'Excel' = 'Excel'; 'PowerPoint' = 'PowerPoint'; 'Outlook' = 'Outlook'; 'Publisher' = 'Publisher'
    }
    if ($families.ContainsKey($core)) { return $families[$core] + ' ' + $year + ' (mua một lần)' }
    return $Id
}

function Get-CaramosOfficeSummary {
    param([AllowNull()][object]$Registry, [AllowNull()][object]$ProgramItems, [bool]$RegistryRead = $true)
    $msiNames = @{ '16.0' = 'Office 2016'; '15.0' = 'Office 2013'; '14.0' = 'Office 2010'; '12.0' = 'Office 2007'; '11.0' = 'Office 2003' }
    $clickToRun = $null
    $c2r = Get-CaramosValue $Registry 'ClickToRun'
    if ($null -ne $c2r) {
        $products = New-Object System.Collections.Generic.List[object]
        foreach ($id in ((Get-CaramosString $c2r 'ProductReleaseIds') -split ',')) {
            $trimmed = $id.Trim()
            if ($trimmed) { $products.Add([ordered]@{ id = $trimmed; name = (ConvertTo-CaramosOfficeProductName $trimmed) }) }
        }
        $clickToRun = [ordered]@{
            version  = Get-CaramosString $c2r 'Version'
            platform = Get-CaramosString $c2r 'Platform'
            products = $products.ToArray()
        }
    }
    $msi = New-Object System.Collections.Generic.List[object]
    foreach ($entry in (ConvertTo-CaramosArray (Get-CaramosValue $Registry 'Msi'))) {
        $version = Get-CaramosString $entry 'Version'
        if ($null -ne $clickToRun -and $version -eq '16.0') { continue }
        $name = $version
        if ($msiNames.ContainsKey($version)) { $name = $msiNames[$version] }
        $msi.Add([ordered]@{ version = $version; name = $name; apps = (ConvertTo-CaramosArray (Get-CaramosValue $entry 'Apps')) })
    }
    $editions = New-Object System.Collections.Generic.List[string]
    $others = New-Object System.Collections.Generic.List[object]
    foreach ($item in (ConvertTo-CaramosArray $ProgramItems)) {
        if ($item.adviceId -eq 'ms-office') {
            $text = $item.name
            if ($item.version) { $text = $text + ' ' + $item.version }
            if (-not $editions.Contains($text)) { $editions.Add($text) }
        }
        elseif ($item.adviceId -eq 'wps' -or $item.adviceId -eq 'onlyoffice' -or $item.adviceId -eq 'libreoffice' -or $item.adviceId -eq 'openoffice') {
            $others.Add([ordered]@{ name = $item.name; version = $item.version })
        }
    }
    $status = 'ok'
    if (-not $RegistryRead) { $status = 'partial' }
    return [ordered]@{
        status      = $status
        found       = ($null -ne $clickToRun -or $msi.Count -gt 0 -or $editions.Count -gt 0)
        editions    = $editions.ToArray()
        clickToRun  = $clickToRun
        msi         = $msi.ToArray()
        otherSuites = $others.ToArray()
    }
}

# ---------------------------------------------------------------------------
# Profile folders: sizes and counts only, never names.
# ---------------------------------------------------------------------------

function Get-CaramosFolderLabel {
    param([string]$Key)
    $labels = @{
        'Desktop' = 'Màn hình nền (Desktop)'; 'Documents' = 'Tài liệu (Documents)'; 'Pictures' = 'Ảnh (Pictures)'
        'Downloads' = 'Tải xuống (Downloads)'; 'Music' = 'Nhạc (Music)'; 'Videos' = 'Video (Videos)'
        'ZaloReceived' = 'Zalo Received Files'
    }
    if ($labels.ContainsKey($Key)) { return $labels[$Key] }
    return $Key
}

function Test-CaramosNetworkPath {
    param([string]$Path)
    if ($Path.StartsWith('\\') -and -not $Path.StartsWith('\\?\')) { return $true }
    if ($Path -match '^[A-Za-z]:\\' -and [System.IO.Path]::DirectorySeparatorChar -eq '\') {
        try {
            $drive = New-Object System.IO.DriveInfo -ArgumentList ($Path.Substring(0, 1))
            if ([string]$drive.DriveType -eq 'Network') { return $true }
        }
        catch { }
    }
    return $false
}

function Get-CaramosFolderLocation {
    param([string]$Path, [AllowNull()][object]$CloudRoots, [AllowNull()][string]$ProfileRoot)
    if (Test-CaramosPathUnder -Path $Path -Roots $CloudRoots) { return 'onedrive' }
    if ($ProfileRoot -and (Test-CaramosPathUnder -Path $Path -Roots @($ProfileRoot))) { return 'default' }
    if ($Path -match '^([A-Za-z]):') {
        $letter = $Matches[1].ToUpperInvariant()
        if (-not $ProfileRoot -or -not $ProfileRoot.StartsWith($letter + ':', [System.StringComparison]::OrdinalIgnoreCase)) { return 'drive:' + $letter }
    }
    return 'other'
}

function New-CaramosFolderPlan {
    param([Parameter(Mandatory = $true)][object]$Known)
    $cloudRoots = ConvertTo-CaramosArray (Get-CaramosValue $Known 'CloudRoots')
    $profileRoot = Get-CaramosString $Known 'ProfileRoot'
    $items = New-Object System.Collections.Generic.List[object]
    foreach ($folder in (ConvertTo-CaramosArray (Get-CaramosValue $Known 'Folders'))) {
        $key = Get-CaramosString $folder 'Key'
        $path = Get-CaramosString $folder 'Path'
        $item = [ordered]@{ key = $key; label = (Get-CaramosFolderLabel $key); status = 'scan'; location = $null; sameAs = $null; excludes = @(); Path = $null; Exclude = @() }
        if ($path.Length -eq 0) { $item.status = 'not-set' }
        elseif (Test-CaramosNetworkPath $path) { $item.status = 'network' }
        elseif (-not (Test-Path -LiteralPath $path -PathType Container)) { $item.status = 'missing' }
        else {
            $full = $path
            try { $full = [System.IO.Path]::GetFullPath($path) } catch { }
            $item.Path = ConvertTo-CaramosComparablePath $full
            $item.location = Get-CaramosFolderLocation -Path $item.Path -CloudRoots $cloudRoots -ProfileRoot $profileRoot
            foreach ($earlier in $items) {
                if ($earlier.status -eq 'scan' -and $earlier.Path.Equals($item.Path, [System.StringComparison]::OrdinalIgnoreCase)) {
                    $item.status = 'same-as'
                    $item.sameAs = $earlier.key
                    break
                }
            }
        }
        $items.Add($item)
    }
    # A folder that lies inside another one (Zalo Received Files inside Documents)
    # is counted on its own row and skipped while walking the outer folder.
    foreach ($outer in $items) {
        if ($outer.status -ne 'scan') { continue }
        $excludePaths = New-Object System.Collections.Generic.List[string]
        $excludeKeys = New-Object System.Collections.Generic.List[string]
        foreach ($inner in $items) {
            if ([object]::ReferenceEquals($inner, $outer) -or $inner.status -ne 'scan') { continue }
            if ($inner.Path.Length -gt $outer.Path.Length -and (Test-CaramosPathUnder -Path $inner.Path -Roots @($outer.Path))) {
                $excludePaths.Add($inner.Path)
                $excludeKeys.Add($inner.key)
            }
        }
        $outer.Exclude = $excludePaths.ToArray()
        $outer.excludes = $excludeKeys.ToArray()
    }
    $extra = @{}
    foreach ($group in @('ZaloApp', 'Outlook')) {
        $paths = New-Object System.Collections.Generic.List[string]
        foreach ($path in (ConvertTo-CaramosArray (Get-CaramosValue $Known $group))) {
            $text = [string]$path
            if ($text -and -not (Test-CaramosNetworkPath $text) -and (Test-Path -LiteralPath $text -PathType Container)) { $paths.Add($text) }
        }
        $extra[$group] = $paths.ToArray()
    }
    return [ordered]@{
        Items      = $items.ToArray()
        ZaloApp    = $extra['ZaloApp']
        Outlook    = $extra['Outlook']
        CloudRoots = $cloudRoots
    }
}

function Test-CaramosLongPathSupport {
    if ($null -ne $CaramosConfig.UseLongPaths) { return [bool]$CaramosConfig.UseLongPaths }
    $supported = $false
    if ([System.IO.Path]::DirectorySeparatorChar -eq '\') {
        try {
            $probe = New-Object System.IO.DirectoryInfo -ArgumentList ('\\?\' + [System.Environment]::SystemDirectory)
            $supported = $probe.Exists
        }
        catch { $supported = $false }
    }
    $CaramosConfig.UseLongPaths = $supported
    return $supported
}

function Get-CaramosDirectoryEntry {
    param([string]$Path)
    $candidates = New-Object System.Collections.Generic.List[string]
    if ((Test-CaramosLongPathSupport) -and -not $Path.StartsWith('\\')) { $candidates.Add('\\?\' + $Path) }
    $candidates.Add($Path)
    foreach ($candidate in $candidates) {
        try {
            $directory = New-Object System.IO.DirectoryInfo -ArgumentList $candidate
            if ($directory.Exists) { return $directory }
        }
        catch { }
    }
    return $null
}

function Get-CaramosChildEntries {
    param([object]$Directory)
    # Lazy enumeration: names are never stored, only attributes, sizes and extensions are read.
    $entries = $Directory.EnumerateFileSystemInfos()
    return , $entries
}

function Get-CaramosLinkKind {
    param([object]$Entry, [bool]$HasLinkType)
    # 'link' = junction or symbolic link (skipped); 'other' = another reparse point,
    # such as a OneDrive placeholder (walked); 'unknown' = PowerShell older than 5.
    if (-not $HasLinkType) { return 'unknown' }
    try {
        $linkType = [string]$Entry.LinkType
        if ($linkType -eq 'Junction' -or $linkType -eq 'SymbolicLink') { return 'link' }
        return 'other'
    }
    catch { return 'link' }
}

function Measure-CaramosFolder {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [AllowNull()][object]$ExcludePaths,
        [AllowNull()][object]$CloudRoots,
        [AllowNull()][object]$Deadline,
        [int]$MaxDepth = 64
    )
    $tracked = $CaramosTrackedExtensions
    $files = [long]0; $bytes = [long]0; $cloudFiles = [long]0; $cloudBytes = [long]0
    $cloudDirs = 0; $links = 0; $unreadable = 0; $tooDeep = 0; $partial = $false
    $extCount = @{}
    $extBytes = @{}
    $exclude = New-Object 'System.Collections.Generic.HashSet[string]' -ArgumentList ([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($excludePath in (ConvertTo-CaramosArray $ExcludePaths)) {
        if ($excludePath) { [void]$exclude.Add((ConvertTo-CaramosComparablePath ([string]$excludePath))) }
    }
    $roots = ConvertTo-CaramosArray $CloudRoots
    $hasLinkType = [bool]$CaramosConfig.HasLinkType
    # FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS (0x400000), FILE_ATTRIBUTE_RECALL_ON_OPEN (0x40000)
    # and FILE_ATTRIBUTE_OFFLINE (0x1000): the content is not on this PC (OneDrive "online-only").
    $recallMask = 0x400000 -bor 0x40000 -bor 0x1000
    $useDeadline = ($Deadline -is [datetime])
    $status = 'ok'
    $root = Get-CaramosDirectoryEntry -Path $Path
    if ($null -eq $root) {
        $status = 'unreadable'
    }
    else {
        $stack = New-Object System.Collections.Generic.Stack[object]
        $stack.Push(@($root, 0))
        $nextReport = 20000
        while ($stack.Count -gt 0) {
            if ($useDeadline -and [datetime]::UtcNow -gt $Deadline) { $partial = $true; break }
            $frame = $stack.Pop()
            $directory = $frame[0]
            $depth = [int]$frame[1]
            try {
                $children = Get-CaramosChildEntries -Directory $directory
                foreach ($entry in $children) {
                    $attributes = [int]$entry.Attributes
                    if (($attributes -band 0x10) -ne 0) {
                        if (($attributes -band 0x6) -eq 0x6) { continue }
                        if (($attributes -band 0x400) -ne 0) {
                            $kind = Get-CaramosLinkKind -Entry $entry -HasLinkType $hasLinkType
                            if ($kind -eq 'link') { $links++; continue }
                            if ($kind -eq 'unknown' -and -not (Test-CaramosPathUnder -Path ([string]$entry.FullName) -Roots $roots)) { $links++; continue }
                        }
                        if (($attributes -band $recallMask) -ne 0) { $cloudDirs++; continue }
                        if ($exclude.Count -gt 0 -and $exclude.Contains((ConvertTo-CaramosComparablePath ([string]$entry.FullName)))) { continue }
                        if ($depth -ge $MaxDepth) { $tooDeep++; continue }
                        $stack.Push(@($entry, ($depth + 1)))
                    }
                    else {
                        if (($attributes -band 0x6) -eq 0x6) { continue }
                        $isCloud = (($attributes -band $recallMask) -ne 0)
                        if ((-not $isCloud) -and (($attributes -band 0x400) -ne 0)) {
                            if ((Get-CaramosLinkKind -Entry $entry -HasLinkType $hasLinkType) -eq 'link') { $links++; continue }
                        }
                        $length = [long]$entry.Length
                        if ($isCloud) { $cloudFiles++; $cloudBytes += $length }
                        else { $files++; $bytes += $length }
                        $extension = [string]$entry.Extension
                        if ($extension.Length -gt 1 -and $tracked.ContainsKey($extension)) {
                            $canonical = $tracked[$extension]
                            if ($extCount.ContainsKey($canonical)) {
                                $extCount[$canonical] = $extCount[$canonical] + 1
                                $extBytes[$canonical] = $extBytes[$canonical] + $length
                            }
                            else {
                                $extCount[$canonical] = 1
                                $extBytes[$canonical] = $length
                            }
                        }
                        if ($files -ge $nextReport) {
                            Write-CaramosStatus ('    ... ' + (Format-CaramosNumber $files) + ' tệp')
                            $nextReport += 20000
                        }
                    }
                }
            }
            catch { $unreadable++ }
        }
    }
    return [ordered]@{
        status         = $status
        files          = $files
        bytes          = $bytes
        cloudFiles     = $cloudFiles
        cloudBytes     = $cloudBytes
        cloudDirs      = $cloudDirs
        skippedLinks   = $links
        unreadableDirs = $unreadable
        tooDeep        = $tooDeep
        partial        = $partial
        ExtCount       = $extCount
        ExtBytes       = $extBytes
    }
}

function Measure-CaramosFolders {
    param([Parameter(Mandatory = $true)][object]$Plan)
    $started = Get-Date
    $deadline = [datetime]::UtcNow.AddSeconds([double]$CaramosConfig.ScanBudgetSeconds)
    $extCount = @{}
    $extBytes = @{}
    $total = [ordered]@{ files = [long]0; bytes = [long]0; cloudFiles = [long]0; cloudBytes = [long]0; cloudDirs = 0; unreadableDirs = 0; skippedLinks = 0; partial = $false }
    $rows = New-Object System.Collections.Generic.List[object]
    foreach ($item in $Plan.Items) {
        $row = [ordered]@{
            key = $item.key; label = $item.label; status = $item.status; location = $item.location; sameAs = $item.sameAs; excludes = $item.excludes
            files = $null; bytes = $null; cloudFiles = $null; cloudBytes = $null; cloudDirs = $null; skippedLinks = $null; unreadableDirs = $null; partial = $false
        }
        if ($item.status -eq 'scan') {
            Write-CaramosStatus ('  ' + $item.label)
            $stats = Measure-CaramosFolder -Path $item.Path -ExcludePaths $item.Exclude -CloudRoots $Plan.CloudRoots -Deadline $deadline -MaxDepth $CaramosConfig.MaxDepth
            if ($stats.status -eq 'ok') { $row.status = 'ok' } else { $row.status = $stats.status }
            foreach ($name in @('files', 'bytes', 'cloudFiles', 'cloudBytes', 'cloudDirs', 'skippedLinks', 'unreadableDirs', 'partial')) { $row[$name] = $stats[$name] }
            foreach ($name in @('files', 'bytes', 'cloudFiles', 'cloudBytes', 'cloudDirs', 'unreadableDirs', 'skippedLinks')) { $total[$name] = $total[$name] + $stats[$name] }
            if ($stats.partial) { $total.partial = $true }
            foreach ($ext in $stats.ExtCount.Keys) {
                if ($extCount.ContainsKey($ext)) { $extCount[$ext] += $stats.ExtCount[$ext]; $extBytes[$ext] += $stats.ExtBytes[$ext] }
                else { $extCount[$ext] = $stats.ExtCount[$ext]; $extBytes[$ext] = $stats.ExtBytes[$ext] }
            }
        }
        $rows.Add($row)
    }
    $zalo = [ordered]@{ found = $false; bytes = [long]0; files = [long]0; partial = $false }
    foreach ($path in (ConvertTo-CaramosArray $Plan.ZaloApp)) {
        $stats = Measure-CaramosFolder -Path ([string]$path) -CloudRoots $Plan.CloudRoots -Deadline $deadline -MaxDepth $CaramosConfig.MaxDepth
        if ($stats.status -eq 'ok') {
            $zalo.found = $true
            $zalo.bytes = $zalo.bytes + $stats.bytes
            $zalo.files = $zalo.files + $stats.files
            if ($stats.partial) { $zalo.partial = $true }
        }
    }
    $outlookCount = @{ '.pst' = 0; '.ost' = 0 }
    $outlookBytes = @{ '.pst' = [long]0; '.ost' = [long]0 }
    foreach ($path in (ConvertTo-CaramosArray $Plan.Outlook)) {
        $stats = Measure-CaramosFolder -Path ([string]$path) -CloudRoots $Plan.CloudRoots -Deadline $deadline -MaxDepth 8
        foreach ($ext in @('.pst', '.ost')) {
            if ($stats.ExtCount.ContainsKey($ext)) {
                $outlookCount[$ext] += $stats.ExtCount[$ext]
                $outlookBytes[$ext] += $stats.ExtBytes[$ext]
            }
        }
    }
    foreach ($ext in @('.pst', '.ost')) {
        if ($extCount.ContainsKey($ext)) { $extCount[$ext] += $outlookCount[$ext]; $extBytes[$ext] += $outlookBytes[$ext] }
        else { $extCount[$ext] = $outlookCount[$ext]; $extBytes[$ext] = $outlookBytes[$ext] }
    }
    return [ordered]@{
        Folders = [ordered]@{
            status          = 'ok'
            items           = $rows.ToArray()
            total           = $total
            zaloAppData     = $zalo
            durationSeconds = [math]::Round(((Get-Date) - $started).TotalSeconds, 1)
        }
        ExtCount = $extCount
        ExtBytes = $extBytes
    }
}

function Get-CaramosFileTypeSummary {
    param([AllowNull()][object]$ExtCount, [AllowNull()][object]$ExtBytes, [bool]$Read = $true)
    $order = @('.xlsm', '.xltm', '.xlsb', '.xla', '.xlam', '.docm', '.dotm', '.pptm', '.doc', '.xls', '.ppt', '.pst', '.ost')
    $counts = [ordered]@{}
    $sizes = [ordered]@{}
    foreach ($ext in $order) {
        $count = 0
        $size = [long]0
        if ($null -ne $ExtCount -and $ExtCount.ContainsKey($ext)) { $count = [long]$ExtCount[$ext] }
        if ($null -ne $ExtBytes -and $ExtBytes.ContainsKey($ext)) { $size = [long]$ExtBytes[$ext] }
        $counts[$ext] = $count
        $sizes[$ext] = $size
    }
    $excel = $counts['.xlsm'] + $counts['.xltm'] + $counts['.xlsb'] + $counts['.xla'] + $counts['.xlam']
    $word = $counts['.docm'] + $counts['.dotm']
    $powerpoint = $counts['.pptm']
    $status = 'ok'
    if (-not $Read) { $status = 'error' }
    return [ordered]@{
        status          = $status
        counts          = $counts
        bytes           = $sizes
        excelMacro      = $excel
        wordMacro       = $word
        powerpointMacro = $powerpoint
        macroTotal      = $excel + $word + $powerpoint
        oldTotal        = $counts['.doc'] + $counts['.xls'] + $counts['.ppt']
    }
}

function Get-CaramosFontSummary {
    param([AllowNull()][object]$FontData)
    $legacy = 0
    $all = New-Object System.Collections.Generic.List[string]
    foreach ($name in (ConvertTo-CaramosArray (Get-CaramosValue $FontData 'System'))) { $all.Add([string]$name) }
    $userFonts = ConvertTo-CaramosArray (Get-CaramosValue $FontData 'User')
    foreach ($name in $userFonts) { $all.Add([string]$name) }
    foreach ($name in $all) {
        $clean = ($name -replace '\s*\([^)]*\)\s*$', '').Trim()
        if ($clean -match '^\.Vn|^VNI[- ]|^VNI$|^VPS ') { $legacy++ }
    }
    return [ordered]@{ status = 'ok'; userInstalled = $userFonts.Count; legacyVietnamese = $legacy }
}

# ---------------------------------------------------------------------------
# The machine section
# ---------------------------------------------------------------------------

function Get-CaramosWindowsFamily {
    param([AllowNull()][object]$Build, [AllowNull()][string]$Caption)
    if ($null -ne $Build -and [int]$Build -gt 0) {
        $number = [int]$Build
        if ($number -ge 22000) { return '11' }
        if ($number -ge 10240) { return '10' }
        if ($number -ge 9600) { return '8.1' }
        if ($number -ge 9200) { return '8' }
        if ($number -ge 7600) { return '7' }
    }
    $match = [regex]::Match([string]$Caption, 'Windows (11|10|8\.1|8|7|Vista|XP)')
    if ($match.Success) { return $match.Groups[1].Value }
    return $null
}

function ConvertTo-CaramosMachineSection {
    param([AllowNull()][object]$Info, [AllowNull()][object]$Tpm)
    if ($null -eq $Info) {
        $Info = [ordered]@{ FailedProbes = @('all') }
    }
    $caption = Get-CaramosString $Info 'WindowsCaption'
    $build = Get-CaramosValue $Info 'WindowsBuild'
    $family = Get-CaramosWindowsFamily -Build $build -Caption $caption
    $name = ($caption -replace '^Microsoft\s+', '').Trim()
    if ($family -eq '11' -and $name -match 'Windows 10') { $name = $name -replace 'Windows 10', 'Windows 11' }
    $buildText = $null
    if ($null -ne $build -and [int]$build -gt 0) {
        $buildText = [string]$build
        $ubr = Get-CaramosValue $Info 'WindowsUbr'
        if ($null -ne $ubr) { $buildText = $buildText + '.' + [string]$ubr }
    }
    $architecture = $null
    $is64 = Get-CaramosValue $Info 'Is64BitOs'
    if ($null -ne $is64) { if ($is64) { $architecture = '64-bit' } else { $architecture = '32-bit' } }
    $tpmStatus = Get-CaramosString $Tpm 'Status'
    if ($tpmStatus.Length -eq 0) { $tpmStatus = 'unknown' }
    $failed = ConvertTo-CaramosArray (Get-CaramosValue $Info 'FailedProbes')
    $status = 'ok'
    if ($failed.Count -gt 0) { $status = 'partial' }
    if ($failed -contains 'all') { $status = 'error' }
    return [ordered]@{
        status       = $status
        manufacturer = (Get-CaramosString $Info 'Manufacturer')
        model        = (Get-CaramosString $Info 'Model')
        windows      = [ordered]@{
            name           = $name
            displayVersion = (Get-CaramosString $Info 'WindowsDisplayVersion')
            build          = $buildText
            family         = $family
            architecture   = $architecture
        }
        cpu          = [ordered]@{
            name          = (Get-CaramosString $Info 'CpuName')
            cores         = (Get-CaramosValue $Info 'CpuCores')
            threads       = (Get-CaramosValue $Info 'CpuThreads')
            architecture  = (Get-CaramosValue $Info 'CpuArchitecture')
            supports64Bit = (Get-CaramosValue $Info 'Cpu64Bit')
        }
        ramBytes     = (Get-CaramosValue $Info 'RamBytes')
        systemDisk   = [ordered]@{
            drive     = (Get-CaramosString $Info 'SystemDrive')
            sizeBytes = (Get-CaramosValue $Info 'DiskSizeBytes')
            freeBytes = (Get-CaramosValue $Info 'DiskFreeBytes')
            mediaType = (Get-CaramosValue $Info 'DiskMediaType')
            busType   = (Get-CaramosValue $Info 'DiskBusType')
        }
        firmware     = (Get-CaramosValue $Info 'Firmware')
        secureBoot   = (Get-CaramosString $Info 'SecureBoot')
        tpm          = [ordered]@{
            status  = $tpmStatus
            version = (Get-CaramosValue $Tpm 'Version')
            source  = (Get-CaramosValue $Tpm 'Source')
        }
        failedProbes = $failed
    }
}

# ---------------------------------------------------------------------------
# Collecting everything
# ---------------------------------------------------------------------------

function New-CaramosReport {
    param([switch]$HideComputerName, [string]$AdviceTablePath, [datetime]$Now = (Get-Date))
    $invariant = [System.Globalization.CultureInfo]::InvariantCulture
    $report = [ordered]@{}
    $report.schema = 'caramos-assess/1'
    $report.scriptVersion = $CaramosAssessVersion
    $report.createdAt = $Now.ToString('yyyy-MM-ddTHH:mm:sszzz', $invariant)
    $report.computerName = $null
    $report.computerNameHidden = [bool]$HideComputerName
    if (-not $HideComputerName) {
        try { $report.computerName = Get-CaramosComputerName } catch { $report.computerName = $null }
    }

    $table = $null
    $tableInfo = [ordered]@{ status = 'missing'; updated = $null; problems = @() }
    if ($AdviceTablePath -and (Test-Path -LiteralPath $AdviceTablePath -PathType Leaf)) {
        try {
            $table = Import-CaramosAdviceTable -Path $AdviceTablePath
            $tableInfo.status = 'ok'
            $tableInfo.updated = $table.Updated
            $tableInfo.problems = $table.Problems
        }
        catch { $tableInfo.status = 'error'; $table = $null }
    }
    $report.adviceTable = $tableInfo

    Write-CaramosStatus 'Đang đọc thông tin máy...'
    $info = $null
    try { $info = Get-CaramosSystemInfo } catch { $info = $null }
    $pnp = @()
    $pnpRead = $false
    try { $pnp = ConvertTo-CaramosArray (Get-CaramosPnpDevices); $pnpRead = $true } catch { $pnp = @() }
    $tpm = $null
    try { $tpm = Get-CaramosTpmInfo -PnpDevices $pnp -PnpRead $pnpRead } catch { $tpm = [ordered]@{ Status = 'unknown'; Version = $null; Source = $null } }
    try { $report.machine = ConvertTo-CaramosMachineSection -Info $info -Tpm $tpm }
    catch { $report.machine = ConvertTo-CaramosMachineSection -Info $null -Tpm $null }

    Write-CaramosStatus 'Đang đọc danh sách chương trình...'
    $programItems = @()
    try {
        $entries = Get-CaramosUninstallEntries
        $programItems = ConvertTo-CaramosProgramItems -Programs (Select-CaramosPrograms -Entries $entries) -Table $table
        $report.programs = [ordered]@{ status = 'ok'; count = $programItems.Count; items = $programItems }
    }
    catch { $report.programs = [ordered]@{ status = 'error'; count = 0; items = @() } }

    Write-CaramosStatus 'Đang đọc máy in và thiết bị...'
    try {
        $printers = ConvertTo-CaramosPrinterItems -Printers (Get-CaramosPrinterData) -Table $table
        $report.printers = [ordered]@{ status = 'ok'; items = $printers }
    }
    catch { $report.printers = [ordered]@{ status = 'error'; items = @() } }
    if ($pnpRead) {
        try {
            $report.scanners = [ordered]@{ status = 'ok'; items = (Get-CaramosScannerItems -Devices $pnp -Table $table) }
        }
        catch { $report.scanners = [ordered]@{ status = 'error'; items = @() } }
        try { $report.usb = Get-CaramosUsbSummary -Devices $pnp -Table $table }
        catch { $report.usb = [ordered]@{ status = 'error'; keyboards = 0; mice = 0; items = @() } }
    }
    else {
        $report.scanners = [ordered]@{ status = 'error'; items = @() }
        $report.usb = [ordered]@{ status = 'error'; keyboards = 0; mice = 0; items = @() }
    }

    $officeRegistry = $null
    $officeRead = $true
    try { $officeRegistry = Get-CaramosOfficeRegistryData } catch { $officeRead = $false }
    try { $report.office = Get-CaramosOfficeSummary -Registry $officeRegistry -ProgramItems $programItems -RegistryRead $officeRead }
    catch { $report.office = [ordered]@{ status = 'error'; found = $false; editions = @(); clickToRun = $null; msi = @(); otherSuites = @() } }

    Write-CaramosStatus 'Đang đếm tệp trong các thư mục người dùng (có thể mất vài phút)...'
    $extCount = $null
    $extBytes = $null
    $foldersRead = $false
    try {
        $known = Get-CaramosKnownFolders
        $plan = New-CaramosFolderPlan -Known $known
        $measured = Measure-CaramosFolders -Plan $plan
        $report.folders = $measured.Folders
        $extCount = $measured.ExtCount
        $extBytes = $measured.ExtBytes
        $foldersRead = $true
    }
    catch {
        $report.folders = [ordered]@{ status = 'error'; items = @(); total = $null; zaloAppData = $null; durationSeconds = $null }
    }
    $report.fileTypes = Get-CaramosFileTypeSummary -ExtCount $extCount -ExtBytes $extBytes -Read $foldersRead

    try { $report.fonts = Get-CaramosFontSummary -FontData (Get-CaramosFontData) }
    catch { $report.fonts = [ordered]@{ status = 'error'; userInstalled = $null; legacyVietnamese = $null } }

    return $report
}

# ---------------------------------------------------------------------------
# JSON (written by hand so the output is the same on PowerShell 5.1 and 7)
# ---------------------------------------------------------------------------

function ConvertTo-CaramosJsonString {
    param([string]$Text)
    $escaped = [regex]::Replace($Text, '[\x00-\x1f"\\<>\u2028\u2029]', {
            param($match)
            $c = $match.Value[0]
            switch ([int]$c) {
                8 { return '\b' }
                9 { return '\t' }
                10 { return '\n' }
                12 { return '\f' }
                13 { return '\r' }
                34 { return '\"' }
                92 { return '\\' }
                default { return '\u' + ([int]$c).ToString('x4') }
            }
        })
    return '"' + $escaped + '"'
}

function Write-CaramosJsonValue {
    param([System.Text.StringBuilder]$Builder, [AllowNull()][object]$Value, [int]$Level)
    $invariant = [System.Globalization.CultureInfo]::InvariantCulture
    $indent = '  ' * ($Level + 1)
    $closing = '  ' * $Level
    if ($null -eq $Value) { [void]$Builder.Append('null'); return }
    if ($Value -is [bool]) { if ($Value) { [void]$Builder.Append('true') } else { [void]$Builder.Append('false') }; return }
    if ($Value -is [string] -or $Value -is [char]) { [void]$Builder.Append((ConvertTo-CaramosJsonString ([string]$Value))); return }
    if ($Value -is [datetime]) { [void]$Builder.Append((ConvertTo-CaramosJsonString $Value.ToString('o', $invariant))); return }
    if ($Value -is [enum]) { [void]$Builder.Append((ConvertTo-CaramosJsonString $Value.ToString())); return }
    $typeCode = [int][System.Type]::GetTypeCode($Value.GetType())
    if ($typeCode -ge 5 -and $typeCode -le 15) {
        if ($Value -is [double] -or $Value -is [single]) {
            if ([double]::IsNaN($Value) -or [double]::IsInfinity($Value)) { [void]$Builder.Append('null'); return }
            [void]$Builder.Append(([double]$Value).ToString('R', $invariant))
            return
        }
        [void]$Builder.Append(([System.IFormattable]$Value).ToString($null, $invariant))
        return
    }
    if ($Value -is [System.Collections.IDictionary]) {
        $keys = @($Value.Keys)
        if ($keys.Count -eq 0) { [void]$Builder.Append('{}'); return }
        [void]$Builder.Append("{`n")
        for ($i = 0; $i -lt $keys.Count; $i++) {
            [void]$Builder.Append($indent).Append((ConvertTo-CaramosJsonString ([string]$keys[$i]))).Append(': ')
            Write-CaramosJsonValue -Builder $Builder -Value $Value[$keys[$i]] -Level ($Level + 1)
            if ($i -lt $keys.Count - 1) { [void]$Builder.Append(',') }
            [void]$Builder.Append("`n")
        }
        [void]$Builder.Append($closing).Append('}')
        return
    }
    if ($Value -is [System.Management.Automation.PSCustomObject]) {
        $ordered = [ordered]@{}
        foreach ($property in $Value.PSObject.Properties) { $ordered[$property.Name] = $property.Value }
        Write-CaramosJsonValue -Builder $Builder -Value $ordered -Level $Level
        return
    }
    if ($Value -is [System.Collections.IEnumerable]) {
        $items = ConvertTo-CaramosArray $Value
        if ($items.Count -eq 0) { [void]$Builder.Append('[]'); return }
        [void]$Builder.Append("[`n")
        for ($i = 0; $i -lt $items.Count; $i++) {
            [void]$Builder.Append($indent)
            Write-CaramosJsonValue -Builder $Builder -Value $items[$i] -Level ($Level + 1)
            if ($i -lt $items.Count - 1) { [void]$Builder.Append(',') }
            [void]$Builder.Append("`n")
        }
        [void]$Builder.Append($closing).Append(']')
        return
    }
    [void]$Builder.Append((ConvertTo-CaramosJsonString ([string]$Value)))
}

function ConvertTo-CaramosJson {
    param([AllowNull()][object]$InputObject)
    $builder = New-Object System.Text.StringBuilder
    Write-CaramosJsonValue -Builder $builder -Value $InputObject -Level 0
    [void]$builder.Append("`n")
    return $builder.ToString()
}

# ---------------------------------------------------------------------------
# HTML report
# ---------------------------------------------------------------------------

function Get-CaramosReportCss {
    return @'
:root { --text: #1f1f1f; --muted: #5f5f5f; --rule: #d4d4d4; --rule-light: #e6e6e6; --accent: #2b6a44; }
* { box-sizing: border-box; }
html { background: #ffffff; }
body { margin: 0; background: #ffffff; color: var(--text); font-family: "Segoe UI", "Be Vietnam Pro", "Noto Sans", Roboto, "Helvetica Neue", Arial, sans-serif; font-size: 15px; line-height: 1.5; }
main { max-width: 900px; margin: 0 auto; padding: 40px 24px 56px; }
h1 { font-size: 1.8em; font-weight: 600; line-height: 1.25; margin: 0 0 6px; }
h2 { font-size: 1.2em; font-weight: 600; line-height: 1.3; margin: 36px 0 12px; padding-bottom: 6px; border-bottom: 2px solid var(--accent); }
h3 { font-size: 1em; font-weight: 600; margin: 22px 0 6px; }
p { margin: 0 0 10px; max-width: 46em; }
a { color: var(--accent); }
.meta { color: var(--muted); margin-bottom: 28px; }
.summary p { margin-bottom: 8px; }
.table-wrap { overflow-x: auto; margin: 4px 0 16px; }
table { width: 100%; border-collapse: collapse; font-size: 0.94em; }
table.fixed { table-layout: fixed; }
table.narrow { max-width: 34em; }
th, td { text-align: left; vertical-align: top; padding: 7px 12px 7px 0; border-bottom: 1px solid var(--rule-light); overflow-wrap: break-word; }
table.fixed td { overflow-wrap: anywhere; }
thead th { font-weight: 600; color: var(--muted); font-size: 0.92em; border-bottom: 1px solid var(--rule); }
tbody th { font-weight: 600; width: 30%; }
td.num, th.num { text-align: right; white-space: nowrap; padding-left: 12px; padding-right: 0; }
tr.total th, tr.total td { font-weight: 600; border-top: 1px solid var(--rule); border-bottom: 0; }
.sub { display: block; color: var(--muted); font-size: 0.9em; }
.muted { color: var(--muted); }
.note { margin-top: 44px; padding-top: 12px; border-top: 1px solid var(--rule); color: var(--muted); font-size: 0.85em; }
.note p { max-width: none; }
@page { size: A4; margin: 15mm 14mm 16mm; }
@media print {
  body { font-size: 10pt; }
  main { max-width: none; padding: 0; }
  h2 { margin-top: 24px; break-after: avoid; page-break-after: avoid; }
  h3 { break-after: avoid; page-break-after: avoid; }
  tr { break-inside: avoid; page-break-inside: avoid; }
  thead { display: table-header-group; }
  .table-wrap { overflow: visible; }
}
@media (max-width: 640px) {
  body { font-size: 14px; }
  main { padding: 24px 16px 40px; }
  th, td { padding-right: 8px; }
  tbody th { width: auto; }
}
'@
}

function Get-CaramosProgramNoun {
    param([long]$Count)
    return [string]$Count + ' chương trình'
}

function Get-CaramosLocationLabel {
    param([AllowNull()][string]$Location)
    if ($Location -eq 'default') { return 'Mặc định' }
    if ($Location -eq 'onedrive') { return 'OneDrive' }
    if ($Location -match '^drive:([A-Z])$') { return 'Ổ ' + $Matches[1] + ':' }
    if ($Location -eq 'other') { return 'Chỗ khác' }
    return ''
}

function Add-CaramosTable {
    param(
        [System.Collections.Generic.List[string]]$Html,
        [string[]]$Headers,
        [string[]]$HeaderClasses,
        [System.Collections.Generic.List[string]]$Rows,
        [int[]]$Widths,
        [string]$TableClass = 'fixed'
    )
    $Html.Add('<div class="table-wrap"><table class="' + $TableClass + '">')
    if ($null -ne $Widths -and $Widths.Count -gt 0) {
        $columns = New-Object System.Text.StringBuilder
        [void]$columns.Append('<colgroup>')
        foreach ($width in $Widths) { [void]$columns.Append('<col style="width: ' + $width + '%">') }
        [void]$columns.Append('</colgroup>')
        $Html.Add($columns.ToString())
    }
    $head = New-Object System.Text.StringBuilder
    [void]$head.Append('<thead><tr>')
    for ($i = 0; $i -lt $Headers.Count; $i++) {
        $class = ''
        if ($null -ne $HeaderClasses -and $i -lt $HeaderClasses.Count -and $HeaderClasses[$i]) { $class = ' class="' + $HeaderClasses[$i] + '"' }
        [void]$head.Append('<th scope="col"' + $class + '>' + (ConvertTo-CaramosHtmlText $Headers[$i]) + '</th>')
    }
    [void]$head.Append('</tr></thead>')
    $Html.Add($head.ToString())
    $Html.Add('<tbody>')
    foreach ($row in $Rows) { $Html.Add($row) }
    $Html.Add('</tbody></table></div>')
}

function Get-CaramosSummaryParagraphs {
    param([System.Collections.IDictionary]$Report)
    $paragraphs = New-Object System.Collections.Generic.List[string]

    $programs = $Report.programs
    if ($programs.status -eq 'ok') {
        $items = ConvertTo-CaramosArray $programs.items
        if ($items.Count -eq 0) {
            $paragraphs.Add('Không thấy chương trình nào trong danh sách cài đặt của Windows.')
        }
        else {
            $sentences = New-Object System.Collections.Generic.List[string]
            $sentences.Add('Máy có ' + (Get-CaramosProgramNoun $items.Count) + ' đã cài.')
            $windowsOnly = @($items | Where-Object { $_.kind -eq 'windows-only' })
            if ($windowsOnly.Count -gt 0) {
                $names = @($windowsOnly | ForEach-Object { $_.name })
                $sentences.Add((Get-CaramosProgramNoun $windowsOnly.Count) + ' chỉ chạy trên Windows: ' + (Join-CaramosList -Items $names -Max 6 -MoreNoun 'chương trình') + '.')
            }
            $parts = New-Object System.Collections.Generic.List[string]
            foreach ($kind in @('alternative', 'available', 'not-needed', 'check', 'unknown')) {
                $count = @($items | Where-Object { $_.kind -eq $kind }).Count
                if ($count -gt 0) { $parts.Add((Get-CaramosProgramNoun $count) + ' ' + (ConvertTo-CaramosLowerFirst $CaramosKindLabels[$kind])) }
            }
            if ($parts.Count -gt 0) {
                $text = Join-CaramosList -Items $parts.ToArray()
                $sentences.Add($text.Substring(0, 1).ToUpperInvariant() + $text.Substring(1) + '.')
            }
            $paragraphs.Add($sentences.ToArray() -join ' ')
        }
    }
    else {
        $paragraphs.Add('Không đọc được danh sách chương trình đã cài.')
    }

    $folders = $Report.folders
    if ($folders.status -eq 'ok' -and $null -ne $folders.total) {
        $total = $folders.total
        $sizeText = Format-CaramosSize $total.bytes
        if (-not $sizeText.StartsWith('dưới')) { $sizeText = 'khoảng ' + $sizeText }
        $text = 'Cần chép ' + $sizeText + ' dữ liệu (' + (Format-CaramosNumber $total.files) + ' tệp) từ các thư mục người dùng.'
        if ($total.cloudFiles -gt 0) {
            $text = $text + ' Ngoài ra có ' + (Format-CaramosNumber $total.cloudFiles) + ' tệp (' + (Format-CaramosSize $total.cloudBytes) + ') trên OneDrive, chưa tải về máy.'
        }
        if ($total.partial) { $text = $text + ' Việc đếm tệp dừng vì quá lâu, nên con số thật lớn hơn.' }
        $paragraphs.Add($text)
    }
    else {
        $paragraphs.Add('Không đếm được dữ liệu trong các thư mục người dùng.')
    }

    $types = $Report.fileTypes
    if ($types.status -eq 'ok') {
        $macroParts = New-Object System.Collections.Generic.List[string]
        if ($types.excelMacro -gt 0) { $macroParts.Add((Format-CaramosNumber $types.excelMacro) + ' tệp Excel') }
        if ($types.wordMacro -gt 0) { $macroParts.Add((Format-CaramosNumber $types.wordMacro) + ' tệp Word') }
        if ($types.powerpointMacro -gt 0) { $macroParts.Add((Format-CaramosNumber $types.powerpointMacro) + ' tệp PowerPoint') }
        $text = ''
        if ($macroParts.Count -gt 0) { $text = 'Có ' + (Join-CaramosList -Items $macroParts.ToArray()) + ' có macro cần thử.' }
        else { $text = 'Không thấy tệp Office có macro.' }
        if ($types.oldTotal -gt 0) { $text = $text + ' Có ' + (Format-CaramosNumber $types.oldTotal) + ' tệp Word, Excel, PowerPoint định dạng cũ (.doc, .xls, .ppt).' }
        $pst = $types.counts['.pst']
        if ($pst -gt 0) { $text = $text + ' Có ' + (Format-CaramosNumber $pst) + ' tệp thư Outlook (.pst), tổng ' + (Format-CaramosSize $types.bytes['.pst']) + '.' }
        $paragraphs.Add($text)
    }

    if ($Report.printers.status -eq 'ok') {
        $allPrinters = ConvertTo-CaramosArray $Report.printers.items
        $real = @($allPrinters | Where-Object { -not $_.virtual })
        if ($real.Count -gt 0) {
            $names = @($real | ForEach-Object { $_.name + ' (' + (ConvertTo-CaramosLowerFirst $_.connectionLabel) + ')' })
            $paragraphs.Add('Máy in: ' + (Join-CaramosList -Items $names -Max 6 -MoreNoun 'máy in') + '.')
        }
        else {
            $paragraphs.Add('Không thấy máy in thật nào, chỉ có máy in ảo.')
        }
    }

    $family = $Report.machine.windows.family
    if ($family -eq '10') { $paragraphs.Add('Máy đang chạy Windows 10; Microsoft đã ngừng hỗ trợ Windows 10 từ ngày 14/10/2025.') }
    elseif ($family -eq '7') { $paragraphs.Add('Máy đang chạy Windows 7; Microsoft đã ngừng hỗ trợ Windows 7 từ ngày 14/01/2020.') }
    elseif ($family -eq '8.1' -or $family -eq '8') { $paragraphs.Add('Máy đang chạy Windows ' + $family + '; Microsoft đã ngừng hỗ trợ Windows 8.1 từ ngày 10/01/2023.') }
    return , ($paragraphs.ToArray())
}

function Get-CaramosMachineRows {
    param([System.Collections.IDictionary]$Machine)
    $rows = New-Object System.Collections.Generic.List[object]
    $unknown = 'không đọc được'
    $model = (($Machine.manufacturer + ' ' + $Machine.model).Trim())
    if ($model) { $rows.Add(@('Hãng, mẫu máy', $model)) }

    $windows = $Machine.windows
    if ($windows.name) {
        $text = $windows.name
        if ($windows.displayVersion) { $text = $text + ' ' + $windows.displayVersion }
        $extra = New-Object System.Collections.Generic.List[string]
        if ($windows.build) { $extra.Add('bản dựng ' + $windows.build) }
        if ($windows.architecture) { $extra.Add($windows.architecture) }
        if ($extra.Count -gt 0) { $text = $text + ' (' + ($extra.ToArray() -join ', ') + ')' }
        $rows.Add(@('Windows', $text))
    }
    else { $rows.Add(@('Windows', $unknown)) }

    $cpu = $Machine.cpu
    if ($cpu.name) {
        $text = $cpu.name
        $extra = New-Object System.Collections.Generic.List[string]
        if ($cpu.cores) { $extra.Add([string]$cpu.cores + ' nhân') }
        if ($cpu.threads) { $extra.Add([string]$cpu.threads + ' luồng') }
        if ($extra.Count -gt 0) { $text = $text + ', ' + ($extra.ToArray() -join ', ') }
        $rows.Add(@('CPU', $text))
    }
    else { $rows.Add(@('CPU', $unknown)) }

    if ($Machine.ramBytes) {
        $gb = [double]$Machine.ramBytes / 1GB
        $decimals = 0
        if ([math]::Abs($gb - [math]::Round($gb)) -gt 0.05) { $decimals = 1 }
        $ramText = (Format-CaramosNumber -Value $gb -Decimals $decimals) + ' GB'
        $rows.Add(@('RAM', $ramText))
    }
    else { $rows.Add(@('RAM', $unknown)) }

    $disk = $Machine.systemDisk
    $diskLabel = 'Ổ hệ thống'
    if ($disk.drive) { $diskLabel = 'Ổ hệ thống (' + $disk.drive + ')' }
    if ($disk.sizeBytes) {
        $text = (Format-CaramosSize $disk.sizeBytes) + ', còn trống ' + (Format-CaramosSize $disk.freeBytes)
        if ($disk.mediaType -eq 'SSD') { $text = $text + '; ổ SSD' }
        elseif ($disk.mediaType -eq 'HDD') { $text = $text + '; ổ cứng cơ (HDD)' }
        else { $text = $text + '; không rõ SSD hay HDD' }
        if ($disk.busType) { $text = $text + ', ' + $disk.busType }
        $rows.Add(@($diskLabel, $text))
    }
    else { $rows.Add(@($diskLabel, $unknown)) }

    $firmware = 'không rõ'
    if ($Machine.firmware -eq 'UEFI') { $firmware = 'UEFI' }
    elseif ($Machine.firmware -eq 'BIOS') { $firmware = 'BIOS cũ (Legacy)' }
    $rows.Add(@('Kiểu khởi động', $firmware))

    $secureBoot = 'không rõ'
    switch ($Machine.secureBoot) {
        'on' { $secureBoot = 'Đang bật' }
        'off' { $secureBoot = 'Đang tắt' }
        'unsupported' { $secureBoot = 'Không có (máy không hỗ trợ hoặc khởi động kiểu BIOS cũ)' }
        'needs-admin' { $secureBoot = $CaramosNeedsAdminText }
    }
    $rows.Add(@('Secure Boot', $secureBoot))

    $tpm = $Machine.tpm
    $tpmText = 'không rõ'
    switch ($tpm.status) {
        'found' {
            if ($tpm.version) { $tpmText = 'TPM ' + $tpm.version } else { $tpmText = 'Có TPM, không rõ phiên bản' }
        }
        'not-found' { $tpmText = 'Không có TPM, hoặc TPM đang tắt' }
        'not-found-pnp' { $tpmText = 'Không thấy TPM trong danh sách thiết bị (có thể đang tắt trong BIOS/UEFI)' }
        'needs-admin' { $tpmText = $CaramosNeedsAdminText }
    }
    $rows.Add(@('TPM', $tpmText))
    return , ($rows.ToArray())
}

function Get-CaramosMachineParagraphs {
    param([System.Collections.IDictionary]$Machine)
    $paragraphs = New-Object System.Collections.Generic.List[string]
    $family = $Machine.windows.family
    $tpm = $Machine.tpm
    if ($family -eq '11') {
        $paragraphs.Add('Máy đang chạy Windows 11.')
    }
    elseif ($family -eq '10') {
        $text = 'Microsoft đã ngừng hỗ trợ Windows 10 từ ngày 14/10/2025. '
        if ($tpm.status -eq 'found' -and $tpm.version -eq '2.0') {
            $text = $text + 'Máy có TPM 2.0, là một điều kiện để lên Windows 11; điều kiện về CPU cần kiểm tra riêng.'
        }
        elseif ($tpm.status -eq 'found' -and $tpm.version) {
            $text = $text + 'Máy chỉ có TPM ' + $tpm.version + ', không đủ điều kiện TPM 2.0 của Windows 11.'
        }
        elseif ($tpm.status -eq 'not-found' -or $tpm.status -eq 'not-found-pnp') {
            $text = $text + 'Không thấy TPM 2.0, là điều kiện bắt buộc để lên Windows 11. Nếu TPM đang tắt trong BIOS/UEFI thì cần bật lên mới biết.'
        }
        else {
            $text = $text + 'Chưa biết máy có TPM 2.0 (điều kiện để lên Windows 11) hay không, vì cần quyền quản trị để đọc.'
        }
        $paragraphs.Add($text)
    }
    elseif ($family -eq '7') { $paragraphs.Add('Microsoft đã ngừng hỗ trợ Windows 7 từ ngày 14/01/2020.') }
    elseif ($family -eq '8' -or $family -eq '8.1') { $paragraphs.Add('Microsoft đã ngừng hỗ trợ Windows 8.1 từ ngày 10/01/2023.') }

    $cpu = $Machine.cpu
    if ($cpu.architecture -eq 'arm64' -or $cpu.architecture -eq 'arm') {
        $paragraphs.Add('Máy dùng CPU ARM. CaramOS chỉ có bản 64-bit cho CPU Intel, AMD (x86-64), nên không cài được trên máy này.')
    }
    elseif ($cpu.supports64Bit -eq $false) {
        $paragraphs.Add('CPU này chỉ chạy 32-bit. CaramOS chỉ có bản 64-bit, nên không cài được trên máy này.')
    }
    elseif ($Machine.windows.architecture -eq '32-bit' -and $cpu.supports64Bit -eq $true) {
        $paragraphs.Add('Windows trên máy là bản 32-bit, nhưng CPU hỗ trợ 64-bit, là điều kiện để cài CaramOS (chỉ có bản 64-bit).')
    }
    if ($Machine.systemDisk.mediaType -eq 'HDD') {
        $paragraphs.Add('Ổ hệ thống là ổ cứng cơ (HDD), nên máy khởi động và mở ứng dụng chậm hơn so với ổ SSD, trên Windows cũng như trên CaramOS.')
    }
    $paragraphs.Add('Để biết phần cứng của máy có chạy được trên CaramOS hay không: khởi động máy bằng USB CaramOS ở chế độ chạy thử (không cài) và mở “Kiểm tra driver”. Công cụ này kiểm tra phần cứng của máy và lưu báo cáo.')
    return , ($paragraphs.ToArray())
}

function Add-CaramosProgramsHtml {
    param([System.Collections.Generic.List[string]]$Html, [System.Collections.IDictionary]$Report)
    $Html.Add('<h2>Chương trình đã cài</h2>')
    $programs = $Report.programs
    if ($programs.status -ne 'ok') {
        $Html.Add('<p>Không đọc được danh sách chương trình đã cài.</p>')
        return
    }
    $items = ConvertTo-CaramosArray $programs.items
    if ($items.Count -eq 0) {
        $Html.Add('<p>Không thấy chương trình nào trong danh sách cài đặt của Windows.</p>')
        return
    }
    $Html.Add('<p>' + (ConvertTo-CaramosHtmlText ('Danh sách lấy từ mục cài đặt của Windows, đã bỏ các bản cập nhật Windows và thành phần hệ thống: ' + (Get-CaramosProgramNoun $items.Count) + '.')) + '</p>')
    if ($Report.adviceTable.status -ne 'ok') {
        $Html.Add('<p>' + (ConvertTo-CaramosHtmlText 'Không đọc được bảng gợi ý (caramos-assess-programs.json), nên các chương trình được liệt kê không kèm gợi ý.') + '</p>')
    }
    foreach ($kind in $CaramosKindOrder) {
        $group = @($items | Where-Object { $_.kind -eq $kind })
        if ($group.Count -eq 0) { continue }
        $Html.Add('<h3>' + (ConvertTo-CaramosHtmlText ($CaramosKindLabels[$kind] + ' (' + $group.Count + ')')) + '</h3>')
        $rows = New-Object System.Collections.Generic.List[string]
        if ($kind -eq 'unknown') {
            foreach ($item in $group) {
                $rows.Add('<tr><td>' + (ConvertTo-CaramosHtmlText $item.name) + '</td><td class="ver">' + (ConvertTo-CaramosHtmlText $item.version) + '</td><td>' + (ConvertTo-CaramosHtmlText $item.publisher) + '</td></tr>')
            }
            Add-CaramosTable -Html $Html -Headers @('Tên', 'Phiên bản', 'Nhà phát hành') -HeaderClasses @('', '', '') -Rows $rows -Widths @(50, 17, 33)
            continue
        }
        $sorted = @($group | Sort-Object -Property @{ Expression = { [string]$_.adviceName } }, @{ Expression = { $_.name.ToLowerInvariant() } })
        for ($i = 0; $i -lt $sorted.Count; $i++) {
            $item = $sorted[$i]
            $cell = ''
            if ($i -eq 0 -or $sorted[$i - 1].adviceId -ne $item.adviceId) {
                $span = 1
                while (($i + $span) -lt $sorted.Count -and $sorted[$i + $span].adviceId -eq $item.adviceId) { $span++ }
                $rowspan = ''
                if ($span -gt 1) { $rowspan = ' rowspan="' + $span + '"' }
                $cell = '<td' + $rowspan + '>' + (ConvertTo-CaramosHtmlText $item.advice) + '</td>'
            }
            $rows.Add('<tr><td>' + (ConvertTo-CaramosHtmlText $item.name) + '</td><td class="ver">' + (ConvertTo-CaramosHtmlText $item.version) + '</td>' + $cell + '</tr>')
        }
        Add-CaramosTable -Html $Html -Headers @('Tên', 'Phiên bản', 'Trên CaramOS') -HeaderClasses @('', '', '') -Rows $rows -Widths @(30, 17, 53)
    }
}

function Add-CaramosPrintersHtml {
    param([System.Collections.Generic.List[string]]$Html, [System.Collections.IDictionary]$Report)
    $Html.Add('<h2>Máy in và máy quét</h2>')
    $printers = $Report.printers
    if ($printers.status -ne 'ok') {
        $Html.Add('<p>Không đọc được danh sách máy in.</p>')
    }
    else {
        $all = ConvertTo-CaramosArray $printers.items
        $real = @($all | Where-Object { -not $_.virtual })
        $virtual = @($all | Where-Object { $_.virtual })
        if ($real.Count -eq 0) {
            $Html.Add('<p>Không thấy máy in thật nào.</p>')
        }
        else {
            $rows = New-Object System.Collections.Generic.List[string]
            foreach ($printer in $real) {
                $connection = $printer.connectionLabel
                if ($printer.address) { $connection = $connection + ' (' + $printer.address + ')' }
                $rows.Add('<tr><td>' + (ConvertTo-CaramosHtmlText $printer.name) + '</td><td>' + (ConvertTo-CaramosHtmlText $printer.driver) + '</td><td>' + (ConvertTo-CaramosHtmlText $connection) + '</td><td>' + (ConvertTo-CaramosHtmlText $printer.advice) + '</td></tr>')
            }
            Add-CaramosTable -Html $Html -Headers @('Máy in', 'Driver trên Windows', 'Kết nối', 'Trên CaramOS') -HeaderClasses @('', '', '', '') -Rows $rows -Widths @(23, 21, 16, 40)
        }
        if ($virtual.Count -gt 0) {
            $names = @($virtual | ForEach-Object { $_.name })
            $Html.Add('<p class="muted">' + (ConvertTo-CaramosHtmlText ('Máy in ảo, không cần chuyển: ' + (Join-CaramosList -Items $names) + '.')) + '</p>')
        }
    }
    $Html.Add('<h3>Máy quét</h3>')
    $scanners = $Report.scanners
    if ($scanners.status -ne 'ok') {
        $Html.Add('<p>Không đọc được danh sách thiết bị.</p>')
        return
    }
    $items = ConvertTo-CaramosArray $scanners.items
    if ($items.Count -eq 0) {
        $Html.Add('<p>Không thấy máy quét nào đang cắm vào máy.</p>')
        return
    }
    $rows = New-Object System.Collections.Generic.List[string]
    foreach ($scanner in $items) {
        $rows.Add('<tr><td>' + (ConvertTo-CaramosHtmlText $scanner.name) + '</td><td class="ver">' + (ConvertTo-CaramosHtmlText $scanner.vidPid) + '</td><td>' + (ConvertTo-CaramosHtmlText $scanner.advice) + '</td></tr>')
    }
    Add-CaramosTable -Html $Html -Headers @('Máy quét', 'VID:PID', 'Trên CaramOS') -HeaderClasses @('', '', '') -Rows $rows -Widths @(30, 14, 56)
}

function Add-CaramosUsbHtml {
    param([System.Collections.Generic.List[string]]$Html, [System.Collections.IDictionary]$Report)
    $Html.Add('<h2>Thiết bị USB</h2>')
    $usb = $Report.usb
    if ($usb.status -ne 'ok') {
        $Html.Add('<p>Không đọc được danh sách thiết bị.</p>')
        return
    }
    $Html.Add('<p>' + (ConvertTo-CaramosHtmlText ('Windows nhận ' + $usb.keyboards + ' bàn phím và ' + $usb.mice + ' chuột; với laptop, con số này gồm cả bàn phím và bàn di chuột có sẵn. Máy in và máy quét đã có ở mục trên.')) + '</p>')
    $items = ConvertTo-CaramosArray $usb.items
    if ($items.Count -eq 0) {
        $Html.Add('<p>Không có thiết bị USB nào khác ngoài bàn phím, chuột và bộ chia USB.</p>')
        return
    }
    $hasNotes = (@($items | Where-Object { $_.note }).Count -gt 0)
    $rows = New-Object System.Collections.Generic.List[string]
    foreach ($item in $items) {
        $name = $item.name
        if ($item.quantity -gt 1) { $name = $name + ' (' + $item.quantity + ' cái)' }
        $row = '<tr><td>' + (ConvertTo-CaramosHtmlText $name) + '</td><td>' + (ConvertTo-CaramosHtmlText $item.classLabel) + '</td><td class="ver">' + (ConvertTo-CaramosHtmlText $item.vidPid) + '</td>'
        if ($hasNotes) { $row = $row + '<td>' + (ConvertTo-CaramosHtmlText $item.note) + '</td>' }
        $rows.Add($row + '</tr>')
    }
    $headers = @('Thiết bị', 'Loại', 'VID:PID')
    $widths = @(50, 30, 20)
    if ($hasNotes) {
        $headers = @('Thiết bị', 'Loại', 'VID:PID', 'Ghi chú')
        $widths = @(30, 17, 13, 40)
    }
    Add-CaramosTable -Html $Html -Headers $headers -HeaderClasses @('', '', '', '') -Rows $rows -Widths $widths
}

function Add-CaramosOfficeHtml {
    param([System.Collections.Generic.List[string]]$Html, [System.Collections.IDictionary]$Report)
    $Html.Add('<h2>Microsoft Office</h2>')
    $office = $Report.office
    if ($office.status -eq 'error') {
        $Html.Add('<p>Không đọc được thông tin Microsoft Office.</p>')
        return
    }
    $lines = New-Object System.Collections.Generic.List[string]
    if ($null -ne $office.clickToRun) {
        $c2r = $office.clickToRun
        $productItems = ConvertTo-CaramosArray $c2r.products
        $products = @($productItems | ForEach-Object { $_.name })
        $text = 'Bản Click-to-Run'
        if ($products.Count -gt 0) { $text = (Join-CaramosList -Items $products) + ', bản Click-to-Run' }
        if ($c2r.version) { $text = $text + ', phiên bản ' + $c2r.version }
        if ($c2r.platform) { $text = $text + ' (' + $c2r.platform + ')' }
        $lines.Add($text + '.')
    }
    foreach ($msi in (ConvertTo-CaramosArray $office.msi)) {
        $text = $msi.name + ' (bản cài MSI, ' + $msi.version + ')'
        $apps = ConvertTo-CaramosArray $msi.apps
        if ($apps.Count -gt 0) { $text = $text + ': ' + (Join-CaramosList -Items $apps) }
        $lines.Add($text + '.')
    }
    $editions = ConvertTo-CaramosArray $office.editions
    if ($editions.Count -gt 0) { $lines.Add('Trong danh sách chương trình: ' + (Join-CaramosList -Items $editions) + '.') }
    if (-not $office.found) { $lines.Add('Không thấy Microsoft Office trên máy.') }
    foreach ($line in $lines) { $Html.Add('<p>' + (ConvertTo-CaramosHtmlText $line) + '</p>') }
    $others = ConvertTo-CaramosArray $office.otherSuites
    if ($others.Count -gt 0) {
        $names = @($others | ForEach-Object { ($_.name + ' ' + $_.version).Trim() })
        $Html.Add('<p>' + (ConvertTo-CaramosHtmlText ('Bộ văn phòng khác đã cài: ' + (Join-CaramosList -Items $names) + '.')) + '</p>')
    }
    elseif ($Report.programs.status -eq 'ok') {
        $Html.Add('<p>Không thấy WPS Office, ONLYOFFICE hay LibreOffice trên máy.</p>')
    }
    if ($office.status -eq 'partial') {
        $Html.Add('<p class="muted">Không đọc được khóa registry của Office; thông tin trên chỉ lấy từ danh sách chương trình.</p>')
    }
    $advice = 'Trên CaramOS, tệp Word, Excel, PowerPoint mở bằng ONLYOFFICE, WPS Office hoặc LibreOffice (cài từ App Center). Cài thêm Microsoft Core Fonts (cũng có trong App Center) để văn bản dùng Times New Roman, Arial hiển thị đúng. Macro VBA không chạy giống như trong Microsoft Office, nên các tệp có macro ở mục cuối cần được mở thử trước khi chuyển.'
    $Html.Add('<p>' + (ConvertTo-CaramosHtmlText $advice) + '</p>')
    $subscription = $false
    if ($null -ne $office.clickToRun) {
        foreach ($product in (ConvertTo-CaramosArray $office.clickToRun.products)) { if ($product.id -match '^O365') { $subscription = $true } }
    }
    foreach ($edition in $editions) { if ($edition -match 'Microsoft 365|Office 365') { $subscription = $true } }
    if ($subscription) {
        $Html.Add('<p>' + (ConvertTo-CaramosHtmlText 'Máy dùng Microsoft 365: với tài khoản Microsoft 365 của công ty, Word, Excel, PowerPoint và Outlook bản web dùng được trong trình duyệt trên CaramOS.') + '</p>')
    }
}

function Add-CaramosFoldersHtml {
    param([System.Collections.Generic.List[string]]$Html, [System.Collections.IDictionary]$Report)
    $Html.Add('<h2>Dữ liệu cần chép</h2>')
    $folders = $Report.folders
    if ($folders.status -ne 'ok') {
        $Html.Add('<p>Không đếm được dữ liệu trong các thư mục người dùng.</p>')
        return
    }
    $labels = @{}
    foreach ($item in (ConvertTo-CaramosArray $folders.items)) { $labels[$item.key] = $item.label }
    $rows = New-Object System.Collections.Generic.List[string]
    foreach ($item in (ConvertTo-CaramosArray $folders.items)) {
        $label = ConvertTo-CaramosHtmlText $item.label
        $excludes = ConvertTo-CaramosArray $item.excludes
        if ($excludes.Count -gt 0) {
            $names = @($excludes | ForEach-Object { $labels[$_] })
            $label = $label + '<span class="sub">' + (ConvertTo-CaramosHtmlText ('không kể ' + (Join-CaramosList -Items $names) + ', tính ở dòng riêng')) + '</span>'
        }
        $location = ''
        $size = ''
        $count = ''
        switch ($item.status) {
            'ok' {
                $location = Get-CaramosLocationLabel $item.location
                $size = Format-CaramosSize $item.bytes
                $count = Format-CaramosNumber $item.files
                if ($item.partial) { $count = $count + ' (chưa đếm hết)' }
            }
            'same-as' { $location = 'Cùng thư mục với ' + $labels[$item.sameAs] }
            'network' { $location = 'Trên máy chủ mạng, không đếm' }
            'missing' { $location = 'Không có' }
            'not-set' { $location = 'Không có' }
            'unreadable' { $location = 'Không đọc được' }
        }
        $rows.Add('<tr><td>' + $label + '</td><td>' + (ConvertTo-CaramosHtmlText $location) + '</td><td class="num">' + (ConvertTo-CaramosHtmlText $size) + '</td><td class="num">' + (ConvertTo-CaramosHtmlText $count) + '</td></tr>')
    }
    $total = $folders.total
    $rows.Add('<tr class="total"><td>Tổng</td><td></td><td class="num">' + (ConvertTo-CaramosHtmlText (Format-CaramosSize $total.bytes)) + '</td><td class="num">' + (ConvertTo-CaramosHtmlText (Format-CaramosNumber $total.files)) + '</td></tr>')
    Add-CaramosTable -Html $Html -Headers @('Thư mục', 'Vị trí', 'Dung lượng', 'Số tệp') -HeaderClasses @('', '', 'num', 'num') -Rows $rows -Widths @(42, 24, 17, 17)

    $notes = New-Object System.Collections.Generic.List[string]
    if ($total.cloudFiles -gt 0) {
        $notes.Add((Format-CaramosNumber $total.cloudFiles) + ' tệp (' + (Format-CaramosSize $total.cloudBytes) + ') trên OneDrive, chưa tải về: chưa tính vào tổng trên. Các tệp này vẫn còn trên OneDrive.')
    }
    if ($total.cloudDirs -gt 0) {
        $notes.Add((Format-CaramosNumber $total.cloudDirs) + ' thư mục trên OneDrive chưa có trên máy nên không đếm được tệp bên trong.')
    }
    if ($total.unreadableDirs -gt 0) {
        $notes.Add((Format-CaramosNumber $total.unreadableDirs) + ' thư mục không đọc được (không có quyền hoặc đường dẫn quá dài) nên không đếm.')
    }
    if ($total.skippedLinks -gt 0) {
        $notes.Add('Bỏ qua ' + (Format-CaramosNumber $total.skippedLinks) + ' liên kết (shortcut thư mục kiểu junction hoặc symbolic link) để không đếm trùng.')
    }
    if ($total.partial) {
        $notes.Add('Việc đếm tệp dừng sau ' + [string][math]::Round([double]$CaramosConfig.ScanBudgetSeconds / 60) + ' phút vì thư mục quá lớn; con số thật lớn hơn.')
    }
    $zalo = $folders.zaloAppData
    if ($null -ne $zalo -and $zalo.found) {
        $notes.Add('Thư mục dữ liệu của ứng dụng Zalo (ZaloPC, ZaloData) chiếm khoảng ' + (Format-CaramosSize $zalo.bytes) + '; phần này không tính vào tổng trên.')
    }
    foreach ($note in $notes) { $Html.Add('<p>' + (ConvertTo-CaramosHtmlText $note) + '</p>') }
    $Html.Add('<p>' + (ConvertTo-CaramosHtmlText 'Công cụ “Chuyển dữ liệu từ Windows” của CaramOS chép các thư mục trên (Desktop, Documents, Pictures, Downloads, Music, Videos, Zalo Received Files), dấu trang trình duyệt (Chrome, Edge, Cốc Cốc), thư Outlook (.pst) sang Thunderbird và font đã cài thêm.') + '</p>')
}

function Add-CaramosFileTypesHtml {
    param([System.Collections.Generic.List[string]]$Html, [System.Collections.IDictionary]$Report)
    $Html.Add('<h2>Tệp có macro và tệp cũ</h2>')
    $types = $Report.fileTypes
    if ($types.status -ne 'ok') {
        $Html.Add('<p>Không đếm được tệp trong các thư mục người dùng.</p>')
        return
    }
    $counts = $types.counts
    $bytes = $types.bytes
    $rows = New-Object System.Collections.Generic.List[string]
    $macroRows = @(
        @('Excel có macro (.xlsm, .xltm)', ($counts['.xlsm'] + $counts['.xltm'])),
        @('Excel nhị phân (.xlsb), có thể có macro', $counts['.xlsb']),
        @('Add-in Excel (.xla, .xlam)', ($counts['.xla'] + $counts['.xlam'])),
        @('Word có macro (.docm, .dotm)', ($counts['.docm'] + $counts['.dotm'])),
        @('PowerPoint có macro (.pptm)', $counts['.pptm'])
    )
    foreach ($row in $macroRows) {
        $rows.Add('<tr><td>' + (ConvertTo-CaramosHtmlText $row[0]) + '</td><td class="num">' + (ConvertTo-CaramosHtmlText (Format-CaramosNumber $row[1])) + '</td></tr>')
    }
    $rows.Add('<tr class="total"><td>Tổng tệp có macro</td><td class="num">' + (ConvertTo-CaramosHtmlText (Format-CaramosNumber $types.macroTotal)) + '</td></tr>')
    Add-CaramosTable -Html $Html -Headers @('Loại tệp', 'Số tệp') -HeaderClasses @('', 'num') -Rows $rows -Widths @(72, 28) -TableClass 'fixed narrow'

    $rows = New-Object System.Collections.Generic.List[string]
    $oldRows = @(
        @('Word định dạng cũ (.doc)', (Format-CaramosNumber $counts['.doc'])),
        @('Excel định dạng cũ (.xls)', (Format-CaramosNumber $counts['.xls'])),
        @('PowerPoint định dạng cũ (.ppt)', (Format-CaramosNumber $counts['.ppt'])),
        @('Thư Outlook (.pst)', (Get-CaramosCountAndSize -Count $counts['.pst'] -Bytes $bytes['.pst'])),
        @('Hộp thư Outlook lưu trên máy (.ost)', (Get-CaramosCountAndSize -Count $counts['.ost'] -Bytes $bytes['.ost']))
    )
    $fonts = $Report.fonts
    if ($fonts.status -eq 'ok') {
        $oldRows += , @('Phông chữ tiếng Việt cũ (TCVN3, VNI)', (Format-CaramosNumber $fonts.legacyVietnamese))
        $oldRows += , @('Phông chữ cài thêm cho người dùng này', (Format-CaramosNumber $fonts.userInstalled))
    }
    foreach ($row in $oldRows) {
        $rows.Add('<tr><td>' + (ConvertTo-CaramosHtmlText $row[0]) + '</td><td class="num">' + (ConvertTo-CaramosHtmlText $row[1]) + '</td></tr>')
    }
    Add-CaramosTable -Html $Html -Headers @('Loại', 'Số lượng') -HeaderClasses @('', 'num') -Rows $rows -Widths @(72, 28) -TableClass 'fixed narrow'

    $paragraphs = New-Object System.Collections.Generic.List[string]
    if ($types.macroTotal -gt 0) {
        $paragraphs.Add('Macro VBA không chạy giống như trong Microsoft Office khi mở bằng ONLYOFFICE, WPS Office hay LibreOffice. Hãy mở thử các tệp có macro quan trọng (bảng lương, công nợ, hàm đọc số tiền thành chữ) trên máy chạy thử CaramOS. Tệp nào bắt buộc cần macro thì giữ một máy Windows có Microsoft Office và mở từ CaramOS bằng Remmina.')
    }
    if ($types.oldTotal -gt 0) {
        $paragraphs.Add('Tệp .doc, .xls, .ppt thường mở được bằng ONLYOFFICE, WPS Office và LibreOffice. Tài liệu cũ gõ bằng phông TCVN3 (.VnTime) hay VNI cần chuyển sang Unicode: trên CaramOS, bấm chuột phải vào tệp rồi chọn “Chuyển mã sang Unicode”.')
    }
    elseif ($fonts.status -eq 'ok' -and $fonts.legacyVietnamese -gt 0) {
        $paragraphs.Add('Máy có phông chữ TCVN3 hoặc VNI, nên có thể còn tài liệu gõ bằng các bảng mã cũ này. Trên CaramOS, bấm chuột phải vào tệp rồi chọn “Chuyển mã sang Unicode”.')
    }
    if ($counts['.pst'] -gt 0) {
        $paragraphs.Add('Tệp thư Outlook (.pst): công cụ “Chuyển dữ liệu từ Windows” chuyển thư sang Thunderbird.')
    }
    if ($counts['.ost'] -gt 0) {
        $paragraphs.Add('Tệp .ost là bản sao trên máy của hộp thư trên máy chủ (Microsoft 365, Exchange hoặc IMAP); thư gốc vẫn nằm trên máy chủ.')
    }
    foreach ($paragraph in $paragraphs) { $Html.Add('<p>' + (ConvertTo-CaramosHtmlText $paragraph) + '</p>') }
}

function Add-CaramosSummaryHtml {
    param([System.Collections.Generic.List[string]]$Html, [System.Collections.IDictionary]$Report)
    $Html.Add('<section class="summary">')
    $Html.Add('<h2>Tóm tắt</h2>')
    foreach ($paragraph in (Get-CaramosSummaryParagraphs -Report $Report)) { $Html.Add('<p>' + (ConvertTo-CaramosHtmlText $paragraph) + '</p>') }
    $Html.Add('</section>')
}

function Add-CaramosMachineHtml {
    param([System.Collections.Generic.List[string]]$Html, [System.Collections.IDictionary]$Report)
    $Html.Add('<h2>Máy tính</h2>')
    $machine = $Report.machine
    if ($machine.status -eq 'error') { $Html.Add('<p>Không đọc được thông tin máy.</p>') }
    $Html.Add('<div class="table-wrap"><table><tbody>')
    foreach ($row in (Get-CaramosMachineRows -Machine $machine)) {
        $Html.Add('<tr><th scope="row">' + (ConvertTo-CaramosHtmlText $row[0]) + '</th><td>' + (ConvertTo-CaramosHtmlText $row[1]) + '</td></tr>')
    }
    $Html.Add('</tbody></table></div>')
    foreach ($paragraph in (Get-CaramosMachineParagraphs -Machine $machine)) { $Html.Add('<p>' + (ConvertTo-CaramosHtmlText $paragraph) + '</p>') }
}

function Get-CaramosCountAndSize {
    param([long]$Count, [long]$Bytes)
    if ($Count -le 0) { return '0' }
    return (Format-CaramosNumber $Count) + ' tệp, ' + (Format-CaramosSize $Bytes)
}

function ConvertTo-CaramosReportHtml {
    param([Parameter(Mandatory = $true)][System.Collections.IDictionary]$Report)
    $invariant = [System.Globalization.CultureInfo]::InvariantCulture
    $html = New-Object System.Collections.Generic.List[string]
    $title = 'Khảo sát chuyển sang CaramOS'
    $documentTitle = $title
    if ($Report.computerName) { $documentTitle = $title + ' – ' + $Report.computerName }
    $created = [datetime]::Now
    try { $created = [datetime]::ParseExact($Report.createdAt.Substring(0, 19), 'yyyy-MM-ddTHH:mm:ss', $invariant) } catch { }
    $when = 'ngày ' + $created.ToString('dd/MM/yyyy', $invariant) + ' lúc ' + $created.ToString('HH:mm', $invariant)
    $meta = 'Khảo sát ' + $when + '.'
    if ($Report.computerName) { $meta = 'Máy ' + $Report.computerName + ', khảo sát ' + $when + '.' }
    elseif ($Report.computerNameHidden) { $meta = 'Khảo sát ' + $when + '. Tên máy đã được ẩn.' }

    $html.Add('<!DOCTYPE html>')
    $html.Add('<html lang="vi">')
    $html.Add('<head>')
    $html.Add('<meta charset="utf-8">')
    $html.Add('<meta name="viewport" content="width=device-width, initial-scale=1">')
    $html.Add('<meta name="generator" content="caramos-assess.ps1 ' + (ConvertTo-CaramosHtmlText $Report.scriptVersion) + '">')
    $html.Add('<title>' + (ConvertTo-CaramosHtmlText $documentTitle) + '</title>')
    $html.Add('<style>')
    $html.Add((Get-CaramosReportCss))
    $html.Add('</style>')
    $html.Add('</head>')
    $html.Add('<body>')
    $html.Add('<main>')
    $html.Add('<h1>' + (ConvertTo-CaramosHtmlText $title) + '</h1>')
    $html.Add('<p class="meta">' + (ConvertTo-CaramosHtmlText $meta) + '</p>')

    $sections = @(
        @('Add-CaramosSummaryHtml', 'Tóm tắt'),
        @('Add-CaramosMachineHtml', 'Máy tính'),
        @('Add-CaramosProgramsHtml', 'Chương trình đã cài'),
        @('Add-CaramosPrintersHtml', 'Máy in và máy quét'),
        @('Add-CaramosUsbHtml', 'Thiết bị USB'),
        @('Add-CaramosOfficeHtml', 'Microsoft Office'),
        @('Add-CaramosFoldersHtml', 'Dữ liệu cần chép'),
        @('Add-CaramosFileTypesHtml', 'Tệp có macro và tệp cũ')
    )
    foreach ($section in $sections) {
        # A section that fails on unexpected data is replaced by one line; the rest of the report stays.
        $mark = $html.Count
        try { & $section[0] -Html $html -Report $Report }
        catch {
            if ($html.Count -gt $mark) { $html.RemoveRange($mark, $html.Count - $mark) }
            $html.Add('<h2>' + (ConvertTo-CaramosHtmlText $section[1]) + '</h2>')
            $html.Add('<p>Không tạo được mục này của báo cáo.</p>')
        }
    }

    $tableDate = ''
    if ($Report.adviceTable.updated) { $tableDate = ', bảng gợi ý cập nhật ngày ' + $Report.adviceTable.updated }
    $note = 'Báo cáo này chỉ ghi số lượng và dung lượng tệp theo thư mục và loại tệp. Script không ghi lại tên tệp, không đọc nội dung tài liệu, không ghi tên người dùng Windows, không xem lịch sử duyệt web hay thư, và không kết nối mạng. Các gợi ý chỉ để tham khảo, cần thử trên máy thật (chạy CaramOS từ USB) trước khi chuyển. Báo cáo được tạo bởi caramos-assess.ps1 phiên bản ' + $Report.scriptVersion + $tableDate + '.'
    $html.Add('<div class="note"><p>' + (ConvertTo-CaramosHtmlText $note) + '</p></div>')
    $html.Add('</main>')
    $html.Add('</body>')
    $html.Add('</html>')
    return ($html.ToArray() -join "`r`n") + "`r`n"
}

# ---------------------------------------------------------------------------
# Saving and the main entry point
# ---------------------------------------------------------------------------

function Get-CaramosFreeFileName {
    param([string]$Directory, [string]$BaseName)
    $candidate = Join-Path $Directory ($BaseName + '.html')
    $number = 2
    while ((Test-Path -LiteralPath $candidate) -or (Test-Path -LiteralPath ([System.IO.Path]::ChangeExtension($candidate, '.json')))) {
        $candidate = Join-Path $Directory ($BaseName + '-' + $number + '.html')
        $number++
    }
    return $candidate
}

function Save-CaramosReportFiles {
    param([string]$Html, [AllowNull()][string]$Json, [AllowNull()][object]$Directories, [string]$BaseName)
    foreach ($directory in (ConvertTo-CaramosArray $Directories)) {
        $dir = [string]$directory
        if ([string]::IsNullOrWhiteSpace($dir)) { continue }
        $htmlPath = $null
        try {
            if (-not (Test-Path -LiteralPath $dir -PathType Container)) { [void][System.IO.Directory]::CreateDirectory($dir) }
            $htmlPath = Get-CaramosFreeFileName -Directory $dir -BaseName $BaseName
            [System.IO.File]::WriteAllText($htmlPath, $Html, (New-Object System.Text.UTF8Encoding -ArgumentList $true))
        }
        catch { continue }
        $jsonPath = $null
        if (-not [string]::IsNullOrEmpty($Json)) {
            $jsonPath = [System.IO.Path]::ChangeExtension($htmlPath, '.json')
            try { [System.IO.File]::WriteAllText($jsonPath, $Json, (New-Object System.Text.UTF8Encoding -ArgumentList $false)) }
            catch { $jsonPath = $null }
        }
        return [pscustomobject]@{ HtmlPath = $htmlPath; JsonPath = $jsonPath; Directory = $dir }
    }
    throw 'Không ghi được báo cáo vào thư mục nào.'
}

function Invoke-CaramosAssessment {
    param(
        [string]$OutputDirectory,
        [switch]$NoOpen,
        [switch]$HideComputerName,
        [string]$ScriptDirectory = $CaramosAssessScriptDirectory
    )
    $now = Get-Date
    Write-CaramosStatus ('Khảo sát chuyển sang CaramOS (caramos-assess ' + $CaramosAssessVersion + ')')
    Write-CaramosStatus 'Script chỉ đọc thông tin: không thay đổi gì trên máy và không kết nối mạng.'
    $tablePath = $null
    if ($ScriptDirectory) { $tablePath = Join-Path $ScriptDirectory 'caramos-assess-programs.json' }
    $report = New-CaramosReport -HideComputerName:$HideComputerName -AdviceTablePath $tablePath -Now $now
    $html = ConvertTo-CaramosReportHtml -Report $report
    $json = $null
    try { $json = ConvertTo-CaramosJson -InputObject $report } catch { $json = $null }
    $desktop = $null
    try { $desktop = Get-CaramosDesktopPath } catch { $desktop = $null }
    $directories = New-Object System.Collections.Generic.List[string]
    if ($OutputDirectory) { $directories.Add($OutputDirectory) } elseif ($ScriptDirectory) { $directories.Add($ScriptDirectory) }
    if ($desktop) { $directories.Add($desktop) }
    $baseName = 'khao-sat-caramos-' + $now.ToString('yyyyMMdd-HHmm', [System.Globalization.CultureInfo]::InvariantCulture)
    $saved = Save-CaramosReportFiles -Html $html -Json $json -Directories $directories.ToArray() -BaseName $baseName
    if ($directories.Count -gt 0 -and $saved.Directory -ne $directories[0]) {
        Write-CaramosStatus 'Không ghi được vào thư mục chứa script, nên báo cáo được lưu ra Desktop.'
    }
    Write-CaramosStatus 'Đã lưu báo cáo:'
    Write-CaramosStatus ('  ' + $saved.HtmlPath)
    if ($saved.JsonPath) { Write-CaramosStatus ('  ' + $saved.JsonPath + ' (cùng dữ liệu, dạng JSON)') }
    if (-not $NoOpen) {
        try { Start-Process -FilePath $saved.HtmlPath } catch { Write-CaramosStatus 'Không tự mở được báo cáo; hãy mở tệp trên bằng trình duyệt.' }
    }
    return [pscustomobject]@{ HtmlPath = $saved.HtmlPath; JsonPath = $saved.JsonPath; Report = $report }
}

# Run only when started as a script, not when dot-sourced by the tests.
if ($MyInvocation.InvocationName -ne '.') {
    try {
        $null = Invoke-CaramosAssessment -OutputDirectory $OutputDirectory -NoOpen:$NoOpen -HideComputerName:$HideComputerName
    }
    catch {
        Write-CaramosStatus ('Không tạo được báo cáo: ' + $_.Exception.Message)
        exit 1
    }
}
