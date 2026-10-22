# Build the portable Windows app: dist\pygoals\pygoals.exe (+ pygoals-cli.exe)
# and dist\pygoals-<version>-win64.zip.
#   .\build.ps1            build
#   .\build.ps1 -Clean     wipe build\ and dist\ first
param([switch]$Clean, [string]$Python = "python")
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if ($Clean) { Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue }

& $Python -m pip install --disable-pip-version-check -q -r requirements-dev.txt
if ($LASTEXITCODE) { throw "pip install failed" }

& $Python -m PyInstaller --noconfirm --clean pygoals.spec
if ($LASTEXITCODE) { throw "PyInstaller failed" }

$out = Join-Path $PSScriptRoot "dist\pygoals"
# Never ship a developer's runtime files.
foreach ($f in "settings.ini", "state.json", "logs") { Remove-Item -Recurse -Force (Join-Path $out $f) -ErrorAction SilentlyContinue }
Copy-Item settings.example.ini, README.md $out

$version = (& $Python -c "from _version import __version__; print(__version__)").Trim()
$zip = Join-Path $PSScriptRoot "dist\pygoals-$version-win64.zip"
Remove-Item $zip -ErrorAction SilentlyContinue
Compress-Archive -Path $out -DestinationPath $zip
$size = (Get-ChildItem $out -Recurse | Measure-Object Length -Sum).Sum / 1MB
Write-Host ("Built {0}\pygoals.exe ({1:N0} MB folder) and {2}" -f $out, $size, $zip)
