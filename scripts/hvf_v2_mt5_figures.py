"""Figures for 8.45 -- the XAUUSD run on IC Markets MT5 data. Writes docs/research/figs/.

Six panels, in the order the argument runs:

  A  equity, XAUUSD across frames        does the frame choice decide the sign?
  B  equity, H24 gross vs net            how much of the gross does carry take?
  C  cost decomposition by frame         where the money goes, per trade
  D  leverage x hold by frame            why finer frames are NOT cheaper to carry
  E  net by instrument at H24            does gold generalise? (it half does)
  F  a rendered setup                    what the detector is actually trading

Panel F exists because 8.42 was found by drawing detections, not by arithmetic. Any run
that reports statistics without rendering what it traded has not been checked.
"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from hvf_v2_mt5_xauusd import (FRAMES, SPEC, carry_frac, run_frame,  # noqa: E402
                               spread_px)

FIGS = ROOT / "docs" / "research" / "figs"
FIGS.mkdir(parents=True, exist_ok=True)
SYM = "XAUUSD"
GREEN, RED, AMBER, BLUE = "#10b981", "#ef4444", "#f59e0b", "#3b82f6"


def _stamp(fig, txt):
    fig.text(0.5, 0.005, txt, ha="center", fontsize=7.5, color="#666")


def panel_a(ax, runs):
    for (hours, _), col in zip(FRAMES, plt.cm.viridis(np.linspace(0, .9, len(FRAMES)))):
        r = runs.get(hours)
        if r is None:
            continue
        eq = r["t"].net.cumsum().to_numpy()
        ax.plot(range(1, len(eq) + 1), eq, color=col, lw=1.8,
                label=f"H{hours}  {len(eq)} trades  {eq[-1]:+.1f}R")
    ax.axhline(0, color="#999", lw=.8, ls="--")
    ax.set_title("A  XAUUSD equity by frame (net R, after real spread + swap)",
                 fontsize=10, loc="left")
    ax.set_xlabel("trade number")
    ax.set_ylabel("cumulative R")
    ax.legend(fontsize=7.5, loc="upper left")


def panel_b(ax, runs):
    r = runs[24]
    t = r["t"]
    n = range(1, len(t) + 1)
    ax.plot(n, t.gross.cumsum(), color=GREEN, lw=1.8,
            label=f"gross  {t.gross.sum():+.1f}R")
    ax.plot(n, t.net.cumsum(), color=BLUE, lw=1.8, label=f"net  {t.net.sum():+.1f}R")
    ax.fill_between(n, t.net.cumsum(), t.gross.cumsum(), color=RED, alpha=.18,
                    label=f"carry + spread  {t.fin.sum() - t.spread.sum():+.1f}R")
    ax.axhline(0, color="#999", lw=.8, ls="--")
    ax.set_title("B  XAUUSD H24: what carry takes out of the gross",
                 fontsize=10, loc="left")
    ax.set_xlabel("trade number")
    ax.set_ylabel("cumulative R")
    ax.legend(fontsize=8, loc="upper left")


def panel_c(ax, runs):
    hs = [h for h, _ in FRAMES if h in runs]
    x = np.arange(len(hs))
    g = [runs[h]["t"].gross.mean() for h in hs]
    f = [runs[h]["t"].fin.mean() for h in hs]
    s = [-runs[h]["t"].spread.mean() for h in hs]
    nt = [runs[h]["t"].net.mean() for h in hs]
    ax.bar(x - .22, g, .2, color=GREEN, label="gross")
    ax.bar(x, f, .2, color=RED, label="financing")
    ax.bar(x + .22, s, .2, color=AMBER, label="spread")
    ax.plot(x, nt, "o-", color="black", lw=1.6, ms=5, label="NET")
    ax.axhline(0, color="#333", lw=.9)
    ax.set_xticks(x, [f"H{h}" for h in hs])
    ax.set_title("C  Mean R per trade, decomposed", fontsize=10, loc="left")
    ax.set_ylabel("R per trade")
    ax.legend(fontsize=8)


def panel_d(ax, runs):
    hs = [h for h, _ in FRAMES if h in runs]
    lev = [runs[h]["t"].lev.mean() for h in hs]
    days = [runs[h]["t"].days.median() for h in hs]
    ax.plot(hs, lev, "o-", color=BLUE, lw=1.8, ms=6, label="leverage (notional/risk)")
    ax.set_xlabel("frame (hours per bar)")
    ax.set_ylabel("leverage x", color=BLUE)
    ax.tick_params(axis="y", labelcolor=BLUE)
    ax2 = ax.twinx()
    ax2.plot(hs, days, "s--", color=RED, lw=1.8, ms=5, label="median hold (days)")
    ax2.set_ylabel("days held", color=RED)
    ax2.tick_params(axis="y", labelcolor=RED)
    ax.set_title("D  Why a finer frame is not cheaper: it raises leverage\n"
                 "     without shortening the hold", fontsize=10, loc="left")
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, fontsize=8, loc="upper right")


def panel_e(ax, cross):
    syms = list(cross)
    net = [cross[s]["t"].net.mean() for s in syms]
    thin = [len(cross[s]["t"]) < 25 for s in syms]
    # alpha has to ride on the colour: barh takes one scalar alpha, not one per bar.
    cols = [matplotlib.colors.to_rgba(GREEN if v > 0 else RED, .35 if t else .9)
            for v, t in zip(net, thin)]
    bars = ax.barh(range(len(syms)), net, color=cols)
    ax.set_yticks(range(len(syms)),
                  [f"{s}  ({365 * carry_frac(s, 1) * 100:+.0f}%/yr L)" for s in syms],
                  fontsize=8)
    ax.axvline(0, color="#333", lw=.9)
    for i, (b, s) in enumerate(zip(bars, syms)):
        ax.text(b.get_width() + (.01 if b.get_width() > 0 else -.01),
                i, f"{len(cross[s]['t'])} tr", va="center", fontsize=7,
                ha="left" if b.get_width() > 0 else "right", color="#555")
    ax.set_title("E  Net R per trade at H24, every instrument pulled\n"
                 "     (faded = under 25 trades, not interpreted)",
                 fontsize=10, loc="left")
    ax.set_xlabel("net R per trade")


def panel_f(ax, runs):
    """Draw the median-sized gated setup on the H24 frame: pivots, entry, stop, targets."""
    r = runs[24]
    f, picks = r["frame"], r["picks"]
    spans = [p["w"][5].index - p["w"][0].index for p in picks]
    p = picks[int(np.argsort(spans)[len(spans) // 2])]
    w, d, arm = p["w"], p["d"], p["arm"]

    lo_i, hi_i = max(0, w[0].index - 12), min(len(f) - 1, arm + 60)
    seg = f.iloc[lo_i:hi_i + 1]
    x = np.arange(lo_i, hi_i + 1)
    up = seg.close >= seg.open
    ax.vlines(x, seg.low, seg.high, color="#999", lw=.7)
    ax.vlines(x[up], seg.open[up], seg.close[up], color=GREEN, lw=2.4)
    ax.vlines(x[~up], seg.open[~up], seg.close[~up], color=RED, lw=2.4)

    for pv, nm in zip(w, ["H1", "L1", "H2", "L2", "H3", "L3"]):
        ax.plot(pv.index, pv.price, "o", color="black", ms=5, zorder=5)
        ax.annotate(nm, (pv.index, pv.price), textcoords="offset points",
                    xytext=(0, 9 if pv.kind == "H" else -15), ha="center",
                    fontsize=8, fontweight="bold")
    ax.plot([pv.index for pv in w], [pv.price for pv in w], color="black",
            lw=.9, alpha=.5, zorder=4)

    c = f["close"].to_numpy(float)[arm]
    e, st = c + p["e_off"], c + p["s_off"]
    ax.axhline(e, color=BLUE, lw=1.4, label=f"entry {e:.2f}")
    ax.axhline(st, color=RED, lw=1.4, ls="--", label=f"stop (RL2) {st:.2f}")
    for i, tp in enumerate(p["tps"], 1):
        ax.axhline(c + tp, color=GREEN, lw=1.1, ls=":" if i < 3 else "-",
                   label=f"TP{i} {c + tp:.2f}  ({abs(tp - p['e_off']) / abs(p['e_off'] - p['s_off']):.1f}R)")
    ax.axvline(arm, color=AMBER, lw=1.2, alpha=.8)
    ax.annotate("armed here\n(RH3 confirmed)", (arm, seg.low.min()),
                textcoords="offset points", xytext=(6, 6), fontsize=7.5, color="#a16207")

    ax.set_title(f"F  A gated {'long' if d > 0 else 'short'} the detector actually took "
                 f"-- {SYM} H24, {f.dt.iloc[arm]:%b %Y}", fontsize=10, loc="left")
    ax.set_xlabel("bar index")
    ax.set_ylabel("price")
    ax.legend(fontsize=7, loc="upper left", ncol=2)


def main():
    print("running frames...")
    runs = {}
    for hours, h1 in FRAMES:
        r = run_frame(SYM, hours, h1, with_null=False)
        if r:
            runs[hours] = r
        print(f"  H{hours}: {len(r['t']) if r else 0} trades")

    print("running cross-section at H24...")
    cross = {}
    for s in SPEC:
        r = run_frame(s, 24, False, with_null=False)
        if r:
            cross[s] = r
        print(f"  {s}: {len(r['t']) if r else 0} trades")

    fig, axes = plt.subplots(3, 2, figsize=(15, 16))
    panel_a(axes[0][0], runs)
    panel_b(axes[0][1], runs)
    panel_c(axes[1][0], runs)
    panel_d(axes[1][1], runs)
    panel_e(axes[2][0], cross)
    panel_f(axes[2][1], runs)

    s = SPEC[SYM]
    fig.suptitle(
        f"HVF 8.45 — {SYM} on IC Markets MT5 data (ICMarketsSC-Demo 52774919)\n"
        f"8.44 config: forming arm · RL2 stop · 8.42 shape gate · Hunt exit "
        f"(half TP2, breakeven, run TP3) · causal 500-bar trend\n"
        f"real terms: swap {365 * carry_frac(SYM, 1) * 100:+.2f}%/yr long, "
        f"{365 * carry_frac(SYM, -1) * 100:+.2f}%/yr short · spread {s['spread']} pts "
        f"(${spread_px(SYM):.2f})",
        fontsize=12, y=.995)
    _stamp(fig, "EXPLORATORY. Gold is one of the eight charts the shape gate was "
                "calibrated on, and this is a 6-frame sweep on used data. "
                "No t-statistic here reaches 2. Not a reversal of the 8.44 NO GO.")
    fig.tight_layout(rect=[0, .012, 1, .965])
    out = FIGS / "8_45_mt5_xauusd.png"
    fig.savefig(out, dpi=130)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
