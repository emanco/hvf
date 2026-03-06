Set-Location C:\hvf_trader
# Kill any existing Python processes
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2

# Start trader as detached process (no output redirection — it logs to its own files)
$p = Start-Process -FilePath "C:\hvf_trader\venv\Scripts\python.exe" -ArgumentList "-u", "C:\hvf_trader\main.py" -PassThru -WindowStyle Hidden
Write-Output "Trader PID: $($p.Id)"
Start-Sleep -Seconds 15
Write-Output "HasExited: $($p.HasExited)"
if ($p.HasExited) {
    Write-Output "ExitCode: $($p.ExitCode)"
} else {
    Write-Output "Running OK"
    Write-Output "--- Last 5 log lines ---"
    Get-Content C:\hvf_trader\logs\main.log -Tail 5 -ErrorAction SilentlyContinue
}
