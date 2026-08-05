"""A detected funnel turned into a tradeable card: geometry, slung, sizing distance.

This is the layer between `hvf_mef.mef_candidates` (which finds funnels) and the
alerting/execution stack (which needs prices to act on).

GEOMETRY (spec 8.31, and the trader's own description of the pattern). Six pivots
are three contracting waves, and every level projects from `C`, the centre of the
smallest funnel:

    waves      amp3 = |RH3 - RL3|   amp2 = |RH2 - RL2|   amp1 = |H1 - RL1|
    centre     C    = (RH3 + RL3) / 2
    entry      C + d * amp3/2       -- i.e. the far edge of the smallest funnel
    stop       RL3 (long) / RH3 (short), optionally a buffer beyond
    TP1        C + d * amp3         TP2  C + d * amp2        TP3  C + d * amp1

Entry sits half a funnel from C and TP1 a full one, so **TP1 is structurally +0.5R**
and TP3 carries the high RRR the pattern is traded for.

SIZING. `risk_distance` is |entry - stop|, never |C - stop|. The two differ by 2x:
C is the funnel's midpoint, so C-to-stop is half the entry-to-stop span. Sizing 1%
of equity on the half-distance while entering at the breakout makes a stop-out cost
2%. `risk_distance` is what goes to `position_sizer.calculate_lot_size`.

THE FORMING ARM, and why it exists. Spec 8.38 found that 34.1% of picks had their
entry already breached at the arming bar -- for a long, the entry sat *below* the
close, so the backtest bought below market and that impossible fill was the entire
measured edge. The cause is ZigZag confirmation lag: RL3 is not knowable until price
has retraced by the box amount, and by then price has often gone through the entry.

Hunt does not have that problem, because he posts setups on funnels that are still
forming. So do we, now: `scan(..., forming=True)` appends the running extreme since
the last confirmed pivot as a provisional 6th pivot. The entry (RH3) is already
confirmed at that point, so a resting stop order can be placed while the entry is
genuinely still ahead of price. The stop is provisional and moves if the low extends,
which is why a forming signal must be re-quoted, not fired once and forgotten.
"""
import logging
from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

from hvf_trader.detector.hvf_mef import mef_candidates
from hvf_trader.detector.hvf_v2 import Pivot, zigzag_pct

logger = logging.getLogger(__name__)

# Hunt's own box, confirmed by his tool's panel ("Box Size 0.5%", "Source H/L").
DEFAULT_BOX_PCT = 0.5

# The band his 13 posted charts fall in (spec 2.1). Reported, never gated on --
# 13 screenshots are a selection-biased sample of what he chose to publish, and
# gating on it would bake his publication bias into the detector. Whether it
# actually selects is an open test; until it settles this is display only.
SLUNG_BAND = (0.37, 0.68)


@dataclass
class HVFSignal:
    """One funnel, priced. All levels are absolute prices in the symbol's quote."""

    symbol: str
    timeframe: str
    direction: int                      # +1 long, -1 short
    pivots: list[Pivot]                 # H1, RL1, RH2, RL2, RH3, RL3 (bullish naming)
    entry: float
    stop: float
    tp1: float
    tp2: float
    tp3: float
    centre: float                       # C -- what every target projects from
    slung: float
    amp1: float
    amp2: float
    amp3: float
    forming: bool                       # 6th pivot provisional, stop may still move
    detected_at: pd.Timestamp = None
    box_pct: float = DEFAULT_BOX_PCT
    meta: dict = field(default_factory=dict)

    @property
    def risk_distance(self) -> float:
        """|entry - stop|. The denominator for position sizing -- NOT |C - stop|."""
        return abs(self.entry - self.stop)

    @property
    def rrr(self) -> float:
        """Reward:risk to the furthest target."""
        r = self.risk_distance
        return abs(self.tp3 - self.entry) / r if r > 0 else 0.0

    @property
    def side(self) -> Literal["LONG", "SHORT"]:
        return "LONG" if self.direction > 0 else "SHORT"

    @property
    def slung_in_band(self) -> bool:
        return SLUNG_BAND[0] <= self.slung <= SLUNG_BAND[1]

    @property
    def targets(self) -> list[float]:
        return [self.tp1, self.tp2, self.tp3]


