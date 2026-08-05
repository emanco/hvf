"""Figures for the 8.40/8.41 results, and Hunt-style renders of detected funnels.

Two jobs. The panels visualise what the numbers in spec 8.41 say. The setup renders do
double duty: they are the eyeball check that detection and geometry agree with what Hunt
draws, and they are the prototype of the chart the alerting stack has to send.

Written to docs/research/figs/.
"""
import contextlib
import io
import sys
import warnings
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
warnings.filterwarnings("ignore")

with contextlib.redirect_stdout(io.StringIO()):
    from hvf_trader.detector.hvf_signal import slung_of
    from hvf_v2_forming import COST_BP, RATE, klass, load_frames
    from hvf_v2_widestop import net_of, picks_for, simulate

FIGS = ROOT / "docs" / "research" / "figs"
ARMS = [("confirmed", "rl3"), ("confirmed", "rl2"),
        ("forming", "rl3"), ("forming", "rl2")]
LABEL = {("confirmed", "rl3"): "confirmed\nstop RL3",
         ("confirmed", "rl2"): "confirmed\nstop RL2",
         ("forming", "rl3"): "forming\nstop RL3",
         ("forming", "rl2"): "forming\nstop RL2"}
GREEN, AMBER, RED, INK = "#10b981", "#f59e0b", "#ef4444", "#1f2933"

# From the 8.41 run, so the figures cannot silently drift from the recorded table.
NET = {("confirmed", "rl3"): -0.223, ("confirmed", "rl2"): -0.125,
       ("forming", "rl3"): -0.220, ("forming", "rl2"): -0.016}
NULL = {("confirmed", "rl3"): -0.380, ("confirmed", "rl2"): -0.177,
        ("forming", "rl3"): -0.468, ("forming", "rl2"): -0.176}
POS = {("confirmed", "rl3"): 10, ("confirmed", "rl2"): 13,
       ("forming", "rl3"): 11, ("forming", "rl2"): 29}
DECOMP = {("confirmed", "rl3"): (-0.118, -0.103, -0.007),
          ("confirmed", "rl2"): (-0.046, -0.076, -0.004),
          ("forming", "rl3"): (-0.139, -0.096, -0.009),
          ("forming", "rl2"): (+0.046, -0.074, -0.005)}


def _tidy(ax):
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.25, lw=0.6)
    ax.set_axisbelow(True)


