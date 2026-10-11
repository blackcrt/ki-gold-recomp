# Configures the Windows port with CMake + Ninja + clang-cl (x64), and builds it
# when asked to.
#
# Adapted from tools/env-msvc.ps1 and BUILDING.md of the WWF WrestleMania 2000
# recomp (GPL-3.0): https://github.com/jessetbh/WWFWrestleMania2000Recomp
#
# From Ubuntu (WSL):
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'C:\src\ki-gold-recomp\tools\build.ps1'
# From PowerShell on Windows:
#   .\tools\build.ps1
#
#   (no switch)   configure only: checks the tools and writes build-msvc\
#   -Build        configure, then compile and link KIGoldRecompiled.exe
#   -Fresh        delete build-msvc\ first and start over
#   -BuildType    Release (default) or Debug
param(
    [switch]$Build,
    [switch]$Fresh,
    [ValidateSet("Release", "Debug")]
    [string]$BuildType = "Release"
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$buildDir = Join-Path $repo "build-msvc"

# Find Visual Studio Build Tools 2022. vswhere is installed with it, always here.
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
if (-not (Test-Path $vswhere)) {
    throw "vswhere.exe not found. Install Visual Studio Build Tools 2022 (docs/SETUP.md, Part 2)."
}
$vsPath = & $vswhere -latest -products * -property installationPath
if (-not $vsPath) { throw "No Visual Studio installation found (docs/SETUP.md, Part 2)." }

# Load the 64-bit environment. The Start menu Developer PowerShell is 32-bit by
# default, and a 32-bit build of the game does not work.
& "$vsPath\Common7\Tools\Launch-VsDevShell.ps1" -Arch amd64 -HostArch amd64 -SkipAutomaticLocation | Out-Null

foreach ($tool in @("clang-cl", "cmake", "ninja")) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        throw "$tool not found after loading the Visual Studio environment."
    }
}
$target = (& clang-cl --version | Select-String "Target:").ToString().Trim()
Write-Host "clang-cl $target"
if ($target -notmatch "x86_64") { throw "clang-cl is not targeting x64: $target" }

if ($Fresh -and (Test-Path $buildDir)) {
    Write-Host "Removing $buildDir"
    Remove-Item -Recurse -Force $buildDir
}

Write-Host "== Configure ($BuildType) =="
& cmake -S $repo -B $buildDir -G Ninja `
    -DCMAKE_C_COMPILER=clang-cl -DCMAKE_CXX_COMPILER=clang-cl `
    "-DCMAKE_BUILD_TYPE=$BuildType"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Configure FAILED (exit $LASTEXITCODE)"
    exit $LASTEXITCODE
}
Write-Host "Configure OK: $buildDir"

if ($Build) {
    Write-Host "== Build =="
    & cmake --build $buildDir --target KIGoldRecompiled
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Build FAILED (exit $LASTEXITCODE)"
        exit $LASTEXITCODE
    }
    Write-Host "Build OK: $buildDir\KIGoldRecompiled.exe"
}
