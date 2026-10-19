# Quick install / update of AULA F87 Control on Windows 10 and 11.
# Run in PowerShell (no admin needed):
#
#   irm https://raw.githubusercontent.com/RadianceADM/aula-f87-control/main/scripts/install-windows.ps1 | iex
#
# Uninstall:
#
#   $env:AULA_UNINSTALL = 1; irm https://raw.githubusercontent.com/RadianceADM/aula-f87-control/main/scripts/install-windows.ps1 | iex
#
# What it does:
#   1. finds Python 3.10+ (installs Python 3.12 with winget if there is none)
#   2. installs the latest release of the app from PyPI with pip
#   3. adds "AULA F87 Control" to the Start menu
#
# Options (environment variables):
#   AULA_VERSION = v0.3.2   install a specific release ("main" = latest code from GitHub)
#   AULA_PACKAGE = <path>   install from a local folder or any pip-installable URL

$ErrorActionPreference = 'Stop'
$Repo = 'RadianceADM/aula-f87-control'
$LinkPath = Join-Path ([Environment]::GetFolderPath('Programs')) 'AULA F87 Control.lnk'

function Write-Step([string]$Text) { Write-Host "==> $Text" -ForegroundColor Cyan }

function Find-Python {
    # Returns the command (as an array, e.g. 'py','-3') of a Python 3.10 or newer, or $null.
    foreach ($candidate in @('py -3', 'python', 'python3')) {
        $parts = $candidate -split ' '
        if (-not (Get-Command $parts[0] -ErrorAction SilentlyContinue)) { continue }
        $extra = @()
        if ($parts.Length -gt 1) { $extra = @($parts[1..($parts.Length - 1)]) }
        try {
            # The Microsoft Store "python" placeholder fails here and is skipped.
            $out = & $parts[0] @extra -c 'import sys; print(sys.version_info >= (3, 10))' 2>$null
        } catch { continue }
        if ($LASTEXITCODE -eq 0 -and "$out".Trim() -eq 'True') { return ,$parts }
    }
    return $null
}

function Invoke-Python([string[]]$Python, [string[]]$Arguments) {
    $extra = @()
    if ($Python.Length -gt 1) { $extra = @($Python[1..($Python.Length - 1)]) }
    & $Python[0] @extra @Arguments
}

$python = Find-Python

if ($env:AULA_UNINSTALL) {
    if ($python) {
        Write-Step 'Uninstalling AULA F87 Control'
        Invoke-Python $python @('-m', 'pip', 'uninstall', '--yes', 'aula-f87-control')
    }
    if (Test-Path $LinkPath) { Remove-Item $LinkPath }
    Remove-Item Env:\AULA_UNINSTALL
    Write-Step 'Uninstalled.'
    return
}

# 1. Python ---------------------------------------------------------------------
if (-not $python) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "Python 3.10 or newer is needed. Install it from https://www.python.org/downloads/ (tick 'Add python.exe to PATH'), then run this again."
    }
    Write-Step 'Installing Python 3.12 with winget'
    winget install --exact --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'User') + ';' + [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $python = Find-Python
    if (-not $python) { throw 'Python was installed but cannot be found yet. Open a new PowerShell window and run this again.' }
}
Write-Step ("Using Python: " + (Invoke-Python $python @('-c', 'import sys; print(sys.executable)')))

# 2. The app ----------------------------------------------------------------------
$package = $env:AULA_PACKAGE
if (-not $package) {
    $version = $env:AULA_VERSION
    if (-not $version) {
        $package = 'aula-f87-control'   # latest release, from PyPI
    } elseif ($version -eq 'main') {
        $package = "https://github.com/$Repo/archive/refs/heads/main.zip"
    } else {
        $package = 'aula-f87-control==' + $version.TrimStart('v')
    }
}
Write-Step "Installing AULA F87 Control from $package"
Invoke-Python $python @('-m', 'pip', 'install', '--upgrade', '--disable-pip-version-check', $package)
if ($LASTEXITCODE -ne 0) {
    Write-Step 'Retrying as a per-user install'
    Invoke-Python $python @('-m', 'pip', 'install', '--upgrade', '--user', '--disable-pip-version-check', $package)
    if ($LASTEXITCODE -ne 0) { throw 'pip could not install the app; see the messages above.' }
}

# 3. Start menu shortcut ------------------------------------------------------------
$scriptDirs = Invoke-Python $python @('-c', "import os, sysconfig; print(sysconfig.get_path('scripts')); print(sysconfig.get_path('scripts', os.name + '_user'))")
$gui = $null
foreach ($dir in $scriptDirs) {
    $candidate = Join-Path "$dir".Trim() 'aula-f87-control-gui.exe'
    if (Test-Path $candidate) { $gui = $candidate; break }
}
if (-not $gui) { throw "Installed, but aula-f87-control-gui.exe wasn't found in: $($scriptDirs -join ', ')" }

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($LinkPath)
$shortcut.TargetPath = $gui
$shortcut.WorkingDirectory = Split-Path $gui
$shortcut.Description = 'Lighting, music sync and battery for the AULA F87 keyboard'
$shortcut.Save()

Write-Step "Done. Open 'AULA F87 Control' from the Start menu."
Write-Host ("Command line: " + (Join-Path (Split-Path $gui) 'aula-f87-control.exe') + " status")
Write-Host 'Close AULA''s own software if it is running. To update later, run the same command again.'
