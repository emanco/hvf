# Setup MT5 auto-start on boot with Algo Trading enabled
# Run this once as Administrator on the VPS

$MT5Path = "C:\Program Files\MetaTrader 5 IC Markets Global\terminal64.exe"
$TaskName = "MT5_AutoStart"

# Remove existing task if present
schtasks /Delete /TN $TaskName /F 2>$null

# Create scheduled task that runs at system startup
# Triggers at boot with a 10-second delay to let Windows settle
$action = New-ScheduledTaskAction -Execute $MT5Path -Argument "/algotrading"
$trigger = New-ScheduledTaskTrigger -AtStartup
$trigger.Delay = "PT10S"
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId "Administrator" -LogonType S4U -RunLevel Highest

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description "Start MetaTrader 5 with Algo Trading enabled on boot"

Write-Host "Created scheduled task: $TaskName"
Write-Host "MT5 will auto-start with /algotrading on every boot"
Write-Host ""

# Verify
schtasks /Query /TN $TaskName /FO LIST | findstr /i "TaskName Status"
