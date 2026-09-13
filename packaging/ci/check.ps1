# The gate: does the built app say it can render?
#
# PATH is stripped on purpose. Someone who downloads an app and double-clicks it
# has put nothing on PATH, so anything the app can only find there it cannot find
# at all.
$env:PATH = "$env:SystemRoot\system32;$env:SystemRoot"
& dist\qalun\qalun.exe --doctor
$code = $LASTEXITCODE

# A windowed app cannot always reach the console it was started from, so fall
# back to the copy the report writes to disk. Without this a failure here is mute.
$report = "$env:LOCALAPPDATA\Qalun\doctor-report.txt"
if (Test-Path $report) { Write-Host "--- report ---"; Get-Content $report }
if ($code -ne 0) { throw "The built app cannot render yet (see above)." }
