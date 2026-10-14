# Builds and runs the stand-alone TLB proof test (tlbtest.cpp) with the same
# x64 clang-cl environment as tools\build.ps1. It does not touch the game build.
#
# From Ubuntu (WSL):
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'C:\src\ki-gold-recomp\tools\tlbtest\build.ps1'
# From PowerShell on Windows:
#   .\tools\tlbtest\build.ps1
#
# Output goes to build-tlbtest\ in the repo root (git-ignored, never committed).

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$outDir = Join-Path $repo "build-tlbtest"

$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
if (-not (Test-Path $vswhere)) {
    throw "vswhere.exe not found. Install Visual Studio Build Tools 2022 (docs/SETUP.md, Part 2)."
}
$vsPath = & $vswhere -latest -products * -property installationPath
if (-not $vsPath) { throw "No Visual Studio installation found (docs/SETUP.md, Part 2)." }
& "$vsPath\Common7\Tools\Launch-VsDevShell.ps1" -Arch amd64 -HostArch amd64 -SkipAutomaticLocation | Out-Null

New-Item -ItemType Directory -Force $outDir | Out-Null
$exe = Join-Path $outDir "tlbtest.exe"

Write-Host "== Build =="
& clang-cl /nologo /O2 /W4 /EHsc /std:c++20 (Join-Path $PSScriptRoot "tlbtest.cpp") "/Fo$outDir\" "/Fe$exe"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Build FAILED (exit $LASTEXITCODE)"
    exit $LASTEXITCODE
}

Write-Host "== Run =="
& $exe
Write-Host "tlbtest exit code: $LASTEXITCODE"
exit $LASTEXITCODE
