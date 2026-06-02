---
name: Asian Gravity strategy designed
description: EURGBP Wednesday-only gravity scalper — 100% WR over 60 days, ready for shadow trading implementation
type: project
originSessionId: f501baf1-25a0-4127-bd25-05baff95b8a7
---
New strategy designed 2026-04-15: Asian Gravity. EURGBP LONG only, Wednesday nights during Asian session (00:00-06:00 UTC).

**Rules**: When formation range (00:00-02:00) is < 10 pips and price drops 3 pips below session open, buy. TP +2 pips, SL -4 pips. One trade per session. Close by 06:00 UTC.

**Backtest**: 100% WR on 10 trades over 60 days (M5 bars via yfinance).

**Key insight**: 1-shot per quiet night transformed a losing strategy (-324 pips with re-entries) into 100% WR. Re-entries after stops compound losses.

**Implementation**: Add as 5th thread to existing bot. ~680 lines new code. Build spec at `ASIAN_GRAVITY_BUILD_SPEC.md`. Strategy spec at `ASIAN_GRAVITY_STRATEGY.md`.

**Next steps**: Build shadow trading (Phase 1), collect 30+ signals over 8+ Wednesdays, then go live.

**How to apply**: When building this, follow the build spec. Do NOT add re-entry logic. Do NOT change to SHORT direction. The edge is specifically LONG-only, 1-shot, quiet nights.
