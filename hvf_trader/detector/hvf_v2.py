"""HVF v2 — Hunt Volatility Funnel detection.

Implements `docs/research/HVF_V2_SPEC.md`. Nothing imports this yet; it is
research code staged in the package so it can be wired up later without moving.

The retired detector (`hvf_detector.py`, retired 2026-06-02) failed for reasons
that are specific and avoidable, and this module is shaped around avoiding them:

  * **Direction came from array-index parity.** Its LONG and SHORT branches were
    byte-identical, so whether a structure was a buy or a sell depended only on
    whether the 6-pivot window happened to start on a high. Here direction is
    decided by the prior trend *into* the exhaustion pivot and nothing else, so
    a candidate is a long iff it starts on a high that ends an uptrend.
  * **A risk filter silently implied a geometry filter.** Its advertised 1.2x
    contraction requirement was really ~2.4x once `MIN_RRR >= 1.5` was resolved
    through its own target and stop definitions. Here geometry is computed
    first, the pattern is admitted, and RRR is applied afterwards as a separate
    counted rejection. Every filter is independently observable in `Rejections`.
  * **The prior-trend precondition was missing entirely** — the one rule Hunt is
    unambiguous about. It is mandatory here, and pluggable, because which test
    to use is undetermined by the evidence (spec 4.2).

Spec tags are quoted at each rule: [V] validated against Hunt's charts,
[D] his doctrine, [I] our inference, [C] our choice.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Literal

import numpy as np
import pandas as pd

Direction = Literal[1, -1]
ProjMode = Literal["lin", "log"]

# Spec 2.6 [C]: Log projection above this bar period, Linear below. The observed
# split is perfect at 14/14 with an empty gap between 18h and 3D; 1 day sits
# inside that gap and is the conventional intraday/swing boundary. The rule
# (period, not range size) is recovered; only the cut point is our choice.
LOG_PROJECTION_MIN_HOURS = 24.0


# --------------------------------------------------------------------------
# Pivots
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Pivot:
    index: int              # positional index into the bar frame
    price: float            # the high (for 'H') or the low (for 'L')
    kind: Literal["H", "L"]
    ts: pd.Timestamp
    confirm: int = -1       # bar at which this pivot became KNOWN, not formed

    # `index` is where the extreme printed; `confirm` is where a percentage
    # ZigZag could first assert it, i.e. once price had reversed box_pct away.
    # The gap between them is pure lookahead and is exactly how a funnel
    # backtest fabricates an edge -- RH3/RL3 are not knowable at `index`. Any
    # simulation must arm on `confirm` and never on `index`.


def zigzag_pct(df: pd.DataFrame, box_pct: float = 0.5) -> list[Pivot]:
    """Fixed-percentage reversal ZigZag on highs and lows.

    Spec 4.1 [I]: the tool's own backtest box reads `Box Size 0.5%` and
    `Source H/L`, which together point at a fixed-percentage reversal computed
    on extremes rather than closes or a bar-count fractal. The existing
    `zigzag.py` is the right family but is ATR-adaptive, so the percentage
    variant lives here.

    Note the structural consequence the spec calls out: a percentage ZigZag
    never emits a pivot for the leg still in progress. The final pivot is only
    confirmed once price has reversed `box_pct` away from it, so live detection
    must treat RH3/RL3 as provisional. Historical scans are unaffected.
    """
    if len(df) < 3 or box_pct <= 0:
        return []

    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    ts = df["dt"].to_numpy()
    thr = box_pct / 100.0

    pivots: list[Pivot] = []

    # Direction is unknown at the first bar. Track both extremes until one of
    # them is retraced by the box size; that retracement names the first pivot
    # and fixes the direction from there on.
    hi, hi_i = highs[0], 0
    lo, lo_i = lows[0], 0
    direction = 0  # 0 undecided, +1 tracking a rise, -1 tracking a fall

    for i in range(1, len(df)):
        h, l = highs[i], lows[i]

        if direction >= 0 and h > hi:
            hi, hi_i = h, i
        if direction <= 0 and l < lo:
            lo, lo_i = l, i

        if direction == 0:
            if hi > 0 and (hi - l) / hi >= thr:
                pivots.append(Pivot(hi_i, hi, "H", pd.Timestamp(ts[hi_i]), i))
                direction, lo, lo_i = -1, l, i
            elif lo > 0 and (h - lo) / lo >= thr:
                pivots.append(Pivot(lo_i, lo, "L", pd.Timestamp(ts[lo_i]), i))
                direction, hi, hi_i = 1, h, i
            continue

        if direction > 0:
            if hi > 0 and (hi - l) / hi >= thr:
                pivots.append(Pivot(hi_i, hi, "H", pd.Timestamp(ts[hi_i]), i))
                direction, lo, lo_i = -1, l, i
        else:
            if lo > 0 and (h - lo) / lo >= thr:
                pivots.append(Pivot(lo_i, lo, "L", pd.Timestamp(ts[lo_i]), i))
                direction, hi, hi_i = 1, h, i

    return _enforce_alternation(pivots)


def _enforce_alternation(pivots: list[Pivot]) -> list[Pivot]:
    """Collapse consecutive same-kind pivots, keeping the more extreme one.

    The walk above cannot normally emit two highs in a row, but the undecided
    opening state can, and downstream code indexes pivots by parity — so the
    invariant is enforced rather than assumed.
    """
    out: list[Pivot] = []
    for p in pivots:
        if out and out[-1].kind == p.kind:
            better = (p.price > out[-1].price) if p.kind == "H" else (p.price < out[-1].price)
            if better:
                out[-1] = p
        else:
            out.append(p)
    return out


# --------------------------------------------------------------------------
# Prior-trend precondition  (spec 4.2 [D], thresholds [C])
# --------------------------------------------------------------------------
#
# Mandatory doctrine, and entirely absent from the retired detector. Which test
# to use is undetermined by the evidence, so all three candidates from the spec
# are implemented and selected by name. Deliberately NOT offered: ADX. The old
# detector applied an ADX floor at the funnel, where a contracting range
# mechanically depresses ADX — the filter was anti-correlated with what it was
# meant to select.

PriorTrendTest = Callable[[pd.DataFrame, int, int], bool]


def prior_trend_extreme_of_m(m: int = 100) -> PriorTrendTest:
    """H1/L1 must be the extreme of the preceding `m` bars. The simplest test."""

    def test(df: pd.DataFrame, idx: int, direction: int) -> bool:
        lo = max(0, idx - m)
        if idx - lo < m // 2:          # not enough history to judge
            return False
        if direction > 0:
            return df["high"].iloc[idx] >= df["high"].iloc[lo:idx + 1].max() - 1e-12
        return df["low"].iloc[idx] <= df["low"].iloc[lo:idx + 1].min() + 1e-12

    return test


def prior_trend_atr_span(k: float = 4.0, n: int = 100, atr_period: int = 14) -> PriorTrendTest:
    """The leg into the exhaustion pivot must span >= `k` x ATR over `n` bars."""

    def test(df: pd.DataFrame, idx: int, direction: int) -> bool:
        lo = max(0, idx - n)
        if idx - lo < n // 2:
            return False
        atr = _atr(df, atr_period).iloc[idx]
        if not np.isfinite(atr) or atr <= 0:
            return False
        window = df.iloc[lo:idx + 1]
        span = (df["high"].iloc[idx] - window["low"].min()) if direction > 0 \
            else (window["high"].max() - df["low"].iloc[idx])
        return span >= k * atr

    return test


def prior_trend_slope(n: int = 100, min_r2: float = 0.5) -> PriorTrendTest:
    """Least-squares slope on the pre-pivot window must run the right way and fit."""

    def test(df: pd.DataFrame, idx: int, direction: int) -> bool:
        lo = max(0, idx - n)
        if idx - lo < n // 2:
            return False
        y = df["close"].iloc[lo:idx + 1].to_numpy(dtype=float)
        x = np.arange(len(y), dtype=float)
        slope, intercept = np.polyfit(x, y, 1)
        if slope * direction <= 0:
            return False
        resid = y - (slope * x + intercept)
        ss_tot = float(((y - y.mean()) ** 2).sum())
        if ss_tot <= 0:
            return False
        return 1.0 - float((resid ** 2).sum()) / ss_tot >= min_r2

    return test


PRIOR_TREND_TESTS: dict[str, Callable[..., PriorTrendTest]] = {
    "extreme_of_m": prior_trend_extreme_of_m,
    "atr_span": prior_trend_atr_span,
    "slope": prior_trend_slope,
}


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder ATR. Cached on the frame — the prior-trend tests call it per pivot."""
    key = f"_atr_{period}"
    if key in df.attrs:
        return df.attrs[key]
    h, l, c = df["high"], df["low"], df["close"].shift(1)
    tr = pd.concat([h - l, (h - c).abs(), (l - c).abs()], axis=1).max(axis=1)
    out = tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    df.attrs[key] = out
    return out