def fig_results(frames):
    fig, axes = plt.subplots(2, 2, figsize=(13.5, 9.5))
    fig.suptitle("HVF 8.41 — widening the stop from the third funnel to the second",
                 fontsize=14, fontweight="bold", y=0.98)
    x = np.arange(4)
    keys = ARMS
    labs = [LABEL[k] for k in keys]

    # (a) net vs the shift-null -----------------------------------------------------
    ax = axes[0, 0]
    ax.bar(x - 0.19, [NULL[k] for k in keys], 0.36, color="#cbd5e1",
           label="shift-null (same geometry, random times)")
    ax.bar(x + 0.19, [NET[k] for k in keys], 0.36,
           color=[GREEN if NET[k] > -0.05 else RED for k in keys], label="net R")
    for i, k in enumerate(keys):
        ax.text(i + 0.19, NET[k] - 0.028, f"{NET[k]:+.3f}", ha="center",
                va="top", fontsize=9, fontweight="bold")
    ax.axhline(0, color=INK, lw=1)
    ax.set_xticks(x, labs, fontsize=9)
    ax.set_ylabel("mean R per trade")
    ax.set_title("(a)  Net expectancy, and the gap over random placement", fontsize=11)
    ax.legend(fontsize=8, loc="lower left")
    _tidy(ax)

    # (b) where the R goes ----------------------------------------------------------
    ax = axes[0, 1]
    gross = np.array([DECOMP[k][0] for k in keys])
    fin = np.array([DECOMP[k][1] for k in keys])
    spr = np.array([DECOMP[k][2] for k in keys])
    ax.bar(x, gross, 0.5, color=[GREEN if g > 0 else RED for g in gross], label="gross")
    ax.bar(x, fin, 0.5, bottom=np.where(gross > 0, 0, gross), color=AMBER,
           label="financing")
    ax.bar(x, spr, 0.5, bottom=np.where(gross > 0, fin, gross + fin), color="#94a3b8",
           label="spread")
    for i, k in enumerate(keys):
        ax.text(i, gross[i] + (0.012 if gross[i] > 0 else -0.012),
                f"gross {gross[i]:+.3f}", ha="center",
                va="bottom" if gross[i] > 0 else "top", fontsize=8, fontweight="bold")
    ax.axhline(0, color=INK, lw=1)
    ax.set_xticks(x, labs, fontsize=9)
    ax.set_ylabel("mean R per trade")
    ax.set_title("(b)  Decomposition — spread was never the binding cost", fontsize=11)
    ax.legend(fontsize=8, loc="lower left")
    _tidy(ax)

    # (c) instruments in profit -----------------------------------------------------
    ax = axes[1, 0]
    n = len(frames)
    ax.bar(x, [POS[k] for k in keys], 0.5,
           color=[GREEN if POS[k] > 20 else "#94a3b8" for k in keys])
    for i, k in enumerate(keys):
        ax.text(i, POS[k] + 0.5, f"{POS[k]}/{n}", ha="center", fontsize=9,
                fontweight="bold")
    ax.axhline(n / 2, color=INK, ls=":", lw=1)
    ax.text(3.45, n / 2 + 0.6, "half", fontsize=8, ha="right", color=INK)
    ax.set_xticks(x, labs, fontsize=9)
    ax.set_ylabel("instruments")
    ax.set_ylim(0, n * 0.62)
    ax.set_title("(c)  Instruments with positive net", fontsize=11)
    _tidy(ax)

    # (d) per class, forming/RL2 ----------------------------------------------------
    ax = axes[1, 1]
    agg = {}
    for name, (f, d) in frames.items():
        r = net_of(f, picks_for(f, d, "forming", "rl2"), name)
        if r:
            agg.setdefault(klass(name), []).append(r[0])
    cls = sorted(agg, key=lambda c: np.mean(agg[c]))
    vals = [float(np.mean(agg[c])) for c in cls]
    ax.barh(range(len(cls)), vals, 0.55,
            color=[GREEN if v > 0 else RED for v in vals])
    ax.set_yticks(range(len(cls)),
                  [f"{c}  ({RATE[c]:.0f}% carry, n={len(agg[c])})" for c in cls],
                  fontsize=9)
    for i, v in enumerate(vals):
        ax.text(v + (0.004 if v > 0 else -0.004), i, f"{v:+.3f}", fontsize=9,
                va="center", ha="left" if v > 0 else "right", fontweight="bold")
    ax.set_xlim(min(vals) * 1.45, max(vals) * 1.45)
    ax.axvline(0, color=INK, lw=1)
    ax.set_xlabel("mean R per trade")
    ax.set_title("(d)  forming/RL2 by class — the cheapest carry is the worst",
                 fontsize=11)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="x", alpha=0.25, lw=0.6)
    ax.set_axisbelow(True)

    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(FIGS / "8_41_results.png", dpi=140)
    plt.close(fig)


