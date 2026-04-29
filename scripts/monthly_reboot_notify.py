"""Pre-reboot Telegram notification + delayed shutdown.

Triggered by the HVF_MonthlyReboot Windows scheduled task. Sends a heads-up
to Telegram so the user knows the reboot is starting and can intervene if
the bot doesn't come back. Then schedules `shutdown /r /t 300` so they
have a 5-minute window to abort via `shutdown /a` if needed.
"""
import os
import subprocess
import urllib.parse
import urllib.request

from dotenv import load_dotenv

load_dotenv(r"C:/hvf_trader/.env")

token = os.getenv("TELEGRAM_BOT_TOKEN")
chat = os.getenv("TELEGRAM_CHAT_ID")

message = (
    "\U0001F501 <b>VPS monthly reboot starting</b>\n"
    "Reboot in <b>5 minutes</b>.\n"
    "Bot will auto-restart via NSSM; MT5 self-spawns with credentials.\n"
    "Watch for the &quot;Bot online&quot; confirmation.\n"
    "If nothing arrives within ~10 min after reboot, RDP in to investigate.\n"
    "To abort the reboot: <code>ssh hvf-vps shutdown /a</code>"
)

if token and chat:
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode(
            {"chat_id": chat, "text": message, "parse_mode": "HTML"}
        ).encode()
        urllib.request.urlopen(url, data=data, timeout=10).read()
        print("Telegram pre-reboot notice sent.")
    except Exception as e:
        print(f"Telegram send failed: {e}")
else:
    print("WARN: missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID env vars.")

subprocess.run([
    "shutdown.exe", "/r", "/t", "300",
    "/c", "HVF monthly auto-reboot (Telegram-notified)"
])
