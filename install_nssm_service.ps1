# Install NSSM and create HVF_Bot Windows service
# Run once as Administrator on VPS

$ErrorActionPreference = "Stop"
$NssmDir = "C:\nssm"
$NssmExe = "$NssmDir\nssm.exe"
$ServiceName = "HVF_Bot"
$PythonExe = "C:\hvf_trader\venv\Scripts\python.exe"
$MainScript = "C:\hvf_trader\main.py"
$WorkDir = "C:\hvf_trader"
$LogDir = "C:\hvf_trader\logs"

# 1. Download NSSM if not present
if (-not (Test-Path $NssmExe)) {
    Write-Output "[1/5] Downloading NSSM..."
    New-Item -ItemType Directory -Path $NssmDir -Force | Out-Null
    $zipPath = "$env:TEMP\nssm.zip"
    Invoke-WebRequest -Uri "https://nssm.cc/release/nssm-2.24.zip" -OutFile $zipPath
    Expand-Archive -Path $zipPath -DestinationPath "$env:TEMP\nssm_extract" -Force
    Copy-Item "$env:TEMP\nssm_extract\nssm-2.24\win64\nssm.exe" $NssmExe
    Remove-Item $zipPath -Force
    Remove-Item "$env:TEMP\nssm_extract" -Recurse -Force
    Write-Output "  NSSM installed to $NssmExe"
} else {
    Write-Output "[1/5] NSSM already installed at $NssmExe"
}

# 2. Stop and remove old Scheduled Task
Write-Output "[2/5] Removing old Scheduled Task..."
Stop-ScheduledTask -TaskName $ServiceName -ErrorAction SilentlyContinue
Start-Sleep 2
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep 2
Unregister-ScheduledTask -TaskName $ServiceName -Confirm:$false -ErrorAction SilentlyContinue
Write-Output "  Scheduled Task removed."

# 3. Remove existing NSSM service if present (clean reinstall)
Write-Output "[3/5] Installing NSSM service..."
$ErrorActionPreference = "Continue"
& $NssmExe stop $ServiceName 2>&1 | Out-Null
& $NssmExe remove $ServiceName confirm 2>&1 | Out-Null
Start-Sleep 1
$ErrorActionPreference = "Stop"

# 4. Install and configure service
& $NssmExe install $ServiceName $PythonExe "-u $MainScript"
& $NssmExe set $ServiceName AppDirectory $WorkDir
& $NssmExe set $ServiceName DisplayName "HVF Auto-Trader Bot"
& $NssmExe set $ServiceName Description "HVF + KZ Hunt automated forex trading bot"

# Restart on failure: 5s delay, max 3 restarts
& $NssmExe set $ServiceName AppExit Default Restart
& $NssmExe set $ServiceName AppRestartDelay 5000
& $NssmExe set $ServiceName AppThrottle 10000

# Stdout/stderr logging
& $NssmExe set $ServiceName AppStdout "$LogDir\service_stdout.log"
& $NssmExe set $ServiceName AppStderr "$LogDir\service_stderr.log"
& $NssmExe set $ServiceName AppStdoutCreationDisposition 4
& $NssmExe set $ServiceName AppStderrCreationDisposition 4
& $NssmExe set $ServiceName AppRotateFiles 1
& $NssmExe set $ServiceName AppRotateBytes 10485760

# Start automatically on boot
& $NssmExe set $ServiceName Start SERVICE_AUTO_START
& $NssmExe set $ServiceName ObjectName LocalSystem

Write-Output "  Service installed."

# 5. Start the service
Write-Output "[4/5] Starting service..."
& $NssmExe start $ServiceName
Start-Sleep 5

Write-Output "[5/5] Verifying..."
& $NssmExe status $ServiceName
Get-Content "$LogDir\main.log" -Tail 3 -ErrorAction SilentlyContinue

Write-Output ""
Write-Output "=== NSSM service install complete ==="
Write-Output "Commands: nssm start|stop|restart|status HVF_Bot"
