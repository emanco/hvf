"""
Migration: Add mt5_ticket_partial column to trade_records.
Safe to run multiple times — checks if column already exists.
"""
import sqlite3
import sys

sys.stdout.reconfigure(encoding='utf-8') if hasattr(sys.stdout, 'reconfigure') else None

db_path = r"C:\hvf_trader\hvf_trader.db"
conn = sqlite3.connect(db_path)
cur = conn.cursor()

# Check if column already exists
cur.execute("PRAGMA table_info(trade_records)")
columns = [row[1] for row in cur.fetchall()]

if "mt5_ticket_partial" in columns:
    print("Column mt5_ticket_partial already exists. No migration needed.", flush=True)
else:
    cur.execute("ALTER TABLE trade_records ADD COLUMN mt5_ticket_partial INTEGER")
    conn.commit()
    print("Added mt5_ticket_partial column to trade_records.", flush=True)

conn.close()
print("Done.", flush=True)