# --------------------------------------------------------------------------
# The pattern
# --------------------------------------------------------------------------

@dataclass
class HVF:
    """A detected funnel with every level the spec defines."""
    direction: Direction
    pivots: list[Pivot]                # 6, in chronological order
    a: float                           # low anchor  -> fib 0.0
    b: float                           # high anchor -> fib 1.0
    fibs: dict[str, float]             # named pivot -> fib coordinate
    slung: float
    entry: float
    stop: float
    target: float
    rrr: float
    proj: ProjMode
    amp1: float
    mid: float

    @property
    def names(self) -> list[str]:
        return (["H1", "RL1", "RH2", "RL2", "RH3", "RL3"] if self.direction > 0
                else ["L1", "RH1", "RL2", "RH2", "RL3", "RH3"])

    @property
    def prices(self) -> dict[str, float]:
        return {n: p.price for n, p in zip(self.names, self.pivots)}

    @property
    def start_ts(self) -> pd.Timestamp:
        return self.pivots[0].ts

    @property
    def end_ts(self) -> pd.Timestamp:
        return self.pivots[-1].ts


@dataclass
class Rejections:
    """Per-reason counters.

    Spec 3.2 [C]: never let a risk filter imply a geometry filter. Every gate
    increments its own counter so the compound selectivity is observable — the
    retired detector's ~0.06 pass rate was invisible precisely because it was
    the product of gates nobody counted separately.
    """
    candidates: int = 0
    no_anchor: int = 0
    prior_trend: int = 0
    wrong_kind: int = 0
    short_window: int = 0
    degenerate_range: int = 0
    contraction: int = 0
    min_rrr: int = 0
    admitted: int = 0
    deduped: int = 0

    def as_dict(self) -> dict[str, int]:
        return {k: v for k, v in self.__dict__.items()}


