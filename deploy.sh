#!/usr/bin/env bash
set -euo pipefail

# HVF Auto-Trader Deploy Script
# Deploys hvf_trader/ package to C:\hvf_trader\ on VPS (single canonical path)

VPS="hvf-vps"
REMOTE_DIR="C:/hvf_trader"
LOCAL_PKG="hvf_trader"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

cd "$SCRIPT_DIR"

BOT_STOPPED=0
BANNER_SHOWN=0
FAILURES=()

# Every scp used to be piped to /dev/null. That hid two things: the error
# text itself, and — because of `set -e` — the fact that the script then
# aborted at step 4 with the bot already stopped at step 1. A failed deploy
# looked like a truncated log and left the service DOWN with no message.
# So: never discard scp stderr, collect every failure rather than dying on
# the first, and make "bot is still stopped" impossible to miss.
scp_checked() {
    local label="$1"
    shift
    if scp "$@"; then
        return 0
    fi
    echo "  ERROR: upload failed — ${label}" >&2
    FAILURES+=("${label}")
    return 0
}

banner_bot_down() {
    # An explicit `exit 1` also fires the EXIT trap, so guard against
    # printing this twice.
    [ "$BANNER_SHOWN" -eq 1 ] && return 0
    BANNER_SHOWN=1
    echo "" >&2
    echo "################################################################" >&2
    echo "#  BOT IS STOPPED and was NOT restarted." >&2
    echo "#  The VPS may hold a PARTIALLY updated tree — do not assume" >&2
    echo "#  the running code matches this repo." >&2
    echo "#" >&2
    echo "#  Fix the cause, then re-run:  ./deploy.sh" >&2
    echo "#  Or start as-is (accepts mixed code):" >&2
    echo "#    ssh ${VPS} \"C:\\nssm\\nssm.exe start HVF_Bot; exit 0\"" >&2
    echo "################################################################" >&2
}

# Catches anything set -e kills that the explicit checks below don't, so an
# unexpected abort can never leave the service quietly down.
on_exit() {
    local rc=$?
    if [ "$rc" -ne 0 ] && [ "$BOT_STOPPED" -eq 1 ]; then
        echo "" >&2
        echo "!!! Deploy ABORTED (exit ${rc})." >&2
        banner_bot_down
    fi
    exit "$rc"
}
trap on_exit EXIT

echo "=== HVF Deploy ==="

# 1. Stop the bot
echo "[1/6] Stopping bot..."
ssh "$VPS" "C:\nssm\nssm.exe stop HVF_Bot; exit 0"
BOT_STOPPED=1
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
    scp_checked "${LOCAL_PKG}/${dir}/" -r "${LOCAL_PKG}/${dir}" "${VPS}:${REMOTE_DIR}/"
done
# Package files (all .py at package root)
scp_checked "${LOCAL_PKG}/*.py" ${LOCAL_PKG}/*.py "${VPS}:${REMOTE_DIR}/"
scp_checked "${LOCAL_PKG}/requirements.txt" "${LOCAL_PKG}/requirements.txt" "${VPS}:${REMOTE_DIR}/"
echo "  Package uploaded."

# 5. Upload top-level scripts and utility scripts
echo "[5/6] Uploading scripts..."
scp_checked "launcher scripts" install_nssm_service.ps1 launch_trader.ps1 start_bot.bat "${VPS}:${REMOTE_DIR}/"
ssh "$VPS" "if (-not (Test-Path '${REMOTE_DIR}/scripts')) { New-Item -ItemType Directory -Path '${REMOTE_DIR}/scripts' -Force | Out-Null }; exit 0"
scp_checked "scripts/*.py" scripts/*.py "${VPS}:${REMOTE_DIR}/scripts/"
echo "  Scripts uploaded."

# Gate the restart on a fully successful upload. Restarting on a partial tree
# would run code that doesn't match any commit; the operator decides instead.
if [ ${#FAILURES[@]} -gt 0 ]; then
    echo "" >&2
    echo "!!! ${#FAILURES[@]} upload(s) FAILED:" >&2
    for f in "${FAILURES[@]}"; do
        echo "!!!   - ${f}" >&2
    done
    banner_bot_down
    exit 1
fi

# 6. Restart the bot
echo "[6/6] Starting bot..."
ssh "$VPS" "C:\nssm\nssm.exe start HVF_Bot; exit 0"
BOT_STOPPED=0
sleep 5
echo "  Verifying..."
ssh "$VPS" "C:\nssm\nssm.exe status HVF_Bot; exit 0"
ssh "$VPS" "Get-Content '${REMOTE_DIR}/logs/main.log' -Tail 3 -ErrorAction SilentlyContinue; exit 0"

echo ""
echo "=== Deploy complete ==="