def fig_stopwidth(frames):
    """The evidence that the stop was too tight, and what widening it costs."""
    atr_r, ratio = [], []
    for name, (f, d) in frames.items():
        h = f["high"].to_numpy(float)
        lo = f["low"].to_numpy(float)
        c = f["close"].to_numpy(float)
        tr = np.maximum(h[1:] - lo[1:], np.maximum(abs(h[1:] - c[:-1]),
                                                   abs(lo[1:] - c[:-1])))
        atr = np.concatenate([[np.nan], np.convolve(tr, np.ones(14) / 14, "same")])
        pk3 = {}
        for p3 in picks_for(f, d, "forming", "rl3"):
            r3 = abs(p3["e_off"] - p3["s_off"])
            pk3[p3["arm"]] = r3
            a = atr[p3["arm"]]
            if np.isfinite(a) and a > 0 and r3 > 0:
                atr_r.append(r3 / a)
        for p2 in picks_for(f, d, "forming", "rl2"):
            r3 = pk3.get(p2["arm"])
            r2 = abs(p2["e_off"] - p2["s_off"])
            if r3 and r3 > 0:
                ratio.append(r2 / r3)

    atr_r = np.array(atr_r)
    ratio = np.array(ratio)
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 4.6))

    ax = axes[0]
    ax.hist(np.clip(atr_r, 0, 6), bins=60, color="#94a3b8", edgecolor="white", lw=0.4)
    inside = float((atr_r < 1).mean())
    ax.axvspan(0, 1, color=RED, alpha=0.12)
    ax.axvline(1, color=RED, lw=1.4)
    ax.axvline(np.median(atr_r), color=INK, ls="--", lw=1.2)
    ax.text(0.98, 0.94, f"{inside:.1%} of stops sit inside\none bar's range (1 ATR14)",
            transform=ax.transAxes, ha="right", va="top", fontsize=10,
            fontweight="bold", color=RED)
    ax.text(np.median(atr_r) + 0.08, ax.get_ylim()[1] * 0.55,
            f"median {np.median(atr_r):.2f} ATR", fontsize=9, color=INK)
    ax.set_xlabel("stop distance at the arming bar, in ATR14")
    ax.set_ylabel("setups")
    ax.set_title("Why the RL3 stop fails: it is inside the noise", fontsize=11)
    _tidy(ax)

    ax = axes[1]
    ax.hist(np.clip(ratio, 1, 12), bins=60, color="#94a3b8", edgecolor="white", lw=0.4)
    ax.axvline(np.median(ratio), color=GREEN, lw=1.6)
    ax.text(np.median(ratio) + 0.15, ax.get_ylim()[1] * 0.8,
            f"median {np.median(ratio):.2f}x\n"
            f"risk widens by this,\nso RRR falls by it too",
            fontsize=9.5, color=INK)
    ax.set_xlabel("risk at the RL2 stop / risk at the RL3 stop")
    ax.set_ylabel("setups")
    ax.set_title("What widening costs: the same targets, more risk", fontsize=11)
    _tidy(ax)

    fig.tight_layout()
    fig.savefig(FIGS / "8_41_stop_width.png", dpi=140)
    plt.close(fig)


def _draw(ax, f, w, direction, title):
    h1, rl1, rh2, rl2, rh3, rl3 = w
    lo_i = max(0, h1.index - 25)
    hi_i = min(len(f) - 1, rl3.index + 70)
    seg = f.iloc[lo_i:hi_i + 1]
    xs = np.arange(len(seg))
    o = seg["open"].to_numpy(float)
    c = seg["close"].to_numpy(float)
    hh = seg["high"].to_numpy(float)
    ll = seg["low"].to_numpy(float)
    up = c >= o
    ax.vlines(xs, ll, hh, color="#94a3b8", lw=0.7, zorder=1)
    ax.bar(xs[up], (c - o)[up], 0.62, bottom=o[up], color=GREEN, zorder=2)
    ax.bar(xs[~up], (o - c)[~up], 0.62, bottom=c[~up], color=RED, zorder=2)

    px = [p.index - lo_i for p in w]
    py = [p.price for p in w]
    ax.plot(px, py, color="#2563eb", lw=1.6, zorder=4)
    ax.scatter(px, py, s=34, color="#2563eb", zorder=5)
    for lab, xx, yy in zip(["H1", "L1", "H2", "L2", "H3", "L3"], px, py):
        ax.annotate(lab, (xx, yy), textcoords="offset points", xytext=(0, 9),
                    ha="center", fontsize=8.5, fontweight="bold", color="#2563eb")

    amp3 = abs(rh3.price - rl3.price)
    centre = (rh3.price + rl3.price) / 2.0
    entry = rh3.price
    tps = [centre + direction * amp3,
           centre + direction * abs(rh2.price - rl2.price),
           centre + direction * abs(h1.price - rl1.price)]
    right = len(seg) - 1
    x0 = px[-1]
    ax.hlines(entry, x0, right, color=INK, lw=1.5, zorder=6)
    ax.text(right, entry, " entry", fontsize=8, va="center", color=INK)
    ax.hlines(rl3.price, x0, right, color=RED, lw=1.3, ls="--", zorder=6)
    ax.text(right, rl3.price, " SL (RL3, old)", fontsize=8, va="center", color=RED)
    ax.hlines(rl2.price, x0, right, color=RED, lw=1.9, zorder=6)
    ax.text(right, rl2.price, " SL (RL2, 8.41)", fontsize=8, va="center",
            color=RED, fontweight="bold")
    for i, t in enumerate(tps, 1):
        ax.hlines(t, x0, right, color=GREEN, lw=1.2, zorder=6)
        ax.text(right, t, f" TP{i}", fontsize=8, va="center", color=GREEN)

    ax.axvspan(px[0], px[-1], color="#2563eb", alpha=0.05, zorder=0)
    ax.set_title(title, fontsize=10)
    ax.set_xlim(0, right + 26)
    lows = [min(ll.min(), min(rl2.price, min(tps)))] if direction < 0 else [ll.min()]
    top = max(hh.max(), max(tps), rl2.price)
    bot = min(ll.min(), min(tps), rl2.price)
    pad = (top - bot) * 0.06
    ax.set_ylim(bot - pad, top + pad)
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_xticks([])
    ax.tick_params(labelsize=8)


