"""NIGHT_TIDE live trades — cumulative PnL broken out by pair.

Pulled from hvf_trader.db (trade_records WHERE pattern_type='NIGHT_TIDE'),
2026-04-28 through 2026-06-23. Three AUDNZD trades fired 2026-04-28/04-30
between 11:07-11:52 UTC, well outside the 22:00-01:00 window — marked with
an X (likely early deployment/timezone bug, not the strategy actually
firing) rather than dropped, so the distortion they'd cause is visible.
"""
from datetime import datetime
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

TRADES = [
    ("AUDNZD", "2026-04-28 11:42", -87.50, True),
    ("AUDNZD", "2026-04-28 11:46", -91.00, True),
    ("AUDCAD", "2026-04-28 22:00", -51.06, False),
    ("AUDNZD", "2026-04-30 11:07", -40.12, True),
    ("NZDCAD", "2026-05-15 00:45", -29.90, False),
    ("NZDCAD", "2026-05-20 00:45", -16.50, False),
    ("AUDCAD", "2026-05-24 22:01", 21.45, False),
    ("AUDCAD", "2026-05-27 00:45", -3.60, False),
    ("AUDCAD", "2026-06-14 22:00", 126.96, False),
    ("NZDCAD", "2026-06-14 22:15", 147.20, False),
    ("AUDNZD", "2026-06-15 22:01", -13.68, False),
    ("AUDCAD", "2026-06-18 00:15", 37.44, False),
    ("AUDCAD", "2026-06-23 00:00", 70.18, False),
    ("AUDCAD", "2026-06-23 00:26", 40.85, False),
    ("NZDCAD", "2026-06-23 00:30", -17.10, False),
]

# Fixed categorical order (dataviz skill: assign hues in fixed order, never cycled)
COLORS = {"AUDCAD": "#2a78d6", "AUDNZD": "#1baf7a", "NZDCAD": "#eda100"}
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"
SURFACE = "#fcfcfb"

plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["font.sans-serif"] = ["Segoe UI", "Helvetica Neue", "Arial", "DejaVu Sans"]

by_pair = {p: [] for p in COLORS}
for symbol, ts, pnl, anomaly in TRADES:
    by_pair[symbol].append((datetime.strptime(ts, "%Y-%m-%d %H:%M"), pnl, anomaly))

fig, ax = plt.subplots(figsize=(11, 6.5))
fig.patch.set_facecolor(SURFACE)
ax.set_facecolor(SURFACE)

all_dates = [datetime.strptime(ts, "%Y-%m-%d %H:%M") for _, ts, _, _ in TRADES]
x_start, x_end = min(all_dates), max(all_dates)

for symbol, pts in by_pair.items():
    pts = sorted(pts, key=lambda r: r[0])
    dates = [x_start] + [p[0] for p in pts]
    cum = [0.0]
    for _, pnl, _ in pts:
        cum.append(cum[-1] + pnl)
    color = COLORS[symbol]

    ax.step(dates, cum, where="post", color=color, lw=2, zorder=2)
    # Normal fills: filled circle. Anomalous (out-of-window) fills: X marker.
    normal_x = [d for d, (_, _, anom) in zip(dates[1:], pts) if not anom]
    normal_y = [c for c, (_, _, anom) in zip(cum[1:], pts) if not anom]
    anom_x = [d for d, (_, _, anom) in zip(dates[1:], pts) if anom]
    anom_y = [c for c, (_, _, anom) in zip(cum[1:], pts) if anom]
    ax.plot(normal_x, normal_y, "o", color=color, ms=7, zorder=3,
             markeredgecolor=SURFACE, markeredgewidth=1)
    if anom_x:
        ax.plot(anom_x, anom_y, "x", color=color, ms=10, mew=2.5, zorder=3)

    # Direct end label (<=4 series, so direct labels are used per the skill's rule)
    ax.annotate(f"{symbol}  {cum[-1]:+.0f}", xy=(dates[-1], cum[-1]),
                xytext=(8, 0), textcoords="offset points",
                color=color, fontsize=10.5, fontweight="bold",
                va="center", ha="left")

ax.axhline(0, color=BASELINE, lw=1)
fig.suptitle("NIGHT_TIDE — live cumulative PnL by pair", color=INK_PRIMARY,
             fontsize=15, fontweight="bold", x=0.02, y=0.98, ha="left")
fig.text(0.02, 0.935, "IC Markets demo · 2026-04-28 to 2026-06-23 · 15 trades",
         color=INK_SECONDARY, fontsize=10.5)

ax.set_ylabel("Cumulative PnL ($)", color=INK_SECONDARY, fontsize=10.5)
ax.grid(axis="y", color=GRID, lw=0.8, zorder=0)
ax.spines[["top", "right", "left"]].set_visible(False)
ax.spines["bottom"].set_color(BASELINE)
ax.tick_params(colors=INK_MUTED, labelsize=9.5)
ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
fig.autofmt_xdate(rotation=0, ha="center")
ax.margins(x=0.08)

# Legend below the plot (avoids colliding with the flat early-period lines)
handles = [plt.Line2D([0], [0], color=c, lw=2, marker="o", ms=7, label=p)
           for p, c in COLORS.items()]
handles.append(plt.Line2D([0], [0], color=INK_MUTED, marker="x", mew=2.5, ms=8,
                           lw=0, label="Outside 22:00–01:00 UTC window (likely bug)"))
ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.14),
          ncol=2, frameon=False, fontsize=9.5, labelcolor=INK_SECONDARY)

plt.subplots_adjust(top=0.88, bottom=0.22)
out = "backtests/charts/night_tide_by_pair.png"
plt.savefig(out, dpi=150, facecolor=SURFACE, bbox_inches="tight")
print(f"Saved: {out}")
