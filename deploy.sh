#!/usr/bin/env bash
set -euo pipefail

# HVF Auto-Trader Deploy Script
# Deploys hvf_trader/ package to C:\hvf_trader\ on VPS (single canonical path)

VPS="hvf-vps"
REMOTE_DIR="C:/hvf_trader"
LOCAL_PKG="hvf_trader"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

cd "$SCRIPT_DIR"

echo "=== HVF Deploy ==="

# 1. Stop the bot
echo "[1/6] Stopping bot..."
ssh "$VPS" "C:\nssm\nssm.exe stop HVF_Bot; exit 0"
sleep 2
echo "  Bot stopped."

# 2. Remove stale nested duplicate
echo "[2/6] Removing nested duplicate (hvf_trader/hvf_trader/)..."
ssh "$VPS" "if (Test-Path '${REMOTE_DIR}/hvf_trader') { Remove-Item '${REMOTE_DIR}/hvf_trader' -Recurse -Force; Write-Output '  Removed.' } else { Write-Output '  Not found, skipping.' }"

# 3. Clear __pycache__ everywhere
echo "[3/6] Clearing __pycache__..."
ssh "$VPS" "Get-ChildItem '${REMOTE_DIR}' -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue; Write-Output '  Cleared.'; exit 0"

# 4. Upload package contents to top level
echo "[4/6] Uploading hvf_trader/ contents..."
# Package subfolders
for dir in alerts backtesting data database detector execution monitoring risk tests; do
    scp -r "${LOCAL_PKG}/${dir}" "${VPS}:${REMOTE_DIR}/" 2>/dev/null
done
# Package files
scp "${LOCAL_PKG}/__init__.py" \
    "${LOCAL_PKG}/config.py" \
    "${LOCAL_PKG}/main.py" \
    "${LOCAL_PKG}/requirements.txt" \
    "${VPS}:${REMOTE_DIR}/" 2>/dev/null
echo "  Package uploaded."

# 5. Upload top-level scripts
echo "[5/6] Uploading scripts..."
scp install_nssm_service.ps1 launch_trader.ps1 start_bot.bat "${VPS}:${REMOTE_DIR}/" 2>/dev/null
echo "  Scripts uploaded."

# 6. Restart the bot
echo "[6/6] Starting bot..."
ssh "$VPS" "C:\nssm\nssm.exe start HVF_Bot; exit 0"
sleep 5
echo "  Verifying..."
ssh "$VPS" "C:\nssm\nssm.exe status HVF_Bot; exit 0"
ssh "$VPS" "Get-Content '${REMOTE_DIR}/logs/main.log' -Tail 3 -ErrorAction SilentlyContinue; exit 0"

echo ""
echo "=== Deploy complete ==="
