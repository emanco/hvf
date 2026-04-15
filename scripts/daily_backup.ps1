# Daily SQLite backup — compressed, keeps last 7 days.
# Uses SQLite .backup command for safe hot-copy (works with WAL mode).
#
# Schedule via Windows Task Scheduler (run once in admin PowerShell):
#   $action = New-ScheduledTaskAction -Execute "PowerShell.exe" -Argument "-File C:\hvf_trader\scripts\daily_backup.ps1"
#   $trigger = New-ScheduledTaskTrigger -Daily -At "22:00"
#   Register-ScheduledTask -TaskName "HVF_DB_Backup" -Action $action -Trigger $trigger -Description "Daily SQLite backup"

$dbPath = "C:\hvf_trader\hvf_trader.db"
$backupDir = "C:\hvf_trader\backups"
$pythonExe = "C:\hvf_trader\venv\Scripts\python.exe"
$maxDays = 7

# Create backup dir if needed
if (-not (Test-Path $backupDir)) {
    New-Item -ItemType Directory -Path $backupDir | Out-Null
}

$timestamp = Get-Date -Format "yyyy-MM-dd"
$tempFile = Join-Path $backupDir "hvf_trader_$timestamp.db"
$backupFile = Join-Path $backupDir "hvf_trader_$timestamp.db.gz"

# Step 1: Safe hot-copy using Python's sqlite3.backup (works with WAL mode)
if (Test-Path $dbPath) {
    try {
        & $pythonExe -c @"
import sqlite3
src = sqlite3.connect(r'$dbPath')
dst = sqlite3.connect(r'$tempFile')
src.backup(dst)
dst.close()
src.close()
print('SQLite backup OK')
"@
        if ($LASTEXITCODE -ne 0) { throw "SQLite backup failed" }
    } catch {
        Write-Output "ERROR: SQLite backup failed: $_"
        exit 1
    }
} else {
    Write-Output "ERROR: Database not found at $dbPath"
    exit 1
}

# Step 2: Compress with GZip and remove temp file
try {
    $sourceStream = [System.IO.File]::OpenRead($tempFile)
    $destStream = [System.IO.File]::Create($backupFile)
    $gzipStream = New-Object System.IO.Compression.GZipStream($destStream, [System.IO.Compression.CompressionMode]::Compress)
    $sourceStream.CopyTo($gzipStream)
    $gzipStream.Close()
    $destStream.Close()
    $sourceStream.Close()
    Remove-Item $tempFile

    $sizeMB = [math]::Round((Get-Item $backupFile).Length / 1MB, 2)
    Write-Output "Backup created: $backupFile ($sizeMB MB)"
} catch {
    Write-Output "ERROR: Compression failed: $_"
    # Clean up temp file on failure
    if (Test-Path $tempFile) { Remove-Item $tempFile }
    exit 1
}

# Step 3: Prune backups older than $maxDays
$cutoff = (Get-Date).AddDays(-$maxDays)
Get-ChildItem $backupDir -Filter "hvf_trader_*.db.gz" |
    Where-Object { $_.LastWriteTime -lt $cutoff } |
    ForEach-Object {
        Remove-Item $_.FullName
        Write-Output "Pruned old backup: $($_.Name)"
    }

Write-Output "Backup complete. Kept last $maxDays days."
