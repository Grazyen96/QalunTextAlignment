# The gate: does the built app say it can render?
#
# PATH is stripped on purpose. Someone who downloads an app and double-clicks it
# has put nothing on PATH, so anything the app can only find there it cannot find
# at all.
$env:PATH = "$env:SystemRoot\system32;$env:SystemRoot"

# Start-Process rather than `& app --doctor`, because the app is built windowed
# and PowerShell neither waits for a windowed executable nor sets $LASTEXITCODE
# for one. The call returned instantly with no exit code at all, and "no exit
# code" compared unequal to zero, so a build whose app had just printed "Ready
# to render." failed its own gate. -Wait -PassThru is the form that waits and
# hands back the real code.
$out = "doctor-out.txt"
$err = "doctor-err.txt"
$proc = Start-Process -FilePath "dist\qalun\qalun.exe" -ArgumentList "--doctor" `
  -Wait -PassThru -NoNewWindow -RedirectStandardOutput $out -RedirectStandardError $err
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

if ($code -ne 0) { throw "The built app cannot render yet (exit code $code; see above)." }
Write-Host "The built app reports it can render."
