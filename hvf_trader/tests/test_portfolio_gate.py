"""Tests for the portfolio gate's pure decision logic (_evaluate)."""
import unittest

from hvf_trader.risk.portfolio_gate import _evaluate, _currencies

CFG = {
    "enabled": True,
    "max_positions": 9,
    "max_total_exposures": 13,
    "min_free_margin_pct": 25.0,
    "max_per_currency": 4,
}


def ev(symbol="AUDNZD", n_pos=0, n_pend=0, n_res=0,
       free_margin=8000.0, equity=8000.0, ccy=None):
    return _evaluate(symbol, n_pos, n_pend, n_res, free_margin, equity,
                     ccy or {}, CFG)


class TestPortfolioGate(unittest.TestCase):
    def test_normal_full_book_allowed(self):
        # Realistic worst normal book: 7 positions, 2 pendings, NT cluster
        ok, reason = ev(n_pos=7, n_pend=2,
                        ccy={"AUD": 2, "NZD": 2, "CAD": 2, "GBP": 1})
        self.assertTrue(ok, reason)

    def test_position_cap(self):
        ok, reason = ev(n_pos=9)
        self.assertFalse(ok)
        self.assertIn("positions", reason)

    def test_reservations_count_toward_position_cap(self):
        ok, _ = ev(n_pos=8, n_res=1)
        self.assertFalse(ok)
        ok, _ = ev(n_pos=8, n_res=0)
        self.assertTrue(ok)

    def test_total_exposures_cap(self):
        ok, reason = ev(n_pos=8, n_pend=5)
        self.assertFalse(ok)
        self.assertIn("pendings", reason)

    def test_margin_floor(self):
        ok, reason = ev(free_margin=1900.0, equity=8000.0)  # 23.75%
        self.assertFalse(ok)
        self.assertIn("margin", reason)
        ok, _ = ev(free_margin=2100.0, equity=8000.0)  # 26.25%
        self.assertTrue(ok)

    def test_zero_equity_skips_margin_check(self):
        ok, _ = ev(free_margin=0.0, equity=0.0)
        self.assertTrue(ok)

    def test_currency_cap(self):
        ok, reason = ev(symbol="GBPUSD", ccy={"GBP": 4})
        self.assertFalse(ok)
        self.assertIn("GBP", reason)
        ok, _ = ev(symbol="AUDNZD", ccy={"GBP": 4})
        self.assertTrue(ok)

    def test_crypto_index_symbols_have_no_currency_legs(self):
        self.assertEqual(_currencies("BTCUSD"), {"BTC", "USD"})
        self.assertEqual(_currencies("US500"), set())
        self.assertEqual(_currencies("DE40"), set())
        # BTCUSD counts USD legs like forex would — generous cap makes this
        # harmless, but verify an index never trips a currency rule
        ok, _ = ev(symbol="DE40", ccy={"USD": 4, "GBP": 4})
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
