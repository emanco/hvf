# Daily SQLite backup — compressed, keeps last 7 days.
# Schedule via Windows Task Scheduler to run daily at 22:00 UTC.
#
# Setup (run once in PowerShell as admin):
#   $action = New-ScheduledTaskAction -Execute "PowerShell.exe" -Argument "-File C:\hvf_trader\scripts\daily_backup.ps1"
#   $trigger = New-ScheduledTaskTrigger -Daily -At "22:00"
#   Register-ScheduledTask -TaskName "HVF_DB_Backup" -Action $action -Trigger $trigger -Description "Daily SQLite backup"

$dbPath = "C:\hvf_trader\hvf_trader.db"
$backupDir = "C:\hvf_trader\backups"
$maxDays = 7

# Create backup dir if needed
if (-not (Test-Path $backupDir)) {
    New-Item -ItemType Directory -Path $backupDir | Out-Null
}

# Create timestamped compressed backup using .NET GZip
$timestamp = Get-Date -Format "yyyy-MM-dd"
$backupFile = Join-Path $backupDir "hvf_trader_$timestamp.db.gz"

if (Test-Path $dbPath) {
    try {
        $sourceStream = [System.IO.File]::OpenRead($dbPath)
        $destStream = [System.IO.File]::Create($backupFile)
        $gzipStream = New-Object System.IO.Compression.GZipStream($destStream, [System.IO.Compression.CompressionMode]::Compress)
        $sourceStream.CopyTo($gzipStream)
        $gzipStream.Close()
        $destStream.Close()
        $sourceStream.Close()

        $sizeMB = [math]::Round((Get-Item $backupFile).Length / 1MB, 2)
        Write-Output "Backup created: $backupFile ($sizeMB MB)"
    } catch {
        Write-Output "ERROR: Backup failed: $_"
        exit 1
    }
} else {
    Write-Output "ERROR: Database not found at $dbPath"
    exit 1
}

# Prune backups older than $maxDays
$cutoff = (Get-Date).AddDays(-$maxDays)
Get-ChildItem $backupDir -Filter "hvf_trader_*.db.gz" |
    Where-Object { $_.LastWriteTime -lt $cutoff } |
    ForEach-Object {
        Remove-Item $_.FullName
        Write-Output "Pruned old backup: $($_.Name)"
    }

Write-Output "Backup complete. Kept last $maxDays days."