def slung_of(pivots: list[Pivot], direction: int) -> float:
    """(fib(RH3) + fib(RL3)) / 2 -- the vertical centre of the final contraction.

    Range units are set by the funnel's own first leg: fib 0 at RL1, fib 1 at H1
    for a bullish funnel, mirrored for a bearish one. Spec 2.1 validates this to
    within 0.005 on 13/13 of Hunt's charts, the tightest agreement in the evidence
    base -- the residual is bounded by his panel displaying two decimals.

    Reads two ways, and they are the same number. A perfectly balanced collapse --
    highs coming down as much as lows go up -- leaves the last funnel dead centre
    at 0.50. Above that the funnel rides high and points up; below, it points down.
    "Highly-slung" is Hunt's term for one too far off centre.
    """
    h1, rl1 = pivots[0], pivots[1]
    if direction > 0:
        a, b = rl1.price, h1.price
    else:
        a, b = h1.price, rl1.price
    rng = b - a
    if rng <= 0:
        return float("nan")
    return sum((p.price - a) / rng for p in pivots[4:6]) / 2.0


def _geometry(pivots: list[Pivot], direction: int, stop_buffer_frac: float):
    """Levels from the three waves. Returns None if the funnel is degenerate."""
    h1, rl1, rh2, rl2, rh3, rl3 = pivots
    amp1 = abs(h1.price - rl1.price)
    amp2 = abs(rh2.price - rl2.price)
    amp3 = abs(rh3.price - rl3.price)
    if amp3 <= 0 or amp1 <= 0:
        return None

    centre = (rh3.price + rl3.price) / 2.0
    entry = centre + direction * amp3 / 2.0
    # The stop sits just outside the smallest funnel; the buffer defaults to zero
    # so live geometry reproduces the backtested numbers exactly.
    stop = centre - direction * amp3 / 2.0 * (1.0 + stop_buffer_frac)
    return dict(
        centre=centre, entry=entry, stop=stop,
        tp1=centre + direction * amp3,
        tp2=centre + direction * amp2,
        tp3=centre + direction * amp1,
        amp1=amp1, amp2=amp2, amp3=amp3,
    )


def _provisional_pivot(df: pd.DataFrame, last: Pivot) -> Pivot | None:
    """The running extreme since `last`, as the not-yet-confirmed opposite pivot.

    This is what lets us alert before the ZigZag confirms. It is deliberately NOT
    given a `confirm` index -- nothing downstream may treat it as known history.
    """
    tail = df.iloc[last.index + 1:]
    if tail.empty:
        return None
    if last.kind == "H":
        pos = int(tail["low"].to_numpy().argmin())
        return Pivot(index=last.index + 1 + pos, price=float(tail["low"].iloc[pos]),
                     kind="L", ts=tail.index[pos], confirm=-1)
    pos = int(tail["high"].to_numpy().argmax())
    return Pivot(index=last.index + 1 + pos, price=float(tail["high"].iloc[pos]),
                 kind="H", ts=tail.index[pos], confirm=-1)


def scan(df: pd.DataFrame, symbol: str, timeframe: str, direction: int,
         box_pct: float = DEFAULT_BOX_PCT, forming: bool = True,
         stop_buffer_frac: float = 0.0) -> list[HVFSignal]:
    """Every funnel in `df` for one direction, priced and ready to alert on.

    `direction` is imposed by the caller from the higher-timeframe trend, never read
    off the funnel's shape (spec 2.2: direction follows the prior trend into the
    exhaustion point). Left to itself the geometry emits 17-50:1 shorts in a bull
    market, which is the trend's asymmetry showing through, not the pattern's.
    """
    pivots = zigzag_pct(df, box_pct)
    if len(pivots) < 6:
        return []

    # mef_candidates yields INDICES into the pivot list, not pivots.
    windows = [[pivots[j] for j in idx] for idx in mef_candidates(pivots, direction)]

    if forming:
        provisional = _provisional_pivot(df, pivots[-1])
        if provisional is not None:
            ext = pivots + [provisional]
            last = len(ext) - 1
            windows += [[ext[j] for j in idx]
                        for idx in mef_candidates(ext, direction) if idx[-1] == last]

    out, seen = [], set()
    for w in windows:
        if len(w) != 6:
            continue
        key = tuple(p.ts.value for p in w)
        if key in seen:
            continue
        seen.add(key)

        geo = _geometry(w, direction, stop_buffer_frac)
        if geo is None:
            continue
        s = slung_of(w, direction)
        if s != s:                                    # NaN -- degenerate first leg
            continue

        out.append(HVFSignal(
            symbol=symbol, timeframe=timeframe, direction=direction, pivots=w,
            slung=s, forming=w[-1].confirm < 0, box_pct=box_pct,
            detected_at=df.index[-1], **geo))

    out.sort(key=lambda x: x.pivots[-1].ts)
    return out