def _anchor_pivot(pivots: list[Pivot], i: int, kind: str) -> Pivot | None:
    """The exhaustion pivot that started the move into the funnel's first pivot.

    Spec 4.3, replacing the falsified adjacency rule. The exhaustion leg is a
    larger degree than the funnel that follows it, so a box fine enough to emit
    RH3/RL3 shatters that leg into sub-pivots and H1 stops being adjacent to
    RH2; a box coarse enough to keep H1 adjacent never emits RH3/RL3 at all.
    USDJPY 4h shows both halves of that trade-off (spec 8.6).

    Recover H1 without a second box size: walk backwards keeping a running
    extreme of same-kind pivots and stop at the last one that improved it — the
    origin of the run of lower highs (higher lows, short side). Parameter-free,
    and it reduces to the old adjacency rule wherever the leg is a single clean
    swing, so gold and HYG are unchanged.
    """
    best: Pivot | None = None
    j = i - 1
    while j >= 0:
        p = pivots[j]
        if p.kind == kind:
            if best is None or (p.price > best.price if kind == "H"
                                else p.price < best.price):
                best = p
            else:
                break
        j -= 1
    return best


def project_target(mid: float, a: float, b: float, direction: int, proj: ProjMode) -> float:
    """Spec 2.5 [V]: AMP1 displacement from the midpoint of the final contraction.

    Additive in Linear mode, multiplicative in Log. Mean absolute error against
    the tool's own printed targets is 0.106% (Linear, n=8) and 0.347% (Log, n=5).

    The important negative result behind this: the textbook triangle target —
    a measured move from the range *edge* — scores R^2 = -18.4 on the same data.
    The midpoint anchor is not a refinement, it is the rule.
    """
    if proj == "log":
        ratio = b / a
        return mid * ratio if direction > 0 else mid / ratio
    return mid + direction * (b - a)


def select_projection(bar_hours: float) -> ProjMode:
    """Spec 2.6: Log at or above 1-day bars, Linear below. 14/14 on the charts."""
    return "log" if bar_hours >= LOG_PROJECTION_MIN_HOURS else "lin"


