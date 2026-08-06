"""Render an HVF setup the way Hunt draws it, for the Telegram alert.

The point is reviewability: the user validated this strategy from annotated charts, and the
self-validation loop asks them to judge a trade after the fact. A row of numbers cannot be
judged that way -- the funnel either looks like Hunt's or it does not. So the alert carries
the same marks as the source charts: the six pivots as three contracting waves, the entry
and the stop, and TP1/TP2/TP3 projected from the small funnel's centre.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

BULL, BEAR = "#10b981", "#ef4444"
INK, GRID, WICK = "#111827", "#e5e7eb", "#6b7280"


def render_setup(frame, setup, symbol: str, out_path: str | Path,
                 context_bars: int = 60, after_bars: int = 25) -> str | None:
    """Draw `setup` on the tail of `frame`. Returns the path, or None if plotting failed.

    Never raises: a chart is a convenience on top of the alert, and an alert that fails to
    send because matplotlib tripped is worse than one without a picture.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.dates as mdates
        import matplotlib.pyplot as plt
    except Exception as e:                                         # noqa: BLE001
        logger.warning("[HVF_V2] matplotlib unavailable, alert will go without a chart: %s", e)
        return None

    try:
        from hvf_trader.detector.hvf_rules import bar_times

        # Bound BOTH edges. Running the view to the end of the frame is what makes a
        # historical setup unreadable -- a 2022 funnel drawn against 2026 prices is a
        # flat line next to a mountain, and the funnel is the thing being judged.
        first = setup.pivots[0].index if setup.pivots else setup.arm
        start = max(0, min(first - 10, setup.arm - context_bars))
        end = min(len(frame), setup.arm + after_bars + 1)
        view = frame.iloc[start:end]
        if len(view) < 5:
            return None

        fig, ax = plt.subplots(figsize=(11, 6.2), dpi=130)
        # Frames carry a `dt` column over a RangeIndex on the research path, so the
        # x values come from there rather than from the index.
        idx = list(bar_times(view))
        width = (idx[1] - idx[0]) * 0.62 if len(idx) > 1 else None

        for ts, (_, row) in zip(idx, view.iterrows()):
            up = row["close"] >= row["open"]
            colour = BULL if up else BEAR
            ax.vlines(ts, row["low"], row["high"], color=WICK, linewidth=0.7, zorder=2)
            lo, hi = sorted((row["open"], row["close"]))
            ax.bar(ts, max(hi - lo, 1e-9), bottom=lo, width=width,
                   color=colour, edgecolor=colour, linewidth=0.4, zorder=3)

        # The three waves, as Hunt draws them: H1>RL1, RH2>RL2, RH3>RL3.
        if len(setup.pivots) == 6:
            pts = [(idx[p.index - start], p.price) for p in setup.pivots
                   if start <= p.index and p.index - start < len(idx)]
            if len(pts) == 6:
                for a, b in ((0, 1), (2, 3), (4, 5)):
                    ax.plot([pts[a][0], pts[b][0]], [pts[a][1], pts[b][1]],
                            color=INK, linewidth=1.5, alpha=0.75, zorder=4)
                # The six pivots are named long-centrically in the rules (h1, rl1, ...),
                # so on a SHORT they are mirrored: what the code calls h1 is a low. Label
                # by what the pivot actually is on the chart, or the picture contradicts
                # itself for every short.
                names = (("H1", "L1", "H2", "L2", "H3", "L3") if setup.direction > 0
                         else ("L1", "H1", "L2", "H2", "L3", "H3"))
                # The third wave is tiny by definition, so its two labels land on top of
                # the second wave's. Push each successive wave's labels further out.
                for w, ((x, y), label) in enumerate(zip(pts, names)):
                    up = label.startswith("H")
                    spread = 7 + 7 * (w // 2)
                    ax.plot(x, y, "o", color=INK, markersize=4.5, zorder=5)
                    ax.annotate(label, (x, y), textcoords="offset points",
                                xytext=(0, spread if up else -(spread + 6)),
                                ha="center", fontsize=8, color=INK, weight="bold")

        right = idx[-1]
        levels = [
            (setup.stop, "SL", BEAR, "-"),
            (setup.entry, "Entry", "#2563eb", "-"),
            (setup.tps[0], "TP1", BULL, "--"),
            (setup.tps[1], "TP2", BULL, "--"),
            (setup.tps[2], "TP3", BULL, "--"),
        ]
        # Nudge labels apart when levels crowd. TP1 sits close to entry by
        # construction (it is the smallest wave), so they overlap often.
        span = max(p for p, *_ in levels) - min(p for p, *_ in levels)
        min_gap, last_y = span * 0.045, None
        for price, label, colour, style in sorted(levels, key=lambda x: x[0]):
            ax.axhline(price, color=colour, linestyle=style, linewidth=1.1,
                       alpha=0.85, zorder=1)
            y = price if last_y is None else max(price, last_y + min_gap)
            last_y = y
            r = setup.r_multiple(price)
            tag = label if label in ("Entry", "SL") else f"{label} {r:+.2f}R"
            ax.annotate(f"{tag}  {price:,.6g}", (right, y),
                        textcoords="offset points", xytext=(8, -3), fontsize=8,
                        color=colour, weight="bold", annotation_clip=False)

        side = "LONG" if setup.direction > 0 else "SHORT"
        ax.set_title(
            f"{symbol}  HVF {side}   entry {setup.entry:,.5g}  stop {setup.stop:,.5g}  "
            f"RRR {setup.rrr:.1f}:1\n"
            f"shape  t3/t1 {setup.t3_t1:.2f}   amp3/amp1 {setup.amp3_amp1:.2f}",
            fontsize=10, color=INK,
        )
        ax.grid(True, color=GRID, linewidth=0.6, zorder=0)
        ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=4, maxticks=9))
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(ax.xaxis.get_major_locator()))
        ax.axvline(idx[min(setup.arm - start, len(idx) - 1)], color=WICK,
                   linestyle=":", linewidth=1.0, zorder=1)
        for spine in ax.spines.values():
            spine.set_color(GRID)
        ax.tick_params(labelsize=8, colors=WICK)
        fig.subplots_adjust(right=0.86)
        fig.autofmt_xdate(rotation=0, ha="center")

        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out_path, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        return str(out_path)
    except Exception as e:                                         # noqa: BLE001
        logger.warning("[HVF_V2] chart render failed, sending alert without it: %s",
                       e, exc_info=True)
        return None
