"""The HVF v2 rules, in one place, shared by the research scripts and the live scanner.

Everything the backtests measured lives here and nowhere else. `scripts/hvf_v2_widestop.py`
grew its own copy of the geometry because it needed a stop that could move independently of
the targets; the live path in `hvf_v2.detect_hvf` grew a different one. Two copies means the
demo account would validate something other than what was measured, so this module is the
single definition and both sides import it.

WHAT IS FIXED HERE, and where it was established:

  * six pivots read as THREE WAVES -- H1>RL1, RH2>RL2, RH3>RL3 (user's own description,
    spec 8.30);
  * targets project from the SMALL funnel's centre `C = (entry + rl3)/2` at amp3, amp2,
    amp1. This reproduces Hunt's published levels to 0.02R (hvf_signal_parity) and is the
    one piece of doctrine that must never be re-derived from the stop;
  * the SHAPE GATE, spec 8.42 -- the only filter that replicated out of sample. The MEF
    rule is scale-free and degenerated to a one-bar third wave; Hunt's symmetry bounds did
    not;
  * DIRECTION is the prior trend into the exhaustion, never the funnel's shape (8.13/8.16).
    Left to itself the geometry emits 17-50:1 shorts in a bull market.

THE STOP IS A DELIBERATE DEVIATION. The user's spec puts it "just outside the tiny funnel"
= RL3. Spec 8.41 moved it to RL2 because 33% of RL3 stops sit inside a single bar's range.
That trade is real and it is not free -- on broker XAUUSD H24, same 134 gate-passing
funnels:

    stop   TP3 median   win    gross      net      total
    RL3        3.42R    42%   +0.003R  -0.109R    -8.7R
    RL2        2.02R    62%   +0.290R  +0.195R   +11.7R

So RRR really is ~8:1 at the 90th percentile with the user's stop; what does not survive is
the assumption that RRR and win rate move independently. `DEFAULT_STOP_AT` is the measured
one, and `stop_at="rl3"` is kept as a first-class option so the user can overrule it.
"""
from __future__ import annotations

import contextlib
import io
from dataclasses import dataclass, field

with contextlib.redirect_stdout(io.StringIO()):
    from hvf_trader.detector.hvf_mef import mef_candidates
    from hvf_trader.detector.hvf_signal import DEFAULT_BOX_PCT
    from hvf_trader.detector.hvf_v2 import Pivot, zigzag_pct

# --- spec 8.42, the shape gate -------------------------------------------------------
T3_T1 = (0.14, 0.55)        # third wave / first wave, in BARS
AMP3_AMP1 = (0.20, 0.52)    # third wave / first wave, in PRICE

# --- spec 8.13/8.16, direction ---------------------------------------------------------
TREND_LOOKBACK = 500        # bars; on H24 that is about two years

# --- spec 8.41, the stop ---------------------------------------------------------------
DEFAULT_STOP_AT = "rl2"
DEFAULT_ARM_ON = "confirmed"

# --- spec 8.43, the exit ---------------------------------------------------------------
# Hunt's own rule: no TP1 leg, half off at TP2, stop to breakeven there, the rest runs.
DEFAULT_EXIT_STYLE = "hunt"


@dataclass(frozen=True)
class Setup:
    """One HVF, in absolute prices, ready to size and to place.

    The research simulator works in offsets from the arming close; the live scanner works
    in prices. Absolute is the honest form -- `as_pick` derives the offsets from it, so the
    two can never drift apart.
    """
    direction: int              # +1 long, -1 short
    arm: int                    # bar index at which the setup becomes actionable
    entry: float                # RH3
    stop: float                 # RL2 or RL3, per stop_at
    tps: tuple[float, float, float]
    risk: float                 # |entry - stop|, the 1% unit
    small_stop: float           # RL3, always -- the funnel tip the targets project from
    centre: float               # C = (entry + small_stop) / 2
    t3_t1: float
    amp3_amp1: float
    pivots: tuple[Pivot, ...] = field(repr=False, default=())

    @property
    def rrr(self) -> float:
        return abs(self.tps[2] - self.entry) / self.risk if self.risk > 0 else 0.0

    def r_multiple(self, price: float) -> float:
        return self.direction * (price - self.entry) / self.risk if self.risk > 0 else 0.0

    def as_pick(self, close_at_arm: float, wait: int) -> dict:
        """The offset form `scripts/hvf_v2_widestop.simulate` consumes."""
        return dict(arm=int(self.arm), d=self.direction,
                    e_off=self.entry - close_at_arm,
                    s_off=self.stop - close_at_arm,
                    tps=[t - close_at_arm for t in self.tps],
                    wait=wait, w=list(self.pivots))


def shape_metrics(w) -> tuple[float, float]:
    """(time ratio, price ratio) of the third wave against the first. (0, 0) if degenerate."""
    h1, rl1, rh2, rl2, rh3, rl3 = w
    t1 = rl1.index - h1.index
    a1 = abs(h1.price - rl1.price)
    if t1 <= 0 or a1 <= 0:
        return 0.0, 0.0
    return (rl3.index - rh3.index) / t1, abs(rh3.price - rl3.price) / a1


def shape_gate(w) -> bool:
    """Hunt's balanced-collapse bounds. Spec 8.42."""
    t3_t1, amp3_amp1 = shape_metrics(w)
    if t3_t1 <= 0 or amp3_amp1 <= 0:
        return False
    return (T3_T1[0] <= t3_t1 <= T3_T1[1]
            and AMP3_AMP1[0] <= amp3_amp1 <= AMP3_AMP1[1])


