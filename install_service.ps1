# Create a Windows Scheduled Task that runs the trader at system startup
# and restarts on failure

$taskName = "HVFTrader"
$pythonPath = "C:\hvf_trader\venv\Scripts\python.exe"
$scriptPath = "C:\hvf_trader\run_trader_debug.py"

# Remove existing task if present
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

# Create the action
$action = New-ScheduledTaskAction -Execute $pythonPath -Argument $scriptPath -WorkingDirectory "C:\hvf_trader"

# Run at startup, also allow manual trigger
$trigger = New-ScheduledTaskTrigger -AtStartup

# Run as current user, with highest privileges
$principal = New-ScheduledTaskPrincipal -UserId "Administrator" -LogonType ServiceAccount -RunLevel Highest

# Settings: restart on failure, don't stop on idle, run indefinitely
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Days 0) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

# Register the task
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description "HVF Auto-Trader (Demo)"

Write-Output "Scheduled task '$taskName' created"

# Start it now
Start-ScheduledTask -TaskName $taskName
Start-Sleep -Seconds 5

$task = Get-ScheduledTask -TaskName $taskName
Write-Output "Task state: $($task.State)"
