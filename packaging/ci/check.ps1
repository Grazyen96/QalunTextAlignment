# The gate: does the built app say it can render?
#
# PATH is stripped on purpose. Someone who downloads an app and double-clicks it
# has put nothing on PATH, so anything the app can only find there it cannot find
# at all.
#
# --release makes playback, Qt's Arabic translation and an Arabic interface font
# blocking: a developer's checkout is only told about them, a release must have them.
# It also makes the Replicate client's import blocking whatever engine is configured,
# because the window offers WhisperX online. The engine is set to local here, so the
# sherpa-onnx runtime line blocks too, whatever the runner's environment says.
#
# When all that passes, check-transcription.sh (the same script macOS and Linux run)
# does a real transcription inside the built app; see the end of this file.
$env:QURANTEXT_TRANSCRIBE_ENGINE = "local"

# Kept for check-transcription.sh, which needs Git's bash and the runner's Python.
# Git's own bash.exe first: a bare `bash` can be WSL's, in System32.
$fullPath = $env:PATH
$gitBash = Join-Path $env:ProgramFiles "Git\bin\bash.exe"
if (-not (Test-Path $gitBash)) {
  # Git installed elsewhere: its bash is in bin\ beside the cmd\ that holds git.exe.
  # A bare `bash` only as the last resort, because that is the one that can be WSL's.
  $git = Get-Command git -ErrorAction SilentlyContinue
  $besideGit = if ($git) { Join-Path (Split-Path (Split-Path $git.Source)) "bin\bash.exe" } else { $null }
  if ($besideGit -and (Test-Path $besideGit)) {
    $gitBash = $besideGit
  } else {
    $found = Get-Command bash -ErrorAction SilentlyContinue
    $gitBash = if ($found) { $found.Source } else { $null }
  }
}

$env:PATH = "$env:SystemRoot\system32;$env:SystemRoot"

# Start-Process rather than `& app --doctor`, because the app is built windowed
# and PowerShell neither waits for a windowed executable nor sets $LASTEXITCODE
# for one. The call returned instantly with no exit code at all, and "no exit
# code" compared unequal to zero, so a build whose app had just printed "Ready
# to render." failed its own gate. -PassThru hands back the process to wait on
# and read the real code from.
#
# Bounded: -Wait would wait for ever, and a hang (starting Qt, asking for audio
# outputs) would hold the job for its 6 hours. After 180 s the app is killed and
# the gate fails.
$limitMs = 180000
$out = "doctor-out.txt"
$err = "doctor-err.txt"
$proc = Start-Process -FilePath "dist\qalun\qalun.exe" -ArgumentList "--doctor","--release" `
  -PassThru -NoNewWindow -RedirectStandardOutput $out -RedirectStandardError $err
# Reading the handle now is what keeps ExitCode readable after the process ends.
$null = $proc.Handle
$finished = $proc.WaitForExit($limitMs)
if (-not $finished) {
  $proc.Kill($true)
  $proc.WaitForExit()
}
$code = $proc.ExitCode

foreach ($file in @($out, $err)) {
  if ((Test-Path $file) -and (Get-Item $file).Length -gt 0) { Get-Content $file }
}

# The app also writes the report to disk. That is what to read if the streams
# came back empty, and it is the file a user is asked to send.
$report = "$env:LOCALAPPDATA\Qalun\doctor-report.txt"
if (Test-Path $report) {
  Write-Host "--- saved report ---"
  Get-Content $report
}

if (-not $finished) {
  throw "The gate failed: the built app's doctor did not finish within $($limitMs / 1000) s."
}
if ($code -ne 0) {
  throw "The gate failed: the built app's doctor reported a problem (exit code $code; see above)."
}
Write-Host "The built app reports it can render."

# A real transcription inside the built app. Only now, so a build that will not ship
# never downloads the model. The script strips PATH for the app itself.
if (-not $gitBash) {
  throw "The gate failed: no Git bash to run packaging/ci/check-transcription.sh with."
}
$env:PATH = $fullPath
& $gitBash packaging/ci/check-transcription.sh
if ($LASTEXITCODE -ne 0) {
  throw "The gate failed: the built app could not transcribe on this computer (exit code $LASTEXITCODE; see above)."
}
