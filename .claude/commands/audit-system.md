# System Audit

Run a comprehensive audit of the live HVF trading system. Collects data from the VPS in one shot and analyzes against benchmarks.

## Steps

1. **Collect data** — Run the audit script on the VPS:
```
ssh hvf-vps "C:\hvf_trader\venv\Scripts\python.exe C:\hvf_trader\scripts\audit_report.py; exit 0"
```
Parse the JSON output. If the script fails, fall back to manual SSH queries.

2. **Bot Health** — Report:
   - Is the bot running? (bot_status should be SERVICE_RUNNING)
   - When was the last scan? (should be within last 2 minutes)
   - Any recent errors? List them.

3. **Account Status** — Report balance, equity, margin usage.

4. **Trade Performance** (since go-live) — Report:
   - Total closed trades, wins, losses, win rate
   - Profit factor, total PnL ($), total pips
   - Per-pair breakdown (which pairs are profitable?)
   - Close reason distribution (SL, trailing stop, invalidation, reconciliation, etc.)
   - Any 0.0 or NULL PnL trades? (these are data quality issues)
   - Current consecutive loss streak

5. **Compare to Benchmarks**:
   - Live PF vs backtest PF (1.53). Expected range: 1.15-1.30
   - Live WR vs backtest WR (61%). Flag if below 50%
   - Consecutive losses vs alert threshold (5)
   - Are we at 50 trades yet? If yes, flag M8 (RRR threshold review) as ready

6. **Pattern Pipeline Health**:
   - How many patterns detected, armed, triggered, rejected, expired?
   - Trigger rate (triggered / (armed + triggered + expired)). Below 20% = problem
   - Top rejection reasons — what's blocking entries?
   - Which pairs get rejected most?

7. **Anomaly Detection** — Flag any of:
   - Reconciliation closes (should be near zero after fixes)
   - 0.0 or NULL PnL trades (data integrity issue)
   - Same pair rejected 5+ times in a row (parameter mismatch)
   - No trades opened in 48+ hours (system may be stuck)
   - Slippage consistently > 1 pip (execution quality issue)

8. **Recommendations** — Based on findings, suggest:
   - Urgent fixes (if any anomalies found)
   - Parameter adjustments (only if 50+ trades milestone reached)
   - Pairs to watch or exclude
   - Next review timing

Format the output as a structured report with clear sections. Use the benchmarks from the expert panel (see CLAUDE.md) to contextualize results. Be honest — if the data is insufficient to draw conclusions, say so.
