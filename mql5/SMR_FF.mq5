//+------------------------------------------------------------------+
//|                                                       SMR_FF.mq5 |
//|              Faithful FF Simple Mean Reversion (#743125)         |
//|              Mirrors the live Python scanner exactly.            |
//+------------------------------------------------------------------+
//| LIVE STRATEGY (Python):                                          |
//|  - 22:00 UTC daily-open capture (= broker 01:00 on UTC+3)        |
//|  - Trigger: ±40 pips from open                                   |
//|  - TP: 12.5 pips,  SL: 40 pips                                   |
//|  - Force exit at 21:00 UTC (= broker 00:00) next day             |
//|  - One trade per session, Mon-Fri capture nights                 |
//|  - Both directions, no filters                                   |
//|                                                                  |
//| EXECUTION CONVENTION:                                            |
//|  - Place BuyLimit at open-40p and SellLimit at open+40p at       |
//|    capture time. When one fills, cancel the other. Same logical  |
//|    behaviour as the live Python scanner's "limit at trigger      |
//|    price" order.                                                 |
//|                                                                  |
//| BACKTEST INSTRUCTIONS:                                           |
//|  - Symbol: EURGBP                                                |
//|  - Timeframe: M1 (or M5 — won't matter, ticks drive logic)       |
//|  - Modelling: "Every tick based on real ticks"                   |
//|  - Period: as far back as IC Markets allows (typically 5y+)      |
//|  - Initial deposit: $10,000                                      |
//|  - Spread: actual or ~1 pip                                      |
//+------------------------------------------------------------------+
#property copyright "HVF Trader"
#property version   "1.00"
#property strict

#include <Trade/Trade.mqh>

input double InpTriggerPips    = 40.0;        // Trigger pips from daily open
input double InpTargetPips     = 12.5;        // TP pips
input double InpStopPips       = 40.0;        // SL pips
input int    InpCaptureUtcHour = 22;          // Daily open capture hour (UTC)
input int    InpForceExitUtcHour = 21;        // Force-exit hour (UTC, next day)
input double InpLotSize        = 0.10;        // Fixed lot for testing
input int    InpMagic          = 50500001;    // Magic number
input int    InpBrokerOffsetH  = 3;           // Broker time offset from UTC

CTrade   trade;
double   pip;             // 0.0001 for 4/5-digit, 0.01 for 2/3-digit
double   sessionOpen = 0; // captured daily open
bool     captured    = false;
bool     traded      = false;
datetime sessionDate = 0;
ulong    pendingBuyTicket  = 0;
ulong    pendingSellTicket = 0;

//+------------------------------------------------------------------+
int OnInit()
{
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(20);
   int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   pip = (digits == 3 || digits == 5) ? 10 * _Point : _Point;
   PrintFormat("[SMR] Init: pip=%.5f digits=%d", pip, digits);
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason) {}

//+------------------------------------------------------------------+
// Convert broker time to UTC (broker is UTC+OFFSET)
datetime BrokerToUtc(datetime broker_time)
{
   return broker_time - InpBrokerOffsetH * 3600;
}

//+------------------------------------------------------------------+
int UtcWeekday(datetime utc_time)
{
   MqlDateTime dt;
   TimeToStruct(utc_time, dt);
   // dt.day_of_week: 0=Sun, 1=Mon, ..., 6=Sat
   // Python weekday(): 0=Mon, ..., 6=Sun. Convert.
   return (dt.day_of_week == 0) ? 6 : (dt.day_of_week - 1);
}

//+------------------------------------------------------------------+
// Reset session state — called when entering the daytime idle window
void ResetSession()
{
   captured = false;
   traded = false;
   sessionOpen = 0;
   sessionDate = 0;
   pendingBuyTicket = 0;
   pendingSellTicket = 0;
}

//+------------------------------------------------------------------+
// Cancel any still-pending orders for this magic
void CancelPendings()
{
   for (int i = OrdersTotal() - 1; i >= 0; i--)
   {
      ulong ticket = OrderGetTicket(i);
      if (ticket == 0) continue;
      if (OrderGetInteger(ORDER_MAGIC) != InpMagic) continue;
      trade.OrderDelete(ticket);
   }
   pendingBuyTicket = 0;
   pendingSellTicket = 0;
}

