---
name: KZ_HUNT exit policy — flat TP optimum 2026-05-05
description: Flat-TP sweep on 117 live trades shows +12p TP wins on PF (1.03) but high-WR-dependent. +20p chosen as more durable (PF 0.99). All blended/trail policies underperform flat TP on this sample.
type: project
originSessionId: b47e514d-24ea-44bd-82fc-3d220690e0f2
---
**Sweep result (117 closed KZ_HUNT trades, 2026-03-25 → 2026-05-05, simulated on M30 IC Markets bars):**

| TP_pips | Net    | WR  | PF   | TP hits |
|---------|--------|-----|------|---------|
| +8      | −98p   | 65% | 0.86 | 76      |
| +10     | −47p   | 62% | 0.94 | 72      |
| **+12** | **+24p** | **59%** | **1.03** | **69**  |
| +15     | −49p   | 52% | 0.95 | 61      |
| +18     | −39p   | 49% | 0.96 | 57      |
| +20     | −13p   | 47% | 0.99 | 55      |
| +22     | −16p   | 44% | 0.99 | 52      |
| +25     | −39p   | 41% | 0.97 | 48      |
| +30     | −173p  | 35% | 0.88 | 41      |
| +50     | −341p  | 23% | 0.80 | 26      |

vs ACTUAL live-bot exit logic: **−197p**, PF 0.79 over the same 117 trades. So flat TP at any reasonable level beats current behaviour.

**Why +12p is the local maximum:** the strategy's edge is high WR on small moves. KZ_HUNT setups frequently push 8–15p into profit then revert; a tight TP captures these reliably. Beyond ~+22p, hit-rate drops faster than per-trade gains rise, killing PF.

**Why +20p was chosen for live (not +12p):**
- R:R 1.18 (vs 0.7 for +12p) — less WR-dependent. Survives a regime shift where WR drops to 50%.
- +12p R:R of 0.7 needs 58.6% WR to break even. Live margin would be ~0.4% — too close to the line.
- 0.5p exit-side slippage shaves ~35p off the +12p sweep result (69 hits × 0.5p), bringing it to roughly the same realistic net as +20p. So the durability argument wins.
- If +20p underperforms after 50+ live trades, +12p is the next test.

**Blended exits all underperformed flat TP** (60% TP@20p + 40% chandelier trail variants from −116 to −184p). Reason: trail leg leaks pips on the 32 of 117 trades (27%) with MFE under 10p — they whip a few pips into profit then reverse to SL, producing trail-tightened losses worse than letting them ride to the original SL.

**Where the giveback was concentrated** (per-bucket capture %):
- 0–5p MFE: 21 trades, capture −525% (i.e. SL'd at full stop despite no real run)
- 5–10p MFE: 11 trades, capture −190%
- 10–20p MFE: 19 trades, capture −20%
- 20–30p MFE: 13 trades, capture +10%
- 30–50p MFE: 15 trades, capture +25%
- **50p+ MFE: 23 trades, capture only +9%** — biggest leak: trades reached +88p avg but kept only +8p

**Live wiring (chosen 2026-05-05):** flat TP @ +20p from entry, original spread-comp SL, **no partial, no trailing**.

**Files: backtests/run_kz_exit_giveback.py and backtests/run_kz_mfe_capture.py reproduce the analysis. backtests/data/kz_giveback_per_trade.csv and kz_mfe_per_trade.csv hold the raw per-trade data.**
