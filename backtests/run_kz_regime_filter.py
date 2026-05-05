"""Regime/context filter analysis for live KZ_HUNT trades under +12p flat TP.

Goal: find single & combined filters that preserve winners and cut losers.
Reads:
  - backtests/data/kz_trades_enriched.csv (118 closed live trades)
  - backtests/data/{SYMBOL}_M30.csv (broker-time M30 bars; UTC = broker - 3h)

Outputs:
  - backtests/data/kz_trades_with_regime.csv (augmented features + sim PnL)
  - backtests/charts/kz_regime_filter.png   (per-feature breakdowns + equity)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
BROKER_OFFSET_HOURS = 3
HOLD_DAYS = 7
TP_PIPS = 12
TRADES_CSV = ROOT / "data/kz_trades_enriched.csv"
OUT_CSV = ROOT / "data/kz_trades_with_regime.csv"
OUT_PNG = ROOT / "charts/kz_regime_filter.png"

ATR_LEN = 14
EMA_LEN = 200
ADR_LEN = 14  # days


# ──────────────────────────── Helpers ────────────────────────────
def pip(symbol: str) -> float:
    return 0.01 if "JPY" in symbol else 0.0001


def to_utc(broker_unix) -> datetime:
    return datetime.fromtimestamp(broker_unix, tz=timezone.utc) - timedelta(hours=BROKER_OFFSET_HOURS)


def load_bars(symbol: str) -> pd.DataFrame | None:
    f = ROOT / f"data/{symbol}_M30.csv"
    if not f.exists():
        return None
    df = pd.read_csv(f)
    df["utc_t"] = df["time"].apply(to_utc)
    df = df.sort_values("utc_t").reset_index(drop=True)
    # ATR (Wilder-ish: simple TR rolling mean, fine for filter bucketing)
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    df["atr"] = tr.rolling(ATR_LEN, min_periods=ATR_LEN).mean()
    df["ema200"] = c.ewm(span=EMA_LEN, adjust=False, min_periods=EMA_LEN).mean()
    return df


def adr_pips_at(df: pd.DataFrame, opened_at: datetime, p: float) -> float | None:
    """14-day average daily range in pips, sampled the day BEFORE trade open."""
    # Resample to UTC daily H/L using strict-prior bars
    prior = df[df["utc_t"] < opened_at]
    if prior.empty:
        return None
    daily = prior.resample("D", on="utc_t").agg(high=("high", "max"), low=("low", "min")).dropna()
    if len(daily) < ADR_LEN:
        return None
    rng = (daily["high"] - daily["low"]).iloc[-ADR_LEN:].mean()
    return rng / p


def atr_pips_at(df: pd.DataFrame, opened_at: datetime, p: float) -> float | None:
    """ATR(14) in pips at the M30 bar STRICTLY before trade open."""
    prior = df[df["utc_t"] < opened_at]
    if prior.empty or pd.isna(prior["atr"].iloc[-1]):
        return None
    return float(prior["atr"].iloc[-1]) / p


def ema_alignment_at(df: pd.DataFrame, opened_at: datetime, direction: str) -> int | None:
    """Bullish alignment if last close > EMA200; LONG aligned with bullish, SHORT with bearish."""
    prior = df[df["utc_t"] < opened_at]
    if prior.empty or pd.isna(prior["ema200"].iloc[-1]):
        return None
    last = prior.iloc[-1]
    bullish = last["close"] > last["ema200"]
    if direction == "LONG":
        return 1 if bullish else 0
    return 1 if not bullish else 0


# ─────────────────────────── Simulator ───────────────────────────
def simulate_flat_tp(df, opened_at, direction, entry, sl, tp_pips, p, hold_days=HOLD_DAYS):
    end = opened_at + timedelta(days=hold_days)
    window = df[(df["utc_t"] >= opened_at) & (df["utc_t"] <= end)]
    if window.empty:
        return None, "NO_DATA"
    tp_price = entry + tp_pips * p if direction == "LONG" else entry - tp_pips * p
    for _, b in window.iterrows():
        if direction == "LONG":
            if b["low"] <= sl:
                return (sl - entry) / p, "SL"
            if b["high"] >= tp_price:
                return tp_pips, "TP"
        else:
            if b["high"] >= sl:
                return (entry - sl) / p, "SL"
            if b["low"] <= tp_price:
                return tp_pips, "TP"
    last = window.iloc[-1]
    pnl = ((last["close"] - entry) if direction == "LONG" else (entry - last["close"])) / p
    return pnl, "TIME"


# ─────────────────────────── Stats ───────────────────────────────
def stats(pnls: list[float]) -> dict | None:
    a = np.array(pnls, dtype=float)
    n = len(a)
    if n == 0:
        return None
    wins = (a > 0).sum()
    gp = a[a > 0].sum() if wins else 0.0
    gl = abs(a[a <= 0].sum()) if (a <= 0).sum() else 0.001
    return {
        "n": n,
        "wr": wins / n * 100,
        "pf": gp / gl,
        "tot": float(a.sum()),
        "avg": float(a.sum() / n),
    }


# ─────────────────────────── Pipeline ────────────────────────────
def build_dataset() -> pd.DataFrame:
    trades = pd.read_csv(TRADES_CSV)
    trades["opened_at"] = pd.to_datetime(trades["opened_at"], utc=True)

    bar_cache: dict[str, pd.DataFrame | None] = {}
    rows = []
    for _, t in trades.iterrows():
        sym = t["symbol"]
        if sym not in bar_cache:
            bar_cache[sym] = load_bars(sym)
        df = bar_cache[sym]
        if df is None:
            continue
        p = pip(sym)
        opened_at = t["opened_at"].to_pydatetime()

        # Simulate +12p flat TP
        sim_pnl, outcome = simulate_flat_tp(
            df, opened_at, t["direction"], t["entry_price"], t["stop_loss"], TP_PIPS, p
        )
        if sim_pnl is None:
            continue

        adr = adr_pips_at(df, opened_at, p)
        atr = atr_pips_at(df, opened_at, p)
        ema_align = ema_alignment_at(df, opened_at, t["direction"])

        kz_name, kz_range_pips = None, None
        meta = t.get("pattern_metadata")
        if isinstance(meta, str) and meta.strip():
            try:
                m = json.loads(meta)
                kz_name = m.get("kz_name")
                if m.get("kz_range") is not None:
                    kz_range_pips = float(m["kz_range"]) / p
            except Exception:
                pass

        rows.append({
            "id": int(t["id"]),
            "symbol": sym,
            "direction": t["direction"],
            "opened_at": opened_at,
            "score": t.get("score"),
            "sim_pnl_12p": sim_pnl,
            "outcome": outcome,
            "actual_pnl_pips": t["pnl_pips"],
            "adr_pips": adr,
            "atr_pips": atr,
            "ema_align": ema_align,
            "kz_name": kz_name,
            "kz_range_pips": kz_range_pips,
            "hour_utc": opened_at.hour,
            "dow": opened_at.weekday(),
        })

    return pd.DataFrame(rows)


# ─────────── Filter analysis: bucket numerical, group categorical ───────
def bucket_terciles(s: pd.Series) -> pd.Series:
    """Return tercile labels (low/mid/high) ignoring NaN."""
    valid = s.dropna()
    if len(valid) < 6:
        return pd.Series([None] * len(s), index=s.index)
    q1, q2 = valid.quantile([1 / 3, 2 / 3]).values
    out = pd.Series(["mid"] * len(s), index=s.index, dtype=object)
    out[s <= q1] = "low"
    out[s > q2] = "high"
    out[s.isna()] = None
    return out


def feature_breakdown(df: pd.DataFrame, feature: str, pnl_col: str = "sim_pnl_12p") -> pd.DataFrame:
    """Return per-bucket WR/PF/Total/N for a feature column."""
    rows = []
    for bucket, sub in df.groupby(feature, dropna=True):
        s = stats(sub[pnl_col].tolist())
        if not s:
            continue
        rows.append({"bucket": bucket, **s})
    return pd.DataFrame(rows)


# ─────────────────────────── Main ────────────────────────────────
def main() -> None:
    print("Building enriched dataset…")
    df = build_dataset()
    print(f"  rows: {len(df)}")
    if df.empty:
        return

    # Buckets for numerics
    df["adr_bucket"] = bucket_terciles(df["adr_pips"])
    df["atr_bucket"] = bucket_terciles(df["atr_pips"])
    df["kz_range_bucket"] = bucket_terciles(df["kz_range_pips"])

    # Hour groups (KZ session blocks, UTC)
    def hour_block(h):
        if 0 <= h < 4:
            return "asian_0_4"
        if 4 <= h < 7:
            return "pre_london_4_7"
        if 7 <= h < 12:
            return "london_7_12"
        if 12 <= h < 16:
            return "ny_morning_12_16"
        if 16 <= h < 21:
            return "ny_evening_16_21"
        return "late_21_24"
    df["hour_block"] = df["hour_utc"].apply(hour_block)

    # ───── Save augmented CSV ─────
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_CSV, index=False)
    print(f"  saved: {OUT_CSV}")

    # ───── Baseline ─────
    base = stats(df["sim_pnl_12p"].tolist())
    print(f"\nBASELINE +12p TP: N={base['n']}  WR={base['wr']:.0f}%  "
          f"PF={base['pf']:.2f}  Total={base['tot']:+.0f}p  Avg={base['avg']:+.2f}p")

    # ───── Per-feature breakdowns ─────
    features = [
        ("adr_bucket", "ADR (14d, pips) terciles"),
        ("atr_bucket", "ATR(14, M30) terciles"),
        ("kz_range_bucket", "KZ range (pips) terciles"),
        ("ema_align", "EMA200 alignment (1=aligned)"),
        ("kz_name", "Kill-zone name"),
        ("hour_block", "UTC hour block"),
        ("dow", "Day of week (0=Mon)"),
        ("symbol", "Symbol"),
        ("direction", "Direction"),
    ]
    print("\n──────── PER-FEATURE BREAKDOWN ────────")
    breakdowns: dict[str, pd.DataFrame] = {}
    for col, label in features:
        bd = feature_breakdown(df, col)
        if bd.empty:
            continue
        bd = bd.sort_values("pf", ascending=False).reset_index(drop=True)
        breakdowns[col] = bd
        print(f"\n{label} ({col}):")
        for _, r in bd.iterrows():
            flag = " *small*" if r["n"] < 15 else ""
            print(f"  {str(r['bucket']):<22} N={int(r['n']):>3} "
                  f"WR={r['wr']:>4.0f}%  PF={r['pf']:>4.2f}  "
                  f"Tot={r['tot']:>+6.1f}p{flag}")

    # ───── Pick top single filters ─────
    # Heuristic: rank single-bucket inclusions by PF*sqrt(N) where bucket size is reasonable.
    candidates = []
    for col, _ in features:
        if col not in breakdowns:
            continue
        for _, r in breakdowns[col].iterrows():
            if r["n"] < 15 or r["pf"] <= 1.05:
                continue
            score = r["pf"] * np.sqrt(r["n"])
            candidates.append((score, col, r["bucket"], r["n"], r["pf"], r["wr"], r["tot"]))
    candidates.sort(reverse=True)
    print("\n──────── TOP SINGLE FILTERS (score = PF*sqrt(N), N>=15, PF>1.05) ────────")
    for score, col, bucket, n, pf, wr, tot in candidates[:8]:
        print(f"  {col}={bucket:<20} N={n:>3} WR={wr:>4.0f}% PF={pf:.2f} "
              f"Tot={tot:+.1f}p score={score:.2f}")

    if len(candidates) < 2:
        print("Not enough strong filters for AND-combo.")
        return

    top1 = candidates[0]
    top2 = candidates[1]
    # Avoid combining two buckets of the same feature (degenerate — they're disjoint)
    if top2[1] == top1[1]:
        for c in candidates[2:]:
            if c[1] != top1[1]:
                top2 = c
                break

    f1_col, f1_bucket = top1[1], top1[2]
    f2_col, f2_bucket = top2[1], top2[2]

    mask1 = df[f1_col] == f1_bucket
    mask2 = df[f2_col] == f2_bucket
    sub_combo = df[mask1 & mask2]
    s_combo = stats(sub_combo["sim_pnl_12p"].tolist())

    sub_f1 = df[mask1]
    s_f1 = stats(sub_f1["sim_pnl_12p"].tolist())
    sub_f2 = df[mask2]
    s_f2 = stats(sub_f2["sim_pnl_12p"].tolist())

    # Filtered-out (rejected) sets
    s_rej1 = stats(df[~mask1]["sim_pnl_12p"].tolist())
    s_rej_combo = stats(df[~(mask1 & mask2)]["sim_pnl_12p"].tolist())

    print("\n──────── FILTER COMPARISON ────────")
    print(f"BASELINE        : N={base['n']:>3} WR={base['wr']:.0f}% PF={base['pf']:.2f} Tot={base['tot']:+.0f}p")
    print(f"FILTER 1 ({f1_col}={f1_bucket})")
    print(f"  KEEP          : N={s_f1['n']:>3} WR={s_f1['wr']:.0f}% PF={s_f1['pf']:.2f} Tot={s_f1['tot']:+.0f}p")
    print(f"  REJECT        : N={s_rej1['n']:>3} WR={s_rej1['wr']:.0f}% PF={s_rej1['pf']:.2f} Tot={s_rej1['tot']:+.0f}p")
    print(f"FILTER 2 ({f2_col}={f2_bucket})")
    print(f"  KEEP          : N={s_f2['n']:>3} WR={s_f2['wr']:.0f}% PF={s_f2['pf']:.2f} Tot={s_f2['tot']:+.0f}p")
    if s_combo:
        flag = " (small N)" if s_combo["n"] < 30 else ""
        print(f"COMBO (AND)     : N={s_combo['n']:>3} WR={s_combo['wr']:.0f}% "
              f"PF={s_combo['pf']:.2f} Tot={s_combo['tot']:+.0f}p{flag}")
    if s_rej_combo:
        print(f"  REJECT (combo): N={s_rej_combo['n']:>3} WR={s_rej_combo['wr']:.0f}% "
              f"PF={s_rej_combo['pf']:.2f} Tot={s_rej_combo['tot']:+.0f}p")

    # ───── Plot ─────
    fig = plt.figure(figsize=(17, 12))
    gs = fig.add_gridspec(3, 3, height_ratios=[1.4, 1.4, 1.6])

    feature_panel_cols = [
        ("adr_bucket", "ADR(14d) terciles"),
        ("atr_bucket", "ATR(14, M30) terciles"),
        ("kz_range_bucket", "KZ range terciles"),
        ("ema_align", "EMA200 alignment"),
        ("kz_name", "Kill-zone name"),
        ("hour_block", "UTC hour block"),
    ]

    panel_axes = []
    for i, (col, label) in enumerate(feature_panel_cols):
        r, c = divmod(i, 3)
        ax = fig.add_subplot(gs[r, c])
        bd = breakdowns.get(col)
        if bd is None or bd.empty:
            ax.set_visible(False)
            continue
        bd = bd.sort_values("bucket")
        x = np.arange(len(bd))
        labels = [str(b) for b in bd["bucket"]]
        bars = ax.bar(x, bd["pf"], color=["#2ca02c" if v >= 1 else "#d62728" for v in bd["pf"]], alpha=0.85)
        for j, (xi, n, wr, tot) in enumerate(zip(x, bd["n"], bd["wr"], bd["tot"])):
            ax.text(xi, bars[j].get_height() + 0.05,
                    f"N={int(n)}\nWR={wr:.0f}%\n{tot:+.0f}p",
                    ha="center", va="bottom", fontsize=8)
        ax.axhline(1.0, color="black", lw=0.7, alpha=0.6, ls="--")
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=20, fontsize=9)
        ax.set_title(label, fontsize=10)
        ax.set_ylabel("PF")
        ax.set_ylim(0, max(2.5, bd["pf"].max() * 1.25))
        ax.grid(alpha=0.3, axis="y")
        panel_axes.append(ax)

    # Equity panel (full bottom row)
    ax = fig.add_subplot(gs[2, :])
    ord_df = df.sort_values("opened_at").reset_index(drop=True)
    eq_base = np.cumsum(ord_df["sim_pnl_12p"].values)
    ax.plot(eq_base, color="#444",
            label=f"BASELINE (+12p)  N={base['n']}  WR={base['wr']:.0f}%  "
                  f"PF={base['pf']:.2f}  Tot={base['tot']:+.0f}p", lw=1.6)

    f1_mask_ord = ord_df[f1_col] == f1_bucket
    eq_f1 = np.cumsum(np.where(f1_mask_ord, ord_df["sim_pnl_12p"], 0))
    ax.plot(eq_f1, color="#1f77b4",
            label=f"F1 [{f1_col}={f1_bucket}]  N={s_f1['n']}  "
                  f"WR={s_f1['wr']:.0f}%  PF={s_f1['pf']:.2f}  Tot={s_f1['tot']:+.0f}p", lw=1.8)

    f2_mask_ord = ord_df[f2_col] == f2_bucket
    eq_f2 = np.cumsum(np.where(f2_mask_ord, ord_df["sim_pnl_12p"], 0))
    ax.plot(eq_f2, color="#ff7f0e",
            label=f"F2 [{f2_col}={f2_bucket}]  N={s_f2['n']}  "
                  f"WR={s_f2['wr']:.0f}%  PF={s_f2['pf']:.2f}  Tot={s_f2['tot']:+.0f}p", lw=1.8)

    if s_combo:
        combo_mask_ord = f1_mask_ord & f2_mask_ord
        eq_combo = np.cumsum(np.where(combo_mask_ord, ord_df["sim_pnl_12p"], 0))
        ax.plot(eq_combo, color="#2ca02c",
                label=f"AND [{f1_col}={f1_bucket} & {f2_col}={f2_bucket}]  "
                      f"N={s_combo['n']}  WR={s_combo['wr']:.0f}%  "
                      f"PF={s_combo['pf']:.2f}  Tot={s_combo['tot']:+.0f}p", lw=2.2)

    # ───── Practical combos (full-coverage features, robust N) ─────
    # 1) EMA-aligned + ATR not-high (volatility cap)
    mask_practical = (ord_df["ema_align"] == 1) & (ord_df["atr_bucket"].isin(["low", "mid"]))
    s_practical = stats(ord_df.loc[mask_practical, "sim_pnl_12p"].tolist())
    s_practical_rej = stats(ord_df.loc[~mask_practical, "sim_pnl_12p"].tolist())
    eq_practical = np.cumsum(np.where(mask_practical, ord_df["sim_pnl_12p"], 0))
    ax.plot(eq_practical, color="#2ca02c", ls="--",
            label=f"PRACTICAL [EMA-aligned & ATR∈low/mid]  "
                  f"N={s_practical['n']}  WR={s_practical['wr']:.0f}%  "
                  f"PF={s_practical['pf']:.2f}  Tot={s_practical['tot']:+.0f}p", lw=2.2)

    # 2) Drop the 3 worst hour blocks (single-feature rule, full coverage)
    bad_hours = ["london_7_12", "ny_morning_12_16", "pre_london_4_7"]
    mask_hour = ~ord_df["hour_block"].isin(bad_hours)
    s_hour = stats(ord_df.loc[mask_hour, "sim_pnl_12p"].tolist())
    s_hour_rej = stats(ord_df.loc[~mask_hour, "sim_pnl_12p"].tolist())
    eq_hour = np.cumsum(np.where(mask_hour, ord_df["sim_pnl_12p"], 0))
    ax.plot(eq_hour, color="#9467bd", ls="-.",
            label=f"HOUR-DROP [exclude {','.join(bad_hours)}]  "
                  f"N={s_hour['n']}  WR={s_hour['wr']:.0f}%  "
                  f"PF={s_hour['pf']:.2f}  Tot={s_hour['tot']:+.0f}p", lw=2.0)

    print("\n──────── PRACTICAL FILTERS (full-coverage features) ────────")
    print(f"EMA-aligned & ATR∈(low,mid):")
    print(f"  KEEP   : N={s_practical['n']:>3} WR={s_practical['wr']:.0f}% "
          f"PF={s_practical['pf']:.2f} Tot={s_practical['tot']:+.0f}p")
    print(f"  REJECT : N={s_practical_rej['n']:>3} WR={s_practical_rej['wr']:.0f}% "
          f"PF={s_practical_rej['pf']:.2f} Tot={s_practical_rej['tot']:+.0f}p")
    print(f"Drop hour blocks {bad_hours}:")
    print(f"  KEEP   : N={s_hour['n']:>3} WR={s_hour['wr']:.0f}% "
          f"PF={s_hour['pf']:.2f} Tot={s_hour['tot']:+.0f}p")
    print(f"  REJECT : N={s_hour_rej['n']:>3} WR={s_hour_rej['wr']:.0f}% "
          f"PF={s_hour_rej['pf']:.2f} Tot={s_hour_rej['tot']:+.0f}p")

    ax.axhline(0, color="black", lw=0.5, alpha=0.5)
    ax.set_title(f"Equity curves — BASELINE vs single filters vs AND-combo (TP=+{TP_PIPS}p)")
    ax.set_xlabel("Trade # (chronological)")
    ax.set_ylabel("Cumulative pips")
    ax.legend(loc="best", fontsize=9)
    ax.grid(alpha=0.3)

    plt.suptitle(
        f"KZ_HUNT regime-filter analysis — {base['n']} trades, +{TP_PIPS}p flat TP",
        fontsize=13, y=0.995,
    )
    plt.tight_layout()
    OUT_PNG.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(OUT_PNG, dpi=110, bbox_inches="tight")
    print(f"\nSaved chart: {OUT_PNG}")


if __name__ == "__main__":
    main()