def detect_hvf(
    df: pd.DataFrame,
    *,
    bar_hours: float,
    box_pct: float = 0.5,
    prior_trend: PriorTrendTest | None = None,
    min_rrr: float | None = None,
    pivots: list[Pivot] | None = None,
    dedupe: bool = True,
) -> tuple[list[HVF], Rejections]:
    """Find every HVF in `df`.

    Spec 4.3. `df` needs columns open/high/low/close and a UTC `dt` column.

    `min_rrr` is applied *after* the pattern is admitted and counted separately,
    never folded into the geometry — see `Rejections`.
    """
    rej = Rejections()
    if pivots is None:
        pivots = zigzag_pct(df, box_pct)
    if len(pivots) < 6:
        return [], rej
    if prior_trend is None:
        prior_trend = prior_trend_extreme_of_m()

    proj = select_projection(bar_hours)
    out: list[HVF] = []

    # i indexes the funnel run RL1..RL3 (5 alternating pivots). H1 is not part
    # of the run — it is recovered by _anchor_pivot, which is why this is not
    # a plain 6-window scan.
    for i in range(1, len(pivots) - 4):
        run = pivots[i:i + 5]
        rej.candidates += 1

        # Direction is set by the prior trend into the exhaustion pivot, so it
        # is decided here and never by window parity (spec 2.2 [V]+[D]). The
        # run opens on RL1 for a long, RH1 for a short, so its kind fixes it.
        direction: Direction = 1 if run[0].kind == "L" else -1

        first = _anchor_pivot(pivots, i, "H" if direction > 0 else "L")
        if first is None:
            rej.no_anchor += 1
            continue
        window = [first] + list(run)

        if not prior_trend(df, first.index, direction):
            rej.prior_trend += 1
            continue

        # Anchors: fib 0.0 is the low anchor, 1.0 the high anchor, in both
        # directions. For a long that is (RL1, H1); for a short (L1, RH1).
        if direction > 0:
            b, a = window[0].price, window[1].price
        else:
            a, b = window[0].price, window[1].price

        if not (b > a > 0):
            rej.degenerate_range += 1
            continue

        span = b - a
        fib = lambda p: (p - a) / span   # spec 1.2 [V]: always linear, both modes
        names = (["H1", "RL1", "RH2", "RL2", "RH3", "RL3"] if direction > 0
                 else ["L1", "RH1", "RL2", "RH2", "RL3", "RH3"])
        fibs = {n: fib(p.price) for n, p in zip(names, window)}

        # Spec 3.1 [V]: each successive high lower, each successive low higher.
        # Expressed on the *named* pivots so it reads identically for both
        # directions — the mirror is in the naming, not in a second branch.
        if not (fibs["RH3"] < fibs["RH2"] < 1.0 and 0.0 < fibs["RL2"] < fibs["RL3"]):
            rej.contraction += 1
            continue

        slung = (fibs["RH3"] + fibs["RL3"]) / 2.0          # spec 2.1 [V]
        rh3 = a + fibs["RH3"] * span
        rl3 = a + fibs["RL3"] * span
        entry, stop = (rh3, rl3) if direction > 0 else (rl3, rh3)   # spec 2.3 [V]

        mid = a + slung * span                              # spec 2.5 [V]
        target = project_target(mid, a, b, direction, proj)
        risk = abs(entry - stop)
        if risk <= 0:
            rej.degenerate_range += 1
            continue
        rrr = abs(target - entry) / risk                    # spec 2.4 [V]

        if min_rrr is not None and rrr < min_rrr:
            rej.min_rrr += 1
            continue

        rej.admitted += 1
        out.append(HVF(
            direction=direction, pivots=list(window), a=a, b=b, fibs=fibs,
            slung=slung, entry=entry, stop=stop, target=target, rrr=rrr,
            proj=proj, amp1=span, mid=mid,
        ))

    kept = _dedupe(out) if dedupe else out
    rej.deduped = len(out) - len(kept)
    return kept, rej


def _dedupe(cands: list[HVF]) -> list[HVF]:
    """Spec 4.3 step 3: drop overlapping candidates, preferring the larger AMP1.

    Consecutive funnel runs share pivots, so a single funnel is found several
    times over.

    Overlap is judged on the FUNNEL span (RL1..RL3), not on the full pivot span.
    That distinction is not cosmetic: H1 is reached by a backwards walk that can
    start far earlier than the funnel (5 pivots back on USDJPY 4h), so including
    it makes unrelated candidates appear to overlap and evicts true ones. With
    the full span this dropped Hunt's own funnel on 2 of the 3 reproducing
    charts, taking recall from 3/3 to 1/3 -- spec 8.7. The anchor is shared
    context, not part of the structure being deduplicated.

    The "prefer larger AMP1" tie-break is unchanged. Once the span is right,
    earliest-completion and tightest-final-contraction give identical results on
    all three charts, so there is nothing to choose between them on this
    evidence and no reason to change it.
    """
    if not cands:
        return []
    ordered = sorted(cands, key=lambda c: (-c.amp1, c.pivots[1].index))
    kept: list[HVF] = []
    for c in ordered:
        lo, hi = c.pivots[1].index, c.pivots[-1].index
        if any(not (hi < k.pivots[1].index or lo > k.pivots[-1].index) for k in kept):
            continue
        kept.append(c)
    return sorted(kept, key=lambda c: c.pivots[1].index)