# Hunt's own 8 funnels, measured from the pivots `hvf_v2_mef.search` matches to his
# drawings. These are DESCRIPTIVE bounds used to render representative examples and to
# draw the comparison; they are not (yet) filters in the detector -- see spec 8.42.
HUNT_SHAPE = dict(span=(19, 202), t3_t1=(0.14, 0.55), amp3_amp1=(0.20, 0.52))


def shape_of(w):
    """(span in bars, wave3/wave1 in time, amp3/amp1 in price)."""
    h1, rl1, rh2, rl2, rh3, rl3 = w
    span = rl3.index - h1.index
    t1 = rl1.index - h1.index
    t3 = rl3.index - rh3.index
    a1 = abs(h1.price - rl1.price)
    a3 = abs(rh3.price - rl3.price)
    return (span,
            t3 / t1 if t1 > 0 else np.nan,
            a3 / a1 if a1 > 0 else np.nan)


def _hunt_like(w):
    span, t31, a31 = shape_of(w)
    lo, hi = HUNT_SHAPE["span"]
    if not (lo <= span <= hi):
        return False
    lo, hi = HUNT_SHAPE["t3_t1"]
    if not (np.isfinite(t31) and lo <= t31 <= hi):
        return False
    lo, hi = HUNT_SHAPE["amp3_amp1"]
    return np.isfinite(a31) and lo <= a31 <= hi


def fig_setups(frames):
    """Render funnels that actually look like Hunt's -- see fig_shape for why."""
    with contextlib.redirect_stdout(io.StringIO()):
        from hvf_trader.detector.hvf_mef import mef_candidates
        from hvf_trader.detector.hvf_signal import DEFAULT_BOX_PCT
        from hvf_trader.detector.hvf_v2 import zigzag_pct

    picked = []
    for name, (f, d) in frames.items():
        if len(picked) >= 6:
            break
        piv = zigzag_pct(f, DEFAULT_BOX_PCT)
        if len(piv) < 6:
            continue
        best = None
        for idx in mef_candidates(piv, d):
            w = [piv[j] for j in idx]
            if w[5].index > len(f) - 90 or w[0].index < 30:
                continue
            s = slung_of(w, d)
            if not (np.isfinite(s) and _hunt_like(w)):
                continue
            # Prefer the most recent qualifying funnel on each instrument.
            if best is None or w[5].index > best[0]:
                best = (w[5].index, w, s)
        if best:
            picked.append((name, f, d, best[1], best[2]))

    if not picked:
        return
    rows = (len(picked) + 1) // 2
    fig, axes = plt.subplots(rows, 2, figsize=(15, 4.1 * rows))
    axes = np.atleast_1d(axes).ravel()
    fig.suptitle("Funnels matching Hunt's shape, priced by the live package "
                 "(hvf_mef + hvf_signal)", fontsize=13, fontweight="bold")
    for ax, (name, f, d, w, s) in zip(axes, picked):
        side = "LONG" if d > 0 else "SHORT"
        span, t31, a31 = shape_of(w)
        _draw(ax, f, w, d,
              f"{name}  {side}   slung {s:.2f}   span {span} bars   "
              f"t3/t1 {t31:.2f}   amp3/amp1 {a31:.2f}   {w[5].ts.date()}")
    for ax in axes[len(picked):]:
        ax.set_visible(False)
    fig.tight_layout(rect=[0, 0, 1, 0.965])
    fig.savefig(FIGS / "8_42_setups.png", dpi=140)
    plt.close(fig)


