# Fetch what the Windows app needs at runtime into vendor/.
$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path vendor | Out-Null

# --- FFmpeg -----------------------------------------------------------------
# Two sources, three tries each. The first is much the smaller build — 106 MB
# against 185 MB, and the difference lands squarely in what someone has to
# download to use this. The second is on GitHub's own CDN, so it is up whenever
# the runner is, and it is why the first one answering 503 can no longer fail a
# release the way it did once already.
$sources = @(
  "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
  "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
)
$got = $false
foreach ($url in $sources) {
  for ($try = 1; $try -le 3 -and -not $got; $try++) {
    try {
      Write-Host "Fetching $url (attempt $try)"
      Invoke-WebRequest -Uri $url -OutFile ffmpeg.zip -UseBasicParsing -TimeoutSec 300
      $got = $true
    } catch {
      Write-Host "  failed: $($_.Exception.Message)"
      Start-Sleep -Seconds (5 * $try)
    }
  }
  if ($got) { break }
}
if (-not $got) { throw "Could not download FFmpeg from any source." }

Expand-Archive ffmpeg.zip -DestinationPath ffmpeg-src -Force
Get-ChildItem -Path ffmpeg-src -Recurse -Include ffmpeg.exe,ffprobe.exe |
  ForEach-Object { Copy-Item $_.FullName -Destination vendor -Force }

# --- FriBiDi ----------------------------------------------------------------
# Pillow asks the loader for fribidi-0.dll, then libfribidi-0.dll, then
# fribidi.dll. MSYS2 ships it as the second; the app tries all three.
#
# MSYS2 does not install to a fixed path on a runner. It lands in the runner's
# temp directory, not C:\msys64, which is what an earlier build failed on. The
# workflow passes the action's own answer in MSYS2_LOCATION; the fixed paths are
# only a fallback.
$roots = @($env:MSYS2_LOCATION, "$env:RUNNER_TEMP\msys64", "C:\msys64") |
  Where-Object { $_ -and (Test-Path $_) }

$dll = $null
$runtime = $null
foreach ($root in $roots) {
  $bin = Join-Path $root "mingw64\bin"
  if (-not (Test-Path $bin)) { continue }
  $dll = Get-ChildItem $bin -Filter "*fribidi*.dll" -ErrorAction SilentlyContinue |
    Select-Object -First 1
  if ($dll) { $runtime = $bin; break }
}
if (-not $dll) {
  Write-Host "MSYS2_LOCATION was: '$env:MSYS2_LOCATION'"
  Write-Host "Looked under: $($roots -join '; ')"
  # Last resort: the installation is somewhere, so go and find it rather than
  # failing on a guess about the layout.
  foreach ($base in @($env:RUNNER_TEMP, "C:\", "D:\a")) {
    if (-not ($base -and (Test-Path $base))) { continue }
    Write-Host "Searching $base ..."
    $dll = Get-ChildItem $base -Recurse -Filter "*fribidi*.dll" -ErrorAction SilentlyContinue |
      Select-Object -First 1
    if ($dll) { $runtime = $dll.DirectoryName; break }
  }
}
if (-not $dll) { throw "FriBiDi not found anywhere; Arabic would not render." }

Write-Host "Found $($dll.FullName)"
Copy-Item $dll.FullName -Destination vendor\fribidi-0.dll -Force

# A MinGW build can lean on its own runtime libraries. Cheap insurance, and
# harmless when they turn out not to be needed.
foreach ($name in @("libwinpthread-1.dll", "libgcc_s_seh-1.dll")) {
  $extra = Join-Path $runtime $name
  if (Test-Path $extra) { Copy-Item $extra -Destination vendor -Force }
}

# Prove it loads now, the same way the app will. A library that is present but
# unusable looks identical to a missing one by the time the app reports it, and
# the end of a ten-minute build is a slow place to learn that.
$probe = 'import ctypes, os; d = os.path.abspath("vendor"); os.add_dll_directory(d); ctypes.CDLL(os.path.join(d, "fribidi-0.dll")); print("FriBiDi loads")'
python -c $probe
if ($LASTEXITCODE -ne 0) { throw "The FriBiDi DLL is there but will not load." }

Get-ChildItem vendor