# --------------------------------------------------------------------------
# Data handling
# --------------------------------------------------------------------------

def load_ohlc(path: str) -> pd.DataFrame:
    """Load a repo CSV and screen it for the defects that have bitten before.

    Two real failure modes, both found in files already in the repo, both silent:
    `backtests/data/GBPAUD_H1.csv` and three siblings carry `time` literally `1`
    on every row; IC's BTCUSD feed carried `low = 0.0` on 2018-03-17, which a
    percentage ZigZag would have selected as the dominant pivot of the decade.
    """
    df = pd.read_csv(path)
    if df["time"].max() < 1_000_000:
        raise ValueError(f"{path}: 'time' column is corrupt (max {df['time'].max()})")
    df["dt"] = pd.to_datetime(df["time"], unit="s", utc=True)
    px = df[["open", "high", "low", "close"]]
    if (px <= 0).any().any():
        bad = df.loc[(px <= 0).any(axis=1), "dt"].tolist()
        raise ValueError(f"{path}: non-positive prices at {bad[:5]}")
    if px.isna().any().any():
        raise ValueError(f"{path}: NaN prices")
    return df.sort_values("time").reset_index(drop=True)


def resample_ohlc(df: pd.DataFrame, hours: float, offset_hours: float = 0.0) -> pd.DataFrame:
    """Resample H1 bars to a `hours`-period frame, anchored `offset_hours` in.

    None of Hunt's intraday charts is a native MT5 period — they are 2h, 4h, 8h
    and 18h — so every one must be rebuilt from H1. TradingView anchors
    non-standard periods to the instrument's session start, and a different
    anchor shifts every bar boundary and therefore every pivot. The offset is
    exposed so it can be swept rather than assumed (spec 11.1).
    """
    g = df.set_index("dt")
    rule = pd.Timedelta(hours=hours)
    out = g.resample(rule, origin="epoch", offset=pd.Timedelta(hours=offset_hours)).agg({
        "open": "first", "high": "max", "low": "min", "close": "last",
        "tick_volume": "sum",
    })
    out = out.dropna(subset=["open", "high", "low", "close"])
    return out.reset_index()


def ratio_series(num: pd.DataFrame, den: pd.DataFrame,
                 mode: Literal["tradingview", "bracket"] = "tradingview") -> pd.DataFrame:
    """Build a synthetic ratio instrument (XAU/XAG) on the shared timestamps.

    The two modes answer different questions and are not interchangeable:

    `tradingview` divides like against like (`high_n / high_d`). This is what
    TradingView actually does for a ratio symbol. It is not defensible as a
    tradable price — the ratio's true high need not occur when either leg peaks
    — but reproducing Hunt's chart means reproducing his platform's convention,
    so this is the mode the acceptance test must use.

    `bracket` divides each extreme by the opposing one (`high_n / low_d`),
    giving the widest range the two bars could have produced. This is the
    honest bound from bar data and is the mode any *backtest* should use, since
    it cannot understate the excursion a stop would have seen.
    """
    n = num.set_index("dt")[["open", "high", "low", "close"]]
    d = den.set_index("dt")[["open", "high", "low", "close"]]
    j = n.join(d, how="inner", lsuffix="_n", rsuffix="_d")
    out = pd.DataFrame(index=j.index)
    out["open"] = j["open_n"] / j["open_d"]
    out["close"] = j["close_n"] / j["close_d"]
    if mode == "tradingview":
        out["high"] = j["high_n"] / j["high_d"]
        out["low"] = j["low_n"] / j["low_d"]
    else:
        out["high"] = j["high_n"] / j["low_d"]
        out["low"] = j["low_n"] / j["high_d"]
    # A ratio of like-for-like extremes can invert, so restore the invariant.
    hi = out[["high", "low"]].max(axis=1)
    lo = out[["high", "low"]].min(axis=1)
    out["high"], out["low"] = hi, lo
    out["tick_volume"] = 0
    return out.reset_index()