//+------------------------------------------------------------------+
// Close any open positions for this magic
void CloseAllOpen(string reason)
{
   for (int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if (ticket == 0) continue;
      if (PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      trade.PositionClose(ticket);
      PrintFormat("[SMR] Force-closed ticket=%I64u reason=%s", ticket, reason);
   }
}

//+------------------------------------------------------------------+
// Returns true if this magic has any open position
bool HasOpenPosition()
{
   for (int i = 0; i < PositionsTotal(); i++)
   {
      ulong ticket = PositionGetTicket(i);
      if (ticket == 0) continue;
      if (PositionGetInteger(POSITION_MAGIC) == InpMagic) return true;
   }
   return false;
}

//+------------------------------------------------------------------+
void OnTick()
{
   datetime broker_now = TimeCurrent();
   datetime utc_now    = BrokerToUtc(broker_now);
   MqlDateTime u;
   TimeToStruct(utc_now, u);
   int hour = u.hour;

   // ---- Force-exit window (21:00 UTC) ----
   if (hour == InpForceExitUtcHour)
   {
      if (HasOpenPosition()) CloseAllOpen("force_exit_21UTC");
      CancelPendings();
      // Reset is gated until we leave this hour to avoid re-arming same hour
      if (captured || traded) ResetSession();
      return;
   }

   // ---- Daytime idle window: just wait, ensure clean state ----
   if (hour > InpForceExitUtcHour && hour < InpCaptureUtcHour)
   {
      // 22 > 21 and 22 < 22 false → won't run during 22:00 capture.
      // Window is [22, 21]; here we're in [22, 22) which is empty for 22→21,
      // i.e., this branch only runs when InpForceExitUtcHour < hour < InpCaptureUtcHour.
      // For defaults (21, 22): never runs. Kept for non-default configs.
      return;
   }

   // ---- Capture window (22:00 UTC) ----
   if (hour == InpCaptureUtcHour)
   {
      if (captured) return;

      int wd = UtcWeekday(utc_now);
      // Mon-Fri capture nights → Tue-Sat trading. (Python days = [0,1,2,3,4])
      if (wd < 0 || wd > 4) return;

      // Capture daily open as the current bid (matches Python scanner —
      // it reads tick.bid at 22:00:xx as session_open via the M5 bar open).
      MqlTick tick;
      if (!SymbolInfoTick(_Symbol, tick)) return;
      sessionOpen = tick.bid;
      sessionDate = utc_now;
      captured    = true;
      traded      = false;

      // Place both pending limits — symmetric, FF "fade either side".
      double buyPrice  = NormalizeDouble(sessionOpen - InpTriggerPips * pip, _Digits);
      double sellPrice = NormalizeDouble(sessionOpen + InpTriggerPips * pip, _Digits);

      double buyTp = NormalizeDouble(buyPrice  + InpTargetPips * pip, _Digits);
      double buySl = NormalizeDouble(buyPrice  - InpStopPips   * pip, _Digits);

      double sellTp = NormalizeDouble(sellPrice - InpTargetPips * pip, _Digits);
      double sellSl = NormalizeDouble(sellPrice + InpStopPips   * pip, _Digits);

      // BuyLimit (fade down)
      if (trade.BuyLimit(InpLotSize, buyPrice, _Symbol, buySl, buyTp, ORDER_TIME_GTC, 0, "SMR Long"))
         pendingBuyTicket = trade.ResultOrder();

      // SellLimit (fade up)
      if (trade.SellLimit(InpLotSize, sellPrice, _Symbol, sellSl, sellTp, ORDER_TIME_GTC, 0, "SMR Short"))
         pendingSellTicket = trade.ResultOrder();

      PrintFormat("[SMR] Captured: open=%.5f buyLimit=%.5f@TP=%.5f/SL=%.5f sellLimit=%.5f@TP=%.5f/SL=%.5f",
                  sessionOpen, buyPrice, buyTp, buySl, sellPrice, sellTp, sellSl);
      return;
   }

   // ---- Trading window (everything outside capture/force-exit) ----
   if (!captured) return;

   // If one pending filled, cancel the other (one trade per session).
   if (!traded && HasOpenPosition())
   {
      // Find which one is open, cancel the surviving pending.
      bool buyOpen  = false;
      bool sellOpen = false;
      for (int i = 0; i < PositionsTotal(); i++)
      {
         ulong t = PositionGetTicket(i);
         if (t == 0) continue;
         if (PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
         long ptype = PositionGetInteger(POSITION_TYPE);
         if (ptype == POSITION_TYPE_BUY)  buyOpen  = true;
         if (ptype == POSITION_TYPE_SELL) sellOpen = true;
      }
      if (buyOpen)  // buyLimit filled, kill the sellLimit
      {
         if (pendingSellTicket != 0)
         {
            trade.OrderDelete(pendingSellTicket);
            pendingSellTicket = 0;
         }
      }
      if (sellOpen)
      {
         if (pendingBuyTicket != 0)
         {
            trade.OrderDelete(pendingBuyTicket);
            pendingBuyTicket = 0;
         }
      }
      traded = true;
   }

   // TP/SL fills handled automatically by the broker — nothing else to do.
   // Force-exit handled at top of OnTick when hour reaches force_exit hour.
}
//+------------------------------------------------------------------+