def trend_direction(closes, i: int | None = None, lookback: int = TREND_LOOKBACK) -> int:
    """Prior trend at bar `i`, using only bars at or before it. Spec 8.13/8.16.

    NOTE this is stricter than `scripts/hvf_v2_forming.direction_for`, which compares the
    frame's LAST close against its 500th-from-last and applies the result to every trade in
    the frame. Live that is causal by construction -- the last bar is now -- but in a
    backtest it lets the end of the series set the direction at the start of it. Measuring
    per-bar here is the correct form and is what the live scanner will actually do.
    """
    n = len(closes)
    if i is None:
        i = n - 1
    if i < 0 or i >= n or i < 200:
        return 0
    return 1 if closes[i] > closes[max(0, i - lookback)] else -1


def find_setups(frame, direction: int | None = None, *,
                arm_on: str = DEFAULT_ARM_ON, stop_at: str = DEFAULT_STOP_AT,
                gate=shape_gate, box_pct: float = DEFAULT_BOX_PCT) -> list[Setup]:
    """Every HVF in `frame`, as absolute prices.

    `direction=None` resolves the trend causally at each setup's own arming bar, which is
    what the live scanner wants. Passing an explicit direction reproduces the research
    harness exactly.

    The gate is applied to the CONFIRMED six pivots in both arming modes, so it never
    depends on a provisional pivot and cannot smuggle in lookahead.
    """
    if stop_at not in ("rl2", "rl3"):
        raise ValueError(f"stop_at must be 'rl2' or 'rl3', got {stop_at!r}")
    if arm_on not in ("confirmed", "forming"):
        raise ValueError(f"arm_on must be 'confirmed' or 'forming', got {arm_on!r}")

    piv = zigzag_pct(frame, box_pct)
    if len(piv) < 6:
        return []
    close = frame["close"].to_numpy(float)
    low = frame["low"].to_numpy(float)
    high = frame["high"].to_numpy(float)
    n = len(frame)
    out, seen = [], set()

    dirs = (1, -1) if direction is None else (direction,)
    for d in dirs:
        for idx in mef_candidates(piv, d):
            w = [piv[j] for j in idx]
            h1, rl1, rh2, rl2, rh3, rl3 = w
            entry = rh3.price
            if gate is not None and not gate(w):
                continue

            if arm_on == "confirmed":
                arm, small_stop = rl3.confirm, rl3.price
            else:
                arm = rh3.confirm
                if arm < 0 or arm >= n:
                    continue
                lo_i = rh3.index + 1
                if lo_i > arm:
                    continue
                seg = low[lo_i:arm + 1] if d > 0 else high[lo_i:arm + 1]
                if seg.size == 0:
                    continue
                small_stop = float(seg.min() if d > 0 else seg.max())
                if d > 0 and not (rl2.price < small_stop < entry):
                    continue
                if d < 0 and not (entry < small_stop < rl2.price):
                    continue
            if arm < 0 or arm >= n - 1:
                continue
            # Every pivot the setup depends on must have CONFIRMED at or before the arming
            # bar. In `forming` the sixth is still provisional, so it is not a dependency.
            # Raises rather than warns: a causality break invalidates the measurement.
            for p in (w if arm_on == "confirmed" else w[:5]):
                if p.confirm < 0 or p.confirm > arm:
                    raise AssertionError(
                        f"pivot at index {p.index} confirms at {p.confirm}, after arm {arm}")

            # Resolved at the arming bar, so a setup never borrows a later trend.
            if direction is None and trend_direction(close, int(arm)) != d:
                continue

            amp3 = abs(entry - small_stop)
            if amp3 <= 0:
                continue
            centre = (entry + small_stop) / 2.0
            tps = (centre + d * amp3,
                   centre + d * abs(rh2.price - rl2.price),
                   centre + d * abs(h1.price - rl1.price))

            stop = small_stop if stop_at == "rl3" else rl2.price
            risk = abs(entry - stop)
            if risk <= 0 or d * (entry - stop) <= 0:
                continue
            if not all(d * (t - entry) > 0 for t in tps):
                continue

            key = (arm, round(entry, 10), round(stop, 10))
            if key in seen:
                continue
            seen.add(key)
            t3_t1, amp3_amp1 = shape_metrics(w)
            out.append(Setup(direction=d, arm=int(arm), entry=entry, stop=stop, tps=tps,
                             risk=risk, small_stop=small_stop, centre=centre,
                             t3_t1=t3_t1, amp3_amp1=amp3_amp1, pivots=tuple(w)))
    return out


def latest_setup(frame, *, max_age_bars: int = 3, **kw) -> Setup | None:
    """The most recent setup still fresh enough to act on. What the live scanner calls.

    A setup arms on the bar that confirms RL3 and the entry sits at RH3 above it, so it
    stays actionable for a few bars. `max_age_bars` bounds how stale an alert may be after
    a restart or a missed cycle.
    """
    setups = find_setups(frame, **kw)
    if not setups:
        return None
    last = len(frame) - 1
    fresh = [s for s in setups if 0 <= last - s.arm <= max_age_bars]
    return max(fresh, key=lambda s: s.arm) if fresh else None
