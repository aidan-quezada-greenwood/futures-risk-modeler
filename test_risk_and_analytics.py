"""Regression tests for financial calculations and decision limits."""

import unittest

import pandas as pd
from scipy.stats import t as student_t

from modules.analytics import by_field, core
from modules.instruments import INSTRUMENTS
from modules.position_sizer import calculate
from modules.pre_trade_checker import BLOCK, PROCEED, REDUCE, WARN, check
from modules.tags import deserialize_tags, serialize_tags
from modules.validation import validate_trade


class PositionSizingTests(unittest.TestCase):
    def test_commissions_and_slippage_included_in_risk(self):
        result = calculate(5000, 0.5, INSTRUMENTS["MES"], 6, 0.35, 0.5)
        self.assertAlmostEqual(result.cost_per_contract, 9.45)
        self.assertEqual(result.max_contracts, 2)
        self.assertLessEqual(result.max_contracts * result.cost_per_contract, 25.0)

    def test_tiny_risk_budget_allows_zero_contracts(self):
        result = calculate(100, 0.1, INSTRUMENTS["MGC"], 30, 0.5, 0.5)
        self.assertEqual(result.max_contracts, 0)


class PreTradeTests(unittest.TestCase):
    def inputs(self, **overrides):
        values = dict(daily_pnl=0, trades_today=0, daily_loss_limit=500,
                      max_trades_per_day=5, proposed_stop_ticks=10,
                      proposed_target_ticks=20, proposed_contracts=1,
                      max_contracts=3, max_stop_ticks=30, min_rr_ratio=1.5,
                      prop_firm_buffer=2500, cost_per_contract=50)
        values.update(overrides)
        return check(**values)

    def test_normal_trade_can_proceed(self):
        result = self.inputs()
        self.assertEqual(result.status, PROCEED)
        self.assertEqual(result.suggested_contracts, 1)

    def test_zero_contracts_allowed_blocks(self):
        result = self.inputs(max_contracts=0)
        self.assertEqual(result.status, BLOCK)
        self.assertEqual(result.suggested_contracts, 0)

    def test_daily_limit_hit_blocks(self):
        self.assertEqual(self.inputs(daily_pnl=-500).status, BLOCK)

    def test_trade_breaching_daily_limit_reduces_size(self):
        result = self.inputs(daily_pnl=-420, proposed_contracts=2)
        self.assertEqual(result.status, REDUCE)
        self.assertEqual(result.suggested_contracts, 1)
        self.assertAlmostEqual(result.daily_limit_pct_used, 100)

    def test_not_enough_daily_buffer_blocks(self):
        self.assertEqual(self.inputs(daily_pnl=-470).status, BLOCK)

    def test_oversized_position_reduces_size(self):
        result = self.inputs(proposed_contracts=5, max_contracts=2)
        self.assertEqual(result.status, REDUCE)
        self.assertEqual(result.suggested_contracts, 2)

    def test_no_prop_buffer_blocks(self):
        self.assertEqual(self.inputs(prop_firm_buffer=0).status, BLOCK)

    def test_prop_buffer_can_force_reduction(self):
        result = self.inputs(prop_firm_buffer=130, proposed_contracts=3)
        self.assertEqual(result.status, REDUCE)
        self.assertEqual(result.suggested_contracts, 2)

    def test_bad_stop_cost_blocks(self):
        self.assertEqual(self.inputs(cost_per_contract=0).status, BLOCK)

    def test_rr_warning(self):
        self.assertEqual(self.inputs(proposed_target_ticks=5).status, WARN)

    def test_positive_daily_pnl_does_not_count_as_loss(self):
        result = self.inputs(daily_pnl=200)
        self.assertEqual(result.daily_limit_pct_used, 0)


class AnalyticsTests(unittest.TestCase):
    def test_expectancy_includes_break_evens_correctly(self):
        metrics = core(pd.DataFrame({"result_r": [2, -1, 0, 0]}))
        self.assertAlmostEqual(metrics["expectancy"], 0.25)
        self.assertEqual(metrics["n_wins"], 1)
        self.assertEqual(metrics["n_losses"], 1)
        self.assertEqual(metrics["n_trades"], 4)

    def test_real_t_distribution_used_for_p_value(self):
        values = [1] * 11 + [-1] * 9
        metrics = core(pd.DataFrame({"result_r": values}))
        self.assertIsNotNone(metrics["t_stat"])
        self.assertAlmostEqual(metrics["p_value"], float(student_t.sf(metrics["t_stat"], 19)))
        self.assertNotEqual(metrics["edge_tier"], "success")

    def test_high_positive_returns_not_called_proof(self):
        values = [0.9, 1.1] * 15
        metrics = core(pd.DataFrame({"result_r": values}))
        self.assertLess(metrics["p_value"], 0.05)
        self.assertIn("Not proof", metrics["edge_label"])

    def test_constant_returns_do_not_forge_significance(self):
        metrics = core(pd.DataFrame({"result_r": [1.0] * 25}))
        self.assertIsNone(metrics["p_value"])
        self.assertEqual(metrics["edge_tier"], "info")

    def test_invalid_values_are_ignored(self):
        metrics = core(pd.DataFrame({"result_r": [1, None, "junk", float("inf"), -1]}))
        self.assertEqual(metrics["n_trades"], 2)
        self.assertAlmostEqual(metrics["expectancy"], 0)

    def test_drawdown_includes_first_trade_loss(self):
        metrics = core(pd.DataFrame({"result_r": [-2, 3, -1]}))
        self.assertEqual(metrics["max_dd_r"], -2.0)

    def test_grouping_ignores_invalid_results(self):
        df = pd.DataFrame({"session": ["AM", "AM", "AM", "PM"],
                           "result_r": [1, 0, None, -1]})
        groups = by_field(df, "session").set_index("session")
        self.assertEqual(groups.loc["AM", "trades"], 2)
        self.assertAlmostEqual(groups.loc["AM", "win_pct"], 0.5)


class UtilityTests(unittest.TestCase):
    def test_tag_round_trip(self):
        tags = ["Liquidity Sweep", "Support / Resistance"]
        self.assertEqual(deserialize_tags(serialize_tags(tags)), tags)

    def test_blank_trade_rejected(self):
        ok, errors = validate_trade({"instrument": "MES", "date": "2026-10-29"})
        self.assertFalse(ok)
        self.assertTrue(errors)


if __name__ == "__main__":
    unittest.main()
