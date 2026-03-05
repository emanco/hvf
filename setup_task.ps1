$action = New-ScheduledTaskAction -Execute "C:\hvf_trader\venv\Scripts\python.exe" -Argument "C:\hvf_trader\main.py" -WorkingDirectory "C:\hvf_trader"
$trigger = New-ScheduledTaskTrigger -AtLogon
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Days 365) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId "Administrator" -LogonType Interactive -RunLevel Highest

# Remove existing task if present
Unregister-ScheduledTask -TaskName "HVF_Bot" -Confirm:$false -ErrorAction SilentlyContinue

# Create and register the task
Register-ScheduledTask -TaskName "HVF_Bot" -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description "HVF Auto-Trader Bot"

# Start it immediately
Start-ScheduledTask -TaskName "HVF_Bot"

Write-Output "Task created and started."
Start-Sleep -Seconds 3
Get-ScheduledTask -TaskName "HVF_Bot" | Format-List TaskName, State
