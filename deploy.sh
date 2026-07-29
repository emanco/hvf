#!/usr/bin/env bash
set -euo pipefail

# HVF Auto-Trader Deploy Script
# Deploys hvf_trader/ package to C:\hvf_trader\ on VPS (single canonical path)

VPS="hvf-vps"
REMOTE_DIR="C:/hvf_trader"
LOCAL_PKG="hvf_trader"
REMOTE_PY="C:/hvf_trader/venv/Scripts/python.exe"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Deploy scope, declared ONCE. Both the upload loop and the post-upload hash
# verification read these, so the check can't drift from what's shipped —
# a verifier with its own copy of the file list would silently stop covering
# anything added to one and not the other.
PKG_DIRS=(alerts backtesting data database detector execution monitoring risk tests)
LAUNCHERS=(install_nssm_service.ps1 launch_trader.ps1 start_bot.bat)

cd "$SCRIPT_DIR"

BOT_STOPPED=0
BANNER_SHOWN=0
TMP_VERIFY=""
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
    [ -n "$TMP_VERIFY" ] && rm -f "$TMP_VERIFY"
    if [ "$rc" -ne 0 ] && [ "$BOT_STOPPED" -eq 1 ]; then
        echo "" >&2
        echo "!!! Deploy ABORTED (exit ${rc})." >&2
        banner_bot_down
    fi
    exit "$rc"
}
trap on_exit EXIT

# Emits a self-contained Python program: a local->remote SHA256 manifest
# followed by the comparison, to be run by the VPS interpreter over stdin.
# Hashing is the only check that proves the upload landed — scp reporting
# success only means the transfer returned 0, not that the bytes on the VPS
# are the bytes in this repo (stale file, truncated write, wrong path).
build_verify_script() {
    python3 - "$LOCAL_PKG" "$REMOTE_DIR" "${PKG_DIRS[@]}" <<'PYGEN'
import sys, os, glob, hashlib, json

pkg, remote_dir = sys.argv[1], sys.argv[2]
pkg_dirs = sys.argv[3:]
man = {}

def add(local_path, remote_path):
    with open(local_path, "rb") as fh:
        man[remote_path] = hashlib.sha256(fh.read()).hexdigest()

# __pycache__ is cleared on the VPS and regenerated at import, so comparing
# it would produce guaranteed false mismatches.
def keep(p):
    return os.path.isfile(p) and "__pycache__" not in p

for d in pkg_dirs:
    for p in glob.glob(os.path.join(pkg, d, "**", "*"), recursive=True):
        if keep(p):
            rel = os.path.relpath(p, pkg).replace(os.sep, "/")
            add(p, f"{remote_dir}/{rel}")

for p in glob.glob(os.path.join(pkg, "*.py")):
    add(p, f"{remote_dir}/{os.path.basename(p)}")

add(os.path.join(pkg, "requirements.txt"), f"{remote_dir}/requirements.txt")

for f in ("install_nssm_service.ps1", "launch_trader.ps1", "start_bot.bat"):
    add(f, f"{remote_dir}/{f}")

for p in glob.glob(os.path.join("scripts", "*.py")):
    add(p, f"{remote_dir}/scripts/{os.path.basename(p)}")

print("MANIFEST = " + json.dumps(man))
PYGEN
    cat <<'PYCHK'
import hashlib, os, sys

differ, missing, ok = [], [], 0
for remote_path, want in MANIFEST.items():
    if not os.path.exists(remote_path):
        missing.append(remote_path)
        continue
    with open(remote_path, "rb") as fh:
        got = hashlib.sha256(fh.read()).hexdigest()
    if got == want:
        ok += 1
    else:
        differ.append(remote_path)

for p in sorted(differ):
    print("  DIFFER   " + p)
for p in sorted(missing):
    print("  MISSING  " + p)
print(f"  {len(MANIFEST)} files in scope: {ok} match, "
      f"{len(differ)} differ, {len(missing)} missing")
sys.exit(1 if (differ or missing) else 0)
PYCHK
}

