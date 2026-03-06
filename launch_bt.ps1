Set-Location C:\hvf_trader
Remove-Item bt_status.txt, bt_results.txt, bt_error.txt -ErrorAction SilentlyContinue
$p = Start-Process -FilePath "C:\hvf_trader\venv\Scripts\python.exe" -ArgumentList "C:\hvf_trader\run_bt.py" -PassThru -WindowStyle Hidden
Write-Output "PID: $($p.Id)"
Start-Sleep -Seconds 5
Write-Output "HasExited: $($p.HasExited)"
if ($p.HasExited) {
    Write-Output "ExitCode: $($p.ExitCode)"
}