def fig_shape(frames):
    """8.42: what we have been detecting is not the shape Hunt draws."""
    with contextlib.redirect_stdout(io.StringIO()):
        from hvf_trader.detector.hvf_mef import mef_candidates
        from hvf_trader.detector.hvf_signal import DEFAULT_BOX_PCT
        from hvf_trader.detector.hvf_v2 import zigzag_pct
        from hvf_v2_charts import CHARTS
        from hvf_v2_mef import search, verdict

    hunt = []
    for c in CHARTS:
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                live, null, seen, _ = search(c)
                v = verdict(live, null)
        except Exception:                                        # noqa: BLE001
            continue
        if v:
            hunt.append(shape_of(v[0][3]))
    ours = []
    for name, (f, d) in frames.items():
        piv = zigzag_pct(f, DEFAULT_BOX_PCT)
        if len(piv) < 6:
            continue
        for idx in mef_candidates(piv, d):
            ours.append(shape_of([piv[j] for j in idx]))
    hunt = np.array(hunt, float)
    ours = np.array(ours, float)

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.6))
    fig.suptitle("8.42 — the detector is not finding the pattern Hunt trades",
                 fontsize=13, fontweight="bold")
    spec = [(0, "funnel span, H1 to L3 (bars)", np.linspace(0, 1200, 70), False),
            (1, "wave 3 / wave 1, in TIME", np.linspace(0, 1.0, 70), False),
            (2, "amp3 / amp1, in PRICE", np.linspace(0, 1.0, 70), False)]
    for col, xlabel, bins, _u in spec:
        ax = axes[col]
        v = ours[:, col]
        v = v[np.isfinite(v)]
        ax.hist(np.clip(v, bins[0], bins[-1]), bins=bins, color="#cbd5e1",
                edgecolor="white", lw=0.3, label=f"ours (n={len(v):,})")
        ax.axvline(np.median(v), color=RED, lw=2,
                   label=f"our median {np.median(v):.2f}")
        h = hunt[:, col]
        h = h[np.isfinite(h)]
        for x in h:
            ax.axvline(x, color="#2563eb", lw=1.1, alpha=0.75)
        ax.axvline(np.median(h), color="#2563eb", lw=2.6, ls="--",
                   label=f"Hunt's median {np.median(h):.2f}  (n={len(h)})")
        ax.set_xlabel(xlabel)
        ax.set_ylabel("candidate funnels")
        ax.legend(fontsize=8.5)
        _tidy(ax)
    axes[1].text(0.5, 0.62,
                 "Hunt's third wave takes ~35% of\nthe first wave's TIME.\n"
                 "Ours takes 1% — a median of\nONE bar. That is not a wave.",
                 transform=axes[1].transAxes, fontsize=10, color=RED,
                 fontweight="bold", va="top")
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    fig.savefig(FIGS / "8_42_shape.png", dpi=140)
    plt.close(fig)


def fig_equity(frames):
    """Pooled cumulative R, chronological, all four arms."""
    fig, ax = plt.subplots(figsize=(11.5, 5.4))
    for (arm, st), col in zip(ARMS, ["#cbd5e1", "#94a3b8", AMBER, GREEN]):
        rows = []
        for name, (f, d) in frames.items():
            pk = picks_for(f, d, arm, st)
            if len(pk) < 15:
                continue
            c = klass(name)
            ts = f.index
            det = simulate(f, pk)
            if len(det) < 15:
                continue
            for b, carry, lev, a in det:
                net = (b - carry * RATE[c] / 100 / 365 - lev * COST_BP[c] * 1e-4)
                rows.append((ts[min(a, len(ts) - 1)], net))
        if not rows:
            continue
        rows.sort(key=lambda r: r[0])
        cum = np.cumsum([r[1] for r in rows])
        ax.plot(np.arange(1, len(cum) + 1), cum, lw=1.6, color=col,
                label=f"{arm}/{st.upper()}   {cum[-1]:+.0f}R over {len(rows):,} trades")
    ax.axhline(0, color=INK, lw=1)
    ax.set_xlabel("trade number (all instruments pooled, chronological)")
    ax.set_ylabel("cumulative R (1 unit risked per trade, pooled)")
    ax.set_title("Pooled equity — the wide stop is the only arm that stops bleeding",
                 fontsize=12, fontweight="bold")
    ax.legend(fontsize=9, loc="lower left")
    _tidy(ax)
    fig.tight_layout()
    fig.savefig(FIGS / "8_41_equity.png", dpi=140)
    plt.close(fig)


def main():
    FIGS.mkdir(parents=True, exist_ok=True)
    frames = load_frames(0)
    print(f"{len(frames)} instruments")
    for fn in (fig_results, fig_stopwidth, fig_shape, fig_setups, fig_equity):
        fn(frames)
        print("  wrote", fn.__name__)
    for p in sorted(FIGS.glob("*.png")):
        print(f"  {p.relative_to(ROOT)}  {p.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