echo "=== HVF Deploy ==="

# 1. Stop the bot
echo "[1/7] Stopping bot..."
ssh "$VPS" "C:\nssm\nssm.exe stop HVF_Bot; exit 0"
BOT_STOPPED=1
sleep 2
echo "  Bot stopped."

# 2. Remove stale nested duplicate
echo "[2/7] Removing nested duplicate (hvf_trader/hvf_trader/)..."
ssh "$VPS" "if (Test-Path '${REMOTE_DIR}/hvf_trader') { Remove-Item '${REMOTE_DIR}/hvf_trader' -Recurse -Force; Write-Output '  Removed.' } else { Write-Output '  Not found, skipping.' }"

# 3. Clear __pycache__ everywhere
echo "[3/7] Clearing __pycache__..."
ssh "$VPS" "Get-ChildItem '${REMOTE_DIR}' -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue; Write-Output '  Cleared.'; exit 0"

# 4. Upload package contents to top level
echo "[4/7] Uploading hvf_trader/ contents..."
for dir in "${PKG_DIRS[@]}"; do
    scp_checked "${LOCAL_PKG}/${dir}/" -r "${LOCAL_PKG}/${dir}" "${VPS}:${REMOTE_DIR}/"
done
# Package files (all .py at package root)
scp_checked "${LOCAL_PKG}/*.py" ${LOCAL_PKG}/*.py "${VPS}:${REMOTE_DIR}/"
scp_checked "${LOCAL_PKG}/requirements.txt" "${LOCAL_PKG}/requirements.txt" "${VPS}:${REMOTE_DIR}/"
echo "  Package uploaded."

# 5. Upload top-level scripts and utility scripts
echo "[5/7] Uploading scripts..."
scp_checked "launcher scripts" "${LAUNCHERS[@]}" "${VPS}:${REMOTE_DIR}/"
ssh "$VPS" "if (-not (Test-Path '${REMOTE_DIR}/scripts')) { New-Item -ItemType Directory -Path '${REMOTE_DIR}/scripts' -Force | Out-Null }; exit 0"
scp_checked "scripts/*.py" scripts/*.py "${VPS}:${REMOTE_DIR}/scripts/"
echo "  Scripts uploaded."

if [ ${#FAILURES[@]} -gt 0 ]; then
    echo "" >&2
    echo "!!! ${#FAILURES[@]} upload(s) FAILED:" >&2
    for f in "${FAILURES[@]}"; do
        echo "!!!   - ${f}" >&2
    done
    banner_bot_down
    exit 1
fi

# 6. Verify every uploaded file byte-for-byte before letting the bot run it
echo "[6/7] Verifying remote tree (SHA256)..."
TMP_VERIFY="$(mktemp -t hvf_verify)"
build_verify_script > "$TMP_VERIFY"
verify_out=""
verify_rc=0
# A failure to RUN the check is itself a verification failure — never treat
# an unreachable or broken verifier as a pass.
if verify_out="$(ssh "$VPS" "$REMOTE_PY -" < "$TMP_VERIFY" 2>&1)"; then
    verify_rc=0
else
    verify_rc=$?
fi
printf '%s\n' "$verify_out" | tr -d '\0\r'
if [ "$verify_rc" -ne 0 ]; then
    echo "" >&2
    echo "!!! VERIFICATION FAILED (exit ${verify_rc}) — remote tree does not" >&2
    echo "!!! match this repo, or the verifier could not run." >&2
    banner_bot_down
    exit 1
fi

# 7. Restart the bot
echo "[7/7] Starting bot..."
ssh "$VPS" "C:\nssm\nssm.exe start HVF_Bot; exit 0"
BOT_STOPPED=0
sleep 5
echo "  Verifying..."
ssh "$VPS" "C:\nssm\nssm.exe status HVF_Bot; exit 0"
ssh "$VPS" "Get-Content '${REMOTE_DIR}/logs/main.log' -Tail 3 -ErrorAction SilentlyContinue; exit 0"

echo ""
echo "=== Deploy complete ==="
